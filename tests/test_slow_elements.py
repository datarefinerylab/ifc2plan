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

    def __init__(self, ifc_class, supertypes=(), **attrs):
        self._class = ifc_class
        # Real ifcopenshell `is_a` walks the inheritance chain; exact string
        # matching would make a fake IfcFacetedBrep invisible to a branch that
        # tests for IfcManifoldSolidBrep. Only the arithmetic is tested with
        # fakes - whether the schema really relates those two names is asserted
        # against the model file, in TestBrepFaceCount.
        self._supertypes = set(supertypes)
        for k, v in attrs.items():
            setattr(self, k, v)

    def is_a(self, other=None):
        if other is None:
            return self._class
        return other == self._class or other in self._supertypes


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


class TestBrepFaceCount:
    """
    Brep solids must be counted (#19).

    They were not, and because IfcPolygonalFaceSet and IfcTriangulatedFaceSet do
    not exist in IFC2X3, that left the counter returning 0 for 3734 of the 3752
    elements in the example - so --max-faces was inert on the entire schema while
    the fake-based tests above stayed green. That is the specific gap these tests
    close, and why the important ones below run against the real file.
    """

    def _brep(self, faces, ifc_class="IfcFacetedBrep", **extra):
        shell = FakeItem("IfcClosedShell", CfsFaces=range(faces))
        return FakeItem(ifc_class, supertypes=["IfcManifoldSolidBrep"],
                        Outer=shell, **extra)

    def test_faceted_brep_counts_its_outer_shell(self):
        assert representation_face_count(FakeElement([self._brep(364)])) == 364

    def test_voids_are_added(self):
        """IfcFacetedBrepWithVoids pays for its inner shells too."""
        voids = [FakeItem("IfcClosedShell", CfsFaces=range(6)),
                 FakeItem("IfcClosedShell", CfsFaces=range(8))]
        item = self._brep(100, ifc_class="IfcFacetedBrepWithVoids", Voids=voids)

        assert representation_face_count(FakeElement([item])) == 114

    def test_brep_without_voids_attribute_is_fine(self):
        """Only IfcFacetedBrepWithVoids has `Voids`; the others must not need it."""
        item = self._brep(12, ifc_class="IfcAdvancedBrep")
        assert not hasattr(item, "Voids")

        assert representation_face_count(FakeElement([item])) == 12

    def test_brep_with_no_outer_shell_does_not_raise(self):
        item = FakeItem("IfcFacetedBrep", supertypes=["IfcManifoldSolidBrep"], Outer=None)

        assert representation_face_count(FakeElement([item])) == 0

    @pytest.mark.example
    def test_faceted_brep_really_is_a_manifold_solid_brep(self, example_ifc):
        """
        The schema assumption the fakes above encode, checked against real
        entities rather than against my belief about the schema.

        One branch matches the supertype so it covers the whole brep family. If
        ifcopenshell did not resolve that name, every test above would still pass
        and the counter would still return 0 on real files.
        """
        breps = example_ifc.by_type("IfcFacetedBrep")
        assert breps, "the example model is expected to contain brep bodies"

        assert breps[0].is_a("IfcManifoldSolidBrep")
        assert len(breps[0].Outer.CfsFaces) > 0

    @pytest.mark.example
    def test_most_elements_have_a_non_zero_count(self, example_ifc):
        """
        The regression that matters: this was 18 of 3752 (0.5%).

        A threshold rather than an exact number, so the test survives a different
        model being swapped in, but far above what the broken counter could reach.
        """
        elements = [e for e in example_ifc.by_type("IfcProduct")
                    if getattr(e, "Representation", None) is not None]
        counts = [representation_face_count(e) for e in elements]
        non_zero = sum(1 for c in counts if c > 0)

        assert non_zero > len(elements) // 2, (
            f"only {non_zero} of {len(elements)} elements have a face count; "
            "a whole body type is probably going uncounted again"
        )

    @pytest.mark.example
    def test_the_ceiling_actually_skips_on_this_model(self, example_ifc):
        """
        End to end: --max-faces must be able to skip something on the committed
        model. Before the fix no threshold could - 12000, the value used to
        verify #13 against spot-a2, skipped 0 of 3752 here.
        """
        stair = example_ifc.by_id(563782)
        faces = representation_face_count(stair)
        assert faces > 0, "this stair's body is an IfcFacetedBrep and counted 0 before"

        processor = IFCGeometryProcessor(max_faces=faces - 1)

        assert processor.process_ifc_element(stair, example_ifc) is None
        assert len(processor.skipped_elements) == 1
        assert processor.skipped_elements[0][0] == faces


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
