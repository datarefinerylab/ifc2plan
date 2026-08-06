"""
The legend, which is the part of the image a reader parses rather than looks at.

Issue #30: polygon_groups is keyed by IFC entity type, and several types share a
rendered label. IfcWall and IfcWallStandardCase both read "Wall" in the same
colour, so a plan containing both drew two identical rows - and the example model
contains both (652 and 282), so the duplicate was baked into the README image.

These test _element_legend_rows rather than the drawn PNG: the rule being checked
is which rows exist, not how matplotlib lays them out.
"""

import matplotlib
matplotlib.use("Agg")  # noqa: E402  - before pyplot, these tests draw nothing

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from formatters import FloorPlanImageFormatter  # noqa: E402

STYLES_WITH_LEGEND = ["professional", "minimal", "colorful"]


def formatter(style):
    return FloorPlanImageFormatter({"style": style})


def groups(*types):
    """A polygon_groups stand-in. Only its keys reach the legend."""
    return {t: [] for t in types}


def legend_rows(style, polygon_groups, room_type_groups=None):
    """The labels of a built legend, in the order they are drawn."""
    fig, ax = plt.subplots()
    try:
        formatter(style)._create_legend(ax, polygon_groups, room_type_groups or {})
        legend = ax.get_legend()
        return [] if legend is None else [t.get_text() for t in legend.get_texts()]
    finally:
        plt.close(fig)


@pytest.mark.parametrize("style", STYLES_WITH_LEGEND)
def test_wall_and_wallstandardcase_share_one_row(style):
    """The reported bug. Both collapse to "Wall", so there is one Wall row."""
    rows = formatter(style)._element_legend_rows(groups("IfcWall", "IfcWallStandardCase"))
    assert list(rows) == ["Wall"]


@pytest.mark.parametrize("style", STYLES_WITH_LEGEND)
def test_whole_palette_collapses_to_its_distinct_labels(style):
    """
    Generalised beyond walls: hand the legend every type the style can colour and
    the rows are exactly the distinct labels, in first-seen order. Catches the
    next label-sharing pair without naming it.
    """
    f = formatter(style)
    labels = [f._legend_label(t) for t in f.colors if t != "IfcSpace"]
    rows = f._element_legend_rows(groups(*f.colors.keys()))

    assert list(rows) == list(dict.fromkeys(labels))
    assert len(rows) < len(labels), (
        "no type in this palette shares a label with another, so this test is "
        "no longer exercising de-duplication"
    )


def test_distinct_types_keep_distinct_rows():
    """De-duplication is on the label, so types that read differently stay apart."""
    rows = formatter("professional")._element_legend_rows(
        groups("IfcWall", "IfcDoor", "IfcWindow"))
    assert list(rows) == ["Wall", "Door", "Window"]


def test_spaces_are_not_element_rows():
    """Spaces are legended by room type, higher up in _create_legend."""
    rows = formatter("professional")._element_legend_rows(groups("IfcSpace", "IfcWall"))
    assert list(rows) == ["Wall"]


def test_uncoloured_types_are_dropped_before_counting():
    """
    The <= 12 cap drops the whole element legend when exceeded, so it has to
    count rows that would be drawn. A type with no colour draws nothing.
    """
    rows = formatter("professional")._element_legend_rows(
        groups("IfcWall", "IfcNotAThingWeColour"))
    assert list(rows) == ["Wall"]


def test_row_keeps_the_colour_and_alpha_of_its_type():
    f = formatter("professional")
    (color, alpha), = f._element_legend_rows(groups("IfcDoor")).values()
    assert color == f.colors["IfcDoor"]
    assert alpha == f.alphas["IfcDoor"]


# ── the blank row between the two halves of the legend ───────────────────────

def test_separator_draws_nothing():
    """
    The gap between room types and elements is a handle with an empty label,
    which is the only way to space two groups apart in one matplotlib legend.
    It used to be a *white* rectangle, which on the legend's frame reads as a
    row whose swatch failed to render rather than as a gap.
    """
    patch = FloorPlanImageFormatter._legend_gap_patch()
    assert patch.get_facecolor()[3] == 0, "separator swatch is painted"
    assert patch.get_edgecolor()[3] == 0, "separator swatch is outlined"


def test_one_blank_row_and_it_is_between_the_sections():
    """Room types are sorted; element rows keep the order they were drawn in."""
    rows = legend_rows("professional",
                       groups("IfcSpace", "IfcWall", "IfcDoor"),
                       {"corridor": [], "bedroom": []})
    assert rows == ["Bedroom", "Corridor", "", "Wall", "Door"]


def test_no_blank_row_without_room_types():
    """Nothing to separate, so the legend must not open with an empty row."""
    rows = legend_rows("professional", groups("IfcWall", "IfcDoor"))
    assert rows == ["Wall", "Door"]
    assert "" not in rows


def test_no_blank_row_without_elements():
    rows = legend_rows("professional", groups("IfcSpace"), {"bedroom": []})
    assert rows == ["Bedroom"]


@pytest.mark.example
def test_example_model_draws_one_wall_row(example_ifc):
    """
    The end the bug was reported from. The model behind the README image carries
    both wall types, which is the condition that produced the duplicate; assert
    that here too, so this test fails loudly if the fixture ever stops
    reproducing the bug rather than passing for the wrong reason.
    """
    present = sorted({e.is_a() for e in example_ifc.by_type("IfcProduct")})
    assert {"IfcWall", "IfcWallStandardCase"} <= set(present)

    rows = formatter("professional")._element_legend_rows(groups(*present))
    assert sum(1 for label in rows if label == "Wall") == 1
