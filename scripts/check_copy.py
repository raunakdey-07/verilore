"""Run `check` over a folder of copy against a kit's rules, with no database.

For a false-positive run on copy that cannot be committed (a style guide or
posts under a non-commercial licence): every finding on copy that follows the
kit is a false one. `tests/test_check_false_positives.py` is the committed
suite.

    python scripts/check_copy.py KIT.md DRAFTS/ [--channel Instagram]

Each line of KIT.md that is not a heading is a rule ("- " bullets are read as
lines). Each .md or .txt file in DRAFTS/ is one draft. Prints each draft's
findings and the rules nothing tested, then a count.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verilore.check import check_draft  # noqa: E402


def rules(kit: Path) -> list[str]:
    lines = []
    for line in kit.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line[2:].strip() if line.startswith(("- ", "* ")) else line)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("kit", type=Path)
    parser.add_argument("drafts", type=Path)
    parser.add_argument("--channel", default=None)
    options = parser.parse_args(argv)
    current = {
        "corpus": options.kit.stem,
        "current_memories": [
            {"id": f"rule-{n}", "claim": claim, "path": options.kit.name}
            for n, claim in enumerate(rules(options.kit))
        ],
    }
    drafts = sorted(p for p in options.drafts.rglob("*") if p.suffix in {".md", ".txt"})
    total = 0
    for path in drafts:
        result = check_draft(path.read_text(encoding="utf-8"), current, channel=options.channel)
        total += len(result.findings)
        for finding in result.findings:
            print(f"{path.relative_to(options.drafts)}: {finding.kind}: {finding.detail}")
    print(f"{total} finding(s) on {len(drafts)} draft(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
