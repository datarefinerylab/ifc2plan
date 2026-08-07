"""
Tests for naming failed conversions (#26).

The bug: `_convert` caught every exception and returned `None`, so a failed
element reached the summary as nothing but `failed_count += 1`. Which element,
of what type, and why were all gone by then - while the *space* half of the same
run returned `(polygon, reason)` and printed the reason.

Two things are worth testing separately, and they fail for different causes:

- the **classification** - given an element and an exception, is the sentence the
  useful one? That is `failure_reason`, and it is tested against fakes because
  the interesting inputs (an element carrying only an Axis) are awkward to find
  on demand and trivial to construct.
- the **plumbing** - does a failure actually survive from `_convert` to the
  list the summary reads, including across the process boundary the parallel
  path puts in the way? Recording the reason is useless if it is dropped.

The reported elements are then asserted against the committed model, so the
classification cannot quietly stop matching real IFC.
"""

import pytest

from geometry_engine import (
    IFCGeometryProcessor,
    failure_reason,
    representation_identifiers,
)


class FakeRepresentation:
    def __init__(self, identifier, representation_type="Curve2D"):
        self.RepresentationIdentifier = identifier
        self.RepresentationType = representation_type
        self.Items = []


class FakeProductRepresentation:
    def __init__(self, representations):
        self.Representations = representations


class FakeElement:
    """An element carrying exactly the representations named."""

    def __init__(self, *identifiers, name="thing", element_id=7, ifc_class="IfcWall"):
        self.Representation = (
            FakeProductRepresentation([FakeRepresentation(i) for i in identifiers])
            if identifiers else None
        )
        self.Name = name
        self._id = element_id
        self._class = ifc_class

    def is_a(self, other=None):
        return self._class if other is None else other == self._class

    def id(self):
        return self._id


BOOM = RuntimeError("Failed to process shape. Product: #1001928=IfcWall(...)")


class TestRepresentationIdentifiers:
    def test_reads_the_identifiers(self):
        assert representation_identifiers(FakeElement("Axis", "Body")) == {"Axis", "Body"}

    def test_no_representation_is_empty_not_an_error(self):
        assert representation_identifiers(FakeElement()) == set()

    def test_survives_an_element_that_raises(self):
        class Hostile:
            @property
            def Representation(self):
                raise RuntimeError("no schema here")

        assert representation_identifiers(Hostile()) == set()


class TestFailureReason:
    def test_axis_only_is_named_as_the_missing_body(self):
        """The diagnosis #26 asks for, and the one that covers every observed case."""
        assert failure_reason(FakeElement("Axis"), BOOM) == (
            "no Body representation (Axis only)"
        )

    def test_several_non_body_identifiers_are_all_listed(self):
        assert failure_reason(FakeElement("Axis", "FootPrint"), BOOM) == (
            "no Body representation (Axis/FootPrint only)"
        )

    def test_identifiers_are_ordered_so_the_sentence_is_stable(self):
        """Same element, either traversal order, one string - it is a set inside."""
        one = failure_reason(FakeElement("FootPrint", "Axis"), BOOM)
        other = failure_reason(FakeElement("Axis", "FootPrint"), BOOM)
        assert one == other

    def test_an_element_with_a_body_is_not_blamed_on_a_missing_body(self):
        """
        It has the thing. Whatever went wrong is something else, and saying
        'no Body representation' would send a reader somewhere useless.
        """
        reason = failure_reason(FakeElement("Axis", "Body"), BOOM)

        assert "no Body representation" not in reason
        assert reason == "Failed to process shape"

    def test_unknown_failure_falls_back_to_the_exception(self):
        assert failure_reason(FakeElement(), ValueError("something odd")) == "something odd"

    def test_fallback_is_capped(self):
        reason = failure_reason(FakeElement(), ValueError("x" * 500))

        assert len(reason) <= 80

    def test_empty_exception_still_says_something(self):
        """An exception with no message must not produce a blank reason."""
        assert failure_reason(FakeElement(), ValueError("")) == "ValueError"


class TestFailuresReachTheSummary:
    def _failing(self, monkeypatch, exception=BOOM):
        processor = IFCGeometryProcessor()

        def blow_up(*_a, **_k):
            raise exception

        monkeypatch.setattr(processor, "_get_settings", blow_up)
        return processor

    def test_a_failure_is_recorded_not_just_counted(self, monkeypatch):
        processor = self._failing(monkeypatch)
        element = FakeElement("Axis", name="dakopstand", element_id=1001928)

        assert processor.process_ifc_element(element, None) is None
        assert len(processor.failed_elements) == 1

        description, reason = processor.failed_elements[0]
        assert "1001928" in description
        assert "dakopstand" in description
        assert "IfcWall" in description
        assert reason == "no Body representation (Axis only)"

    def test_a_successful_element_records_nothing(self, monkeypatch):
        processor = IFCGeometryProcessor()
        monkeypatch.setattr(processor, "_convert", lambda *a, **k: "mesh")

        processor.process_ifc_element(FakeElement("Body"), None)

        assert processor.failed_elements == []

    def test_failures_accumulate(self, monkeypatch):
        processor = self._failing(monkeypatch)
        for i in range(3):
            processor.process_ifc_element(FakeElement("Axis", element_id=i), None)

        assert len(processor.failed_elements) == 3

    def test_conversion_still_returns_none(self, monkeypatch):
        """Diagnostics must not change what a failed conversion produces."""
        processor = self._failing(monkeypatch)

        assert processor.process_ifc_element(FakeElement("Axis"), None) is None


class TestWorkerContract:
    """
    The parallel path is where a diagnostic gets silently lost: the worker's
    lists live in another process, so anything not packed into the return value
    never reaches the summary. This pins the tuple's shape.
    """

    def test_worker_ships_three_diagnostic_lists(self, monkeypatch):
        import ifc_processor

        processor = IFCGeometryProcessor()
        monkeypatch.setattr(processor, "_convert", lambda *a, **k: "mesh")

        element = FakeElement("Body", element_id=99)

        class FakeModel:
            def by_id(self, _):
                return element

        monkeypatch.setattr(ifc_processor, "_worker_model", FakeModel())
        monkeypatch.setattr(ifc_processor, "_worker_processor", processor)

        element_id, mesh, diagnostics = ifc_processor._process_element_worker(99)

        assert element_id == 99
        assert mesh == "mesh"
        assert len(diagnostics) == 3, (
            "a fourth diagnostic list was added without being shipped back, "
            "or failures were dropped from the tuple"
        )

    def test_worker_ships_the_failure_itself(self, monkeypatch):
        import ifc_processor

        processor = IFCGeometryProcessor()
        monkeypatch.setattr(processor, "_get_settings", lambda: (_ for _ in ()).throw(BOOM))

        element = FakeElement("Axis", element_id=1001928, name="dakopstand")

        class FakeModel:
            def by_id(self, _):
                return element

        monkeypatch.setattr(ifc_processor, "_worker_model", FakeModel())
        monkeypatch.setattr(ifc_processor, "_worker_processor", processor)

        _, mesh, (_slow, _skipped, failed) = ifc_processor._process_element_worker(1001928)

        assert mesh is None
        assert len(failed) == 1
        assert failed[0][1] == "no Body representation (Axis only)"


@pytest.mark.example
class TestAgainstTheCommittedModel:
    """
    #26 names four walls on `04 dak`. If the classification stops matching real
    IFC, these fail while every fake-based test above still passes.
    """

    def test_the_dakopstand_walls_are_axis_only(self, example_ifc):
        for wall_id in (1001928, 1002495, 1011360, 1012623):
            wall = example_ifc.by_id(wall_id)

            assert wall.is_a() == "IfcWall"
            assert representation_identifiers(wall) == {"Axis"}, (
                "these walls are the fixture for 'no Body representation'; "
                "if they gained a Body the test is no longer testing it"
            )

    def test_such_a_wall_fails_and_is_named(self, example_ifc):
        """End to end through the real converter, no monkeypatching."""
        processor = IFCGeometryProcessor()
        wall = example_ifc.by_id(1001928)

        assert processor.process_ifc_element(wall, example_ifc) is None
        assert len(processor.failed_elements) == 1

        description, reason = processor.failed_elements[0]
        assert "1001928" in description
        assert "dakopstand" in description
        assert reason == "no Body representation (Axis only)"

    def test_an_ordinary_wall_still_converts(self, example_ifc):
        """
        The guard against 'diagnose everything as a missing Body': a normal wall
        on the same model must still produce a mesh and record nothing.
        """
        processor = IFCGeometryProcessor()
        walls = [w for w in example_ifc.by_type("IfcWall")
                 if "Body" in representation_identifiers(w)]

        assert walls, "no wall on this model carries a Body representation"

        assert processor.process_ifc_element(walls[0], example_ifc) is not None
        assert processor.failed_elements == []
