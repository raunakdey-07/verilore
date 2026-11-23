"""One file at a time and the whole folder at once hold the same notes (STATUS-2).

STATUS-1 holds a document that declares no status as a draft when another in
its folder sync says `status: approved`. Two edges were left:

* **One file at a time.** `guide.md` (approved) and then `notes.md` (no status)
  through the one-file route: the note was served as approved, where a folder
  sync of the same two files holds it. Holding it there by default would change
  what a v0.12 integration that posts files one at a time serves (the brand-kit
  scenario test posts a kit that way), so the route now warns where a sync
  would differ, and holds the note as a draft when asked (`hold_unmarked`).
  When the approved file arrives second, the warning names the notes already
  stored, because only a sync of their folder (or a status) holds them.
* **The rule letting go.** Archive or move the last approved file, and the next
  sync serves the unmarked notes beside it as approved. That was reported as
  `[OK]`. It is a warning now, and the summary names each one.

`remember` is unchanged: an approved statement it writes declares no status.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

APPROVED = "---\nstatus: approved\n---\n\n"
GUIDE = "# Brand guide\n\n- Our voice is warm, plain and direct.\n"
NOTES = "# Kickoff notes\n\n- Our voice is bold, cheeky and loud.\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from verilore import Verilore

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.delenv("VERILORE_DEFAULT_STATE", raising=False)
    return Verilore(f"unmarked-order-{uuid.uuid4().hex[:10]}")


def _one_file(client, path, content, hold=False):
    """The one-file route: what `POST /api/ingest/file` and `verilore ingest` run."""
    from verilore.api.routers import ingest as route
    from verilore.api.services.ingestion import IngestionService

    calls = {}
    original = IngestionService.ingest_file

    async def spy(self, *args, **kwargs):
        calls.update(kwargs)
        return await original(self, *args, **kwargs)

    IngestionService.ingest_file = spy
    try:
        request = route.IngestFileRequest(
            content=content, path=path, corpus=client.name, hold_unmarked=hold
        )
        response = asyncio.run(route.ingest_file(request))
    finally:
        IngestionService.ingest_file = original
    assert calls.get("unmarked_rule") == ("hold" if hold else "warn")
    return response


def _served(client):
    return {c.path for c in client.memory.current().current_memories}


def test_a_note_ingested_after_the_approved_guide_is_served_with_a_warning(client):
    _one_file(client, "brand/guide.md", APPROVED + GUIDE)
    response = _one_file(client, "notes/kickoff.md", NOTES)
    (warning,) = response.warnings
    assert (warning["code"], warning["field"]) == ("unmarked_beside_approved", "brand/guide.md")
    assert _served(client) == {"brand/guide.md", "notes/kickoff.md"}


def test_asked_to_hold_it_the_route_holds_it_as_a_sync_does(client):
    _one_file(client, "brand/guide.md", APPROVED + GUIDE, hold=True)
    response = _one_file(client, "notes/kickoff.md", NOTES, hold=True)
    assert not response.warnings
    assert _served(client) == {"brand/guide.md"}
    assert "notes/kickoff.md" in {d["path"] for d in client.memory.review().drafts}


def test_a_note_ingested_before_it_is_named_when_the_guide_arrives(client):
    first = _one_file(client, "notes/kickoff.md", NOTES)
    assert not first.warnings
    second = _one_file(client, "brand/guide.md", APPROVED + GUIDE)
    (warning,) = second.warnings
    assert (warning["code"], warning["field"]) == ("unmarked_still_approved", "notes/kickoff.md")


def test_a_folder_sync_then_holds_the_note(tmp_path, client):
    _one_file(client, "notes/kickoff.md", NOTES)
    _one_file(client, "brand/guide.md", APPROVED + GUIDE)
    (tmp_path / "brand").mkdir()
    (tmp_path / "notes").mkdir()
    (tmp_path / "brand" / "guide.md").write_text(APPROVED + GUIDE)
    (tmp_path / "notes" / "kickoff.md").write_text(NOTES)
    assert client.sync(str(tmp_path)).unmarked == ["notes/kickoff.md"]
    assert _served(client) == {"brand/guide.md"}


def test_an_approved_statement_remembered_beside_the_kit_stays_approved(client):
    _one_file(client, "brand/guide.md", APPROVED + GUIDE)
    client.memory.remember("Our tagline is Ride further.", key="tagline", state="approved")
    assert any("Ride further" in c.claim for c in client.memory.current().current_memories)


def test_a_sync_that_lets_a_held_note_go_says_so(tmp_path, client):
    (tmp_path / "brand").mkdir()
    (tmp_path / "notes").mkdir()
    (tmp_path / "brand" / "guide.md").write_text(APPROVED + GUIDE)
    (tmp_path / "notes" / "kickoff.md").write_text(NOTES)
    assert client.sync(str(tmp_path)).unmarked == ["notes/kickoff.md"]

    (tmp_path / "brand" / "guide.md").unlink()
    summary = client.sync(str(tmp_path), delete_removed=True)
    assert summary.promoted == ["notes/kickoff.md"]
    assert not summary.success and summary.failed == 0
    assert any("served as approved again" in e for e in summary.errors)
    assert _served(client) == {"notes/kickoff.md"}

    # Nothing changes on the next sync, and nothing is reported again.
    again = client.sync(str(tmp_path), delete_removed=True)
    assert again.promoted == [] and again.success


def test_the_cli_reports_it_as_a_warning(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from verilore.cli.main import app

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.delenv("VERILORE_DEFAULT_STATE", raising=False)
    corpus = f"unmarked-order-{uuid.uuid4().hex[:10]}"
    (tmp_path / "brand").mkdir()
    (tmp_path / "notes").mkdir()
    (tmp_path / "brand" / "guide.md").write_text(APPROVED + GUIDE)
    (tmp_path / "notes" / "kickoff.md").write_text(NOTES)
    runner = CliRunner()
    assert runner.invoke(app, ["ingest-repo", str(tmp_path), "--corpus", corpus]).exit_code == 0
    (tmp_path / "brand" / "guide.md").unlink()
    result = runner.invoke(
        app, ["ingest-repo", str(tmp_path), "--corpus", corpus, "--delete-removed"]
    )
    output = result.output + (result.stderr if result.stderr_bytes is not None else "")
    # The first tagged line, as in test_cli_ingest_repo_exit_codes: a logging
    # handler an earlier test left on a closed stream can print before it.
    first = next(line for line in output.splitlines() if line.startswith("["))
    assert first.startswith("[WARN] sync:"), output
    assert "notes/kickoff.md: served as approved again" in output
    assert result.exit_code == 0
