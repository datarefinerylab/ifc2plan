import os

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.shape
import ifcopenshell.util.unit
import ifcopenshell.ifcopenshell_wrapper
import numpy as np
import networkx as nx
from ifcopenshell.util.element import get_decomposition
from shapely.geometry import Polygon, LineString
from shapely.ops import polygonize, unary_union
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
from functools import partial

from geometry_engine import IFCGeometryProcessor, SLOW_ELEMENT_SECONDS
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
    Extract room type from an IfcSpace.

    Delegates to get_room_type so the two cannot drift apart. They had: this one
    looked only at Pset_SpaceCommon.Reference and returned None without it, which
    on the example file meant None for all 100 spaces while get_room_type
    returned a value for all 100.

    Args:
        space: IfcSpace element
        naming_conversion: dict mapping original names to English names (case-insensitive)

    Returns:
        str: Room type, or None if the element is not an IfcSpace
    """
    return get_room_type(space, naming_conversion=naming_conversion)


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

    # 2) IfcSpace.LongName. The docstring has always promised this step but the
    # code went straight from the pset to ObjectType, so a model that names its
    # rooms only in LongName - as the Schependomlaan example does, where not one
    # of the 100 spaces carries Pset_SpaceCommon.Reference - came out entirely as
    # "Unknown". Matching on the first word is what makes 'slaapkamer 1' and
    # 'slaapkamer 2' resolve to the single 'slaapkamer' entry in the conversion.
    if getattr(element, "LongName", None):
        roomtype = _map(_first_word(str(element.LongName)))
        if roomtype:
            return clean_room_type(roomtype)

    if hasattr(element, "ObjectType") and element.ObjectType:
        roomtype = _map(_first_word(str(element.ObjectType)))
        # Apply room type cleaning/normalization
        return clean_room_type(roomtype)

    # Apply cleaning even to "Unknown"
    return clean_room_type("Unknown")


def get_room_name_original(element):
    """
    The raw room name as it appears in the model, before any mapping.

    Returned alongside the converted room type so the naming conversion is not
    lossy: 35 of the example file's 100 spaces have no entry in
    naming_conversion.csv, and without this their original Dutch name would only
    survive as a "remaining_" prefix. Downstream work can still group on the real
    name, and it makes the gaps in the conversion table visible.

    Args:
        element: IFC element (only IfcSpace carries room names)

    Returns:
        str: raw name, or "" when the element has none
    """
    if not element.is_a("IfcSpace"):
        return ""

    try:
        psets = ifcopenshell.util.element.get_psets(element)
        reference = psets.get('Pset_SpaceCommon', {}).get('Reference', '')
        if reference:
            return str(reference).strip()
    except Exception:
        pass

    if getattr(element, "LongName", None):
        return str(element.LongName).strip()

    if getattr(element, "ObjectType", None):
        return str(element.ObjectType).strip()

    return ""


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


def space_geometry_settings():
    """
    Geometry settings for reading space outlines.

    dimensionality is the whole of issue #4. It defaults to SURFACES_AND_SOLIDS,
    which silently excludes curve-only representations - and 94 of the example
    file's 100 spaces carry nothing but a FootPrint/GeometricCurveSet, so
    create_shape raised "Failed to process shape" for all of them. Including
    curves makes all 100 load.

    The settings this replaced probed SEW_SHELLS and USE_BREP_DATA, neither of
    which exists in ifcopenshell 0.8.x; the surrounding `except AttributeError:
    pass` meant the block quietly configured almost nothing.
    """
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("weld-vertices", True)
    settings.set("dimensionality",
                 ifcopenshell.ifcopenshell_wrapper.CURVES_SURFACES_AND_SOLIDS)
    return settings


def _polygon_from_edges(shape):
    """
    Assemble the outline by following the shape's edges.

    A footprint comes back as a vertex list plus an edge list. Building a polygon
    straight from the vertex list assumes ifcopenshell returns them in ring order.
    That happens to hold for every space in the example file - all 94 footprints
    have strictly sequential edges - but it is not guaranteed, and where it fails
    it fails silently by producing a self-intersecting shape rather than an error.
    Following the edges removes the assumption.

    Returns None when the edges close into no usable ring at all, leaving the
    caller to fall back on vertex order.
    """
    try:
        verts = ifcopenshell.util.shape.get_vertices(shape.geometry)
        edges = ifcopenshell.util.shape.get_edges(shape.geometry)
        if len(verts) < 3 or len(edges) < 3:
            return None

        lines = [LineString([verts[a][:2], verts[b][:2]]) for a, b in edges]
        rings = [p for p in polygonize(unary_union(lines))
                 if p.is_valid and p.area > 1e-6]
        if not rings:
            return None

        # A footprint with a courtyard, atrium or service shaft closes into more
        # than one ring: polygonize returns the outline already carrying the hole
        # as an interior, *plus* the hole again as a filled ring of its own.
        # Requiring exactly one ring rejected that correct result and sent the
        # caller to the vertex-order fallback, which concatenates the loops into
        # one self-intersecting list - so buffer(0) produced a shape matching
        # neither the outline-with-hole nor the outline alone, and it passed
        # every check in space_outline_polygon. Drop the rings that sit inside
        # another ring's hole and keep the outlines.
        filled = [Polygon(p.exterior) for p in rings]
        points = [p.representative_point() for p in rings]
        outlines = [p for i, p in enumerate(rings)
                    if not any(j != i and filled[j].contains(points[i])
                               for j in range(len(rings)))]
        if not outlines:
            return None

        # What survives can still be several *adjacent* faces rather than one
        # outline: any edge crossing the interior - an internal divider, or a
        # solid clipped by a roof or stair - splits the footprint into tiles
        # that are all equally "outer". Taking the largest would return one tile
        # and call half a room a whole one, so merge them first. The union runs
        # after the containment filter, not before: unioning the raw rings would
        # weld each hole back into its outline and quietly fill the courtyard in.
        merged = unary_union(outlines)
        if merged.geom_type == "Polygon":
            return merged

        # Genuinely disjoint parts of one IfcSpace. One polygon per space is all
        # the rest of the pipeline carries, so take the largest - still a real
        # outline, unlike the self-intersecting fallback.
        return max(outlines, key=lambda p: p.area)
    except Exception:
        return None


def space_outline_polygon(space, settings):
    """
    The plan outline of a single IfcSpace, or None.

    Used by both the default and the --space-only path so spaces are extracted the
    same way everywhere. Spaces are never sectioned: a FootPrint curve already is
    the plan geometry, and the 6 spaces that do have a Body are handled by the
    same call through geometry_from_shape's graph-based branch.

    Returns:
        (polygon, reason) - reason is None on success, otherwise a short string
        naming why nothing came out, so the caller can report it instead of
        counting it as an anonymous "skipped".
    """
    try:
        shape = ifcopenshell.geom.create_shape(settings, space)
    except Exception as e:
        # An exception with a blank message splitlines() to [], so indexing it
        # raised out of the handler whose whole job is to keep one unreadable
        # space from taking the file down.
        detail = (str(e).splitlines() or [type(e).__name__])[0]
        return None, f"create_shape failed: {detail[:80]}"

    polygon = _polygon_from_edges(shape)
    if polygon is None:
        polygon = geometry_from_shape(shape)

    if polygon is None:
        return None, "no polygon could be built from the shape"
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or not polygon.is_valid:
        return None, "polygon invalid after repair"
    if polygon.area <= 1e-6:
        return None, f"degenerate area {polygon.area:.2e}"

    return polygon, None


def space_representations(space):
    """Representation identifier/type pairs, for reporting what a space carries"""
    try:
        reps = space.Representation.Representations if space.Representation else []
        return ", ".join(f"{r.RepresentationIdentifier}/{r.RepresentationType}"
                         for r in reps) or "none"
    except Exception:
        return "unknown"


# Per-process state for the parallel path. Each worker process opens the model
# once in _init_worker and reuses it for every element it handles; these globals
# are how the initializer hands it to the worker, since Pool gives no other way
# to keep state between tasks.
_worker_model = None
_worker_processor = None


def _init_worker(ifc_path, slow_seconds=SLOW_ELEMENT_SECONDS, max_faces=None):
    """Pool initializer: open the model once per worker process."""
    global _worker_model, _worker_processor
    _worker_model = ifcopenshell.open(ifc_path)
    _worker_processor = IFCGeometryProcessor(slow_seconds=slow_seconds, max_faces=max_faces)


def _process_element_worker(element_id):
    """Worker function for parallel processing - processes a single element.

    Opening the model belongs in _init_worker, not here. It used to happen per
    element, which on a 97 MB model cost 1.9 s of parsing for ~0.03 s of geometry
    - so the parallel path lost to plain sequential processing (2127 s against
    335 s for one storey of spot-a2). Same storey now takes 208 s.

    Returns the element's diagnostics alongside its mesh because the worker runs
    in another process: the processor's own lists accumulate there and the parent
    never sees them, so anything needed for the end-of-pass summary has to travel
    back with the result.
    """
    element = _worker_model.by_id(element_id)

    del _worker_processor.slow_elements[:]
    del _worker_processor.skipped_elements[:]

    mesh = _worker_processor.process_ifc_element(element, _worker_model)

    diagnostics = (list(_worker_processor.slow_elements),
                   list(_worker_processor.skipped_elements))

    return element_id, mesh, diagnostics


def _worker_count(ifc_path):
    """How many workers a model of this size can afford.

    A parsed model is roughly 6x the file on disk (97 MB -> ~600 MB resident) and
    every worker holds its own copy, so on a large model the core count is not the
    binding constraint - memory is. Overcommitting here is what turns a slow run
    into a swapping one.
    """
    cores = cpu_count()
    try:
        budget = _memory_budget_bytes()
        footprint = os.path.getsize(ifc_path) * 6
    except OSError:
        return cores

    if not budget or footprint <= 0:
        return cores

    return max(1, min(cores, int(budget // footprint)))


def _memory_budget_bytes():
    """Bytes of RAM the pool may use, or None if it cannot be determined.

    Half of physical memory: the parent process is holding its own copy of the
    model at the same time, and the OS needs room to not swap.
    """
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None
    return total // 2


def get_elements_and_shapes(model, ifc_path, filter_fn=None, filter_expr=None, max_elements=None,
                            parallel=False, slow_seconds=SLOW_ELEMENT_SECONDS, max_faces=None):
    """
    Extract elements and their geometries from IFC model with optional parallel processing.

    Args:
        model: IFC model
        ifc_path: Path to IFC file (needed for parallel processing)
        filter_fn: Function to filter elements
        filter_expr: IFC filter expression
        max_elements: Maximum number of elements to process (for testing)
        parallel: Use parallel processing (default: False - sequential is faster for most cases)
        slow_seconds: Name any element taking longer than this to convert
        max_faces: Skip elements whose representation declares more faces than
            this. Off by default - it drops geometry, so it is opt-in only.

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

    # Diagnostics for #13, gathered from whichever path runs below.
    slow_elements = []
    face_skipped = []

    if parallel and len(elements) > 10:  # Only use parallel for larger sets
        # Parallel processing
        workers = _worker_count(ifc_path)
        print(f"⚡ Using parallel processing with {workers} of {cpu_count()} cores")

        # Prepare arguments (element IDs; the model itself is opened per worker)
        element_ids = [el.id() for el in elements if el.Representation is not None]

        skipped_count = len(elements) - len(element_ids)

        # Process in parallel
        with Pool(workers, initializer=_init_worker,
                  initargs=(str(ifc_path), slow_seconds, max_faces)) as pool:
            results = list(tqdm(
                pool.imap(_process_element_worker, element_ids),
                total=len(element_ids),
                desc="Converting elements",
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'
            ))

        # Collect results
        element_id_to_mesh = {el_id: mesh for el_id, mesh, _ in results}
        for _, _, (slow, skipped) in results:
            slow_elements.extend(slow)
            face_skipped.extend(skipped)

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
        processor = IFCGeometryProcessor(slow_seconds=slow_seconds, max_faces=max_faces)
        slow_elements = processor.slow_elements
        face_skipped = processor.skipped_elements

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

    # A filter matching nothing is reachable now that spaces are excluded from
    # the mesh pass: a storey holding only IfcSpace leaves it empty. Percentages
    # of nothing raised ZeroDivisionError, and process_ifc_file catches per file,
    # so one such storey took every remaining storey of that file down with it.
    total = len(elements)
    pct = (lambda n: f"{n / total * 100:.1f}%") if total else (lambda n: "n/a")

    print(f"\n✅ Processing complete!")
    print(f"   📊 Total processed: {total}")
    print(f"   ✅ Valid geometries: {len(valid_elements)} ({pct(len(valid_elements))})")
    print(f"   ❌ Failed conversions: {failed_count} ({pct(failed_count)})")
    print(f"   ⭐️ Skipped (no representation): {skipped_count} ({pct(skipped_count)})")

    if face_skipped:
        total_faces = sum(faces for faces, _ in face_skipped)
        print(f"   ⏭  Skipped (over --max-faces): {len(face_skipped)} "
              f"({total_faces:,} faces not converted)")

    # The point of #13: a storey that takes half an hour should say where the time
    # went. Four elements out of 669 were 99% of one storey's conversion time and
    # nothing in the output named them.
    if slow_elements:
        slowest = sorted(slow_elements, reverse=True)[:5]
        share = sum(elapsed for elapsed, _ in slow_elements)
        print(f"\n   ⏱  {len(slow_elements)} slow element(s), {share:.0f}s total:")
        for elapsed, description in slowest:
            print(f"      {elapsed:7.1f}s  {description}")
        if len(slow_elements) > len(slowest):
            print(f"      ... and {len(slow_elements) - len(slowest)} more")

    return valid_elements, meshes


def storey_elevation_metres(storey, unit_scale):
    """
    A storey's elevation in metres.

    IfcBuildingStorey.Elevation is in the model's own length unit, but
    ifcopenshell hands back geometry already converted to metres. Mixing the two
    is the unit half of issue #3: this model declares MILLI METRE, so dividing by
    1000 was accidentally right and the bug stayed invisible on it.
    """
    elevation = getattr(storey, "Elevation", None)
    return (elevation or 0.0) * unit_scale


def mesh_z_spans(meshes):
    """(low, high) z-extent of each mesh, skipping any without usable bounds"""
    spans = []
    for mesh in meshes:
        try:
            bounds = mesh.bounds
            if bounds is None:
                continue
            spans.append((float(bounds[0][2]), float(bounds[1][2])))
        except Exception:
            continue
    return spans


def best_covering_height(spans):
    """
    The height crossed by the most meshes, or None if there is nothing to cut.

    Used only as a fallback when the requested plane lies outside a storey's
    geometry entirely. Candidates are the midpoints between consecutive z edges,
    so the plane lands strictly inside a span rather than exactly on a face,
    where sectioning is degenerate.
    """
    if not spans:
        return None, 0

    edges = sorted({z for span in spans for z in span})
    candidates = [(a + b) / 2 for a, b in zip(edges, edges[1:])]
    if not candidates:
        return None, 0

    best_height, best_count = None, 0
    for height in candidates:
        count = sum(1 for low, high in spans if low <= height <= high)
        if count > best_count:
            best_height, best_count = height, count

    return best_height, best_count


def process_storeys(context):
    """Process floor plans using IfcBuildingStorey elements - OPTIMIZED with storey filtering."""

    model = ifcopenshell.open(context["ifc_path"])
    ifc_path = context["ifc_path"]

    print("Loading building storeys...")
    storeys = list(model.by_type("IfcBuildingStorey"))

    # Metres per model unit. Read from the model rather than assumed: a
    # metre-based file was previously cut at 1/1000 of the intended height.
    unit_scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    section_offset = context.get("section_offset", 1.5)

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
    space_settings = space_geometry_settings()

    # Process each storey individually (OPTIMIZATION: only load elements for current storey)
    for idx, storey in enumerate(storeys):
        s0 = storey
        name = s0.Name or f"Level_{s0.id()}"

        # Section height: a fixed offset above this storey's own elevation.
        # The old rule used the midpoint to the storey above, which depended on
        # the storey list and so gave a different height under --storey N than in
        # a full run (the single-storey path leaves one entry, taking the
        # last-storey branch). This depends on nothing but the storey itself.
        elevation = storey_elevation_metres(s0, unit_scale)
        section_height = elevation + section_offset

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

        # Spaces are not sectioned. A room's FootPrint curve already is its plan
        # outline, and most spaces have no solid to cut anyway - 94 of the example
        # file's 100 carry only FootPrint/GeometricCurveSet, so the mesh path
        # produced nothing for them and the whole storey's rooms came out of the
        # handful that happened to have a Body. Extracting all of them the same
        # way is both more complete and more consistent.
        storey_spaces = [el for el in storey_elements if el.is_a("IfcSpace")]

        # Convert to meshes (only for this storey - MAJOR OPTIMIZATION)
        storey_element_ids = {el.id() for el in storey_elements
                              if not el.is_a("IfcSpace")}

        # Create a filter that only includes elements from this storey
        def storey_filter(el):
            return el.id() in storey_element_ids and (not filter_fn or filter_fn(el))

        if storey_element_ids:
            elements, meshes = get_elements_and_shapes(
                model,
                ifc_path,
                filter_fn=storey_filter,
                max_elements=context.get("max_elements"),
                parallel=context.get("parallel", True),
                slow_seconds=context.get("slow_seconds", SLOW_ELEMENT_SECONDS),
                max_faces=context.get("max_faces"),
            )
        else:
            # Nothing but spaces on this storey, so the mesh pass has no work to
            # do. Its outlines are still extracted below.
            elements, meshes = [], []

        print(f"Loaded {len(elements)} elements with valid geometry")

        # A storey's geometry is not always where its datum implies. In the
        # example file '-1 fundering' sits entirely below its own elevation and
        # '04 dak' entirely below elevation + 1.5 m, so the requested plane misses
        # the storey completely and it silently produces nothing. Fall back to a
        # height that actually cuts something, and say so.
        spans = mesh_z_spans(meshes)
        if spans:
            storey_low = min(low for low, _ in spans)
            storey_high = max(high for _, high in spans)
            if not (storey_low <= section_height <= storey_high):
                fallback, crossed = best_covering_height(spans)
                print(f"  ⚠️  Plane at {section_height:.2f}m is outside this storey's "
                      f"geometry ({storey_low:.2f}m..{storey_high:.2f}m)")
                if fallback is None:
                    print(f"      No usable fallback height; storey will be empty")
                else:
                    print(f"      Falling back to {fallback:.2f}m, crossing "
                          f"{crossed} of {len(spans)} elements")
                    section_height = fallback

        level_polygons = []
        missed = Counter()

        processor.engine.reset_stats()

        for element, mesh in zip(elements, meshes):
            room_type = get_room_type(element, naming_conversion=context.get("naming_conversion"))

            # Elements that never reach the plane produce nothing and used to
            # vanish without trace. Record them by type so a thin output is
            # attributable rather than mysterious.
            bounds = getattr(mesh, "bounds", None)
            if bounds is not None and not (bounds[0][2] <= section_height <= bounds[1][2]):
                missed[element.is_a()] += 1
                continue

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
                    room_type,
                    get_room_name_original(element)
                ))

        # Spaces, from their footprint rather than a section
        space_failures = []
        for space in storey_spaces:
            polygon, reason = space_outline_polygon(space, space_settings)
            if polygon is None:
                space_failures.append((space, reason))
                continue
            level_polygons.append((
                "IfcSpace",
                space.Name or f"Space_{space.id()}",
                polygon,
                get_room_type(space, naming_conversion=context.get("naming_conversion")),
                get_room_name_original(space)
            ))

        if storey_spaces:
            print(f"  Extracted {len(storey_spaces) - len(space_failures)} of "
                  f"{len(storey_spaces)} space outline(s)")
        for space, reason in space_failures:
            print(f"  ⚠️  No geometry for IfcSpace {space.id()} "
                  f"{space.Name or '(unnamed)'!r} [{space_representations(space)}]: {reason}")

        if missed:
            total_missed = sum(missed.values())
            breakdown = ", ".join(f"{n} {t}" for t, n in missed.most_common())
            print(f"  ⚠️  {total_missed} of {len(elements)} element(s) do not reach "
                  f"the {section_height:.2f}m plane: {breakdown}")

        if level_polygons:
            print(f"  Found {len(level_polygons)} intersections")

            stats = processor.engine.stats
            if stats["open_fragments"] or stats["unusable_rings"]:
                print(f"  ⚠️  Discarded section geometry on "
                      f"{stats['elements_affected']} element(s): "
                      f"{stats['open_fragments']} open fragment(s), "
                      f"{stats['unusable_rings']} unusable ring(s)")

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
    settings = space_geometry_settings()

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
        failures = []

        # Room type no longer decides whether geometry is attempted. It used to:
        # a space with no room type was skipped before create_shape was called,
        # and since get_room_type_from_space needed Pset_SpaceCommon.Reference -
        # which not one space in the example file has - that discarded every
        # space in the model before geometry was ever tried.
        for space in tqdm(spaces, desc=f"Processing {name}", leave=False):
            polygon, reason = space_outline_polygon(space, settings)

            if polygon is None:
                failures.append((space, reason))
                continue

            level_polygons.append((
                "IfcSpace",
                space.Name or f"Space_{space.id()}",
                polygon,
                get_room_type_from_space(space, naming_conversion),
                get_room_name_original(space)
            ))

        print(f"  Extracted {len(level_polygons)} valid space polygons "
              f"({len(failures)} without geometry)")

        # Name every space that produced nothing, with what it actually carries.
        # A bare "skipped" count reads like filtering rather than data loss.
        for space, reason in failures:
            print(f"  ⚠️  No geometry for IfcSpace {space.id()} "
                  f"{space.Name or '(unnamed)'!r} [{space_representations(space)}]: {reason}")

        if level_polygons:
            # Run formatters (CSV, images, etc.)
            for formatter in context["formatters"]:
                formatter.process(name, spaces, level_polygons)
