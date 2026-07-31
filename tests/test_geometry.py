"""
Ring assembly and polygon repair. No IFC file is touched here.

Every case below is a bug that reached main or was one review away from it, so
these are regression tests rather than illustrations. `_polygon_from_edges` takes
a shape and asks ifcopenshell for its vertices and edges; the fixtures fake that
pair directly, which is what lets a courtyard or a clipped solid be expressed in
four lines instead of a hand-built IFC file.
"""

import pytest
from shapely.geometry import Polygon

import ifc_processor
import ifcopenshell.util.shape

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]          # area 100
COURTYARD = [(4, 1), (6, 1), (6, 9), (4, 9)]           # area 16, inside SQUARE
DETACHED = [(20, 0), (26, 0), (26, 6), (20, 6)]        # area 36, disjoint


class _Shape:
    """Stands in for an ifcopenshell shape; only .geometry is ever read."""

    def __init__(self, verts, edges):
        self.geometry = self
        self.verts = verts
        self.edges = edges


def build_shape(loops, extra_edges=()):
    """A shape whose edges trace each loop in order, plus any extra edges."""
    verts, edges, offset = [], [], 0
    for loop in loops:
        n = len(loop)
        verts.extend((x, y, 0.0) for x, y in loop)
        edges.extend((offset + i, offset + (i + 1) % n) for i in range(n))
        offset += n
    return _Shape(verts, list(edges) + list(extra_edges))


@pytest.fixture(autouse=True)
def fake_shape_reader(monkeypatch):
    """Point ifcopenshell's vertex/edge readers at the fake shapes above."""
    monkeypatch.setattr(ifcopenshell.util.shape, "get_vertices", lambda g: g.verts)
    monkeypatch.setattr(ifcopenshell.util.shape, "get_edges", lambda g: g.edges)


def test_simple_outline():
    poly = ifc_processor._polygon_from_edges(build_shape([SQUARE]))
    assert poly is not None
    assert poly.area == pytest.approx(100.0)
    assert len(poly.interiors) == 0


def test_courtyard_keeps_its_hole():
    """
    A footprint with a courtyard polygonizes into two rings: the outline already
    carrying the hole, plus the hole again as a filled ring. Requiring exactly
    one ring rejected the correct result and fell back to vertex order, which
    concatenates both loops into a self-intersecting list - buffer(0) then
    returned 88.89, matching neither the outline with its hole (84) nor the
    outline alone (100), and every validity check passed.
    """
    poly = ifc_processor._polygon_from_edges(build_shape([SQUARE, COURTYARD]))
    assert poly is not None
    assert len(poly.interiors) == 1, "the courtyard must survive as a hole"
    assert poly.area == pytest.approx(84.0)


def test_internal_edge_does_not_halve_the_room():
    """
    An edge crossing the interior - an internal divider, or a solid clipped by a
    roof or stair - splits the footprint into adjacent faces that are all equally
    'outer'. Picking the largest returned one tile and called half a room a whole
    one; the faces have to be merged.
    """
    poly = ifc_processor._polygon_from_edges(build_shape([SQUARE], extra_edges=[(0, 2)]))
    assert poly is not None
    assert poly.area == pytest.approx(100.0), "adjacent faces must merge, not compete"


def test_detached_parts_return_a_real_outline():
    """
    One space in genuinely separate parts. The pipeline carries one polygon per
    space, so the largest part is returned - the point is that it is a real
    outline and not the self-intersecting fallback.
    """
    poly = ifc_processor._polygon_from_edges(build_shape([SQUARE, DETACHED]))
    assert poly is not None
    assert poly.is_valid
    assert poly.area == pytest.approx(100.0)


def test_degenerate_input_returns_none():
    assert ifc_processor._polygon_from_edges(build_shape([[(0, 0), (1, 1)]])) is None


@pytest.mark.parametrize("loops,expected_area", [
    ([SQUARE], 100.0),
    ([SQUARE, COURTYARD], 84.0),
])
def test_result_is_always_valid(loops, expected_area):
    poly = ifc_processor._polygon_from_edges(build_shape(loops))
    assert poly.is_valid and not poly.is_empty
    assert poly.area == pytest.approx(expected_area)


# ── geometry engine ──────────────────────────────────────────────────────────

def test_assemble_with_holes_preserves_repaired_interiors():
    """
    A ring repaired by buffer(0) can arrive already carrying interiors.
    Rebuilding it from its exterior alone filled those back in and overstated
    the section area.
    """
    from geometry_engine import ShapelyTrimeshEngine

    ring = Polygon(SQUARE, [COURTYARD])
    assert len(ring.interiors) == 1

    result = ShapelyTrimeshEngine()._assemble_with_holes([ring])
    assert sum(p.area for p in result) == pytest.approx(84.0)


def test_engine_self_test_passes():
    """The module's own self-test, so `python geometry_engine.py` cannot rot."""
    from geometry_engine import test_geometry_engine
    test_geometry_engine()
