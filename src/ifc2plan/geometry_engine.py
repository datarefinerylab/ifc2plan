import time
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Union
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.strtree import STRtree
import trimesh

# An element that takes longer than this to convert gets named in the log.
# Ordinary elements finish in under 0.2 s and the pathological ones take tens of
# seconds, so the gap is wide and the exact value does not matter much.
SLOW_ELEMENT_SECONDS = 5.0


class GeometryEngine(ABC):
    """Abstract base class for geometry engines"""

    @abstractmethod
    def create_polygon_from_points(self, points: List[Tuple[float, float]]) -> any:
        pass

    @abstractmethod
    def intersect_with_plane(self, geometry: any, plane_origin: Tuple[float, float, float],
                             plane_normal: Tuple[float, float, float]) -> any:
        pass

    @abstractmethod
    def get_polygon_area(self, polygon: any) -> float:
        pass

    @abstractmethod
    def render_to_image(self, geometries: List[any], width: int, height: int,
                        colors: Optional[List[str]] = None) -> np.ndarray:
        pass


class ShapelyTrimeshEngine(GeometryEngine):
    """Geometry engine using Shapely for 2D and Trimesh for 3D operations"""

    def __init__(self):
        self.tolerance = 1e-6
        self.reset_stats()

    def reset_stats(self):
        """Reset the per-run counters reported in the storey summary"""
        self.stats = {
            "open_fragments": 0,   # section entities not part of any closed loop
            "unusable_rings": 0,   # closed loops that yielded no valid polygon
            "elements_affected": 0,  # elements that lost at least one of the above
        }

    def create_polygon_from_points(self, points: List[Tuple[float, float]]) -> Polygon:
        """Create a polygon from a list of 2D points"""
        if len(points) < 3:
            raise ValueError("Need at least 3 points to create a polygon")

        # Ensure the polygon is closed
        if points[0] != points[-1]:
            points = points + [points[0]]

        return Polygon(points)

    def intersect_with_plane(self, mesh: trimesh.Trimesh, plane_origin: Tuple[float, float, float],
                             plane_normal: Tuple[float, float, float]) -> List[Polygon]:
        """
        Intersect a 3D mesh with a plane and return 2D polygons.

        Each solid of the mesh is sectioned on its own. An IFC element is usually
        several solids that touch - a door is a leaf, two frame jambs, stops,
        glazing beads - and they share corner points where they meet. Sectioning
        the whole mesh at once lets trimesh's path builder weld those shared points
        and trace a single chain that hops from one solid to the next across the air
        between them. That chain does not close, and forcing it shut invents an edge
        that is in no solid: on storey 3 of the example file it produced 38 open
        chains with gaps up to 914 mm, and two "doors" that were bare triangles.

        Sectioning per solid removes the opportunity: every loop then closes on its
        own.
        """
        try:
            # Convert to numpy arrays and normalize
            plane_origin = np.array(plane_origin, dtype=float)
            plane_normal = np.array(plane_normal, dtype=float)
            plane_normal = plane_normal / np.linalg.norm(plane_normal)

            polygons = []
            # Tracked across the whole element: an element with 20 solids that
            # loses geometry in 5 of them is one affected element, not five.
            affected = False

            for solid in self._solids(mesh):
                # split() can hand back a solid with no faces, whose bounds are
                # None. Handle it per solid: one empty solid must not abort the
                # rest of the element, or a good part disappears with it.
                try:
                    bounds = solid.bounds
                    if bounds is None:
                        continue

                    low, high = bounds[0][2], bounds[1][2]
                    if not (low <= plane_origin[2] <= high):
                        continue

                    section = solid.section(plane_origin=plane_origin,
                                            plane_normal=plane_normal)
                    if section is None:
                        continue

                    # Stitch this solid's line entities into closed loops, then
                    # work out which loops are holes inside which others.
                    rings, lost = self._closed_rings(section)
                    affected = affected or lost
                    polygons.extend(self._assemble_with_holes(rings))

                except Exception as e:
                    print(f"Warning: Failed to section one solid: {e}")
                    continue

            if affected:
                self.stats["elements_affected"] += 1

            return self._postprocess_polygons(polygons)

        except Exception as e:
            print(f"Warning: Failed to intersect mesh with plane: {e}")
            return []

    def _solids(self, mesh: trimesh.Trimesh) -> List[trimesh.Trimesh]:
        """
        Split a mesh into the separate solids it is made of.

        This relies on the mesh having been built with process=False, so that
        vertices belonging to different solids were never welded together and the
        solids are still separate connected components. See process_ifc_element.
        """
        try:
            solids = mesh.split(only_watertight=False)
        except Exception:
            solids = []

        return list(solids) if len(solids) else [mesh]

    def _closed_rings(self, section: trimesh.path.Path3D) -> Tuple[List[Polygon], bool]:
        """
        Closed loops of a section, as 2D polygons in world XY, plus whether any
        geometry was discarded. This runs once per solid, so the caller is the
        only place that knows where one element ends and the next begins.

        `section.discrete` walks the section's line entities and joins them into
        closed loops, which is what an element outline actually is. Taking each
        entity on its own instead (as this used to) turns one door into a pile of
        disconnected fragments.

        Coordinates stay in world XY on purpose: `section.to_2D()` re-origins onto
        the cutting plane's own frame, and every downstream consumer - WKT output,
        image formatter, room lookup - expects world coordinates.
        """
        try:
            loops = section.discrete
        except Exception:
            loops = []

        rings = []
        unusable = 0
        for loop in loops:
            polys = self._polygons_from_ring(np.asarray(loop))
            if polys:
                rings.extend(polys)
            else:
                unusable += 1

        # Entities that never closed into a loop are dangling fragments. The old
        # code dropped them with a bare `len(points) >= 3` guard; count them so a
        # run that quietly loses geometry says so.
        used = set()
        for path in getattr(section, "paths", []):
            used.update(int(i) for i in path)
        open_fragments = max(len(section.entities) - len(used), 0)

        self.stats["open_fragments"] += open_fragments
        self.stats["unusable_rings"] += unusable

        return rings, bool(open_fragments or unusable)

    def _polygons_from_ring(self, points: np.ndarray) -> List[Polygon]:
        """
        Turn one closed loop into zero or more valid polygons.

        A self-intersecting loop is repaired with buffer(0), which can legitimately
        split it into several pieces - hence a list rather than a single polygon.
        """
        if len(points) < 3:
            return []

        if points.ndim != 2:
            return []

        # Drop Z: the section plane is horizontal, so world XY is the plan view
        if points.shape[1] > 2:
            points = points[:, :2]

        try:
            poly = Polygon(points)
            if not poly.is_valid:
                poly = poly.buffer(0)
        except Exception:
            return []

        if poly.is_empty or not poly.is_valid:
            return []

        parts = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
        return [p for p in parts if isinstance(p, Polygon) and p.area > self.tolerance]

    def _assemble_with_holes(self, rings: List[Polygon]) -> List[Polygon]:
        """
        Nest rings into shells with interiors, using even-odd containment depth.

        A ring contained by an even number of other rings is a shell; one contained
        by an odd number is a hole in its smallest containing shell. This is the
        same rule trimesh's `polygons_full` applies, but built on Shapely's STRtree
        so it needs no `rtree`/libspatialindex native dependency.
        """
        if len(rings) <= 1:
            return rings

        tree = STRtree(rings)

        depth = [0] * len(rings)
        parent = [None] * len(rings)

        # Containment is tested on the whole ring, not on a point inside it. A
        # representative point of the OUTER ring of a hollow section lands inside
        # the inner ring, which made both rings look enclosed, classified both as
        # holes and dropped the element entirely - every tube and hollow column
        # disappeared from the output.
        # The area guard keeps duplicate rings from enclosing each other.
        for i, ring in enumerate(rings):
            for j in tree.query(ring):
                j = int(j)
                if j == i or rings[j].area <= ring.area:
                    continue
                if not rings[j].contains(ring):
                    continue
                depth[i] += 1
                if parent[i] is None or rings[j].area < rings[parent[i]].area:
                    parent[i] = j

        result = []
        for i, ring in enumerate(rings):
            if depth[i] % 2 != 0:
                continue  # a hole; attached to its shell below

            holes = [
                rings[k].exterior.coords
                for k in range(len(rings))
                if parent[k] == i and depth[k] == depth[i] + 1
            ]

            # A ring repaired by buffer(0) in _polygons_from_ring can arrive
            # already carrying interiors. Rebuilding it from its exterior alone
            # would fill those back in and over-state the section's area.
            holes.extend(interior.coords for interior in ring.interiors)

            poly = Polygon(ring.exterior.coords, holes) if holes else ring
            if not poly.is_valid:
                poly = poly.buffer(0)
            result.extend(
                p for p in (poly.geoms if isinstance(poly, MultiPolygon) else [poly])
                if isinstance(p, Polygon) and p.area > self.tolerance
            )

        return result

    def _postprocess_polygons(self, polygons: List[Polygon]) -> List[Polygon]:
        """
        Drop degenerate polygons and exact duplicates.

        This used to unary_union everything "similar to how OCC handles wire
        connections". The union welded a door's distinct sub-parts - leaf, frame
        jambs, glazing beads, stops - into single L-, H- and ring-shaped polygons
        wherever they touched, destroying rectangles that were already correct.

        The union was compensating for the old entity-by-entity assembly, which
        produced open and overlapping fragments. _assemble_with_holes now yields
        properly closed, properly nested loops, so there is nothing left to
        compensate for and parts stay parts.
        """
        result: List[Polygon] = []

        for poly in polygons:
            if poly is None or poly.is_empty or not poly.is_valid:
                continue
            if poly.area <= self.tolerance:
                continue

            # Mesh triangulation leaves vertices sitting exactly on the segment
            # between their neighbours. simplify(0) drops those and nothing else -
            # the area is unchanged to floating point - so an outline is described
            # by its corners rather than by every triangle edge that met it.
            poly = poly.simplify(0)
            if poly.is_empty or not poly.is_valid:
                continue

            # Coincident faces in a mesh can section to the same loop twice
            if any(poly.equals(kept) for kept in result):
                continue
            result.append(poly)

        return result

    def get_polygon_area(self, polygon: Polygon) -> float:
        """Get the area of a polygon"""
        return polygon.area

    def render_to_image(self, geometries: List[Union[Polygon, MultiPolygon]],
                        width: int, height: int, colors: Optional[List[str]] = None) -> np.ndarray:
        """Render geometries to a raster image using matplotlib"""
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
        from matplotlib.collections import PatchCollection
        from io import BytesIO
        import PIL.Image

        # Create figure
        fig, ax = plt.subplots(1, 1, figsize=(width / 100, height / 100), dpi=100)

        # Calculate bounds
        all_bounds = []
        for geom in geometries:
            if geom and not geom.is_empty:
                all_bounds.extend(geom.bounds)

        if not all_bounds:
            # Return blank image if no geometries
            return np.ones((height, width, 3), dtype=np.uint8) * 255

        min_x = min(all_bounds[::2])
        min_y = min(all_bounds[1::2])
        max_x = max(all_bounds[::2])
        max_y = max(all_bounds[1::2])

        # Add padding
        padding = max(max_x - min_x, max_y - min_y) * 0.1
        ax.set_xlim(min_x - padding, max_x + padding)
        ax.set_ylim(min_y - padding, max_y + padding)

        # Render each geometry
        for i, geom in enumerate(geometries):
            if geom is None or geom.is_empty:
                continue

            color = colors[i] if colors and i < len(colors) else 'blue'

            if isinstance(geom, Polygon):
                patch = patches.Polygon(list(geom.exterior.coords),
                                        facecolor=color, alpha=0.7, edgecolor='black')
                ax.add_patch(patch)

                # Add holes
                for interior in geom.interiors:
                    hole_patch = patches.Polygon(list(interior.coords),
                                                 facecolor='white', edgecolor='black')
                    ax.add_patch(hole_patch)

            elif isinstance(geom, MultiPolygon):
                for poly in geom.geoms:
                    patch = patches.Polygon(list(poly.exterior.coords),
                                            facecolor=color, alpha=0.7, edgecolor='black')
                    ax.add_patch(patch)

                    for interior in poly.interiors:
                        hole_patch = patches.Polygon(list(interior.coords),
                                                     facecolor='white', edgecolor='black')
                        ax.add_patch(hole_patch)

        # Remove axes and make it tight
        ax.set_aspect('equal')
        ax.axis('off')
        plt.tight_layout(pad=0)

        # Convert to numpy array
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0, dpi=100)
        buf.seek(0)

        # Load as PIL image and convert to numpy
        pil_img = PIL.Image.open(buf)
        img_array = np.array(pil_img)

        plt.close(fig)
        buf.close()

        # Resize to exact dimensions if needed
        if img_array.shape[:2] != (height, width):
            pil_img = PIL.Image.fromarray(img_array)
            pil_img = pil_img.resize((width, height), PIL.Image.Resampling.LANCZOS)
            img_array = np.array(pil_img)

        return img_array


def representation_face_count(ifc_element) -> int:
    """Faces declared in an element's representation, before any conversion.

    Deliberately a cheap upper-ish estimate read straight off the entity, not an
    exact triangle count: it exists so a caller can predict that an element will
    be expensive *without* paying the create_shape cost that makes it expensive.
    Item types it does not recognise contribute 0, so an unknown representation
    can only make an element look cheaper than it is, never dearer - a wrong
    guess skips nothing.

    That safety rule has a failure mode worth knowing about: a whole schema can
    land in the hole. IfcPolygonalFaceSet and IfcTriangulatedFaceSet are IFC4
    entities that do not exist in IFC2X3, so on an IFC2X3 file the two branches
    below that read tessellations can never fire, and before the brep branch was
    added this returned 0 for 3734 of the 3752 elements in the Schependomlaan
    example - making --max-faces silently inert on that whole schema. When adding
    a body type here, check it against both schemas.
    """
    def count_items(items, depth=0):
        # Mapped representations can nest; the depth bound is paranoia about a
        # cyclic MappingSource rather than a case seen in the data.
        if depth > 4:
            return 0

        total = 0
        for item in items:
            try:
                if item.is_a("IfcPolygonalFaceSet"):
                    total += len(item.Faces or ())
                elif item.is_a("IfcTriangulatedFaceSet"):
                    total += len(item.CoordIndex or ())
                elif item.is_a("IfcManifoldSolidBrep"):
                    # The brep family, matched on the supertype so one branch
                    # covers IfcFacetedBrep (the dominant body type in IFC2X3),
                    # IfcFacetedBrepWithVoids and IFC4's IfcAdvancedBrep. All
                    # three carry the outer shell in `Outer`; only the second
                    # has `Voids`, hence the getattr.
                    outer = item.Outer
                    total += len(outer.CfsFaces or ()) if outer else 0
                    for void in (getattr(item, "Voids", None) or ()):
                        total += len(void.CfsFaces or ())
                elif item.is_a("IfcMappedItem"):
                    source = item.MappingSource
                    if source and source.MappedRepresentation:
                        total += count_items(source.MappedRepresentation.Items, depth + 1)
                elif item.is_a("IfcFaceBasedSurfaceModel"):
                    total += sum(len(s.CfsFaces or ()) for s in (item.FbsmFaces or ()))
                elif item.is_a("IfcShellBasedSurfaceModel"):
                    total += sum(len(getattr(s, "CfsFaces", ()) or ())
                                 for s in (item.SbsmBoundary or ()))
            except (AttributeError, RuntimeError):
                continue
        return total

    try:
        representation = ifc_element.Representation
        if representation is None:
            return 0
        return sum(count_items(rep.Items or ())
                   for rep in (representation.Representations or ()))
    except (AttributeError, RuntimeError):
        return 0


def _describe_element(ifc_element) -> str:
    """Class, id and name - the part of a log line that identifies the element."""
    try:
        name = (getattr(ifc_element, "Name", None) or "").split(":")[0][:50]
        return f"{ifc_element.is_a()} #{ifc_element.id()} {name!r}"
    except (AttributeError, RuntimeError):
        return "element"


def _describe(ifc_element, faces: int) -> str:
    """Short identifier for log lines: class, id, name, tessellation size."""
    return f"{_describe_element(ifc_element)} ({faces:,} faces)"


def representation_identifiers(ifc_element) -> set:
    """The RepresentationIdentifiers an element carries, e.g. {'Axis', 'Body'}."""
    try:
        representation = ifc_element.Representation
        if representation is None:
            return set()
        return {rep.RepresentationIdentifier
                for rep in (representation.Representations or ())
                if rep.RepresentationIdentifier}
    except (AttributeError, RuntimeError):
        return set()


def failure_reason(ifc_element, exception) -> str:
    """
    Why an element could not be converted, in a sentence worth reading (#26).

    The raw ifcopenshell message is a 200-character dump of the STEP line, which
    tells a reader nothing they can act on. The one classification that matters
    is whether there was ever a solid to section: an element carrying no `Body`
    representation cannot produce plan geometry no matter what the sectioning
    code does, and that accounts for every failure observed so far - the
    Axis/Curve2D `dakopstand` walls on the example model, and the
    Axis/MappedRepresentation beams on matchbox.

    Anything else falls back to the exception's first sentence rather than
    pretending to a diagnosis.
    """
    identifiers = representation_identifiers(ifc_element)
    if identifiers and "Body" not in identifiers:
        return f"no Body representation ({'/'.join(sorted(identifiers))} only)"

    detail = str(exception).split(".")[0].strip()
    return detail[:80] or type(exception).__name__


def _report(message: str):
    """Print without tearing a tqdm progress bar."""
    try:
        from tqdm import tqdm
        tqdm.write(message)
    except Exception:
        print(message, flush=True)


class IFCGeometryProcessor:
    """Processor for IFC geometry using the new engine"""

    def __init__(self, engine: GeometryEngine = None,
                 slow_seconds: float = SLOW_ELEMENT_SECONDS,
                 max_faces: Optional[int] = None):
        self.engine = engine or ShapelyTrimeshEngine()
        # Cache settings object to avoid recreating for every element
        self._settings = None

        # Diagnostics for #13. A run used to give no sign of which element it was
        # stuck on: the progress bar simply stopped advancing.
        self.slow_seconds = slow_seconds
        self.max_faces = max_faces
        self.slow_elements = []   # (elapsed, description) over the threshold
        self.skipped_elements = []  # (faces, description) refused by max_faces
        # (description, reason) for #26: a failure used to leave nothing behind
        # but an increment of a counter.
        self.failed_elements = []

    def _get_settings(self):
        """Get or create cached geometry settings"""
        if self._settings is None:
            import ifcopenshell.geom
            self._settings = ifcopenshell.geom.settings()
            self._settings.set(self._settings.USE_WORLD_COORDS, True)
            self._settings.set(self._settings.WELD_VERTICES, True)
        return self._settings

    def process_ifc_element(self, ifc_element, ifc_file) -> Optional[trimesh.Trimesh]:
        """Convert IFC element to trimesh geometry"""
        faces = representation_face_count(ifc_element)

        if self.max_faces is not None and faces > self.max_faces:
            # Opt-in only: this drops geometry, so it is never the default.
            description = _describe(ifc_element, faces)
            self.skipped_elements.append((faces, description))
            _report(f"   ⏭  Skipped over --max-faces {self.max_faces:,}: {description}")
            return None

        started = time.perf_counter()
        try:
            return self._convert(ifc_element, ifc_file)
        finally:
            # In a finally block so an element that is both slow *and* failing is
            # still named. Those are the ones worth knowing about, and
            # _convert swallows the exception that would otherwise reveal them.
            elapsed = time.perf_counter() - started
            if elapsed >= self.slow_seconds:
                description = _describe(ifc_element, faces)
                self.slow_elements.append((elapsed, description))
                _report(f"   ⏱  Slow element: {description} took {elapsed:.1f}s")

    def _record_failure(self, ifc_element, exception):
        """Keep what a failed conversion was, so the run can name it later."""
        self.failed_elements.append(
            (_describe_element(ifc_element), failure_reason(ifc_element, exception))
        )

    def _convert(self, ifc_element, ifc_file) -> Optional[trimesh.Trimesh]:
        try:
            import ifcopenshell.geom

            # Use cached settings
            settings = self._get_settings()

            # Get shape from IFC element
            shape = ifcopenshell.geom.create_shape(settings, ifc_element)

            if shape is None:
                return None

            # Extract vertices and faces
            vertices = shape.geometry.verts
            faces = shape.geometry.faces

            # Reshape vertices (they come as flat array)
            vertices = np.array(vertices).reshape(-1, 3)
            faces = np.array(faces).reshape(-1, 3)

            # process=False is load-bearing, not an optimisation. Trimesh's default
            # processing welds vertices that sit at the same point, and in an IFC
            # element those are the corners where separate solids touch - a door
            # leaf against its frame. Welding them fuses distinct solids into one
            # torn, non-manifold surface: door 670101 goes from 219 vertices, 20
            # watertight solids and 0 broken faces to 128 vertices, 68 fragments
            # and 234 broken faces. ifcopenshell has already welded vertices
            # correctly within each solid (WELD_VERTICES above); doing it again
            # across solids is what corrupts the mesh.
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

            # Apply transformation matrix if available
            if hasattr(shape, 'transformation') and shape.transformation is not None:
                matrix = np.array(shape.transformation.matrix).reshape(4, 4).T
                mesh.apply_transform(matrix)

            return mesh

        except Exception as e:
            # Still skipped, but no longer silently (#26). The two arms this
            # replaces were byte-identical and RuntimeError is an Exception, so
            # splitting them only made the discarding look deliberate.
            self._record_failure(ifc_element, e)
            return None

    def extract_floor_plan_at_height(self, ifc_elements, ifc_file, height: float,
                                     tolerance: float = 0.1) -> List[Polygon]:
        """Extract 2D floor plan at specified height"""
        plane_origin = (0, 0, height)
        plane_normal = (0, 0, 1)  # Z-up

        floor_polygons = []

        for element in ifc_elements:
            mesh = self.process_ifc_element(element, ifc_file)
            if mesh is None:
                continue

            # Check if element intersects with the plane
            bounds = mesh.bounds
            if bounds[2] <= height + tolerance and bounds[5] >= height - tolerance:
                # Element potentially intersects the plane
                polygons = self.engine.intersect_with_plane(mesh, plane_origin, plane_normal)
                if polygons:
                    floor_polygons.extend(polygons)

        return floor_polygons


def create_geometry_engine() -> GeometryEngine:
    """Factory function to create the default geometry engine"""
    return ShapelyTrimeshEngine()


# Test suite
def test_geometry_engine():
    """Test suite for the geometry engine"""
    print("Testing ShapelyTrimeshEngine...")

    engine = ShapelyTrimeshEngine()

    # Test 1: Basic polygon creation
    print("Test 1: Polygon creation")
    points = [(0, 0), (1, 0), (1, 1), (0, 1)]
    poly = engine.create_polygon_from_points(points)
    assert poly.is_valid
    assert abs(poly.area - 1.0) < 1e-6
    print("✓ Polygon creation works")

    # Test 2: Mesh-plane intersection with a simple cube
    print("Test 2: Mesh-plane intersection")

    # Create a simple cube mesh
    cube = trimesh.creation.box(extents=[2, 2, 2])
    cube.apply_translation([1, 1, 1])  # Center at (1,1,1)

    # Intersect with horizontal plane at z=1 (should cut through middle)
    plane_origin = (0, 0, 1)
    plane_normal = (0, 0, 1)
    polygons = engine.intersect_with_plane(cube, plane_origin, plane_normal)

    assert len(polygons) > 0, "Should find intersection"
    total_area = sum(p.area for p in polygons)
    expected_area = 4.0  # 2x2 square
    assert abs(total_area - expected_area) < 0.1, f"Area mismatch: {total_area} vs {expected_area}"
    print("✓ Mesh-plane intersection works")

    # Test 3: No intersection case
    print("Test 3: No intersection case")
    high_plane = (0, 0, 10)  # Way above the cube
    no_polygons = engine.intersect_with_plane(cube, high_plane, plane_normal)
    assert len(no_polygons) == 0, "Should find no intersection"
    print("✓ No intersection case works")

    # Test 4: Complex mesh intersection
    print("Test 4: Complex mesh intersection")

    # Create a more complex mesh (cylinder)
    cylinder = trimesh.creation.cylinder(radius=1, height=3)
    cylinder.apply_translation([0, 0, 1.5])  # Center at z=1.5

    # Intersect with plane at z=1.5 (middle)
    plane_origin = (0, 0, 1.5)
    cyl_polygons = engine.intersect_with_plane(cylinder, plane_origin, plane_normal)

    assert len(cyl_polygons) > 0, "Should find cylinder intersection"
    # Should be approximately circular with area π*r²
    total_area = sum(p.area for p in cyl_polygons)
    expected_area = np.pi * 1 ** 2
    assert abs(total_area - expected_area) < 0.2, f"Cylinder area mismatch: {total_area} vs {expected_area}"
    print("✓ Complex mesh intersection works")

    print("All tests passed! ✓")


if __name__ == "__main__":
    test_geometry_engine()
