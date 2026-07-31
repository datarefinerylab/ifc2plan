"""
Unit handling and section-plane selection (issue #3).

The asymmetry these guard: IfcBuildingStorey.Elevation is in the model's own
length unit, while ifcopenshell hands geometry back already converted to metres.
Mixing them was invisible on a millimetre model because /1000 was accidentally
right.
"""

import pytest

from ifc_processor import best_covering_height, mesh_z_spans, storey_elevation_metres


class FakeStorey:
    def __init__(self, elevation):
        self.Elevation = elevation


@pytest.mark.parametrize("elevation,scale,expected", [
    (6000.0, 0.001, 6.0),      # millimetre model
    (6.0, 1.0, 6.0),           # metre model - same storey, same answer
    (0.0, 0.001, 0.0),
    (-1000.0, 0.001, -1.0),    # below datum, as '-1 fundering' is
])
def test_elevation_converts_with_the_declared_unit(elevation, scale, expected):
    assert storey_elevation_metres(FakeStorey(elevation), scale) == pytest.approx(expected)


def test_missing_elevation_is_zero():
    assert storey_elevation_metres(FakeStorey(None), 0.001) == 0.0


def test_unit_scale_matches_the_example(example_ifc):
    """The example declares MILLI METRE, so the scale must be 0.001."""
    import ifcopenshell.util.unit
    assert ifcopenshell.util.unit.calculate_unit_scale(example_ifc) == pytest.approx(0.001)


def test_storey_elevations_are_plausible_metres(example_ifc):
    """
    Converted elevations must land in a sane building range. Catches a factor of
    1000 in either direction, which is the failure this whole area is about.
    """
    import ifcopenshell.util.unit
    scale = ifcopenshell.util.unit.calculate_unit_scale(example_ifc)
    for storey in example_ifc.by_type("IfcBuildingStorey"):
        assert -20.0 < storey_elevation_metres(storey, scale) < 200.0


# ── fallback plane selection ─────────────────────────────────────────────────

def test_best_covering_height_picks_the_busiest_band():
    spans = [(0.0, 3.0), (0.0, 3.0), (0.0, 3.0), (10.0, 12.0)]
    height, count = best_covering_height(spans)
    assert count == 3
    assert 0.0 < height < 3.0


def test_best_covering_height_handles_nothing_to_cut():
    assert best_covering_height([]) == (None, 0)


def test_best_covering_height_lands_inside_a_span():
    """
    Candidates are midpoints between z edges so the plane never lands exactly on
    a face, where sectioning is degenerate.
    """
    spans = [(11.62, 13.11)]
    height, count = best_covering_height(spans)
    assert count == 1
    assert 11.62 < height < 13.11


def test_mesh_z_spans_skips_unusable_meshes():
    class NoBounds:
        bounds = None

    class Broken:
        @property
        def bounds(self):
            raise RuntimeError("no geometry")

    assert mesh_z_spans([NoBounds(), Broken()]) == []
