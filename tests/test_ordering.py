"""
Deterministic element order (#9).

`get_decomposition` returns a `set`, so iteration order varied between processes
and the same command produced CSVs whose rows moved between runs. Contents were
always identical as a set; only the order shifted - which is exactly what makes
it dangerous, because "diff the output against main" then reports differences
that are not real.

`test_output_is_reproducible` in test_extraction.py covers this end to end. These
pin the guarantee at its source, so a regression names the cause rather than just
showing a byte diff.
"""

import pytest

import ifc_processor
from ifc_processor import storey_decomposition


class FakeElement:
    def __init__(self, element_id):
        self._id = element_id

    def id(self):
        return self._id

    def __repr__(self):
        return f"<el {self._id}>"


class TestStoreyDecomposition:
    def test_returns_sorted_by_id(self, monkeypatch):
        elements = {FakeElement(i) for i in (55, 3, 900, 12)}
        monkeypatch.setattr(ifc_processor, "get_decomposition", lambda s: elements)

        assert [e.id() for e in storey_decomposition(object())] == [3, 12, 55, 900]

    def test_returns_a_list_not_a_set(self, monkeypatch):
        """
        Callers index and re-filter the result, and a set has no order to preserve.
        Returning a sequence is the property that makes everything downstream
        deterministic.
        """
        monkeypatch.setattr(ifc_processor, "get_decomposition",
                            lambda s: {FakeElement(1)})

        assert isinstance(storey_decomposition(object()), list)

    def test_order_is_independent_of_input_order(self, monkeypatch):
        """
        The fix must not merely preserve whatever order it was handed - that is
        the bug. Two different iteration orders of the same elements must produce
        the same output.
        """
        elements = [FakeElement(i) for i in (7, 2, 90, 40)]

        monkeypatch.setattr(ifc_processor, "get_decomposition", lambda s: list(elements))
        forward = [e.id() for e in storey_decomposition(object())]

        monkeypatch.setattr(ifc_processor, "get_decomposition",
                            lambda s: list(reversed(elements)))
        backward = [e.id() for e in storey_decomposition(object())]

        assert forward == backward == [2, 7, 40, 90]

    def test_empty_storey(self, monkeypatch):
        monkeypatch.setattr(ifc_processor, "get_decomposition", lambda s: set())

        assert storey_decomposition(object()) == []

    def test_sorts_numerically_not_lexically(self, monkeypatch):
        """IFC ids are integers; sorting them as strings would put 100 before 20."""
        elements = {FakeElement(i) for i in (20, 100, 3)}
        monkeypatch.setattr(ifc_processor, "get_decomposition", lambda s: elements)

        assert [e.id() for e in storey_decomposition(object())] == [3, 20, 100]


@pytest.mark.example
class TestOnTheRealModel:
    def test_repeated_calls_agree(self, example_ifc):
        storey = example_ifc.by_type("IfcBuildingStorey")[0]

        first = [e.id() for e in storey_decomposition(storey)]
        second = [e.id() for e in storey_decomposition(storey)]

        assert first == second
        assert first, "example storey decomposes to nothing"

    def test_same_elements_as_the_unsorted_call(self, example_ifc):
        """Ordering is the only thing that may change - nothing gained or lost."""
        storey = example_ifc.by_type("IfcBuildingStorey")[0]

        ordered = storey_decomposition(storey)
        raw = ifc_processor.get_decomposition(storey)

        assert len(ordered) == len(raw)
        assert {e.id() for e in ordered} == {e.id() for e in raw}

    def test_ids_are_strictly_increasing(self, example_ifc):
        """
        Strictly, not merely non-decreasing: IFC ids are unique within a file, so
        a duplicate would mean the decomposition returned the same element twice.
        """
        for storey in example_ifc.by_type("IfcBuildingStorey"):
            ids = [e.id() for e in storey_decomposition(storey)]
            assert ids == sorted(set(ids)), f"duplicate or unsorted ids in {storey.Name}"
