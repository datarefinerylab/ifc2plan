"""
Each module must import what it uses.

`ifc_processor` called `ifcopenshell.geom.settings()` and
`ifcopenshell.geom.create_shape()` without ever importing `ifcopenshell.geom`.
It worked only because ifcopenshell 0.8.4 imported that submodule as a side
effect of another one. 0.8.5 stopped, and every geometry path in the module died
with `AttributeError: module 'ifcopenshell' has no attribute 'geom'`.

Nothing in the rest of the suite catches this. `geometry_engine` imports
`ifcopenshell.geom` inside its own functions, so once any test has touched the
engine the submodule is in `sys.modules` and `ifcopenshell.geom` resolves for
everyone - including the module that never imported it. The bug is only visible
to a process that imports `ifc_processor` and nothing else, which is why these
tests shell out.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "ifc2plan"


def _run_isolated(body: str) -> subprocess.CompletedProcess:
    """Run a snippet in a fresh interpreter with only src/ifc2plan importable."""
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(SRC)!r})
    """) + textwrap.dedent(body)

    return subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=300)


def test_ifc_processor_can_use_geom_without_help():
    """
    The exact failure CI found on ifcopenshell 0.8.5 / Python 3.13.

    `space_geometry_settings` is the first thing the space path calls, and it was
    reaching for `ifcopenshell.geom` that nothing had imported.
    """
    result = _run_isolated("""
        import ifc_processor
        settings = ifc_processor.space_geometry_settings()
        assert settings is not None
        print("OK")
    """)

    assert result.returncode == 0, (
        f"importing ifc_processor alone is not enough to use it:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_geometry_engine_can_convert_without_help():
    """The same guarantee for the other module that reaches into ifcopenshell.geom."""
    result = _run_isolated("""
        from geometry_engine import IFCGeometryProcessor
        processor = IFCGeometryProcessor()
        assert processor._get_settings() is not None
        print("OK")
    """)

    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


@pytest.mark.parametrize("module", ["ifc_processor", "geometry_engine", "formatters",
                                    "extract_floor_plans"])
def test_module_imports_standalone(module):
    """
    Every module imports on its own.

    The package uses flat imports and has no pyproject.toml, so import order is
    whatever the entry point happens to establish. A module that only works when
    something else was imported first is a latent break waiting for a caller in a
    different order.
    """
    result = _run_isolated(f"import {module}; print('OK')")

    assert result.returncode == 0, f"{module} does not import standalone:\n{result.stderr}"
