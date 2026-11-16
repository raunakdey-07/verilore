"""Lines that name no subject are never paired with another document's lines.

A derived key is `md:<subject>:<n>`. Under a heading, the subject is the heading
path, so two documents with the same heading share keys and a difference between
them is a conflict a person should see; that is unchanged here.

Prose and lines under no heading had no subject in their key: every prose
sentence was `md:prose:<n>` and every heading-less line `md:section-e3b0c442:<n>`,
in every document. The first sentence of a voice guide and the first sentence of
an FAQ then shared a key, were reported as a conflict, and neither was served as
current. In a brief, the model was told the two "disagree".
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from verilore.api.services import markdown_claims
from verilore.api.services.ingestion import IngestionService


def _keys(body: str, path: str) -> dict[str, str]:
    claims, _warnings = markdown_claims.extract(body, markdown_claims._chunks(body), path=path)
    return {claim["claim"]: claim["key"] for claim in claims}


def test_prose_and_heading_less_lines_are_keyed_by_their_own_document():
    body = "- Ships in two days.\n\nWe write in plain words.\n"
    notes = _keys(body, "notes.txt")
    other = _keys(body, "other/notes.txt")
    assert notes["We write in plain words."] != other["We write in plain words."]
    assert notes["Ships in two days."] != other["Ships in two days."]
    # Both still end in an ordinal, so an edit inside one document keeps its key.
    assert markdown_claims._split_key(notes["We write in plain words."]) is not None
    assert markdown_claims._split_key(notes["Ships in two days."]) is not None
    # And a document's prose never shares a base with its own bullets.
    assert notes["We write in plain words."].rsplit(":", 1)[0] != (
        notes["Ships in two days."].rsplit(":", 1)[0]
    )


def test_prose_under_a_heading_is_still_keyed_by_its_own_document():
    body = "# Voice\n\nWe write in plain words.\n"
    assert _keys(body, "brand/voice.md") != _keys(body, "drafts/voice.md")


def test_lines_under_the_same_heading_still_share_a_key():
    body = (
        "# Voice\n\n- Our voice is warm.\n\n| Channel | Rule |\n|---|---|\n| Blog | Long form |\n"
    )
    assert _keys(body, "brand/voice.md") == _keys(body, "drafts/voice.md")


def test_without_a_path_the_keys_are_what_they_were():
    claims, _ = markdown_claims.extract(
        "- Ships in two days.\n\nWe write in plain words.\n",
        markdown_claims._chunks("- Ships in two days.\n\nWe write in plain words.\n"),
    )
    assert {c["key"] for c in claims} == {"md:prose:0", "md:section-e3b0c442:0"}


@pytest.fixture
def corpus():
    from verilore.api.services.corpora import create_corpus
    from verilore.api.services.db import session_scope

    async def make():
        async with session_scope() as db:
            return await create_corpus(db, f"keys-{uuid.uuid4().hex[:12]}", "keys")

    made = asyncio.run(make())
    return made["id"], made["name"]


def _sync(root, corpus_id):
    return asyncio.run(IngestionService().sync_repo(str(root), corpus_id, delete_removed=False))


def _read(corpus_name):
    from verilore.api.models.memory import MemoryRequest
    from verilore.api.services import memory_public

    return asyncio.run(memory_public.execute("current", MemoryRequest(corpus=corpus_name)))


def test_two_documents_of_prose_and_two_plain_notes_are_all_current(tmp_path, corpus, monkeypatch):
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    (tmp_path / "voice.md").write_text("# Voice\n\nOur voice is warm, plain and direct.\n")
    (tmp_path / "faq.md").write_text("# FAQ\n\nReturns are accepted for 30 days.\n")
    (tmp_path / "shipping.md").write_text("- Orders ship within two days.\n")
    (tmp_path / "gifts.md").write_text("- Gift wrap is free on every order.\n")

    result = _sync(tmp_path, corpus[0])
    assert result["failed"] == 0, result
    response = _read(corpus[1])
    assert response.conflicts == []
    assert {(c.path, c.claim) for c in response.current_memories} == {
        ("voice.md", "Our voice is warm, plain and direct."),
        ("faq.md", "Returns are accepted for 30 days."),
        ("shipping.md", "Orders ship within two days."),
        ("gifts.md", "Gift wrap is free on every order."),
    }


def test_the_same_heading_in_two_documents_is_still_a_conflict(tmp_path, corpus, monkeypatch):
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    (tmp_path / "brand").mkdir()
    (tmp_path / "old").mkdir()
    (tmp_path / "brand" / "voice.md").write_text("# Voice\n\n- Our voice is warm.\n")
    (tmp_path / "old" / "voice.md").write_text("# Voice\n\n- Our voice is loud.\n")

    _sync(tmp_path, corpus[0])
    response = _read(corpus[1])
    assert len(response.conflicts) == 1
    assert {c.claim for c in response.conflicts[0].claims} == {
        "Our voice is warm.",
        "Our voice is loud.",
    }


def test_an_archive_written_with_the_old_keys_reads_without_false_conflicts(
    tmp_path, corpus, monkeypatch
):
    """Claims already stored as `md:prose:0` and `md:section-e3b0c442:0` in two
    documents are read as two current lines, without re-ingesting anything."""
    from verilore.api.services.db import session_scope
    from verilore.api.services.memory import _load, _query_result

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    (tmp_path / "voice.md").write_text("# Voice\n\nOur voice is warm, plain and direct.\n")
    (tmp_path / "faq.md").write_text("# FAQ\n\nReturns are accepted for 30 days.\n")
    (tmp_path / "shipping.md").write_text("- Orders ship within two days.\n")
    (tmp_path / "gifts.md").write_text("- Gift wrap is free on every order.\n")
    _sync(tmp_path, corpus[0])

    async def read():
        async with session_scope() as db:
            return await _load(db, corpus[0])

    versions = asyncio.run(read())
    legacy = {
        "voice.md": "md:prose:0",
        "faq.md": "md:prose:0",
        "shipping.md": "md:section-e3b0c442:0",
        "gifts.md": "md:section-e3b0c442:0",
    }
    for version in versions:
        for claim in version["claims"]:
            claim["key"] = legacy[version["path"]]

    result = _query_result(versions, "", None)
    assert result["conflicts"] == []
    assert len(result["current_memories"]) == 4
