"""
The generated IFC4 fixture: the IfcPolygonalFaceSet coverage nothing else provides.

Issue #20. Every committed model before this one - the IFC2X3 Schependomlaan example
and the five open-access IFC4 files from #29 - contains **zero** IfcPolygonalFaceSet.
In the models this tool is actually pointed at, that entity carries most of the solid
geometry. So the first branch of `representation_face_count`, the one that reads the
dominant body type of every real model, was reachable only through the FakeItem stubs
in test_slow_elements.py.

Stubs assert the code does what we believe the schema does. Issue #19 is what that is
worth: a blind spot on IFC2X3 breps the stubs did not catch, which left --max-faces
silently inert on that whole schema. These tests run the same code against a file
ifcopenshell parses, on geometry it converts.

The fixture is generated (examples/make_synthetic_ifc4.py) and committed. Being
generated is what makes the numbers below exact rather than approximate - 6 * 24**2
faces is a property of the script, not an observation about someone's building - and
test_fixture_matches_its_generator is what keeps the file and the script from drifting
apart.
"""

import subprocess
import sys

import ifcopenshell
import ifcopenshell.util.unit
import pytest

import ifc_processor
from geometry_engine import IFCGeometryProcessor, representation_face_count
from ifc_processor import (
    space_geometry_settings,
    space_outline_polygon,
    storey_decomposition,
    storey_elevation_metres,
)

from conftest import REPO_ROOT, SYNTHETIC_MODEL

# 6 sides x TESSELLATED**2 quads, straight out of the generator.
TESSELLATED_FACES = 6 * 24 ** 2
PLAIN_FACES = 6

pytestmark = pytest.mark.synthetic


@pytest.fixture(scope="module")
def synthetic_ifc():
    if not SYNTHETIC_MODEL.exists():
        pytest.fail(
            f"missing: {SYNTHETIC_MODEL}. This file is committed; restore it with "
            "`git checkout examples/data/synthetic` or regenerate it with "
            "`python examples/make_synthetic_ifc4.py`.")
    return ifcopenshell.open(str(SYNTHETIC_MODEL))


# ── the fixture is what it claims to be ──────────────────────────────────────

def test_fixture_is_present():
    """
    Committed, so absence is a broken checkout or a .gitignore change that
    re-excluded it - and everywhere else it would show up as a skip, not a
    failure, leaving CI green while testing nothing.
    """
    assert SYNTHETIC_MODEL.exists(), f"{SYNTHETIC_MODEL} is missing"


def test_fixture_is_ifc4(synthetic_ifc):
    assert synthetic_ifc.schema == "IFC4"


def test_fixture_stays_small():
    """
    It is committed, so its size is everyone's problem. The point of generating a
    fixture rather than sourcing one is that it can be shaped to hit the untested
    branches without carrying a building's worth of bytes.
    """
    size_kb = SYNTHETIC_MODEL.stat().st_size / 1024
    assert size_kb < 1024, f"fixture has grown to {size_kb:,.0f} KB"


def test_fixture_matches_its_generator():
    """
    The committed file must be what the committed script produces.

    A fixture whose generator no longer generates it is worse than no generator:
    it reads as reviewable and reproducible while being neither, and the next
    person to regenerate gets a large unexplained diff.

    The comparison is over entities with reals normalised to 9 significant digits,
    not over bytes. The header carries a timestamp and an ifcopenshell version, and
    float rendering differs between the two ifcopenshell releases the CI matrix
    pins - this test failed on the 3.13 leg for exactly that before the
    normalisation went in. Both are differences in the bytes and neither is a
    difference in the fixture. A coordinate moved by a micrometre still fails.
    """
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / "make_synthetic_ifc4.py"), "--check"],
        capture_output=True, text=True)

    assert result.returncode == 0, (
        f"{SYNTHETIC_MODEL.name} is out of step with make_synthetic_ifc4.py:\n"
        f"{result.stdout}{result.stderr}")


# ── the coverage it exists for ───────────────────────────────────────────────

def test_some_committed_model_carries_polygonal_face_sets():
    """
    The whole reason this fixture exists (#20).

    Written over every committed model rather than over the synthetic one alone,
    because the invariant that matters is "CI reaches IfcPolygonalFaceSet at all".
    If a real IFC4 model carrying them is added later this keeps passing and the
    synthetic file becomes removable - which is the outcome to hope for.

    by_type raises rather than returning [] when the schema has no such entity,
    which is the same IFC2X3/IFC4 asymmetry this fixture exists for, arriving as
    an exception instead of a silent zero.
    """
    from conftest import EXAMPLE_MODEL, _open_models

    carriers = {}
    for path in [EXAMPLE_MODEL, SYNTHETIC_MODEL, *_open_models()]:
        if not path.exists():
            continue
        model = ifcopenshell.open(str(path))
        try:
            count = len(model.by_type("IfcPolygonalFaceSet"))
        except RuntimeError:
            continue  # entity not in this file's schema, i.e. IFC2X3
        if count:
            carriers[path.name] = count

    assert carriers, (
        "no committed model contains IfcPolygonalFaceSet, so representation_face_count's "
        "first branch is tested only by stubs - see issue #20")


def test_polygonal_face_sets_are_counted(synthetic_ifc):
    """
    The IFC4 branch of representation_face_count, on a file rather than a FakeItem.

    IfcPolygonalFaceSet cannot appear in IFC2X3, so on the Schependomlaan example
    this branch can never fire.
    """
    by_name = {}
    for wall in synthetic_ifc.by_type("IfcWall"):
        by_name.setdefault(representation_face_count(wall), []).append(wall.Name)

    assert TESSELLATED_FACES in by_name, (
        f"no wall counted {TESSELLATED_FACES} faces; got {sorted(by_name)}")
    assert PLAIN_FACES in by_name, f"no plain box counted {PLAIN_FACES} faces"


def test_mapped_tessellation_is_counted_through_the_recursion(synthetic_ifc):
    """
    count_items recursing through IfcMappedItem into a tessellation.

    The open-access models do contain IfcMappedItem, but every one of them wraps
    an extruded solid, so the mapped-into-tessellation path is stub-only without
    this. A wall reporting 0 here means the recursion silently returned nothing -
    the failure mode is an element looking cheaper than it is, which #19 showed
    makes --max-faces quietly inert rather than loud.
    """
    mapped = [w for w in synthetic_ifc.by_type("IfcWall")
              if any(r.RepresentationType == "MappedRepresentation"
                     for r in w.Representation.Representations)]

    assert mapped, "fixture no longer carries a MappedRepresentation wall"
    for wall in mapped:
        assert representation_face_count(wall) == PLAIN_FACES, (
            f"{wall.Name!r}: mapped tessellation counted "
            f"{representation_face_count(wall)} faces, expected {PLAIN_FACES}")


def test_tessellated_bodies_convert_and_section(synthetic_ifc):
    """
    An IfcPolygonalFaceSet has to survive the whole mesh path, not just be counted.

    Counting it and converting it are different code: process_ifc_element builds a
    trimesh from the shape and the engine sections it. A model that counts faces
    correctly and then produces no geometry is exactly as useless.
    """
    processor = IFCGeometryProcessor()
    walls = synthetic_ifc.by_type("IfcWall")

    meshes = [processor.process_ifc_element(w, synthetic_ifc) for w in walls]
    converted = [m for m in meshes if m is not None]

    assert len(converted) == len(walls), (
        f"{len(walls) - len(converted)} of {len(walls)} walls did not convert")
    for mesh, wall in zip(meshes, walls):
        assert len(mesh.faces) > 0, f"{wall.Name!r} converted to an empty mesh"


# ── the model as a whole ─────────────────────────────────────────────────────

def test_storeys_are_metres_and_distinct(synthetic_ifc):
    """
    The fixture declares metres, so unit_scale is 1.0 and Elevation passes through.

    Two storeys at different elevations is what gives section-height selection a
    choice to make; one storey would let a bug that ignores the datum pass.
    """
    scale = ifcopenshell.util.unit.calculate_unit_scale(synthetic_ifc)
    assert scale == pytest.approx(1.0)

    storeys = synthetic_ifc.by_type("IfcBuildingStorey")
    elevations = [storey_elevation_metres(s, scale) for s in storeys]

    assert elevations == [0.0, 3.0]


def test_every_storey_has_elements_and_spaces(synthetic_ifc):
    for storey in synthetic_ifc.by_type("IfcBuildingStorey"):
        elements = storey_decomposition(storey)
        assert [e for e in elements if e.is_a("IfcWall")], f"{storey.Name}: no walls"
        assert [e for e in elements if e.is_a("IfcSpace")], f"{storey.Name}: no spaces"


def test_footprint_only_spaces_produce_outlines(synthetic_ifc):
    """
    The space path on IFC4, over spaces carrying nothing but a FootPrint curve.

    94 of the example model's 100 spaces are FootPrint-only (#4), so the fixture
    would misrepresent real data if its spaces had a Body to fall back on.
    """
    settings = space_geometry_settings()
    spaces = synthetic_ifc.by_type("IfcSpace")
    assert spaces

    for space in spaces:
        polygon, reason = space_outline_polygon(space, settings)
        assert polygon is not None, f"space {space.Name!r} produced nothing: {reason}"
        assert polygon.is_valid and polygon.area > 0


# ── end to end, through the CLI ──────────────────────────────────────────────

def _run_cli(*args):
    src = str(ifc_processor.__file__).rsplit("/", 1)[0]
    return subprocess.run([sys.executable, "extract_floor_plans.py", *args],
                          cwd=src, capture_output=True, text=True)


def test_max_faces_refuses_the_tessellated_wall(tmp_path):
    """
    --max-faces having something real to refuse, which is the end-to-end half of #20.

    Before this fixture the threshold could only be tested against IFC2X3 breps or
    against stubs, so the branch that reads the body type every real model uses was
    never exercised by a run. The gap between 6 faces and 3,456 is wide enough that
    the threshold is unambiguous.
    """
    result = _run_cli(str(SYNTHETIC_MODEL), "-s", "0", "--max-faces", "1000",
                      "--formatter", "wkt", "-o", str(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{TESSELLATED_FACES:,} faces" in result.stdout, (
        f"the tessellated wall was not reported as skipped:\n{result.stdout}")
    assert "Skipped (over --max-faces): 1" in result.stdout


def test_max_faces_above_the_ceiling_converts_everything(tmp_path):
    """
    The other side of the threshold, so the test above cannot pass by never
    converting anything. Same model, same storey, ceiling raised past the wall.
    """
    result = _run_cli(str(SYNTHETIC_MODEL), "-s", "0", "--max-faces", "10000",
                      "--formatter", "wkt", "-o", str(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skipped (over --max-faces)" not in result.stdout
    assert "Valid geometries: 4" in result.stdout


def test_a_full_run_writes_both_storeys(tmp_path):
    """
    Both storeys cut, and the walls actually landing in the CSV.

    The wall rectangles are exact because the generator placed them: a 6.0 x 4.0 m
    room of 0.3 m walls, sectioned 1.5 m above each storey datum. Checking one
    corner coordinate catches a unit or placement regression that a row count
    would not - the first floor's south wall arrives through an IfcMappedItem and
    has to land on top of where the ground floor's directly-placed one does.
    """
    result = _run_cli(str(SYNTHETIC_MODEL), "-s", "all", "--formatter", "wkt",
                      "-o", str(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr

    written = sorted(p.name for p in tmp_path.rglob("*.csv"))
    assert written == ["00 ground floor_floor_plan.csv", "01 first floor_floor_plan.csv"]

    for name in written:
        text = next(tmp_path.rglob(name)).read_text()
        assert text.count("IfcWall") == 4, f"{name}: expected 4 walls\n{text}"
        assert "POLYGON ((0 0, 6 0, 6 0.3, 0 0.3, 0 0))" in text, (
            f"{name}: the south wall is not where the generator put it\n{text}")
