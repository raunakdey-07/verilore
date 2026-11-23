"""The next-Python watcher reads the bound the package declares (DOCS-1)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _watch():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import watch_python
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    return watch_python


def test_it_watches_the_python_requires_python_excludes():
    text = (ROOT / "pyproject.toml").read_text()
    upper = re.search(r'^requires-python = ".*<(\d+)\.(\d+)"', text, re.M).groups()
    assert _watch().excluded() == f"cp{upper[0]}{upper[1]}"


def test_it_finds_a_wheel_for_that_python_and_nothing_else():
    release = {
        "urls": [
            {"filename": "onnxruntime-1.40.0-cp314-cp314-manylinux_2_27_x86_64.whl"},
            {"filename": "onnxruntime-1.40.0-cp315-cp315-manylinux_2_27_x86_64.whl"},
            {"filename": "onnxruntime-1.40.0.tar.gz"},
        ]
    }
    assert _watch().wheels("cp315", release) == [
        "onnxruntime-1.40.0-cp315-cp315-manylinux_2_27_x86_64.whl"
    ]
    assert _watch().wheels("cp316", release) == []


def test_the_readme_says_why_the_next_python_is_not_supported():
    readme = (ROOT / "README.md").read_text()
    assert "Python 3.15 is not supported yet" in readme
    workflow = (ROOT / ".github" / "workflows" / "watch-python.yml").read_text()
    assert "python3 scripts/watch_python.py" in workflow and "schedule:" in workflow
