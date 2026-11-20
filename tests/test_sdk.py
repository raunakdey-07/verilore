"""SDK smoke tests: the developer-facing Verilore client.

These run against a live database when DATABASE_URL is set; they exercise
the exact flow from the product thesis:

    mp = Verilore("my-corpus")
    mp.sync("./docs")
    context = mp.context("question", budget_tokens=4000)
"""

from __future__ import annotations

import os

import pytest

from verilore.api.services.db_url import sync_url as to_sync_url

# SDK is a synchronous client; tests call it synchronously.


def _db_available() -> bool:
    if not os.getenv("DATABASE_URL"):
        return False
    try:
        import sqlalchemy as sa

        url = to_sync_url(os.getenv("DATABASE_URL", ""))
        engine = sa.create_engine(url)
        with engine.connect():
            engine.dispose()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="no reachable DATABASE_URL")


@pytest.fixture(autouse=True)
def _cleanup_sdk_corpus():
    def purge():
        import sqlalchemy as sa

        engine = sa.create_engine(to_sync_url(os.environ["DATABASE_URL"]))
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "DELETE FROM ingestion_manifest WHERE corpus_id IN "
                        "(SELECT id FROM corpora WHERE name = 'sdk-test-corpus')"
                    )
                )
                conn.execute(
                    sa.text(
                        "DELETE FROM chunks WHERE doc_id IN "
                        "(SELECT id FROM documents WHERE corpus_id IN "
                        "(SELECT id FROM corpora WHERE name = 'sdk-test-corpus'))"
                    )
                )
                conn.execute(
                    sa.text(
                        "DELETE FROM documents WHERE corpus_id IN "
                        "(SELECT id FROM corpora WHERE name = 'sdk-test-corpus')"
                    )
                )
                conn.execute(
                    sa.text(
                        "SELECT set_config('mindpalace.tenant_scope', '{*}', true); "
                        "SELECT set_config('mindpalace.erasure', 'on', true); "
                        "SELECT mindpalace_erase_corpus(id) FROM corpora "
                        "WHERE name = 'sdk-test-corpus'"
                    )
                )
                conn.execute(sa.text("DELETE FROM corpora WHERE name = 'sdk-test-corpus'"))
        finally:
            engine.dispose()

    if _db_available():
        purge()
    yield
    if _db_available():
        purge()


@requires_db
def test_sdk_end_to_end(tmp_path):
    """The full product flow: create -> sync -> context with attribution."""
    from verilore.sdk import Verilore

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "auth.md").write_text("""---
title: "Authentication Guide"
date: 2024-07-01
tags: ["security"]
document_type: "note"
summary: "How authentication works"
prose: off
---

# Authentication

The system uses flurble-token authentication with wibble rotation every hour.
""")

    # `prose: off`: this is the flow for a document that declares no claims,
    # found through its chunks. Since v0.12 a paragraph is read unless the
    # document asks otherwise.
    mp = Verilore("sdk-test-corpus")

    summary = mp.sync(str(docs))
    # Plain prose with no rule-like sentence: nothing to extract. Since #158 the
    # first ingest says so (`prose_not_extracted`), which makes the sync report
    # not fully successful -- but nothing failed. Owner-approved change.
    assert summary.failed == 0
    assert all(e.endswith(("prose_not_extracted", "no_claims_declared")) for e in summary.errors)
    assert summary.added == 1
    assert summary.chunk_count >= 1

    # Re-sync unchanged content: nothing to do.
    again = mp.sync(str(docs))
    assert again.added == 0
    assert again.unchanged == 1

    pack = mp.context("how does authentication work", budget_tokens=2000)
    assert pack.token_estimate > 0
    assert "flurble-token" in pack.context
    assert any(s.title == "Authentication Guide" for s in pack.sources)
    assert not pack.truncated


@requires_db
def test_sdk_budget_enforced(tmp_path):
    from verilore.sdk import Verilore

    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(5):
        (docs / f"doc{i}.md").write_text(f"""---
title: "Budget Doc {i}"
date: 2024-07-01
document_type: "note"
---

# Doc {i}

Padding text {"x" * 900} unique marker {i}.
""")

    mp = Verilore("sdk-test-corpus")
    mp.sync(str(docs))

    pack = mp.context("unique markers in budget docs", budget_tokens=1024)
    # 1024 tokens * 4 chars = ~4096 chars max
    assert len(pack.context) <= 4096 + 10  # small tolerance for separators
