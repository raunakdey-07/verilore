"""`recall`, `explain` and `receipt` take --path-prefix; `verilore --version` exists (CLI-1).

`brief`, `check` and `review` scope to folders, and so does the SDK's `query`,
but the three commands that answer a question did not: asked "What is the
offer?" in a kit with a spring and an autumn campaign, the command line could
not say which one (Team 052). And `verilore --version` did not exist, so a
release prompt that asked for it failed.
"""

from __future__ import annotations

import json
import os
import uuid
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]


def test_the_version_is_the_installed_packages():
    from verilore.cli.main import app

    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"verilore {version('verilore')}"


@pytest.mark.parametrize("command", ["recall", "explain", "receipt"])
def test_the_question_commands_take_a_path_prefix(command):
    from typer.main import get_command

    from verilore.cli.main import app

    options = {o for p in get_command(app).commands[command].params for o in p.opts}
    assert "--path-prefix" in options


@pytest.fixture(scope="module")
def corpus():
    from verilore import Verilore

    previous = {
        name: os.environ.get(name)
        for name in ("VERILORE_LEXICAL", "VERILORE_INGEST_ROOTS", "VERILORE_RUNTIME")
    }
    os.environ.update(
        {"VERILORE_LEXICAL": "1", "VERILORE_INGEST_ROOTS": str(ROOT), "VERILORE_RUNTIME": "off"}
    )
    try:
        name = f"cli-scope-{uuid.uuid4().hex[:10]}"
        Verilore(name).sync(str(ROOT / "examples" / "trailhead"))
        yield name
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run(*args):
    from verilore.cli.main import app

    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    # Standard output only: lexical mode says so on standard error.
    return result.stdout


def test_recall_answers_from_the_folder_named(corpus):
    question = "What is the offer?"
    autumn = _run("recall", "--corpus", corpus, "--path-prefix", "campaigns/autumn", question)
    spring = _run("recall", "--corpus", corpus, "--path-prefix", "campaigns/spring", question)
    assert "15 percent off" in autumn and "free helmet" not in autumn
    assert "free helmet" in spring and "15 percent off" not in spring


def test_explain_and_receipt_are_scoped_too(corpus, tmp_path):
    question = "What is the offer?"
    explained = json.loads(
        _run("explain", "--corpus", corpus, "--path-prefix", "campaigns/autumn", "--json", question)
    )
    paths = {c["path"] for c in explained["response"]["current_memories"]}
    assert paths == {"campaigns/autumn/brief.md"}
    out = tmp_path / "receipt.json"
    _run(
        "receipt", "--corpus", corpus, "--path-prefix", "campaigns/spring", "-o", str(out), question
    )
    receipt = json.loads(out.read_text())
    claims = receipt["response"]["current_memories"]
    assert {c["path"] for c in claims} == {"campaigns/spring/brief.md"}
