"""
Coverage the committed example cannot provide.

Schependomlaan is IFC2X3 and declares millimetres, so two things are untestable
on it: the IFC4 tessellation entities, and any unit scale other than 0.001. The
models fetched by `python examples/fetch_open_models.py` cover both - see
docs/test-models.md for what they are and what their licences permit.

Everything here skips when nothing has been fetched. That is deliberate: CI and a
fresh clone must stay green without them.
"""

import ifcopenshell
import ifcopenshell.util.unit
import pytest

from geometry_engine import representation_face_count
from ifc_processor import space_outline_polygon, space_geometry_settings, storey_elevation_metres

from conftest import _open_models


def test_open_model_is_ifc4_or_newer(open_model_path):
    """The whole point of fetching these. An IFC2X3 file here means the wrong download."""
    model = ifcopenshell.open(str(open_model_path))
    assert model.schema.startswith("IFC4"), (
        f"{open_model_path.name} is {model.schema}; these models exist to cover IFC4 and later"
    )


def test_open_model_storeys_convert_to_plausible_metres(open_model_path):
    """
    Elevations run through storey_elevation_metres, whatever unit is declared.

    On a model declaring metres the scale is 1.0, so a stray /1000 would push
    every storey to millimetre-sized numbers and this catches it. That is the
    half of issue #3 the millimetre-only example cannot test.
    """
    model = ifcopenshell.open(str(open_model_path))
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    storeys = model.by_type("IfcBuildingStorey")
    assert storeys, f"{open_model_path.name} declares no IfcBuildingStorey"

    for storey in storeys:
        metres = storey_elevation_metres(storey, scale)
        assert -50.0 < metres < 500.0, (
            f"{open_model_path.name}: storey {storey.Name!r} converts to {metres} m"
        )


def test_open_model_spaces_produce_valid_outlines(open_model_path):
    model = ifcopenshell.open(str(open_model_path))
    spaces = model.by_type("IfcSpace")
    if not spaces:
        pytest.skip(f"{open_model_path.name} contains no IfcSpace")

    settings = space_geometry_settings()
    extracted = 0
    for space in spaces[:200]:
        polygon, reason = space_outline_polygon(space, settings)
        if polygon is None:
            assert reason, "a failed space must say why"
            continue
        extracted += 1
        assert polygon.is_valid and not polygon.is_empty and polygon.area > 0

    assert extracted > 0, f"no space in {open_model_path.name} produced geometry"


# ── coverage the whole fetched set is supposed to have ───────────────────────

def _fetched():
    models = _open_models()
    if not models:
        pytest.skip("no open-access models fetched: python examples/fetch_open_models.py")
    return models


def test_some_fetched_model_declares_metres():
    """
    Guards the reason `fzk-haus`, `institute` and `smiley-west` are in the set at
    all. If only the millimetre models are ever fetched, the unit path is still
    only tested at one scale and the test above proves less than it looks.
    """
    scales = {
        path.name: ifcopenshell.util.unit.calculate_unit_scale(ifcopenshell.open(str(path)))
        for path in _fetched()
    }
    assert any(scale == pytest.approx(1.0) for scale in scales.values()), (
        f"none of the fetched models declares metres: {scales}"
    )


def test_tessellated_bodies_are_counted():
    """
    The IFC4 branch of representation_face_count, on a real file.

    IfcTriangulatedFaceSet does not exist in IFC2X3, so on the committed example
    this branch can never fire - it is stubbed in test_slow_elements.py, which
    verifies the code against what we believe the schema does rather than against
    the schema. This runs it on geometry we did not author.
    """
    counted = {}
    for path in _fetched():
        model = ifcopenshell.open(str(path))
        if not model.by_type("IfcTriangulatedFaceSet"):
            continue
        for element in model.by_type("IfcProduct"):
            if not getattr(element, "Representation", None):
                continue
            faces = representation_face_count(element)
            if faces:
                counted.setdefault(path.name, []).append(faces)

    if not counted:
        pytest.skip("no fetched model carries IfcTriangulatedFaceSet (fetch pcert-ifc4)")

    for name, counts in counted.items():
        assert max(counts) > 0, f"{name}: tessellated bodies counted as 0 faces"
