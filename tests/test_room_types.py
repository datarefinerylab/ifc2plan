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


@pytest.mark.xfail(reason="open vocabulary question: should 'elevator shaft' collapse to "
                          "'elevator' and 'cera' expand to its full name? Both sit in "
                          "KEEP_AS_IS, so today they are returned unchanged",
                   strict=True)
@pytest.mark.parametrize("value,expected", [
    ("elevator shaft", "elevator"),
    ("cera", "Central Energy Recovery Airflow"),
])
def test_documented_normalisation_rules(value, expected):
    """
    These two rules were documented in clean_room_type's docstring but never
    implemented - both values sit in KEEP_AS_IS, which is checked first.

    The #10 rewrite dropped the claim from the docstring, so the docs no longer
    describe behaviour that does not exist. That resolves the documentation half
    only. Whether the normalisation *should* happen is a vocabulary decision
    nobody has made, so it stays recorded here rather than being settled by
    whoever happened to touch the file.

    xfail(strict), so if the rules are ever implemented this fails loudly instead
    of being forgotten.
    """
    assert clean_room_type(value) == expected


def test_translated_value_is_not_flagged_as_unmapped():
    """
    naming_conversion.csv maps Entree -> entrance. That used to come back as
    remaining_entrance because 'entrance' is absent from KEEP_AS_IS, so "has a
    remaining_ prefix" was not a reliable test for "was not translated" (#10).

    Was an xfail(strict) from #11 until the fix landed.
    """
    assert get_room_type(FakeSpace(long_name="entree"), CONVERSION) == "entrance"


def test_untranslated_value_still_gets_the_prefix():
    """
    The other half of #10, and the reason the prefix exists: a name with no entry
    must still be flagged, or the fix would have made the signal useless rather
    than accurate.
    """
    assert get_room_type(FakeSpace(long_name="keuken"), {}) == "remaining_keuken"


def test_prefix_tracks_the_supplied_table_not_a_global_set():
    """
    The accepted vocabulary is per-run, since --naming-conversion is an argument.
    The same name must be prefixed or not according to the table it was given -
    which no hardcoded set can express, and which is why the fix keys off whether
    the lookup hit rather than off KEEP_AS_IS membership.
    """
    space = FakeSpace(long_name="entree")

    assert get_room_type(space, {"entree": "entrance"}) == "entrance"
    assert get_room_type(space, {}) == "remaining_entree"


def test_target_colliding_with_an_untranslated_name_is_unambiguous():
    """
    'gallery' is a target in the real table. A different room that is *named*
    gallery, with no entry of its own, has not been translated and must still be
    flagged - which membership-testing the target column would get wrong, and
    asking the lookup gets right.
    """
    table = {"galerij": "gallery"}

    assert get_room_type(FakeSpace(long_name="galerij"), table) == "gallery"
    assert get_room_type(FakeSpace(long_name="gallery"), table) == "remaining_gallery"


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
