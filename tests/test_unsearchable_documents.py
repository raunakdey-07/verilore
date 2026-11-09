"""Draft, rejected and superseded documents stay out of the search index (#138).

The chunk routes -- /api/search, /api/query, the retrieval half of /api/context,
and the MCP search and context tools -- return raw text with no state label. So a
document whose own state is withheld is archived as usual (its claims stay
reachable through current, pack and query with include_states) but never indexed
for them. That includes a statement saved with remember(state="rejected").
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from verilore.api.main import app
from verilore.api.services import ingestion as ingestion_service
from verilore.api.services import markdown_claims

API_BASE = "http://test"
SECRET = "Our holiday campaign headline is Glow Up Gold."
PUBLIC = "Our spring campaign headline is Fresh Start Green."


def prose(status: str | None, sentence: str) -> str:
    front = f"---\nstatus: {status}\n---\n\n" if status else ""
    return f"{front}# Campaign notes\n\n{sentence} It was chosen after review.\n"


def bullets(status: str | None, sentence: str) -> str:
    front = f"---\nstatus: {status}\n---\n\n" if status else ""
    return f"{front}# Campaign headlines\n\n- {sentence}\n"


# ------------------------------------------------------------------ the rule


def test_unsearchable_states_are_the_withheld_states():
    from verilore.api.services.memory_public import _WITHHELD_STATES

    assert markdown_claims.UNSEARCHABLE_STATES == _WITHHELD_STATES


@pytest.mark.parametrize(
    "metadata,searchable",
    [
        ({}, True),
        ({"status": "approved"}, True),
        ({"status": "draft"}, False),
        ({"status": "rejected"}, False),
        ({"status": "superseded"}, False),
        ({"tags": ["archived"]}, False),
    ],
)
def test_is_searchable(metadata, searchable):
    assert markdown_claims.is_searchable(metadata) is searchable


# ----------------------------------------------------- what gets indexed


async def _chunks(store, path: str) -> int:
    return (
        await store.db.execute(
            text("""
            SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE d.corpus_id = :c AND d.path = :p
            """),
            {"c": store.corpus, "p": path},
        )
    ).scalar_one()


@pytest.mark.parametrize("status", ["draft", "rejected", "superseded"])
async def test_live_path_does_not_index_a_withheld_document(store, status):
    service = ingestion_service.IngestionService(memory_enabled=False)
    await service.ingest_file(content=prose(status, SECRET), path="a.md", corpus_id=store.corpus)
    await service.ingest_file(content=prose(None, PUBLIC), path="b.md", corpus_id=store.corpus)
    assert await _chunks(store, "a.md") == 0
    assert await _chunks(store, "b.md") > 0


@pytest.mark.parametrize("status", ["draft", "rejected", "superseded"])
async def test_memory_path_does_not_index_a_withheld_document(store, status):
    service = ingestion_service.IngestionService(memory_enabled=True, require_embeddings=False)
    await service.ingest_file(content=bullets(status, SECRET), path="a.md", corpus_id=store.corpus)
    await service.ingest_file(content=bullets(None, PUBLIC), path="b.md", corpus_id=store.corpus)
    assert await _chunks(store, "a.md") == 0
    assert await _chunks(store, "b.md") > 0


@pytest.mark.parametrize("memory_enabled", [False, True])
async def test_publishing_indexes_and_withdrawing_unindexes(store, memory_enabled):
    # Only the status line changes; the body does not.
    service = ingestion_service.IngestionService(
        memory_enabled=memory_enabled, require_embeddings=False
    )
    make = bullets if memory_enabled else prose
    await service.ingest_file(content=make("draft", SECRET), path="a.md", corpus_id=store.corpus)
    assert await _chunks(store, "a.md") == 0
    await service.ingest_file(content=make("approved", SECRET), path="a.md", corpus_id=store.corpus)
    assert await _chunks(store, "a.md") > 0
    await service.ingest_file(content=make("rejected", SECRET), path="a.md", corpus_id=store.corpus)
    assert await _chunks(store, "a.md") == 0


class _FixedEmbedder:
    model_name = "fixed"
    dimension = 384
    version = "test"

    def embed(self, texts):
        return [[0.0] * 383 + [1.0] for _ in texts]


async def test_reindex_keeps_withheld_documents_out(store):
    from verilore.api.services.rehydrate import rehydrate_corpus

    service = ingestion_service.IngestionService(memory_enabled=True, require_embeddings=False)
    await service.ingest_file(content=bullets("draft", SECRET), path="a.md", corpus_id=store.corpus)
    await service.ingest_file(content=bullets(None, PUBLIC), path="b.md", corpus_id=store.corpus)
    await rehydrate_corpus(store.db, store.corpus, embedder=_FixedEmbedder())
    assert await _chunks(store, "a.md") == 0
    assert await _chunks(store, "b.md") > 0


# ------------------------------------------------- through the chunk routes


async def _corpus(client) -> str:
    name = f"t{uuid4().hex[:12]}"
    response = await client.post("/api/corpora", json={"name": name})
    assert response.status_code == 201, response.text
    return name


async def _ingest(client, corpus: str, path: str, content: str) -> None:
    response = await client.post(
        "/api/ingest/file", json={"content": content, "path": path, "corpus": corpus}
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_search_and_context_do_not_return_a_draft():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _ingest(client, corpus, "campaigns/holiday.md", bullets("draft", SECRET))
        await _ingest(client, corpus, "campaigns/spring.md", bullets(None, PUBLIC))
        search = await client.get(
            "/api/search",
            params={"q": "campaign headline", "corpus": corpus, "k": 10, "hybrid": "true"},
        )
        assert search.status_code == 200, search.text
        context = await client.get(
            "/api/context", params={"q": "What is the campaign headline?", "corpus": corpus}
        )
        assert context.status_code == 200, context.text
        pack = await client.post(
            "/api/memory/pack",
            json={"corpus": corpus, "query": "", "budget": 16000, "include_states": ["draft"]},
        )
        assert pack.status_code == 200, pack.text
    assert "Glow Up Gold" not in search.text
    assert "Fresh Start Green" in search.text
    assert "Glow Up Gold" not in context.text
    # Still archived, and still reachable on request.
    assert "Glow Up Gold" in pack.text


@pytest.mark.asyncio
async def test_a_rejected_remembered_statement_is_not_searchable():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        for statement, state in ((SECRET, "rejected"), (PUBLIC, "approved")):
            response = await client.post(
                "/api/memory/remember",
                json={"corpus": corpus, "statement": statement, "state": state},
            )
            assert response.status_code == 200, response.text
        search = await client.get(
            "/api/search",
            params={"q": "campaign headline", "corpus": corpus, "k": 10, "hybrid": "true"},
        )
        assert search.status_code == 200, search.text
    assert "Glow Up Gold" not in search.text
    assert "Fresh Start Green" in search.text
