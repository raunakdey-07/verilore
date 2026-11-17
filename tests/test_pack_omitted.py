"""A bounded pack says what it left out, not only that it left something out (#151).

`truncated: true` was the whole report. With every current memory in the pack and
one change entry over the budget, a caller read `truncated` and could not tell
"the answer is incomplete" from "the history of the answer is incomplete". Change
entries repeat the claims they move between, so they are the first thing a
budget cuts.

`omitted_counts` is a diagnostic, like `expired_count`: carried on REST, MCP and
the SDK, and kept out of the canonical JSON, the budget and the receipt digest.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from verilore.api.models.memory import MemoryRequest, MemoryResponse, MemoryWire
from verilore.api.services.ingestion import IngestionService


@pytest.fixture
def corpus():
    from verilore.api.services.corpora import create_corpus
    from verilore.api.services.db import session_scope

    async def make():
        async with session_scope() as db:
            return await create_corpus(db, f"omit-{uuid.uuid4().hex[:12]}", "omitted")

    made = asyncio.run(make())
    return made["id"], made["name"]


def _pack(name: str, budget: int) -> MemoryResponse:
    from verilore.api.services import memory_public

    return asyncio.run(memory_public.execute("pack", MemoryRequest(corpus=name, budget=budget)))


@pytest.fixture
def changed(tmp_path, corpus, monkeypatch):
    """Four current lines, and a change entry from editing one document."""
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    (tmp_path / "brand").mkdir()
    guide = tmp_path / "brand" / "guide.md"
    guide.write_text("# Voice\n\n- Our voice is warm.\n- We never use the word premium.\n")
    (tmp_path / "brand" / "specs.md").write_text(
        "# Trail 2\n\n- The Trail 2 weighs 9.8 kg.\n- The Trail 2 costs Rs 24,999.\n"
    )
    sync = IngestionService().sync_repo
    asyncio.run(sync(str(tmp_path), corpus[0], delete_removed=False))
    guide.write_text(
        "# Voice\n\n- Our voice is warm and plain.\n- We never use the word premium.\n"
    )
    asyncio.run(sync(str(tmp_path), corpus[0], delete_removed=False))
    return corpus[1]


def test_a_pack_that_fits_omits_nothing_and_says_so(changed):
    full = _pack(changed, 128_000)
    assert full.truncated is False
    assert full.omitted_counts == {}
    assert full.changes, "the edit must have produced a change entry"


def test_a_pack_that_drops_only_history_says_every_current_memory_is_in(changed):
    full = _pack(changed, 128_000)
    current = len(full.current_memories)
    size = len(full.canonical_json())
    # The smallest budget that still holds every current memory: below the full
    # size, change entries are the first thing cut.
    found = None
    for budget in range(size - 1, 0, -25):
        packed = _pack(changed, budget)
        if len(packed.current_memories) < current:
            break
        if packed.truncated:
            found = packed
    assert found is not None, "no budget cut history while keeping every current memory"
    assert found.truncated is True
    assert "current_memories" not in found.omitted_counts
    assert found.omitted_counts.get("changes", 0) >= 1
    assert all(count > 0 for count in found.omitted_counts.values())


def test_a_pack_that_drops_a_current_memory_counts_it(changed):
    full = _pack(changed, 128_000)
    tight = _pack(changed, 512)  # the smallest budget a request may ask for
    assert len(tight.current_memories) < len(full.current_memories)
    assert tight.truncated is True
    assert tight.omitted_counts["current_memories"] == len(full.current_memories) - len(
        tight.current_memories
    )


def test_the_counts_are_a_diagnostic_and_never_part_of_what_was_answered(changed):
    full = _pack(changed, 128_000)
    packed = None
    for budget in range(len(full.canonical_json()) - 1, 0, -25):
        packed = _pack(changed, budget)
        if packed.omitted_counts:
            break
    assert packed is not None and packed.omitted_counts
    # Not in the digest, so a receipt for this pack is the receipt it always was.
    assert "omitted_counts" not in json.loads(packed.canonical_json())
    assert len(packed.canonical_json()) <= budget
    # But on every surface a caller reads.
    assert packed.public_dict()["omitted_counts"] == packed.omitted_counts
    wire = MemoryWire.model_validate(packed.public_dict())
    assert json.loads(wire.model_dump_json())["omitted_counts"] == packed.omitted_counts
    assert wire.canonical_json() == packed.canonical_json()


def test_the_cli_says_what_a_truncated_pack_left_out():
    from verilore.cli.render import render_recall

    response = MemoryResponse(
        query="",
        corpus="c",
        truncated=True,
        omitted_counts={"changes": 2, "historical_memories": 1},
    )
    text = render_recall(response)
    assert "(truncated to fit the response budget: left out 2 changes, 1 historical memory)" in (
        text
    )
