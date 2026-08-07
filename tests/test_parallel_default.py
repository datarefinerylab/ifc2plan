"""
Parallelism stays opt-in for every caller, not just the CLI.

Issue #39. `process_storeys` read `context.get("parallel", True)` while the CLI
declares `--parallel` as `store_true` (default False), documents it under "reach for
these on large models", and `get_elements_and_shapes` itself declares `parallel=False`.
The call site was the only place in the codebase that said otherwise.

No user command was affected, because the CLI always writes the key and `.get`'s
default never applied on that path - which is exactly why it survived. It bites a
caller that builds a context without the key: a test, a notebook, a future entry
point. That is not a harmless default. `_worker_count` sizes the pool against memory
because a parsed model is roughly 6x the file on disk and every worker holds its own
copy, so opting someone in by accident on a 199 MB model is how a run starts swapping
- the failure the sizing logic exists to prevent, reached through the one door that
bypasses the caller's intent.

Pinned as a test because a default nobody exercises is a default nobody notices
changing back.
"""

import pytest

import ifc_processor
from ifc_processor import process_storeys


class RecordingEngine:
    """Enough of a GeometryEngine for process_storeys to hold and report on."""

    def __init__(self):
        self.stats = {"open_fragments": 0, "unusable_rings": 0, "elements_affected": 0}

    def reset_stats(self):
        pass


@pytest.fixture
def spy(monkeypatch):
    """
    Capture the `parallel` argument process_storeys passes down.

    Stubbing the call rather than letting it run keeps this about the decision and
    off the geometry: no pool is started either way, so a regression fails as an
    assertion rather than as a machine under memory pressure.
    """
    seen = []

    def fake_get_elements_and_shapes(model, ifc_path, **kwargs):
        seen.append(kwargs.get("parallel"))
        return [], []

    monkeypatch.setattr(ifc_processor, "get_elements_and_shapes",
                        fake_get_elements_and_shapes)
    return seen


def _context(example_model, **overrides):
    context = {
        "ifc_path": str(example_model),
        "engine": RecordingEngine(),
        "formatters": [],
        "storey_selection": "0",
    }
    context.update(overrides)
    return context


@pytest.mark.example
def test_a_context_without_the_key_does_not_get_a_process_pool(spy, example_model):
    """The whole of #39: absence of the key must mean sequential."""
    process_storeys(_context(example_model))

    assert spy, "get_elements_and_shapes was never called; the test proves nothing"
    assert all(parallel is False for parallel in spy), (
        f"a context with no 'parallel' key was run with parallel={spy}")


@pytest.mark.example
@pytest.mark.parametrize("requested", [False, True])
def test_an_explicit_choice_is_still_honoured(spy, example_model, requested):
    """
    The fix must not become "never parallel".

    Hard-coding False at the call site would pass the test above and quietly
    disable --parallel for everyone, which is a worse bug than the one being
    fixed - and an invisible one, since the only symptom is a slow run.
    """
    process_storeys(_context(example_model, parallel=requested))

    assert spy == [requested], f"asked for parallel={requested}, passed {spy}"
