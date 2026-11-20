"""A file with no status, beside files marked approved, is not approved (v0.12.1).

Team 052's evaluation synced the hard kit: `brand/` and `campaigns/` say
`status: approved`, and `notes/2025-pricing.md` says nothing. Without a
`path_prefix`, the brief and `recall` served the note's "Rs 450" as a current,
approved price, next to the real Rs 520. Safety depended on every integrator
remembering the scope.

A team that marks what it approved did not approve what it left unmarked. In a
folder sync where any document declares an approved status, a document that
declares none is held as a draft: withheld from brief, check, recall and pack,
listed by `review`, and named in the sync summary. A folder that marks nothing
approved is unchanged, and `VERILORE_DEFAULT_STATE` is still the explicit
choice for every unmarked document.
"""

from __future__ import annotations

import uuid

import pytest

from verilore.api.services import markdown_claims

APPROVED = "---\nstatus: approved\n---\n\n"
PRODUCTS = "# Products\n\n## Assam Gold\n\n- Price: Rs 520 for a 250 g tin.\n"
NOTES = "# Pricing notes from 2025\n\n- Price: Rs 450 for a 250 g tin of Assam Gold.\n"


def _kit(root, products_status=APPROVED, notes_status=""):
    (root / "brand").mkdir(exist_ok=True)
    (root / "notes").mkdir(exist_ok=True)
    (root / "brand" / "products.md").write_text(products_status + PRODUCTS)
    (root / "notes" / "2025-pricing.md").write_text(notes_status + NOTES)


@pytest.fixture
def client(tmp_path, monkeypatch):
    from verilore import Verilore

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.delenv("VERILORE_DEFAULT_STATE", raising=False)
    return Verilore(f"unmarked-{uuid.uuid4().hex[:10]}")


def _served(client):
    return {(c.path, c.claim) for c in client.memory.current().current_memories}


def test_an_unmarked_note_beside_approved_files_is_held_as_a_draft(tmp_path, client):
    _kit(tmp_path)
    summary = client.sync(str(tmp_path))
    assert summary.failed == 0, summary
    assert summary.unmarked == ["notes/2025-pricing.md"]

    brief = client.memory.brief(task="Assam Gold price", max_tokens=500)
    assert "Rs 520" in brief.text and "Rs 450" not in brief.text
    assert not brief.disagreements
    assert ("notes/2025-pricing.md", "Price: Rs 450 for a 250 g tin of Assam Gold.") not in (
        _served(client)
    )
    recalled = client.memory.recall("How much does Assam Gold cost?")
    assert all(c.path != "notes/2025-pricing.md" for c in recalled.current_memories)
    # check compares a draft with approved lines only: the old price is wrong.
    finding = client.memory.check("Assam Gold is Rs 450 a tin.").findings[0]
    assert (finding.kind, finding.quote, finding.expected) == ("number", "Rs 450", "Rs 520")
    # A person sees it waiting, and can mark it.
    waiting = {draft["path"] for draft in client.memory.review().drafts}
    assert "notes/2025-pricing.md" in waiting


def test_marking_the_note_serves_it_and_unmarking_the_folder_restores_the_old_default(
    tmp_path, client
):
    _kit(tmp_path)
    client.sync(str(tmp_path))
    note = ("notes/2025-pricing.md", "Price: Rs 450 for a 250 g tin of Assam Gold.")
    assert note not in _served(client)

    # Someone marks the note approved: it is served.
    _kit(tmp_path, notes_status=APPROVED)
    assert client.sync(str(tmp_path)).unmarked == []
    assert note in _served(client)

    # A folder that marks nothing approved serves what it holds, as before,
    # though the note's own file did not change since the first sync.
    _kit(tmp_path, products_status="")
    summary = client.sync(str(tmp_path))
    assert summary.unmarked == []
    assert note in _served(client)


def test_a_folder_that_marks_nothing_approved_is_unchanged(tmp_path, client):
    _kit(tmp_path, products_status="")
    assert client.sync(str(tmp_path)).unmarked == []
    served = _served(client)
    assert ("brand/products.md", "Price: Rs 520 for a 250 g tin.") in served
    assert ("notes/2025-pricing.md", "Price: Rs 450 for a 250 g tin of Assam Gold.") in served


def test_a_folder_that_marks_only_drafts_keeps_unmarked_files_approved(tmp_path, client):
    _kit(tmp_path, products_status="", notes_status="---\nstatus: draft\n---\n\n")
    assert client.sync(str(tmp_path)).unmarked == []
    assert ("brand/products.md", "Price: Rs 520 for a 250 g tin.") in _served(client)


def test_the_default_state_setting_is_still_the_explicit_choice(tmp_path, client, monkeypatch):
    monkeypatch.setenv("VERILORE_DEFAULT_STATE", "approved")
    _kit(tmp_path)
    assert client.sync(str(tmp_path)).unmarked == []
    assert ("notes/2025-pricing.md", "Price: Rs 450 for a 250 g tin of Assam Gold.") in (
        _served(client)
    )


def test_the_cli_names_the_files_it_holds(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from verilore.cli.main import app

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.delenv("VERILORE_DEFAULT_STATE", raising=False)
    _kit(tmp_path)
    result = CliRunner().invoke(
        app, ["ingest-repo", str(tmp_path), "--corpus", f"unmarked-{uuid.uuid4().hex[:10]}"]
    )
    output = result.output + (result.stderr if result.stderr_bytes is not None else "")
    assert "1 file(s) declare no status" in output, output
    assert "notes/2025-pricing.md" in output


@pytest.mark.parametrize(
    "metadatas,expected",
    [
        ([{"status": "approved"}, {}], "draft"),
        ([{"status": "Published"}, {}], "draft"),
        ([{"tags": ["final"]}, {}], "draft"),
        ([{}, {}], None),
        ([{"status": "draft"}, {}], None),
        ([{"status": "archived"}, {}], None),
    ],
)
def test_which_folders_hold_unmarked_files(metadatas, expected, monkeypatch):
    monkeypatch.delenv("VERILORE_DEFAULT_STATE", raising=False)
    assert markdown_claims.unmarked_state(metadatas) == expected


def test_the_state_is_kept_with_the_document_and_its_own_status_wins():
    held = markdown_claims.with_unmarked_state({"title": "Notes"}, "draft")
    assert held == {"title": "Notes", "default_status": "draft"}
    assert markdown_claims.document_state(held)[0] == "draft"
    own = markdown_claims.with_unmarked_state({"status": "approved"}, "draft")
    assert "default_status" not in own
    assert markdown_claims.document_state(own)[0] == "approved"
    # A folder that no longer holds it drops it.
    assert markdown_claims.with_unmarked_state(held, None) == {"title": "Notes"}


def test_a_rebuilt_index_keeps_the_held_note_out_of_search(tmp_path, client):
    """`verilore reindex` rebuilds the search index from the archive. The held
    state is not in the note's text, so the rebuild reads it from the version."""
    import asyncio

    from sqlalchemy import text

    from verilore.api.services.db import session_scope
    from verilore.api.services.rehydrate import rehydrate_corpus

    class FixedEmbedder:
        model_name = "test-only"
        dimension = 384

        def embed(self, texts):
            return [[1.0] + [0.0] * 383 for _ in texts]

    # Frontmatter without a status: the rebuild reads the note's own fields.
    _kit(tmp_path, notes_status="---\ntitle: Pricing notes\n---\n\n")
    assert client.sync(str(tmp_path)).unmarked == ["notes/2025-pricing.md"]
    corpus_id = client._corpus_id()

    async def rebuild_and_count():
        async with session_scope() as db:
            async with db.begin():
                await rehydrate_corpus(db, corpus_id, embedder=FixedEmbedder())
            return (
                await db.execute(
                    text(
                        "SELECT count(*) FROM chunks c JOIN documents d "
                        "ON d.id = c.doc_id "
                        "WHERE d.corpus_id = :c AND d.path = :p"
                    ),
                    {"c": corpus_id, "p": "notes/2025-pricing.md"},
                )
            ).scalar_one()

    assert asyncio.run(rebuild_and_count()) == 0
