"""
Room-type resolution and the naming conversion.

The bug that motivated most of this: get_room_type's docstring promised a
LongName step that the code never implemented, so a model naming its rooms only
in LongName - which is every model here - resolved entirely to "Unknown".
"""

import pytest

import ifc_processor
from ifc_processor import clean_room_type, get_room_name_original, get_room_type


class FakeSpace:
    """
    Minimal stand-in for an IfcSpace.

    get_room_type calls ifcopenshell.util.element.get_psets(element) inside a
    bare try/except, so a stub that has no psets exercises the LongName and
    ObjectType branches without needing a real entity.
    """

    def __init__(self, long_name=None, object_type=None, ifc_class="IfcSpace"):
        self.LongName = long_name
        self.ObjectType = object_type
        self._ifc_class = ifc_class

    def is_a(self, name=None):
        if name is None:
            return self._ifc_class
        return self._ifc_class == name


CONVERSION = {
    "slaapkamer": "bedroom",
    "woonkamer": "livingroom",
    "badkamer": "bathroom",
    "entree": "entrance",
}


def test_non_space_returns_none():
    assert get_room_type(FakeSpace(long_name="whatever", ifc_class="IfcWall")) is None


def test_long_name_is_read():
    """The step the docstring promised and the code skipped."""
    assert get_room_type(FakeSpace(long_name="badkamer"), CONVERSION) == "bathroom"


def test_long_name_matches_on_first_word():
    """'slaapkamer 1' and 'slaapkamer 2' both resolve to the one entry."""
    assert get_room_type(FakeSpace(long_name="slaapkamer 1"), CONVERSION) == "bedroom"
    assert get_room_type(FakeSpace(long_name="slaapkamer 2"), CONVERSION) == "bedroom"


def test_long_name_beats_object_type():
    room = FakeSpace(long_name="woonkamer", object_type="badkamer")
    assert get_room_type(room, CONVERSION) == "livingroom"


def test_object_type_used_when_no_long_name():
    assert get_room_type(FakeSpace(object_type="badkamer"), CONVERSION) == "bathroom"


def test_unmapped_name_is_flagged():
    """No conversion entry - the name survives behind the remaining_ prefix."""
    assert get_room_type(FakeSpace(long_name="keuken"), CONVERSION) == "remaining_keuken"


def test_original_name_is_preserved_unmapped():
    """
    room_type_original carries the untranslated name so the conversion is not
    lossy for the rooms with no entry.
    """
    assert get_room_name_original(FakeSpace(long_name="instal. ruimte")) == "instal. ruimte"


def test_original_name_is_not_cleaned():
    room = FakeSpace(long_name="slaapkamer 1")
    assert get_room_name_original(room) == "slaapkamer 1"
    assert get_room_type(room, CONVERSION) == "bedroom"


def test_missing_name_gives_empty_original():
    assert get_room_name_original(FakeSpace()) == ""


def test_get_room_type_from_space_agrees_with_get_room_type():
    """
    These two disagreed completely - None for all 100 spaces against a value for
    all 100 - because one required a pset the model does not carry.
    """
    room = FakeSpace(long_name="badkamer")
    assert (ifc_processor.get_room_type_from_space(room, CONVERSION)
            == get_room_type(room, CONVERSION))


# ── clean_room_type ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("bathroom", "bathroom"),
    ("bedroom", "bedroom"),
    ("Bathroom", "bathroom"),        # canonical casing comes from the set
    ("  bedroom  ", "bedroom"),      # surrounding whitespace is stripped
    ("elevator shaft", "elevator shaft"),
    ("cera", "cera"),
    ("", ""),
])
def test_clean_room_type_known_values(value, expected):
    """Current behaviour. See test_documented_normalisation_rules for the gap."""
    assert clean_room_type(value) == expected


def test_clean_room_type_flags_unknown():
    assert clean_room_type("keuken") == "remaining_keuken"


def test_clean_room_type_prefix_is_idempotent():
    assert clean_room_type("remaining_keuken") == "remaining_keuken"


@pytest.mark.xfail(reason="clean_room_type's docstring documents rules 1 and 2 that the "
                          "code never implements; both values sit in KEEP_AS_IS, which is "
                          "checked first and returns them unchanged",
                   strict=True)
@pytest.mark.parametrize("value,expected", [
    ("elevator shaft", "elevator"),
    ("cera", "Central Energy Recovery Airflow"),
])
def test_documented_normalisation_rules(value, expected):
    """
    Same shape as the LongName bug in #4: the docstring promises a step the
    implementation skips. Either the rules should exist or the docstring should
    stop claiming them - a vocabulary decision, so it is recorded rather than
    silently changed.
    """
    assert clean_room_type(value) == expected


@pytest.mark.xfail(reason="issue #10: KEEP_AS_IS has drifted from naming_conversion.csv, "
                          "so successfully translated values are still flagged unmapped",
                   strict=True)
def test_translated_value_is_not_flagged_as_unmapped():
    """
    naming_conversion.csv maps Entree -> entrance, yet the result comes back
    remaining_entrance because 'entrance' is absent from KEEP_AS_IS. 'has a
    remaining_ prefix' is therefore not a reliable test for 'was not translated'.

    xfail(strict) so this starts passing loudly the moment #10 is fixed.
    """
    assert get_room_type(FakeSpace(long_name="entree"), CONVERSION) == "entrance"


# ── naming conversion loading ────────────────────────────────────────────────

def test_naming_conversion_loads(naming_conversion):
    assert len(naming_conversion) > 0


def test_blank_row_does_not_crash_lookup(naming_conversion):
    """
    naming_conversion.csv has a blank-original row mapping to 'not defined'.
    pandas reads that cell as NaN, which has caused
    AttributeError: 'float' object has no attribute 'lower'.
    """
    assert get_room_type(FakeSpace(long_name="badkamer"), naming_conversion) == "bathroom"
