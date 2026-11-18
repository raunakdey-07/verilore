"""A command a reader copies from the docs runs as pasted.

A ```bash block is what the copy button copies. `$ verilore init` pasted into a
shell is "$: command not found", and `verilore feedback <query_id>` is a
redirection from a file named `query_id`. A transcript, with output, is a
```console block, where the `$` marks which lines are typed. And the five-minute
path runs the README's quickstart verbatim, so the quickstart must still be
found once its prompts are gone.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL_BLOCK = re.compile(r"```(?:bash|sh|shell|zsh)\n(.*?)```", re.S)
#: Records of what happened, not instructions to follow.
NOT_INSTRUCTIONS = ("docs/archive/", "docs/research/", "docs/performance/", "CHANGELOG.md")


def _docs() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [path for path in tracked if not path.startswith(NOT_INSTRUCTIONS)]


def _command_part(line: str) -> str:
    """The line without quoted strings and without a trailing comment."""
    bare = re.sub(r"'[^']*'|\"[^\"]*\"", "''", line)
    return bare.split(" #")[0]


def test_no_shell_block_a_reader_copies_has_a_prompt_or_a_placeholder():
    problems = []
    for path in _docs():
        text = (ROOT / path).read_text(encoding="utf-8")
        for block in SHELL_BLOCK.finditer(text):
            first = text[: block.start()].count("\n") + 2
            for offset, line in enumerate(block.group(1).splitlines()):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                where = f"{path}:{first + offset}: {stripped}"
                if re.match(r"(\$|>|%)\s", stripped):
                    problems.append(f"prompt  {where}")
                elif re.search(r"(?<![<\w])<[A-Za-z][\w -]*>", _command_part(stripped)):
                    problems.append(f"placeholder  {where}")
    assert not problems, "\n".join(problems)


def test_the_five_minute_path_still_finds_the_readme_quickstart():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import cleanroom_quickstart
    finally:
        sys.path.pop(0)
    assert cleanroom_quickstart.readme_commands()[:8] == [
        "verilore init",
        "verilore ingest-repo ./docs/adr --corpus project",
        'verilore recall "What is the primary datastore?" --corpus project',
        'verilore remember "The primary datastore is PostgreSQL 16." --corpus project '
        "--key architecture.datastore --topic-key architecture.datastore",
        'verilore recall "What is the primary datastore?" --corpus project',
        'verilore history "" --corpus project',
        'verilore receipt "What is the primary datastore?" --corpus project -o receipt.json',
        "verilore verify receipt.json",
    ]
