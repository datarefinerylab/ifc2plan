from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Union
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
import trimesh


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
        Intersect a 3D mesh with a plane and return 2D polygons
        """
        try:
            # Convert to numpy arrays and normalize
            plane_origin = np.array(plane_origin, dtype=float)
            plane_normal = np.array(plane_normal, dtype=float)
            plane_normal = plane_normal / np.linalg.norm(plane_normal)

            # Use trimesh's section method - this is the key replacement for OCC
            section = mesh.section(plane_origin=plane_origin, plane_normal=plane_normal)

            if section is None:
                return []

            # Stitch the section's line entities into closed loops, then work out
            # which loops are holes inside which others.
            rings = self._closed_rings(section)
            polygons = self._assemble_with_holes(rings)

            return self._postprocess_polygons(polygons)

        except Exception as e:
            print(f"Warning: Failed to intersect mesh with plane: {e}")
            return []

    def _closed_rings(self, section: trimesh.path.Path3D) -> List[Polygon]:
        """
        Closed loops of a section, as 2D polygons in world XY.

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
        if open_fragments or unusable:
            self.stats["elements_affected"] += 1

        return rings

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
        points = [r.representative_point() for r in rings]

        depth = [0] * len(rings)
        parent = [None] * len(rings)

        for i, point in enumerate(points):
            for j in tree.query(point):
                j = int(j)
                if j == i or not rings[j].contains(point):
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

            poly = Polygon(ring.exterior.coords, holes) if holes else ring
            if not poly.is_valid:
                poly = poly.buffer(0)
            result.extend(
                p for p in (poly.geoms if isinstance(poly, MultiPolygon) else [poly])
                if isinstance(p, Polygon) and p.area > self.tolerance
            )

        return result

    def _postprocess_polygons(self, polygons: List[Polygon]) -> List[Polygon]:
        """Post-process polygons to match OCC behavior"""
        if not polygons:
            return []

        # Remove duplicates and merge overlapping polygons
        valid_polygons = []
        for poly in polygons:
            if poly is not None and poly.is_valid and poly.area > self.tolerance:
                valid_polygons.append(poly)

        if not valid_polygons:
            return []

        # Merge overlapping polygons (similar to how OCC handles wire connections)
        try:
            union_result = unary_union(valid_polygons)
            if isinstance(union_result, Polygon):
                return [union_result]
            elif isinstance(union_result, MultiPolygon):
                return list(union_result.geoms)
            else:
                return valid_polygons
        except Exception:
            return valid_polygons

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


class IFCGeometryProcessor:
    """Processor for IFC geometry using the new engine"""

    def __init__(self, engine: GeometryEngine = None):
        self.engine = engine or ShapelyTrimeshEngine()
        # Cache settings object to avoid recreating for every element
        self._settings = None

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

            # Create trimesh
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces)

            # Apply transformation matrix if available
            if hasattr(shape, 'transformation') and shape.transformation is not None:
                matrix = np.array(shape.transformation.matrix).reshape(4, 4).T
                mesh.apply_transform(matrix)

            return mesh

        except RuntimeError as e:
            # Skip problematic elements silently
            return None
        except Exception as e:
            # Skip other errors silently
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
