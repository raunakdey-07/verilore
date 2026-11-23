"""A Python without onnxruntime gets one sentence, not a ModuleNotFoundError (DEV-2).

DEV-1 turned "the model could not be downloaded" into one sentence. A Python
with no onnxruntime wheel (3.15, as this is written) fails earlier: the
embedder falls back to the torch backend, which a default install does not
have either, and an ingest logged `claim_embedding_cache_fill_failed
error=ModuleNotFoundError`. It is the same situation for a reader (claims
stored, recall ranks by words), with a different fix.
"""

from __future__ import annotations

import logging

import pytest


def _missing(name):
    error = ModuleNotFoundError(f"No module named '{name}'")
    error.name = name
    return error


def _wrapped(cause):
    try:
        try:
            raise cause
        except Exception as inner:
            raise RuntimeError("building the embedder failed") from inner
    except RuntimeError as outer:
        return outer


@pytest.mark.parametrize(
    "error,missing",
    [
        (_missing("onnxruntime"), True),
        (_wrapped(_missing("sentence_transformers")), True),
        (_missing("torch.nn"), True),
        (_missing("yaml"), False),
        (ImportError("cannot import name 'x'"), False),
    ],
)
def test_a_model_package_that_is_not_installed(error, missing):
    from verilore.api.services import embedder

    assert embedder.runtime_missing(error) is missing
    assert embedder.model_unavailable(error) is missing


def test_an_ingest_without_onnxruntime_says_so_in_one_sentence(tmp_path, monkeypatch, caplog):
    import asyncio
    import uuid

    from verilore.api.services import claim_embeddings, embedder
    from verilore.api.services.corpora import create_corpus
    from verilore.api.services.db import session_scope
    from verilore.api.services.ingestion import IngestionService

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.delenv("VERILORE_LEXICAL", raising=False)
    monkeypatch.setattr(embedder, "_TOLD", False)

    async def not_installed(*_args, **_kwargs):
        raise _wrapped(_missing("sentence_transformers"))

    monkeypatch.setattr(claim_embeddings, "embed_representations", not_installed)
    for n in range(2):
        (tmp_path / f"plans-{n}.md").write_text(f"# Plans\n\n- Plan {n} costs £{n + 3} a month.\n")

    async def run():
        async with session_scope() as db:
            corpus = await create_corpus(db, f"no-runtime-{uuid.uuid4().hex[:10]}", "no runtime")
        return await IngestionService().sync_repo(str(tmp_path), corpus["id"])

    caplog.set_level(logging.INFO)
    result = asyncio.run(run())
    assert result["failed"] == 0 and result["claim_count"] == 2, result
    assert "claim_embedding_cache_fill_failed" not in caplog.text
    told = [r for r in caplog.records if r.getMessage() == embedder.RUNTIME_MISSING]
    assert len(told) == 1, caplog.text
    assert "pip install onnxruntime" in embedder.RUNTIME_MISSING


def test_doctor_names_the_package(monkeypatch):
    from verilore.api.services import embedder
    from verilore.cli import doctor

    monkeypatch.delenv("VERILORE_LEXICAL", raising=False)

    class NotInstalled:
        def __init__(self):
            raise _wrapped(_missing("onnxruntime"))

    monkeypatch.setattr(embedder, "Embedder", NotInstalled)
    ok, _detail, fix = doctor.check_embedding_model()
    assert not ok and "pip install onnxruntime" in fix
