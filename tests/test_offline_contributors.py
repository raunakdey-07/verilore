"""A contributor without the model, or with an asyncpg URL, gets a clean run (v0.12.1).

Team 052's evaluation ran the suite where the embedding model could not be
downloaded:

* 77 of 2,602 tests failed or errored, almost all because the model was missing;
* the helpers that rewrite `DATABASE_URL` for the sync driver knew
  `postgresql://` and `postgresql+psycopg://`, so a `postgresql+asyncpg://` URL
  reached psycopg2 in some tests, and asyncpg where it wanted psycopg2 in others
  (MissingGreenlet in the MCP tests);
* an ingest printed `claim_embedding_cache_fill_failed error=ProxyError`, a log
  key, where a person needed one sentence.

Also the last non-database leftovers of the old name: the test database was
`mindpalace_test_<pid>`, and Alembic's fallback URL named a `mindpalace` database.
"""

from __future__ import annotations

import logging

import pytest


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@h:5432/d",
        "postgres://u:p@h:5432/d",
        "postgresql+asyncpg://u:p@h:5432/d",
        "postgresql+psycopg://u:p@h:5432/d",
        "postgresql+psycopg2://u:p@h:5432/d",
    ],
)
def test_every_postgresql_url_reaches_the_driver_asked_for(url):
    from verilore.api.services.db_url import async_url, sync_url

    assert async_url(url) == "postgresql+asyncpg://u:p@h:5432/d"
    assert sync_url(url) == "postgresql+psycopg2://u:p@h:5432/d"


def test_a_url_that_is_not_postgresql_is_left_alone():
    from verilore.api.services.db_url import async_url

    assert async_url("sqlite:///x.db") == "sqlite:///x.db"
    # Only the scheme: a password that says "postgresql://" stays as it is.
    assert async_url("postgresql://u:postgresql%3A%2F%2F@h/d").endswith("@h/d")


def test_the_application_reads_with_the_shared_rewrite():
    from verilore.api.services import db

    assert db.ASYNC_DATABASE_URL.startswith("postgresql+asyncpg://")
    assert db.async_url is not None and db.sync_url is not None


class ProxyError(Exception):
    """Named like httpx's, which is what a refusing proxy raises."""


def _caused_by(cause):
    try:
        try:
            raise cause
        except Exception as inner:
            raise RuntimeError("loading the model failed") from inner
    except RuntimeError as outer:
        return outer


@pytest.mark.parametrize(
    "error,unavailable",
    [
        (ProxyError("403 Forbidden"), True),
        (_caused_by(ProxyError("403 Forbidden")), True),
        (OSError("We couldn't connect to 'https://huggingface.co' to load this file"), True),
        (OSError("No space left on device"), False),
        (ValueError("embedding count does not match chunk count"), False),
    ],
)
def test_what_counts_as_a_model_that_could_not_be_fetched(error, unavailable):
    from verilore.api.services.embedder import model_unavailable

    assert model_unavailable(error) is unavailable


def test_an_ingest_without_the_model_says_so_in_one_sentence(tmp_path, monkeypatch, caplog):
    import asyncio
    import uuid

    from verilore.api.services import claim_embeddings, embedder
    from verilore.api.services.corpora import create_corpus
    from verilore.api.services.db import session_scope
    from verilore.api.services.ingestion import IngestionService

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.delenv("VERILORE_LEXICAL", raising=False)
    monkeypatch.setattr(embedder, "_TOLD", False)

    async def refuse(*_args, **_kwargs):
        raise ProxyError("403 Forbidden (agent proxy: no rule allows this host)")

    monkeypatch.setattr(claim_embeddings, "embed_representations", refuse)
    for n in range(2):
        (tmp_path / f"plans-{n}.md").write_text(f"# Plans\n\n- Plan {n} costs £{n + 3} a month.\n")

    async def run():
        async with session_scope() as db:
            corpus = await create_corpus(db, f"offline-{uuid.uuid4().hex[:10]}", "offline")
        return await IngestionService().sync_repo(str(tmp_path), corpus["id"])

    caplog.set_level(logging.INFO)
    result = asyncio.run(run())
    assert result["failed"] == 0 and result["claim_count"] == 2, result
    assert "claim_embedding_cache_fill_failed" not in caplog.text
    told = [r for r in caplog.records if r.getMessage() == embedder.MODEL_UNAVAILABLE]
    assert len(told) == 1, caplog.text
    assert "VERILORE_LEXICAL=1" in embedder.MODEL_UNAVAILABLE


def test_offline_mode_skips_only_what_the_missing_model_failed(monkeypatch):
    import offline_model

    monkeypatch.setenv("VERILORE_TEST_OFFLINE", "1")
    assert offline_model.skip_reason(ProxyError("403")) == offline_model.REASON
    assert offline_model.skip_reason(AssertionError("wrong answer")) is None
    monkeypatch.delenv("VERILORE_TEST_OFFLINE")
    assert offline_model.skip_reason(ProxyError("403")) is None


def test_the_old_name_is_gone_from_what_is_not_a_database_object():
    import session_database

    assert session_database._database_name().startswith("verilore_test_")
    from pathlib import Path

    env = Path(__file__).resolve().parents[1] / "verilore" / "migrations" / "env.py"
    assert "/mindpalace" not in env.read_text()
