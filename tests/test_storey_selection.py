"""
--storey selection, the overview table, and CLI exit codes.

The selection parser is the one place a user's typing turns into which storeys
get cut, so a silent misread here means a run that quietly produces the wrong
building. Every accepted form is pinned, and so is the refusal to guess.
"""

import subprocess
import sys

import pytest

import ifc_processor
from ifc_processor import (
    StoreySelectionError,
    format_storey_table,
    resolve_storey_selection,
    storey_rows,
)


class FakeStorey:
    """Enough of an IfcBuildingStorey for the selection parser."""

    def __init__(self, name, entity_id=0):
        self.Name = name
        self._id = entity_id

    def id(self):
        return self._id


STOREYS = [
    FakeStorey("-1 fundering"),
    FakeStorey("00 begane grond"),
    FakeStorey("01 eerste verdieping"),
    FakeStorey("02 tweede verdieping"),
]


# ── accepted forms ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec,expected", [
    (None, [0, 1, 2, 3]),          # unset means the whole building
    ("all", [0, 1, 2, 3]),
    ("ALL", [0, 1, 2, 3]),         # not case-sensitive
    (" all ", [0, 1, 2, 3]),
    ("2", [2]),
    (2, [2]),                      # argparse gives a str, callers may not
    ("0,2", [0, 2]),
    ("0, 2", [0, 2]),              # spaces after commas are natural to type
    ("1-3", [1, 2, 3]),            # inclusive at both ends
    ("0-0", [0]),
    ("begane", [1]),               # a name fragment off the overview table
    ("BEGANE", [1]),
    ("verdieping", [2, 3]),        # a fragment may legitimately match several
    ("0,begane", [0, 1]),          # forms mix
])
def test_accepted_selections(spec, expected):
    assert resolve_storey_selection(STOREYS, spec) == expected


def test_result_is_ordered_and_deduplicated():
    """
    '2,0,2' and '0,2' are the same run.

    Storey order is the order output files are written in, so letting the
    selection dictate it would make output depend on argument order.
    """
    assert resolve_storey_selection(STOREYS, "2,0,2") == [0, 2]
    assert resolve_storey_selection(STOREYS, "1-2,2,1") == [1, 2]


def test_digits_are_read_as_an_index_not_a_name():
    """
    '0' is index 0, even though '00 begane grond' contains the character.

    Ambiguity resolved toward the documented form rather than toward whichever
    branch runs first.
    """
    assert resolve_storey_selection(STOREYS, "0") == [0]


# ── refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec", [
    "9",            # past the end
    "-1",           # not a Python-style index from the end
    "0-9",          # range past the end
    "3-1",          # backwards
    "kitchen",      # matches no name
    ",",            # selects nothing
])
def test_rejected_selections(spec):
    with pytest.raises(StoreySelectionError):
        resolve_storey_selection(STOREYS, spec)


def test_error_lists_the_available_storeys():
    """
    The message has to be enough to fix the command.

    Being told an index is invalid and then having to re-run --overview to find
    a valid one is the loop this replaces.
    """
    with pytest.raises(StoreySelectionError) as excinfo:
        resolve_storey_selection(STOREYS, "9")

    message = str(excinfo.value)
    assert "0-3" in message
    for storey in STOREYS:
        assert storey.Name in message


def test_negative_index_is_refused_rather_than_wrapped():
    """
    '-1' must not silently mean the top storey.

    A storey named '-1 fundering' makes this a plausible thing to type, and
    quietly cutting the roof instead is worse than an error.
    """
    with pytest.raises(StoreySelectionError):
        resolve_storey_selection(STOREYS, "-1")


# ── the overview table ───────────────────────────────────────────────────────

def test_storey_rows_report_elevations_in_metres(example_ifc):
    """
    The table's elevations are metres, not the model's raw units.

    The example declares millimetres, so a storey at 3000 model units has to
    read 3.00 m - it sits next to --section-offset, which is metres.
    """
    rows = storey_rows(example_ifc, 0.001)

    assert len(rows) == 6
    elevations = [elevation for _, _, elevation, _, _ in rows]
    assert elevations == sorted(elevations)
    assert min(elevations) == pytest.approx(-1.0)
    assert max(elevations) == pytest.approx(12.0)


def test_storey_rows_space_counts_match_the_model(example_ifc):
    """
    The 'spaces' column has to predict what --space-only will extract.

    It is the number people read to decide whether a storey is worth cutting,
    so it counts spaces the way that mode does: over the raw decomposition.
    """
    rows = storey_rows(example_ifc, 0.001)
    total = sum(spaces for _, _, _, _, spaces in rows)

    assert total == len(example_ifc.by_type("IfcSpace"))


def test_table_renders_every_storey_with_its_index(example_ifc):
    rows = storey_rows(example_ifc, 0.001)
    table = format_storey_table(rows)

    for idx, name, _, _, _ in rows:
        assert f"[{idx}]" in table
        assert name in table
    assert "elevation" in table


def test_table_handles_no_storeys():
    assert "no IfcBuildingStorey" in format_storey_table([])


# ── exit codes ───────────────────────────────────────────────────────────────

def _run_cli(*args):
    src = str(ifc_processor.__file__).rsplit("/", 1)[0]
    return subprocess.run([sys.executable, "extract_floor_plans.py", *args],
                          cwd=src, capture_output=True, text=True)


@pytest.mark.example
def test_bad_storey_selection_exits_nonzero(example_model, tmp_path):
    """
    A mistyped --storey must not look like a successful empty run.

    Exiting 0 here meant a batch script carried on and the missing storey was
    only noticed downstream, if at all.
    """
    result = _run_cli(str(example_model), "-s", "kitchen", "-o", str(tmp_path))

    assert result.returncode != 0
    assert "kitchen" in result.stdout
    assert not list(tmp_path.rglob("*.csv"))


@pytest.mark.example
def test_overview_exits_zero_and_shows_the_table(example_model):
    result = _run_cli(str(example_model), "--overview")

    assert result.returncode == 0
    assert "begane grond" in result.stdout
    assert "-1.00 m" in result.stdout, "elevations are shown in metres"


def test_missing_file_exits_nonzero(tmp_path):
    result = _run_cli(str(tmp_path / "nothing-here*.ifc"), "--overview")

    assert result.returncode != 0


def test_skip_failed_is_rejected_rather_than_ignored(tmp_path):
    """
    #34: --skip-failed was accepted and read by nothing, so a script passing it
    got a byte-identical run and no sign the flag did nothing. Being told the
    argument does not exist is the honest outcome; silently accepting it is not.

    Pinned as a test because "removed" and "accepted but ignored" are
    indistinguishable from the outside, which is exactly how it survived.
    """
    result = _run_cli(str(tmp_path / "whatever.ifc"), "--overview", "--skip-failed")

    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr
    assert "--skip-failed" in result.stderr
