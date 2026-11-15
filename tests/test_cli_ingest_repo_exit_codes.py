"""`verilore ingest-repo` exits 0 when the documents landed, warnings or not.

A warning used to make the whole sync `[FAIL]` with exit code 1, although every
claim was stored. A job that runs the sync could not tell a kit with one odd
frontmatter value from a kit that did not ingest.
"""

from __future__ import annotations

import os
import uuid

import pytest
from typer.testing import CliRunner

from verilore.sdk import SyncSummary

RULES = '---\nstatus: maybe\n---\n\n# Rules\n\n- Never use the word "premium" in copy.\n'
CLEAN = "# Specs\n\n- The house blend is roasted in Bengaluru.\n"


def _invoke(args, root):
    from verilore.cli.main import app

    env = dict(os.environ, VERILORE_INGEST_ROOTS=str(root), VERILORE_LEXICAL="1")
    return CliRunner().invoke(app, args, env=env)


@pytest.fixture
def corpus():
    return f"sync-exit-{uuid.uuid4().hex[:10]}"


def test_a_warning_is_reported_and_the_sync_still_exits_zero(tmp_path, corpus):
    (tmp_path / "rules.md").write_text(RULES)
    (tmp_path / "specs.md").write_text(CLEAN)

    result = _invoke(["ingest-repo", str(tmp_path), "--corpus", corpus], tmp_path)

    assert result.exit_code == 0, result.output
    first = next(line for line in result.output.splitlines() if line.startswith("["))
    assert first.startswith("[WARN] sync: +2 ~0 =0 -0 !0, "), first
    assert first.endswith("2 claims, 1 warning"), first
    assert "  - rules.md: unknown_status" in result.output
    assert "Every document was ingested" in result.output


def test_strict_turns_the_same_warning_into_exit_one(tmp_path, corpus):
    (tmp_path / "rules.md").write_text(RULES)

    result = _invoke(["ingest-repo", str(tmp_path), "--corpus", corpus, "--strict"], tmp_path)

    assert result.exit_code == 1, result.output
    assert "[WARN] sync:" in result.output
    assert "--strict to exit 1" not in result.output


def test_a_clean_kit_is_ok(tmp_path, corpus):
    (tmp_path / "specs.md").write_text(CLEAN)

    result = _invoke(["ingest-repo", str(tmp_path), "--corpus", corpus, "--strict"], tmp_path)

    assert result.exit_code == 0, result.output
    assert "[OK] sync: +1 ~0 =0 -0 !0, " in result.output
    assert "warning" not in result.output


def test_a_document_that_failed_is_still_a_failure(tmp_path, monkeypatch):
    from verilore import sdk

    summary = SyncSummary(success=False, added=1, failed=1, errors=["bad.md: could not be read"])
    monkeypatch.setattr(sdk.Verilore, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(sdk.Verilore, "sync", lambda self, *a, **k: summary)

    result = _invoke(["ingest-repo", str(tmp_path), "--corpus", "any"], tmp_path)

    assert result.exit_code == 1, result.output
    assert "[FAIL] sync: +1 ~0 =0 -0 !1, " in result.output
    assert "  - bad.md: could not be read" in result.output


def test_the_summary_separates_warnings_from_failures():
    warned = SyncSummary(success=False, added=1, warnings=["rules.md: unknown_status"])
    assert warned.ok and not warned.success
    assert not SyncSummary(success=False, failed=1).ok
