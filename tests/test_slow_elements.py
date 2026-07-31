"""
Tests for the slow-element diagnostics and the opt-in face ceiling (#13).

The bug: a handful of elements with very large tessellations dominated a whole
run and nothing said so. On one storey of spot-a2, four elements out of 669 were
99% of the conversion time; the progress bar simply stopped advancing for 35
minutes with no output naming them.

`process_ifc_element` swallows every exception, so a slow *and* failing element
was doubly invisible - hence the timing lives in a `finally`.
"""

import time

import pytest

from geometry_engine import (
    IFCGeometryProcessor,
    SLOW_ELEMENT_SECONDS,
    representation_face_count,
)


class FakeItem:
    """Stands in for a representation item without needing an IFC file."""

    def __init__(self, ifc_class, **attrs):
        self._class = ifc_class
        for k, v in attrs.items():
            setattr(self, k, v)

    def is_a(self, other=None):
        return self._class if other is None else self._class == other


class FakeRepresentation:
    def __init__(self, items):
        self.Items = items


class FakeProductRepresentation:
    def __init__(self, representations):
        self.Representations = representations


class FakeElement:
    def __init__(self, items, name="thing", element_id=42, ifc_class="IfcCovering"):
        self.Representation = FakeProductRepresentation([FakeRepresentation(items)])
        self.Name = name
        self._id = element_id
        self._class = ifc_class

    def id(self):
        return self._id

    def is_a(self, other=None):
        return self._class if other is None else self._class == other


class TestFaceCount:
    def test_polygonal_face_set(self):
        el = FakeElement([FakeItem("IfcPolygonalFaceSet", Faces=range(26011))])
        assert representation_face_count(el) == 26011

    def test_triangulated_face_set(self):
        el = FakeElement([FakeItem("IfcTriangulatedFaceSet", CoordIndex=range(300))])
        assert representation_face_count(el) == 300

    def test_items_are_summed(self):
        el = FakeElement([
            FakeItem("IfcPolygonalFaceSet", Faces=range(10)),
            FakeItem("IfcPolygonalFaceSet", Faces=range(5)),
        ])
        assert representation_face_count(el) == 15

    def test_mapped_item_is_resolved(self):
        """Doors and windows reach their geometry through IfcMappedItem."""
        inner = FakeRepresentation([FakeItem("IfcPolygonalFaceSet", Faces=range(99))])
        source = FakeItem("IfcRepresentationMap", MappedRepresentation=inner)
        el = FakeElement([FakeItem("IfcMappedItem", MappingSource=source)])

        assert representation_face_count(el) == 99

    def test_no_representation_is_zero(self):
        el = FakeElement([])
        el.Representation = None
        assert representation_face_count(el) == 0

    def test_unknown_item_type_counts_zero_not_error(self):
        """
        An unrecognised item must under-count, never over-count.

        The count gates an opt-in skip, so guessing high would silently drop
        geometry the user never asked to lose. Guessing low only forgoes a
        speedup.
        """
        el = FakeElement([FakeItem("IfcSomethingNobodyHasSeen", Whatever=range(9999))])
        assert representation_face_count(el) == 0

    def test_malformed_representation_does_not_raise(self):
        el = FakeElement([])
        el.Representation = object()  # no .Representations
        assert representation_face_count(el) == 0

    def test_cyclic_mapping_terminates(self):
        """A MappingSource that points back at itself must not hang the run."""
        rep = FakeRepresentation([])
        source = FakeItem("IfcRepresentationMap", MappedRepresentation=rep)
        item = FakeItem("IfcMappedItem", MappingSource=source)
        rep.Items = [item]  # cycle
        el = FakeElement([item])

        assert representation_face_count(el) == 0


class TestSlowElementReporting:
    def _processor_over_threshold(self, monkeypatch, delay, threshold):
        processor = IFCGeometryProcessor(slow_seconds=threshold)
        monkeypatch.setattr(
            processor, "_convert",
            lambda *a, **k: (time.sleep(delay), "mesh")[1],
        )
        return processor

    def test_slow_element_is_recorded(self, monkeypatch):
        processor = self._processor_over_threshold(monkeypatch, delay=0.05, threshold=0.01)
        el = FakeElement([FakeItem("IfcPolygonalFaceSet", Faces=range(26011))],
                         name="waterslag", element_id=462475)

        processor.process_ifc_element(el, None)

        assert len(processor.slow_elements) == 1
        elapsed, description = processor.slow_elements[0]
        assert elapsed >= 0.05
        assert "462475" in description
        assert "IfcCovering" in description
        assert "26,011" in description, "the face count is the actionable part"

    def test_fast_element_is_not_recorded(self, monkeypatch):
        processor = self._processor_over_threshold(monkeypatch, delay=0, threshold=5.0)
        processor.process_ifc_element(FakeElement([]), None)

        assert processor.slow_elements == []

    def test_mesh_still_returned(self, monkeypatch):
        """Diagnostics must not change what conversion produces."""
        processor = self._processor_over_threshold(monkeypatch, delay=0.02, threshold=0.01)

        assert processor.process_ifc_element(FakeElement([]), None) == "mesh"

    def test_slow_and_failing_element_is_still_named(self, monkeypatch):
        """
        The case the `finally` exists for.

        `_convert` returns None on any exception, so an element that is both slow
        and broken produced no mesh *and* no diagnostic - the worst combination,
        and the one most worth reporting.
        """
        processor = IFCGeometryProcessor(slow_seconds=0.01)
        monkeypatch.setattr(
            processor, "_convert",
            lambda *a, **k: (time.sleep(0.05), None)[1],
        )

        assert processor.process_ifc_element(FakeElement([]), None) is None
        assert len(processor.slow_elements) == 1

    def test_default_threshold_ignores_ordinary_elements(self):
        """Ordinary elements convert in well under 0.2 s; the default must not fire."""
        assert SLOW_ELEMENT_SECONDS >= 1.0


class TestFaceCeiling:
    def test_off_by_default(self, monkeypatch):
        """The ceiling drops geometry, so it must never apply unasked."""
        processor = IFCGeometryProcessor()
        monkeypatch.setattr(processor, "_convert", lambda *a, **k: "mesh")
        el = FakeElement([FakeItem("IfcPolygonalFaceSet", Faces=range(10 ** 6))])

        assert processor.process_ifc_element(el, None) == "mesh"
        assert processor.skipped_elements == []

    def test_element_over_ceiling_is_skipped(self, monkeypatch):
        processor = IFCGeometryProcessor(max_faces=12000)
        monkeypatch.setattr(processor, "_convert",
                            lambda *a, **k: pytest.fail("must not convert"))
        el = FakeElement([FakeItem("IfcPolygonalFaceSet", Faces=range(15736))])

        assert processor.process_ifc_element(el, None) is None
        assert processor.skipped_elements == [
            (15736, processor.skipped_elements[0][1])
        ]

    def test_element_under_ceiling_is_converted(self, monkeypatch):
        processor = IFCGeometryProcessor(max_faces=12000)
        monkeypatch.setattr(processor, "_convert", lambda *a, **k: "mesh")
        el = FakeElement([FakeItem("IfcPolygonalFaceSet", Faces=range(2343))])

        assert processor.process_ifc_element(el, None) == "mesh"
        assert processor.skipped_elements == []

    def test_boundary_is_inclusive_of_the_limit(self, monkeypatch):
        """`--max-faces N` keeps an element with exactly N faces."""
        processor = IFCGeometryProcessor(max_faces=1000)
        monkeypatch.setattr(processor, "_convert", lambda *a, **k: "mesh")
        el = FakeElement([FakeItem("IfcPolygonalFaceSet", Faces=range(1000))])

        assert processor.process_ifc_element(el, None) == "mesh"

    def test_skipped_element_is_not_also_timed(self, monkeypatch):
        """A skip is instant; it must not appear in the slow list as well."""
        processor = IFCGeometryProcessor(max_faces=10, slow_seconds=0.0)
        el = FakeElement([FakeItem("IfcPolygonalFaceSet", Faces=range(100))])

        processor.process_ifc_element(el, None)

        assert processor.slow_elements == []
        assert len(processor.skipped_elements) == 1


@pytest.mark.example
def test_face_count_works_on_the_real_model(example_ifc):
    """The fakes above encode my understanding of the schema; this checks it."""
    walls = [w for w in example_ifc.by_type("IfcWall") if w.Representation is not None]
    assert walls, "example model has no walls with representations"

    counts = [representation_face_count(w) for w in walls]

    assert all(c >= 0 for c in counts)
    assert not any(c is None for c in counts)


@pytest.mark.example
def test_no_slow_elements_on_the_example_model(example_ifc):
    """
    The example converts quickly, so a default run should report nothing.

    Guards against a threshold regression that would make every run noisy.
    """
    processor = IFCGeometryProcessor()
    for wall in [w for w in example_ifc.by_type("IfcWall")
                 if w.Representation is not None][:40]:
        processor.process_ifc_element(wall, example_ifc)

    assert processor.slow_elements == []
