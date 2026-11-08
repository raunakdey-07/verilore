"""The wheel ships one top-level namespace: `verilore`.

`verilore_sdk` and `verilore_errors` remain as deprecated top-level shims for
this release; nothing else may be a top-level module or package.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys

import pytest

import verilore


def test_shims_alias_the_package() -> None:
    """The deprecated shims alias the package modules exactly.

    Aliasing ``sys.modules`` keeps private names and monkeypatch targets
    identical to importing ``verilore.sdk`` / ``verilore.errors`` directly.
    Importing a shim emits a DeprecationWarning once.
    """
    sys.modules.pop("verilore_sdk", None)
    with pytest.warns(DeprecationWarning):
        import verilore_sdk
    assert verilore_sdk is verilore.sdk

    sys.modules.pop("verilore_errors", None)
    with pytest.warns(DeprecationWarning):
        import verilore_errors
    assert verilore_errors is verilore.errors


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
