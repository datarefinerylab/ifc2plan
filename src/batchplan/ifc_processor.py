import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.shape
import numpy as np
import networkx as nx
from ifcopenshell.util.element import get_decomposition
from shapely.geometry import Polygon
from tqdm import tqdm

from geometry_engine import IFCGeometryProcessor


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
        str: Room type or None if not found
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

                return roomtype
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
        str: Room type or "Unknown" if not found, None if not IfcSpace
    """
    # Only process IfcSpace elements
    if not element.is_a("IfcSpace"):
        return None

    naming_conversion = naming_conversion or {}

    # Create case-insensitive lookup dictionary
    # Filter out NaN/float keys and convert valid keys to strings
    naming_conversion_lower = {str(k).lower(): v for k, v in naming_conversion.items() if k and not (isinstance(k, float) and k != k)}

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
                    return roomtype
    except:
        pass

    if hasattr(element, "ObjectType") and element.ObjectType:
        return _map(_first_word(str(element.ObjectType)))

    return "Unknown"


def geometry_from_shape(shape):
    """
    Extract 2D polygon from 3D shape - uses notebook's proven graph-based method.

    This handles:
    - Disconnected floor components (selects largest)
    - Complex geometries with proper edge connectivity
    - Multi-level spaces (extracts floor level only)

    Args:
        shape: ifcopenshell geometry shape

    Returns:
        Polygon: Largest valid 2D polygon, or None if extraction fails
    """
    try:
        # Extract vertices and edges from shape
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


def get_elements_and_shapes(model, filter_fn=None, filter_expr=None, max_elements=None):
    """
    Extract elements and their geometries from IFC model.

    Args:
        model: IFC model
        filter_fn: Function to filter elements
        filter_expr: IFC filter expression
        max_elements: Maximum number of elements to process (for testing)

    Returns:
        Tuple of (elements, meshes)
    """
    processor = IFCGeometryProcessor()

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
    """Process floor plans using IfcBuildingStorey elements - full geometry mode."""

    model = ifcopenshell.open(context["ifc_path"])
    print("Loading and filtering elements...")

    elements, meshes = get_elements_and_shapes(
        model,
        filter_fn=context.get("filter_fn"),
        max_elements=context.get("max_elements")
    )

    print(f"Loaded {len(elements)} elements with valid geometry")

    processor = IFCGeometryProcessor(context['engine'])

    # Process each storey
    storeys = list(model.by_type("IfcBuildingStorey"))

    for s0, s1 in zip(storeys[:-1], storeys[1:]):
        name = s0.Name or f"Level_{s0.id()}"
        section_height = (s0.Elevation + s1.Elevation) / 2000

        print(f"Processing storey: {name} at height {section_height:.2f}m")

        storey_elements = get_decomposition(s0)
        storey_element_ids = {el.id() for el in storey_elements}

        level_polygons = []

        for element, mesh in zip(elements, meshes):
            if element.id() in storey_element_ids:
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


def process_storeys_space_only(context):
    """
    Process floor plans using ONLY IfcSpace elements - space-only mode.

    Core workflow:
    1. Extract IfcSpace elements from each storey
    2. Get room types from Pset_SpaceCommon.Reference
    3. Apply naming conversion (if provided)
    4. Extract 2D geometry using graph-based method
    5. Output to CSV/images
    """

    model = ifcopenshell.open(context["ifc_path"])
    print("Loading IfcSpace elements only...")

    # Get configuration
    naming_conversion = context.get("naming_conversion", {})

    # Process each storey
    storeys = list(model.by_type("IfcBuildingStorey"))

    for s0 in storeys:
        name = s0.Name or f"Level_{s0.id()}"

        print(f"\nProcessing storey: {name}")

        # Get all spaces in this storey
        storey_elements = get_decomposition(s0)
        spaces = [el for el in storey_elements if el.is_a("IfcSpace")]

        print(f"  Found {len(spaces)} IfcSpace elements")

        if not spaces:
            continue

        # Setup geometry settings - version-compatible
        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)

        # Try optional settings (skip if not available)
        for setting_name in ['SEW_SHELLS', 'USE_BREP_DATA', 'WELD_VERTICES']:
            try:
                setting = getattr(settings, setting_name)
                settings.set(setting, True if setting_name != 'USE_BREP_DATA' else False)
            except AttributeError:
                pass

        level_polygons = []
        skipped = 0

        for space in tqdm(spaces, desc=f"Processing {name}", leave=False):
            # Extract room type
            room_type = get_room_type_from_space(space, naming_conversion)

            if room_type is None:
                skipped += 1
                continue

            try:
                # Get shape geometry
                shape = ifcopenshell.geom.create_shape(settings, space)

                # Extract 2D polygon using notebook's graph-based method
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
