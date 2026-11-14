"""The wheel ships one top-level namespace: `verilore`.

`verilore_sdk` and `verilore_errors` were deprecated shims for v0.11 only and
are gone; nothing but `verilore` may be a top-level module or package.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path

import pytest

import verilore


@pytest.mark.parametrize("name", ["verilore_sdk", "verilore_errors"])
def test_the_v011_shims_are_gone(name: str) -> None:
    """v0.11 warned "removed in v0.12" on import; v0.12 removes them.

    The file is what an import from a checkout or a wheel would find, and
    tests/test_wheel_contents.py holds that the built wheel ships only `verilore`.
    """
    root = Path(__file__).resolve().parents[1]
    assert not (root / f"{name}.py").exists(), f"{name}.py is still in the repository"
    assert name not in dir(verilore)


def test_pack_is_dependency_free() -> None:
    """`verilore.pack` (and the verifier surface) imports no heavy dependency.

    Runs in a subprocess so ``sys.modules`` reflects a cold import of only the
    standard-library surface.
    """
    code = (
        "import sys, verilore.pack\n"
        "bad = {'httpx', 'fastapi', 'sqlalchemy', 'onnxruntime'} & set(sys.modules)\n"
        "print(sorted(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_version_matches_metadata() -> None:
    assert verilore.__version__ == importlib.metadata.version("verilore")
