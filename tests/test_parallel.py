"""
Tests for the parallel mesh pass.

The bug these exist for (#12): `_process_element_worker` called
`ifcopenshell.open(ifc_path)` itself, so the whole file was reparsed once per
element instead of once per worker process. On a 97 MB model that was 1.9 s of
parsing for ~0.03 s of geometry, and it made the parallel path lose to plain
sequential processing.

It is not visible in output - only in runtime - so nothing else in the suite
would catch it coming back.
"""

import inspect
import os

import pytest

import ifc_processor
from ifc_processor import (
    _init_worker,
    _memory_budget_bytes,
    _process_element_worker,
    _worker_count,
    get_elements_and_shapes,
)


class TestWorkerOpensModelOnce:
    def test_worker_does_not_open_the_file(self, example_model, monkeypatch):
        """
        The regression guard for #12.

        Asserts on the mechanism rather than on elapsed time: a timing threshold
        would be flaky on a loaded machine, and the defect is precisely "who calls
        open", which is exactly what this counts.
        """
        _init_worker(str(example_model))

        opens = []
        real_open = ifc_processor.ifcopenshell.open
        monkeypatch.setattr(
            ifc_processor.ifcopenshell, "open",
            lambda *a, **k: (opens.append(a), real_open(*a, **k))[1],
        )

        element_id = next(
            e.id() for e in ifc_processor._worker_model.by_type("IfcWall")
            if e.Representation is not None
        )
        returned_id, _, _ = _process_element_worker(element_id)

        assert returned_id == element_id
        assert opens == [], f"worker reopened the model {len(opens)} time(s)"

    def test_init_worker_sets_up_reusable_state(self, example_model):
        ifc_processor._worker_model = None
        ifc_processor._worker_processor = None

        _init_worker(str(example_model))

        assert ifc_processor._worker_model is not None
        assert ifc_processor._worker_processor is not None

    def test_worker_takes_a_bare_id_not_a_tuple(self, example_model):
        """
        The worker signature changed from ``(element_id, ifc_path)`` to a bare id,
        and `pool.imap` passes exactly one argument.

        Checked by signature rather than by calling with a tuple: `by_id` accepts
        a tuple without complaining and `process_ifc_element` swallows every
        exception, so the wrong argument shape returns ``(args, None)`` silently
        instead of raising. That is the same silent-drop behaviour that makes this
        code hard to test, and it means a call-based check proves nothing.
        """
        params = inspect.signature(_process_element_worker).parameters
        assert len(params) == 1, f"imap passes one argument, worker takes {len(params)}"

        _init_worker(str(example_model))
        element_id = next(
            e.id() for e in ifc_processor._worker_model.by_type("IfcWall")
            if e.Representation is not None
        )
        returned_id, mesh, diagnostics = _process_element_worker(element_id)

        assert returned_id == element_id
        assert mesh is not None, "a wall with a representation should produce a mesh"

        slow, face_skipped, failed = diagnostics
        assert slow == [] and face_skipped == [] and failed == [], (
            "an ordinary wall is neither slow, oversized, nor a failed conversion"
        )


class TestWorkerCount:
    def test_at_least_one_worker(self, tmp_path):
        """A model larger than the whole memory budget must not yield 0 workers."""
        huge = tmp_path / "huge.ifc"
        huge.write_bytes(b"x")
        os.truncate(huge, 500 * 1024 ** 3)  # sparse; never read

        assert _worker_count(str(huge)) == 1

    def test_small_model_uses_all_cores(self, example_model):
        assert _worker_count(str(example_model)) == ifc_processor.cpu_count()

    def test_never_exceeds_core_count(self, example_model, tmp_path):
        tiny = tmp_path / "tiny.ifc"
        tiny.write_bytes(b"x")

        assert _worker_count(str(tiny)) <= ifc_processor.cpu_count()

    def test_missing_file_falls_back_to_cores(self, tmp_path):
        """Sizing must never be the thing that breaks a run."""
        assert _worker_count(str(tmp_path / "nope.ifc")) == ifc_processor.cpu_count()

    def test_budget_is_positive_and_below_physical_memory(self):
        budget = _memory_budget_bytes()
        if budget is None:
            pytest.skip("cannot determine physical memory on this platform")
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        assert 0 < budget < total


@pytest.mark.example
def test_parallel_and_sequential_agree(example_model, example_ifc):
    """
    Both paths must select the same elements and produce the same mesh count.

    This is the check that makes the #12 fix safe to land: it is the only thing
    standing between "faster" and "faster but quietly dropping elements".
    Meshes are compared by count and by element id, not by vertex data - trimesh
    objects round-trip through pickle in the parallel path and exact float
    equality is not the property under test.
    """
    seq_els, seq_meshes = get_elements_and_shapes(
        example_ifc, str(example_model),
        filter_fn=lambda el: el.is_a("IfcWall"), parallel=False,
    )
    par_els, par_meshes = get_elements_and_shapes(
        example_ifc, str(example_model),
        filter_fn=lambda el: el.is_a("IfcWall"), parallel=True,
    )

    assert len(seq_meshes) > 0, "fixture produced no meshes; test proves nothing"
    assert sorted(e.id() for e in seq_els) == sorted(e.id() for e in par_els)
    assert len(seq_meshes) == len(par_meshes)
