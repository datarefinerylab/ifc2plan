"""
Tests that the conversion counts partition the elements (#36).

The bug: `process_ifc_element` returns `None` both for an element the
`--max-faces` ceiling deliberately refused and for one whose conversion threw,
and the caller counted every `None` as a failure. So a run that skipped 585
elements on request reported them twice - once as skipped, once as failed - and
announced an 83% failure rate with nothing wrong.

The invariant worth pinning is not "the number is 585". It is that every element
lands in exactly one bucket:

    valid + failed + no-representation + over-max-faces == total

That is what was violated, it holds for any model and any threshold, and it
would have caught the bug in either processing path. Both paths are tested,
because they count in entirely separate code and only one of them was ever
exercised by a default run.
"""

import pytest

import ifc_processor
from geometry_engine import IFCGeometryProcessor, representation_face_count
from ifc_processor import get_elements_and_shapes


def counts(model, path, **kwargs):
    """Run the mesh pass and return (total, valid, failed, norep, ceiling)."""
    elements = [e for e in model.by_type("IfcWall")][:40]
    keep = set(e.id() for e in elements)

    valid, _meshes = get_elements_and_shapes(
        model, path, filter_fn=lambda el: el.id() in keep, **kwargs
    )
    return elements, valid


@pytest.mark.example
class TestCeilingSkipsAreNotFailures:
    """
    Against the real model, because the two `None`s only ever meet in the real
    converter - a fake that returns None cannot tell you which kind it was.
    """

    def _run(self, example_ifc, example_model, ids, max_faces, parallel):
        keep = set(ids)
        return get_elements_and_shapes(
            example_ifc,
            str(example_model),
            filter_fn=lambda el: el.id() in keep,
            max_faces=max_faces,
            parallel=parallel,
        )

    def _tessellated_ids(self, example_ifc, wanted=12):
        """Elements with a face count a ceiling can actually bite on."""
        ids = []
        for element in example_ifc.by_type("IfcBeam"):
            if element.Representation is None:
                continue
            if representation_face_count(element) > 0:
                ids.append(element.id())
            if len(ids) >= wanted:
                break
        return ids

    def test_the_model_can_exercise_the_ceiling(self, example_ifc):
        """Guard: if nothing has a face count, the tests below prove nothing."""
        assert len(self._tessellated_ids(example_ifc)) >= 5

    @pytest.mark.parametrize("parallel", [False, True])
    def test_a_refused_element_is_not_also_a_failure(
        self, example_ifc, example_model, parallel, capsys
    ):
        ids = self._tessellated_ids(example_ifc)

        self._run(example_ifc, example_model, ids, max_faces=1, parallel=parallel)
        out = capsys.readouterr().out

        assert "Skipped (over --max-faces)" in out, "the ceiling did not bite"

        failed = _reported(out, "Failed conversions:")
        assert failed == 0, (
            f"{failed} refused elements were reported as failures; "
            "a deliberate skip is not a failure"
        )

    @pytest.mark.parametrize("parallel", [False, True])
    def test_the_counts_partition_the_total(
        self, example_ifc, example_model, parallel, capsys
    ):
        ids = self._tessellated_ids(example_ifc)

        self._run(example_ifc, example_model, ids, max_faces=1, parallel=parallel)
        out = capsys.readouterr().out

        total = _reported(out, "Total processed:")
        valid = _reported(out, "Valid geometries:")
        failed = _reported(out, "Failed conversions:")
        norep = _reported(out, "Skipped (no representation):")
        ceiling = _reported(out, "Skipped (over --max-faces):")

        assert valid + failed + norep + ceiling == total, (
            f"buckets do not partition the total: {valid} valid + {failed} failed "
            f"+ {norep} no-rep + {ceiling} over-ceiling != {total}"
        )

    @pytest.mark.parametrize("parallel", [False, True])
    def test_without_a_ceiling_nothing_changes(
        self, example_ifc, example_model, parallel, capsys
    ):
        """
        The guard against fixing this by never counting failures: with no ceiling
        set, these walls convert and the counts still add up.
        """
        ids = self._tessellated_ids(example_ifc)

        self._run(example_ifc, example_model, ids, max_faces=None, parallel=parallel)
        out = capsys.readouterr().out

        assert "Skipped (over --max-faces)" not in out

        total = _reported(out, "Total processed:")
        valid = _reported(out, "Valid geometries:")
        failed = _reported(out, "Failed conversions:")
        norep = _reported(out, "Skipped (no representation):")

        assert valid + failed + norep == total
        assert valid > 0, "these elements should convert when nothing refuses them"


class TestRefusalIsDistinguishableAtAll:
    """
    The unit-level reason the fix is possible: the processor records a refusal,
    so the caller never has to infer it from a bare None.
    """

    def test_a_refused_element_is_recorded_as_skipped_not_failed(self, monkeypatch):
        import geometry_engine

        processor = IFCGeometryProcessor(max_faces=10)
        monkeypatch.setattr(geometry_engine, "representation_face_count", lambda _el: 99)

        class Element:
            Representation = object()

            def is_a(self, other=None):
                return "IfcBeam" if other is None else other == "IfcBeam"

            def id(self):
                return 1

            Name = "beam"

        assert processor.process_ifc_element(Element(), None) is None
        assert len(processor.skipped_elements) == 1
        assert processor.failed_elements == [], (
            "a refusal must not also land in the failed list, or the summary "
            "double-counts it again by a different route"
        )


def _reported(output, label):
    """The integer the run printed after `label`, or 0 if it printed no such line."""
    for line in output.splitlines():
        if label in line:
            after = line.split(label, 1)[1].strip()
            digits = after.split()[0].replace(",", "")
            return int(digits)
    return 0
