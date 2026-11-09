"""A first ingest says what it could not read (#158), and ingest runs without the
model when it has to (#173).

#158: a bullet-free document with no rule-like sentence, ingested into a corpus
with no memory yet, took the live path and said nothing. The same document in a
corpus that already held memory warned `prose_not_extracted`. A team's first
ingest is exactly the silent case.

#173: `VERILORE_LEXICAL=1` covered reads only. Ingesting a document with no
claims embedded its chunks, and without the model the document failed with
ModuleNotFoundError.
"""

from sqlalchemy import text

from verilore.api.services import ingestion as ingestion_service

PROSE = (
    "# Team notes\n\n"
    "The team met on Tuesday to talk about the launch plan. Everyone brought coffee\n"
    "and the room was warm. We went through the calendar together.\n"
)
BULLETS = "# Brand voice\n\n- Headlines stay under sixty characters.\n"


def _codes(result: dict) -> list[str]:
    return [w["code"] for w in result.get("warnings", [])]


class _Vectors:
    model_name = "fixed"
    dimension = 384

    def embed(self, texts):
        return [[0.0] * 383 + [1.0] for _ in texts]


class _NoModel:
    model_name = "missing"
    dimension = 384

    def embed(self, texts):
        raise ModuleNotFoundError("No module named 'onnxruntime'")


class _MustNotLoad:
    model_name = "unused"
    dimension = 384

    def embed(self, texts):
        raise AssertionError("lexical mode loaded the model")


def _service(embedder=None) -> ingestion_service.IngestionService:
    service = ingestion_service.IngestionService(memory_enabled=False)
    service.embedder = embedder or _Vectors()
    return service


async def _null_vectors(store, path: str) -> tuple[int, int]:
    row = (
        await store.db.execute(
            text("""
            SELECT count(*), count(*) FILTER (WHERE c.embedding IS NULL)
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE d.corpus_id = :c AND d.path = :p
            """),
            {"c": store.corpus, "p": path},
        )
    ).one()
    return row[0], row[1]


# ------------------------------------------------------------------- #158


async def test_fresh_corpus_prose_warns(store):
    result = await _service().ingest_file(content=PROSE, path="notes.md", corpus_id=store.corpus)
    assert result["success"]
    assert "prose_not_extracted" in _codes(result)
    assert not result.get("claim_count")


async def test_the_warning_is_the_same_once_the_corpus_has_memory(store):
    service = _service()
    await service.ingest_file(content=BULLETS, path="voice.md", corpus_id=store.corpus)
    result = await service.ingest_file(content=PROSE, path="notes.md", corpus_id=store.corpus)
    assert "prose_not_extracted" in _codes(result)


async def test_an_unchanged_reingest_still_warns(store):
    service = _service()
    await service.ingest_file(content=PROSE, path="notes.md", corpus_id=store.corpus)
    again = await service.ingest_file(content=PROSE, path="notes.md", corpus_id=store.corpus)
    assert "prose_not_extracted" in _codes(again)


async def test_rule_like_prose_still_extracts_in_a_fresh_corpus(store):
    body = (
        "# Email rules\n\n"
        "Every subject line must stay under fifty characters. Product names must\n"
        "always be written in full.\n"
    )
    result = await _service().ingest_file(content=body, path="rules.md", corpus_id=store.corpus)
    assert result.get("claim_count", 0) >= 1
    assert "prose_not_extracted" not in _codes(result)


# ------------------------------------------------------------------- #173


async def test_lexical_ingest_does_not_load_the_model(store, monkeypatch):
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    result = await _service(_MustNotLoad()).ingest_file(
        content=PROSE, path="notes.md", corpus_id=store.corpus
    )
    assert result["success"]
    assert "embedding_unavailable" not in _codes(result)
    total, missing = await _null_vectors(store, "notes.md")
    assert total > 0 and missing == total


async def test_a_missing_model_degrades_instead_of_failing(store, monkeypatch):
    monkeypatch.delenv("VERILORE_LEXICAL", raising=False)
    result = await _service(_NoModel()).ingest_file(
        content=PROSE, path="notes.md", corpus_id=store.corpus
    )
    assert result["success"]
    assert "embedding_unavailable" in _codes(result)
    total, missing = await _null_vectors(store, "notes.md")
    assert total > 0 and missing == total


async def test_a_present_model_is_unchanged(store, monkeypatch):
    monkeypatch.delenv("VERILORE_LEXICAL", raising=False)
    result = await _service().ingest_file(content=PROSE, path="notes.md", corpus_id=store.corpus)
    assert "embedding_unavailable" not in _codes(result)
    total, missing = await _null_vectors(store, "notes.md")
    assert total > 0 and missing == 0
