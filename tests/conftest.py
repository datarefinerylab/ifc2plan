"""
Shared fixtures and model discovery.

Two things here are load-bearing:

1. The package is imported by path, not installed. `src/ifc2plan` uses flat
   imports (`from geometry_engine import ...`) and there is no pyproject.toml,
   so the directory has to be on sys.path before any test module is collected.
   Doing it here means tests import the same way the CLI does.

2. Models are discovered, not hardcoded. The Schependomlaan example is committed
   and always present. The KAAN models are client data, gitignored, and exist
   only on machines that have them - so tests over them must skip cleanly rather
   than fail, or CI can never be green. The open-access IFC4 models are fetched
   rather than committed (`python examples/fetch_open_models.py`) and follow the
   same rule: present, they are tested; absent, nothing fails.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "ifc2plan"

# Must happen at import time, before test modules are collected.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXAMPLE_MODEL = REPO_ROOT / "examples" / "data" / "Shependomlaan" / "IFC Schependomlaan.ifc"
PRIVATE_DIR = REPO_ROOT / "examples" / "data" / "private"
OPEN_DIR = REPO_ROOT / "examples" / "data" / "open"

# Models large enough that a full run is not something you want on every commit.
# Sizes are the KAAN set as of writing; the threshold is what matters, not the list.
SLOW_THRESHOLD_BYTES = 60 * 1024 * 1024


def _private_models():
    if not PRIVATE_DIR.is_dir():
        return []
    return sorted(PRIVATE_DIR.glob("*.ifc"))


def _open_models():
    """
    Open-access IFC4 models, if they have been fetched. See docs/test-models.md
    for what they are and what each one's licence permits.
    """
    if not OPEN_DIR.is_dir():
        return []
    return sorted(OPEN_DIR.glob("*.ifc"))


def _mark_for(path: Path):
    marks = [pytest.mark.private]
    if path.stat().st_size >= SLOW_THRESHOLD_BYTES:
        marks.append(pytest.mark.slow)
    return marks


def _model_params():
    """
    Every model available on this machine, as pytest params.

    The example is always included. Open-access and private models are added only
    if present; when neither is there the parametrisation still yields the
    example, so the suite is meaningful on a fresh clone and on CI.
    """
    params = [pytest.param(EXAMPLE_MODEL, id="schependomlaan", marks=[pytest.mark.example])]
    for path in _open_models():
        params.append(pytest.param(path, id=path.stem, marks=[pytest.mark.open_model]))
    for path in _private_models():
        params.append(pytest.param(path, id=path.stem, marks=_mark_for(path)))
    return params


@pytest.fixture(scope="session", params=_model_params())
def model_path(request):
    """An IFC file to run against. Parameterised over every model present."""
    path = request.param
    if not path.exists():
        pytest.skip(f"model not available: {path.name}")
    return path


@pytest.fixture(
    scope="session",
    params=[pytest.param(p, id=p.stem, marks=[pytest.mark.open_model]) for p in _open_models()],
)
def open_model_path(request):
    """
    One fetched open-access model. Empty when none have been fetched, which
    pytest reports as a skip rather than a failure.
    """
    return request.param


@pytest.fixture(scope="session")
def example_model():
    """The committed public model. The only one guaranteed to exist."""
    if not EXAMPLE_MODEL.exists():
        pytest.skip("Schependomlaan example not found")
    return EXAMPLE_MODEL


@pytest.fixture(scope="session")
def naming_conversion_path():
    return REPO_ROOT / "naming_conversion.csv"


@pytest.fixture(scope="session")
def naming_conversion(naming_conversion_path):
    from extract_floor_plans import load_naming_conversion
    return load_naming_conversion(str(naming_conversion_path))


@pytest.fixture(scope="session")
def example_ifc(example_model):
    """The parsed example model, opened once for the whole session."""
    import ifcopenshell
    return ifcopenshell.open(str(example_model))


@pytest.fixture(scope="session")
def opened_model(model_path):
    """
    The parsed model for the current parametrisation, opened once per model.

    Session-scoped deliberately: opening lumiere.ifc takes seconds and several
    tests need it.
    """
    import ifcopenshell
    return ifcopenshell.open(str(model_path))


def pytest_configure(config):
    config.addinivalue_line("markers", "example: runs against the committed public model")
    config.addinivalue_line(
        "markers", "open_model: needs the fetched open-access models (auto-skips when absent)")
    config.addinivalue_line("markers", "private: needs the gitignored KAAN models")
    config.addinivalue_line("markers", "slow: full run over a large model")
