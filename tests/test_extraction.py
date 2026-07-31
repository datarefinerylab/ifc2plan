"""
Extraction against real IFC files.

Parameterised over every model present: the committed Schependomlaan example
always, plus any KAAN model found in examples/data/private. Run with
`-m "not private"` for the public-only subset CI can reproduce.

Assertions here are invariants and counts, never row order - output ordering is
not reproducible between runs (issue #9), so a byte-exact comparison would flake.
"""

import subprocess
import sys

import pytest

import ifc_processor
from ifc_processor import (
    get_elements_and_shapes,
    space_geometry_settings,
    space_outline_polygon,
)


def test_model_opens_and_has_storeys(opened_model, model_path):
    storeys = opened_model.by_type("IfcBuildingStorey")
    assert storeys, f"{model_path.name} declares no IfcBuildingStorey"


def test_every_extracted_space_is_usable(opened_model, model_path):
    """
    Whatever comes out must be a valid, non-degenerate polygon. A space that
    yields nothing is allowed - three KAAN models carry no IfcSpace at all - but
    a space that yields a broken polygon is not, because it reaches the output
    looking plausible.
    """
    spaces = opened_model.by_type("IfcSpace")
    if not spaces:
        pytest.skip(f"{model_path.name} contains no IfcSpace")

    settings = space_geometry_settings()
    extracted = 0
    for space in spaces[:400]:          # cap: lumiere has 3096
        polygon, reason = space_outline_polygon(space, settings)
        if polygon is None:
            assert reason, "a failed space must say why"
            continue
        extracted += 1
        assert polygon.is_valid, f"invalid polygon for space {space.id()}"
        assert not polygon.is_empty
        assert polygon.area > 0

    assert extracted > 0, f"no space in {model_path.name} produced geometry"


def test_space_extraction_rate_on_example(example_ifc):
    """
    The example's 100 spaces must all come out. This was 0 before #4 - every
    space was dropped at a room-type gate before geometry was attempted - and 6
    if you measured create_shape directly instead of running the path.
    """
    spaces = example_ifc.by_type("IfcSpace")
    assert len(spaces) == 100

    settings = space_geometry_settings()
    extracted = [s for s in spaces if space_outline_polygon(s, settings)[0] is not None]
    assert len(extracted) == 100


def test_space_areas_are_plausible(example_ifc, naming_conversion):
    """Rooms should be room-sized. Catches a unit slip that validity checks miss."""
    settings = space_geometry_settings()
    areas = [p.area for s in example_ifc.by_type("IfcSpace")
             if (p := space_outline_polygon(s, settings)[0]) is not None]

    assert min(areas) > 0.1, "a room smaller than 0.1 m2 suggests a unit error"
    assert max(areas) < 1000.0, "a room larger than 1000 m2 suggests a unit error"


# ── regressions ──────────────────────────────────────────────────────────────

def test_filter_matching_nothing_does_not_raise(example_ifc, example_model):
    """
    Excluding spaces from the mesh pass made an empty filter reachable: a storey
    holding only IfcSpace. The percentage summary then divided by zero, and
    process_ifc_file catches per file - so one such storey aborted every
    remaining storey of that IFC. spot-r has 59 of them and produced nothing.
    """
    elements, meshes = get_elements_and_shapes(
        example_ifc, str(example_model), filter_fn=lambda el: False, parallel=False
    )
    assert elements == [] and meshes == []


def test_spaces_only_storeys_still_extract(opened_model, model_path):
    """
    A storey whose every element is a space must still produce outlines. This is
    the shape spot-r has and the example does not, which is why the crash above
    was invisible on Schependomlaan.
    """
    from ifcopenshell.util.element import get_decomposition

    spaces_only = [
        s for s in opened_model.by_type("IfcBuildingStorey")
        if (els := get_decomposition(s)) and all(e.is_a("IfcSpace") for e in els)
    ]
    if not spaces_only:
        pytest.skip(f"{model_path.name} has no spaces-only storey")

    settings = space_geometry_settings()
    storey = spaces_only[0]
    spaces = [e for e in get_decomposition(storey) if e.is_a("IfcSpace")]
    extracted = [s for s in spaces if space_outline_polygon(s, settings)[0] is not None]

    assert extracted, "a spaces-only storey produced no geometry"


def test_blank_exception_message_is_reported_not_raised(monkeypatch):
    """
    The handler indexed str(e).splitlines()[0], which is an IndexError when the
    message is blank - so an exception with no text escaped the handler whose
    job is to reduce it to one reported skip.
    """
    class Blank(Exception):
        pass

    def boom(*_args, **_kwargs):
        raise Blank()

    monkeypatch.setattr(ifc_processor.ifcopenshell.geom, "create_shape", boom)

    polygon, reason = space_outline_polygon(object(), None)
    assert polygon is None
    assert "Blank" in reason


# ── end-to-end ───────────────────────────────────────────────────────────────

def _run_cli(model, outdir, *extra):
    src = str(ifc_processor.__file__).rsplit("/", 1)[0]
    cmd = [sys.executable, "extract_floor_plans.py", str(model),
           "--formatter", "wkt", "--output", str(outdir), *extra]
    return subprocess.run(cmd, cwd=src, capture_output=True, text=True)


@pytest.mark.example
def test_cli_space_only_writes_expected_columns(example_model, tmp_path, naming_conversion_path):
    import csv

    result = _run_cli(example_model, tmp_path, "--space-only",
                      "--naming-conversion", str(naming_conversion_path))
    assert result.returncode == 0, result.stderr[-2000:]

    files = list(tmp_path.rglob("*.csv"))
    assert files, "no CSV written"

    rows = []
    for path in files:
        with open(path, newline="") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == [
                "type", "name", "room_type", "room_type_original", "geometry"
            ]
            rows.extend(reader)

    assert len(rows) == 100, f"expected 100 spaces, got {len(rows)}"
    assert all(r["room_type_original"] for r in rows), "every space keeps its original name"
    assert all(r["geometry"].startswith(("POLYGON", "MULTIPOLYGON")) for r in rows)


@pytest.mark.xfail(reason="issue #9: row order is not reproducible between runs",
                   strict=False)
def test_output_is_reproducible(example_model, tmp_path, naming_conversion_path):
    """
    Two runs over the same input should be byte-identical. They are not: element
    order comes from get_decomposition, which returns a set. Until #9 lands,
    'diff the output against main' reports differences that are not real.
    """
    one, two = tmp_path / "one", tmp_path / "two"
    for out in (one, two):
        assert _run_cli(example_model, out, "--space-only",
                        "--naming-conversion", str(naming_conversion_path)).returncode == 0

    a = sorted(p.relative_to(one) for p in one.rglob("*.csv"))
    b = sorted(p.relative_to(two) for p in two.rglob("*.csv"))
    assert a == b and a

    for rel in a:
        assert (one / rel).read_text() == (two / rel).read_text(), f"{rel} differs between runs"
