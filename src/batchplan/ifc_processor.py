import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.shape
import numpy as np
import networkx as nx
from ifcopenshell.util.element import get_decomposition
from shapely.geometry import Polygon
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
from functools import partial

from geometry_engine import IFCGeometryProcessor
from collections import Counter, defaultdict


# ── Room Type Cleaning Rules ─────────────────────────────────────────────────

KEEP_AS_IS = {
    "storage", "bathroom", "shaft", "corridor", "bedroom",
    "livingroom", "balcony", "area",
    "GO_Logiesfunctie", "esco", "VG", "staircase",
    "elevator shaft", "cera",
    "GO_Woonfunctie", "elevator",
    "GBO_buitenruimte", "GBO",
}

# Build a lowercase lookup for keep-as-is matching (preserves original casing)
KEEP_LOWER = {v.lower(): v for v in KEEP_AS_IS}


def clean_room_type(room_type: str) -> str:
    """
    Clean and normalize room type names according to standardized rules.

    Rules applied:
      1. "elevator shaft" or "elevator" (case-insensitive)  → "elevator"
      2. "cera" (case-insensitive)                          → "Central Energy Recovery Airflow"
      3. Values in the KEEP_AS_IS set                       → unchanged
      4. Non-empty values not matched above                 → prefix "remaining_"
      5. Empty / blank values                               → unchanged (left empty)

    Args:
        room_type: Raw room type string

    Returns:
        str: Cleaned room type value
    """
    raw = room_type  # keep original for whitespace logic
    stripped = raw.strip()

    # Empty → leave alone
    if not stripped:
        return raw  # preserve whatever was there (blank stays blank)

    lower = stripped.lower()

    # Rule: keep-as-is set (case-sensitive exact match first, then case-insensitive)
    if stripped in KEEP_AS_IS:
        return stripped
    if lower in KEEP_LOWER:
        return KEEP_LOWER[lower]   # return canonical casing from the set

    # Rule: everything else non-empty → prefix (idempotent: skip if already prefixed)
    if stripped.startswith("remaining_"):
        return stripped
    return "remaining_" + stripped


def print_ifc_overview(ifc_path):
    """
    Print a detailed overview of IFC file contents without processing geometry.
    Shows project info, total counts, and per-storey breakdown.

    Args:
        ifc_path: Path to IFC file
    """
    model = ifcopenshell.open(ifc_path)

    # Get project info
    project = model.by_type("IfcProject")[0] if model.by_type("IfcProject") else None
    building = model.by_type("IfcBuilding")[0] if model.by_type("IfcBuilding") else None

    print("\n" + "=" * 60)
    print("IFC FILE OVERVIEW")
    print("=" * 60)

    if project:
        print(f"Project: {project.Name or 'N/A'}")
    if building:
        print(f"Building: {building.Name or 'N/A'}")

    # Get schema version
    schema = model.schema
    print(f"Schema: {schema}")

    # Get all products (elements)
    all_products = model.by_type("IfcProduct")

    # Count by type
    type_counts = Counter(el.is_a() for el in all_products)

    # Get storeys
    storeys = list(model.by_type("IfcBuildingStorey"))

    print(f"\nTotal Storeys: {len(storeys)}")
    print(f"Total Elements: {len(all_products)}")

    # Overall element types
    print(f"\nElement Types (Overall):")
    for element_type, count in type_counts.most_common():
        print(f"  {element_type}: {count}")

    # Per-storey details
    if storeys:
        print(f"\nStorey Details:\n")

        for idx, storey in enumerate(storeys):
            name = storey.Name or f"Storey_{storey.id()}"
            long_name = storey.LongName if hasattr(storey, 'LongName') and storey.LongName else name

            # Get elevation
            elevation = storey.Elevation if hasattr(storey, 'Elevation') and storey.Elevation else 0.0

            # Get elements in this storey
            storey_elements = get_decomposition(storey)

            # Filter to only products with representation
            storey_products = [el for el in storey_elements
                               if el.is_a("IfcProduct") and el.Representation is not None]

            # Count by type
            storey_type_counts = Counter(el.is_a() for el in storey_products)

            print(f"  [{idx}] {name}")
            if long_name != name:
                print(f"      Long Name: {long_name}")
            print(f"      Elevation: {elevation:.2f}")
            print(f"      Elements: {len(storey_products)}")

            if storey_type_counts:
                print(f"      Element Types:")
                # Show top 5 types
                top_types = storey_type_counts.most_common(5)
                for element_type, count in top_types:
                    print(f"        {element_type}: {count}")

                # Show count of remaining types
                remaining = len(storey_type_counts) - len(top_types)
                if remaining > 0:
                    print(f"        ... and {remaining} more types")

            print()  # Empty line between storeys

    print("=" * 60 + "\n")


def default_filter():
    """Default filter function - exclude problematic element types"""

    def fn(el):
        # Skip annotations and other non-geometric elements that often cause issues
        skip_types = {
            "IfcAnnotation", "IfcGrid", "IfcGridAxis",
            "IfcOpeningElement", "IfcVirtualElement", "IfcProjectionElement"
        }

        return (el.is_a("IfcProduct") and
                el.Representation is not None and
                not any(el.is_a(skip_type) for skip_type in skip_types))

    return fn


def space_filter():
    """Filter function for IfcSpace elements only"""

    def fn(el):
        return el.is_a("IfcSpace") and el.Representation is not None

    return fn


def get_room_type_from_space(space, naming_conversion=None):
    """
    Extract room type from IfcSpace element using Pset_SpaceCommon.Reference.

    Args:
        space: IfcSpace element
        naming_conversion: dict mapping original names to English names (case-insensitive)

    Returns:
        str: Room type or None if not found (cleaned according to normalization rules)
    """
    # Only process IfcSpace elements
    if not space.is_a("IfcSpace"):
        return None

    naming_conversion = naming_conversion or {}

    # Create case-insensitive lookup dictionary
    naming_conversion_lower = {k.lower(): v for k, v in naming_conversion.items()}

    try:
        # Use ifcopenshell utility to get all property sets
        psets = ifcopenshell.util.element.get_psets(space)

        # Check if Pset_SpaceCommon exists
        if 'Pset_SpaceCommon' in psets:
            reference = psets['Pset_SpaceCommon'].get('Reference', '')
            if reference:
                # Get first word (matches notebook logic)
                roomtype = reference.split()[0]

                # Apply naming conversion if provided (case-insensitive)
                if naming_conversion_lower:
                    roomtype = naming_conversion_lower.get(roomtype.lower(), roomtype)

                # Apply room type cleaning/normalization
                return clean_room_type(roomtype)
    except Exception:
        pass

    return None


def get_room_type(element, naming_conversion=None):
    """
    Extract room type information from IFC element with fallback hierarchy.
    Only processes IfcSpace elements.

    Priority:
    1. Pset_SpaceCommon.Reference (first word) - for IfcSpace
    2. IfcSpace.LongName
    3. IfcSpace.ObjectType
    4. Other property sets
    5. Fallback to ObjectType

    Args:
        element: IFC element (must be IfcSpace)
        naming_conversion: optional dict mapping raw codes -> English names (case-insensitive)

    Returns:
        str: Room type or "Unknown" if not found, None if not IfcSpace (cleaned according to normalization rules)
    """
    # Only process IfcSpace elements
    if not element.is_a("IfcSpace"):
        return None

    naming_conversion = naming_conversion or {}

    # Create case-insensitive lookup dictionary
    # Filter out NaN/float keys and convert valid keys to strings
    naming_conversion_lower = {str(k).lower(): v for k, v in naming_conversion.items() if
                               k and not (isinstance(k, float) and k != k)}

    def _map(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return value
        # Case-insensitive lookup
        return naming_conversion_lower.get(value.lower(), value) if naming_conversion_lower else value

    def _first_word(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        return value.split()[0]

    # 1) Preferred: Pset_SpaceCommon.Reference (first word)
    try:
        psets = ifcopenshell.util.element.get_psets(element)
        if 'Pset_SpaceCommon' in psets:
            reference = psets['Pset_SpaceCommon'].get('Reference', '')
            if reference:
                roomtype = _map(_first_word(str(reference)))
                if roomtype:
                    # Apply room type cleaning/normalization
                    return clean_room_type(roomtype)
    except:
        pass

    if hasattr(element, "ObjectType") and element.ObjectType:
        roomtype = _map(_first_word(str(element.ObjectType)))
        # Apply room type cleaning/normalization
        return clean_room_type(roomtype)

    # Apply cleaning even to "Unknown"
    return clean_room_type("Unknown")


def geometry_from_shape_fast(shape):
    """
    Fast path for simple geometries - skips graph construction when possible.

    For geometries where all vertices are at the same Z level, we can skip
    the expensive graph-based approach and create a polygon directly.

    Args:
        shape: ifcopenshell geometry shape

    Returns:
        Polygon: 2D polygon, or None if extraction fails
    """
    try:
        nodes = ifcopenshell.util.shape.get_vertices(shape.geometry)

        if len(nodes) < 3:
            return None

        # Check if all vertices at same Z level (simple case)
        z_values = np.unique(nodes[:, 2])

        if len(z_values) == 1:
            # Fast path: all points at same level - create polygon directly
            points_2d = [(x, y) for x, y, z in nodes]
            try:
                polygon = Polygon(points_2d)
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                if polygon.is_valid and polygon.area > 1e-6:
                    return polygon
            except:
                pass  # Fall through to complex method

        # Complex case: use graph-based method
        return geometry_from_shape_complex(shape, nodes)

    except Exception:
        return None


def geometry_from_shape_complex(shape, nodes=None):
    """
    Extract 2D polygon from 3D shape - uses graph-based method for complex geometries.

    This handles:
    - Disconnected floor components (selects largest)
    - Complex geometries with proper edge connectivity
    - Multi-level spaces (extracts floor level only)

    Args:
        shape: ifcopenshell geometry shape
        nodes: optional pre-extracted vertices (for performance)

    Returns:
        Polygon: Largest valid 2D polygon, or None if extraction fails
    """
    try:
        # Extract vertices and edges from shape
        if nodes is None:
            nodes = ifcopenshell.util.shape.get_vertices(shape.geometry)
        edges = ifcopenshell.util.shape.get_edges(shape.geometry)

        # Build graph to understand connectivity
        graph = nx.Graph()
        graph.add_nodes_from([(i, {"position": d}) for i, d in enumerate(nodes)])
        graph.add_edges_from(edges)

        max_area = 0
        best_polygon = None

        # Process each connected component separately
        for subgraph in nx.connected_components(graph):
            nodes_subgraph = np.array([nodes[i] for i in list(subgraph)])

            # Find lowest Z level in this component
            z_values = np.unique(nodes_subgraph[:, 2])
            if len(z_values) == 0:
                continue

            z_low = z_values[0]

            # Extract 2D points at the lowest Z level
            nodes_2d = [(x, y) for x, y, z in nodes_subgraph
                        if z_low - 1e-6 < z < z_low + 1e-6]

            if len(nodes_2d) < 3:
                continue

            try:
                polygon = Polygon(nodes_2d)

                # Fix invalid polygons
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)

                # Keep the largest valid polygon
                if polygon.is_valid and polygon.area > max_area:
                    best_polygon = polygon
                    max_area = polygon.area
            except Exception:
                continue

        return best_polygon

    except Exception:
        return None


# Use the fast path by default
geometry_from_shape = geometry_from_shape_fast


def _process_element_worker(args):
    """Worker function for parallel processing - processes a single element"""
    element_id, ifc_path = args

    # Each worker needs its own IFC model instance
    model = ifcopenshell.open(ifc_path)
    element = model.by_id(element_id)

    processor = IFCGeometryProcessor()
    mesh = processor.process_ifc_element(element, model)

    return element_id, mesh


def get_elements_and_shapes(model, ifc_path, filter_fn=None, filter_expr=None, max_elements=None, parallel=False):
    """
    Extract elements and their geometries from IFC model with optional parallel processing.

    Args:
        model: IFC model
        ifc_path: Path to IFC file (needed for parallel processing)
        filter_fn: Function to filter elements
        filter_expr: IFC filter expression
        max_elements: Maximum number of elements to process (for testing)
        parallel: Use parallel processing (default: False - sequential is faster for most cases)

    Returns:
        Tuple of (elements, meshes)
    """
    # Get elements to process
    if filter_expr and hasattr(model, 'by_type'):
        from ifcopenshell.util.selector import filter_elements
        elements = filter_elements(model, filter_expr)
    else:
        elements = model.by_type("IfcProduct")

    # Filter elements
    if filter_fn:
        elements = [el for el in elements if filter_fn(el)]

    # Limit elements for testing
    if max_elements and len(elements) > max_elements:
        print(f"📄 Limiting to first {max_elements} elements for testing")
        elements = elements[:max_elements]

    print(f"📄 Processing {len(elements)} filtered elements...")

    # Convert to meshes with progress tracking
    valid_elements = []
    meshes = []
    failed_count = 0
    skipped_count = 0

    if parallel and len(elements) > 10:  # Only use parallel for larger sets
        # Parallel processing
        print(f"⚡ Using parallel processing with {cpu_count()} cores")

        # Prepare arguments (element IDs and IFC path)
        element_ids = [el.id() for el in elements if el.Representation is not None]
        args_list = [(el_id, str(ifc_path)) for el_id in element_ids]

        skipped_count = len(elements) - len(element_ids)

        # Process in parallel
        with Pool(cpu_count()) as pool:
            results = list(tqdm(
                pool.imap(_process_element_worker, args_list),
                total=len(args_list),
                desc="Converting elements",
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'
            ))

        # Collect results
        element_id_to_mesh = {el_id: mesh for el_id, mesh in results}

        for element in elements:
            if element.Representation is None:
                continue
            mesh = element_id_to_mesh.get(element.id())
            if mesh is not None:
                valid_elements.append(element)
                meshes.append(mesh)
            else:
                failed_count += 1
    else:
        # Sequential processing (for small sets or when parallel is disabled)
        processor = IFCGeometryProcessor()

        progress_bar = tqdm(elements, desc="Converting elements",
                            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {postfix}')

        for i, element in enumerate(progress_bar):
            if element.Representation is None:
                skipped_count += 1
                continue

            mesh = processor.process_ifc_element(element, model)
            if mesh is not None:
                valid_elements.append(element)
                meshes.append(mesh)
            else:
                failed_count += 1

            # Update progress bar
            processed = i + 1
            success_rate = (len(valid_elements) / processed) * 100 if processed > 0 else 0
            progress_bar.set_postfix({
                'Valid': len(valid_elements),
                'Failed': failed_count,
                'Skipped': skipped_count,
                'Success': f'{success_rate:.1f}%'
            })

    print(f"\n✅ Processing complete!")
    print(f"   📊 Total processed: {len(elements)}")
    print(f"   ✅ Valid geometries: {len(valid_elements)} ({(len(valid_elements) / len(elements) * 100):.1f}%)")
    print(f"   ❌ Failed conversions: {failed_count} ({(failed_count / len(elements) * 100):.1f}%)")
    print(f"   ⭐️ Skipped (no representation): {skipped_count} ({(skipped_count / len(elements) * 100):.1f}%)")

    return valid_elements, meshes


def process_storeys(context):
    """Process floor plans using IfcBuildingStorey elements - OPTIMIZED with storey filtering."""

    model = ifcopenshell.open(context["ifc_path"])
    ifc_path = context["ifc_path"]

    print("Loading building storeys...")
    storeys = list(model.by_type("IfcBuildingStorey"))

    if not storeys:
        print("⚠️  No building storeys found in IFC file")
        return

    # Filter to specific storey if requested
    storey_index = context.get("storey_index")
    if storey_index is not None:
        if storey_index < 0 or storey_index >= len(storeys):
            print(f"❌ Error: Storey index {storey_index} out of range (0-{len(storeys) - 1})")
            print(f"   Use --overview to see available storeys")
            return

        print(f"📍 Processing only storey [{storey_index}]: {storeys[storey_index].Name}")
        storeys = [storeys[storey_index]]
    else:
        print(f"Found {len(storeys)} storeys")

    processor = IFCGeometryProcessor(context['engine'])

    # Process each storey individually (OPTIMIZATION: only load elements for current storey)
    for idx, storey in enumerate(storeys):
        s0 = storey
        name = s0.Name or f"Level_{s0.id()}"

        # Calculate section height
        # Use midpoint between this storey and next, or this storey's elevation if it's the last one
        if idx < len(storeys) - 1:
            s1 = storeys[idx + 1]
            section_height = (s0.Elevation + s1.Elevation) / 2000
        else:
            # Last storey - use this storey's elevation + reasonable offset
            section_height = s0.Elevation / 1000 + 1.5  # 1.5m above floor

        print(f"\n{'=' * 60}")
        print(f"Processing storey: {name} at height {section_height:.2f}m")
        print(f"{'=' * 60}")

        # Get elements for THIS storey only
        storey_elements = get_decomposition(s0)

        # Filter elements by type
        filter_fn = context.get("filter_fn")
        if filter_fn:
            storey_elements = [el for el in storey_elements if filter_fn(el)]

        print(f"Found {len(storey_elements)} elements in this storey")

        if not storey_elements:
            print(f"⚠️  No elements found in storey {name}, skipping")
            continue

        # Convert to meshes (only for this storey - MAJOR OPTIMIZATION)
        storey_element_ids = {el.id() for el in storey_elements}

        # Create a filter that only includes elements from this storey
        def storey_filter(el):
            return el.id() in storey_element_ids and (not filter_fn or filter_fn(el))

        elements, meshes = get_elements_and_shapes(
            model,
            ifc_path,
            filter_fn=storey_filter,
            max_elements=context.get("max_elements"),
            parallel=context.get("parallel", True)
        )

        print(f"Loaded {len(elements)} elements with valid geometry")

        level_polygons = []

        for element, mesh in zip(elements, meshes):
            room_type = get_room_type(element, naming_conversion=context.get("naming_conversion"))

            polygons = processor.engine.intersect_with_plane(
                mesh,
                plane_origin=(0, 0, section_height),
                plane_normal=(0, 0, 1)
            )

            for poly in polygons:
                level_polygons.append((
                    element.is_a(),
                    element.Name or f"{element.is_a()}_{element.id()}",
                    poly,
                    room_type
                ))

        if level_polygons:
            print(f"  Found {len(level_polygons)} intersections")

            for formatter in context["formatters"]:
                formatter.process(name, storey_elements, level_polygons)
        else:
            print(f"  ⚠️  No intersections found for storey {name}")


def process_storeys_space_only(context):
    """
    Process floor plans using ONLY IfcSpace elements - OPTIMIZED space-only mode.

    Core workflow:
    1. Extract IfcSpace elements from each storey
    2. Get room types from Pset_SpaceCommon.Reference
    3. Apply naming conversion (if provided)
    4. Extract 2D geometry using optimized method (fast path + graph fallback)
    5. Output to CSV/images
    """

    model = ifcopenshell.open(context["ifc_path"])
    print("Loading IfcSpace elements only...")

    # Get configuration
    naming_conversion = context.get("naming_conversion", {})

    # Process each storey
    storeys = list(model.by_type("IfcBuildingStorey"))

    # Filter to specific storey if requested
    storey_index = context.get("storey_index")
    if storey_index is not None:
        if storey_index < 0 or storey_index >= len(storeys):
            print(f"❌ Error: Storey index {storey_index} out of range (0-{len(storeys) - 1})")
            print(f"   Use --overview to see available storeys")
            return

        print(f"📍 Processing only storey [{storey_index}]: {storeys[storey_index].Name}")
        storeys = [storeys[storey_index]]

    # Setup geometry settings ONCE (moved outside loop - OPTIMIZATION)
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    # Try optional settings (skip if not available)
    for setting_name in ['SEW_SHELLS', 'USE_BREP_DATA', 'WELD_VERTICES']:
        try:
            setting = getattr(settings, setting_name)
            settings.set(setting, True if setting_name != 'USE_BREP_DATA' else False)
        except AttributeError:
            pass

    for s0 in storeys:
        name = s0.Name or f"Level_{s0.id()}"

        print(f"\n{'=' * 60}")
        print(f"Processing storey: {name}")
        print(f"{'=' * 60}")

        # Get all spaces in this storey
        storey_elements = get_decomposition(s0)
        spaces = [el for el in storey_elements if el.is_a("IfcSpace")]

        print(f"  Found {len(spaces)} IfcSpace elements")

        if not spaces:
            continue

        level_polygons = []
        skipped = 0

        for space in tqdm(spaces, desc=f"Processing {name}", leave=False):
            # Extract room type
            room_type = get_room_type_from_space(space, naming_conversion)

            if room_type is None:
                skipped += 1
                continue

            try:
                # Get shape geometry (using cached settings - OPTIMIZATION)
                shape = ifcopenshell.geom.create_shape(settings, space)

                # Extract 2D polygon using OPTIMIZED method (fast path for simple geometries)
                polygon = geometry_from_shape(shape)

                if polygon is not None and polygon.is_valid and polygon.area > 1e-6:
                    level_polygons.append((
                        "IfcSpace",
                        space.Name or f"Space_{space.id()}",
                        polygon,
                        room_type
                    ))
                else:
                    skipped += 1

            except Exception:
                skipped += 1
                continue

        print(f"  Extracted {len(level_polygons)} valid space polygons ({skipped} skipped)")

        if level_polygons:
            # Run formatters (CSV, images, etc.)
            for formatter in context["formatters"]:
                formatter.process(name, spaces, level_polygons)
