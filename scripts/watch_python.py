"""Exit 1 once onnxruntime ships a wheel for the Python `requires-python` excludes.

Run weekly by `.github/workflows/watch-python.yml`. Reads the upper bound from
pyproject.toml (`<3.15`) and PyPI's JSON for onnxruntime's latest release;
installs nothing. Exit 0: still no wheel, the bound stands. Exit 1: there is
one; raise the bound, the README's "Python 3.11 to 3.14" and the CI matrix.
Exit 2: PyPI could not be read.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def excluded() -> str:
    """The Python `requires-python` stops below, as a wheel tag: "cp315"."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    bound = re.search(r'^requires-python = ".*<(\d+)\.(\d+)"', text, re.MULTILINE)
    if not bound:
        raise SystemExit("pyproject.toml: no upper bound in requires-python")
    return f"cp{bound.group(1)}{bound.group(2)}"


def wheels(tag: str, release: dict) -> list[str]:
    return sorted(
        f["filename"]
        for f in release.get("urls", [])
        if f["filename"].endswith(".whl") and f"-{tag}-" in f["filename"]
    )


def main() -> int:
    tag = excluded()
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/onnxruntime/json", timeout=30) as r:
            release = json.load(r)
    except OSError as exc:
        print(f"could not read PyPI: {exc}", file=sys.stderr)
        return 2
    found = wheels(tag, release)
    version = release.get("info", {}).get("version", "?")
    if found:
        print(
            f"onnxruntime {version} ships {len(found)} wheel(s) for {tag}, e.g. {found[0]}. "
            "Raise requires-python in pyproject.toml, the README's Python range and the "
            "CI matrix, once the 'Installs and runs on Python' job passes there."
        )
        return 1
    print(f"onnxruntime {version}: no {tag} wheel yet; requires-python stands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
