"""`query` withholds draft, rejected and superseded claims, like current and pack (#138).

Before this, current and pack withheld them but query only labelled them, so an
app that answered from query served unapproved copy. Withholding happens before
ranking, so a draft can neither be the answer nor push an approved claim out.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from verilore.api.main import app

API_BASE = "http://test"
APPROVED = "The launch email goes out on Tuesday mornings."
DRAFT = "Maybe the launch email goes out on Friday evenings."


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


async def _query(client, corpus: str, question: str, **fields) -> dict:
    response = await client.post(
        "/api/memory/query", json={"corpus": corpus, "query": question, **fields}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _texts(body: dict) -> set[str]:
    return {
        c["claim"]
        for field in ("current_memories", "historical_memories", "uncertain_memories")
        for c in body.get(field, [])
    }


async def _unapproved(client, corpus: str, status: str) -> None:
    content = f"---\nstatus: {status}\n---\n\n# Launch ideas\n\n- {DRAFT}\n"
    await _ingest(client, corpus, "launch/plan.md", content)


async def _approved_and(client, corpus: str, status: str) -> None:
    await _ingest(client, corpus, "launch/schedule.md", f"# Launch schedule\n\n- {APPROVED}\n")
    await _unapproved(client, corpus, status)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "rejected", "superseded"])
async def test_query_withholds_unapproved_claims_by_default(status):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _approved_and(client, corpus, status)
        body = await _query(client, corpus, "When does the launch email go out?")
    assert DRAFT not in str(body)
    assert APPROVED in _texts(body)
    assert body.get("withheld_counts", {}).get(status) == 1


@pytest.mark.asyncio
async def test_query_include_states_returns_them_labelled():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _unapproved(client, corpus, "draft")
        body = await _query(
            client, corpus, "When does the launch email go out?", include_states=["draft"]
        )
    shown = {
        c["claim"]: c
        for field in ("current_memories", "historical_memories", "uncertain_memories")
        for c in body.get(field, [])
    }
    assert shown[DRAFT]["info_state"] == "draft"
    assert not body.get("withheld_counts")


@pytest.mark.asyncio
async def test_a_draft_alone_is_not_an_answer():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _unapproved(client, corpus, "draft")
        body = await _query(client, corpus, "When does the launch email go out?")
    assert DRAFT not in str(body)
    assert not body.get("current_memories")


@pytest.mark.asyncio
async def test_path_prefix_and_withholding_combine():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _ingest(client, corpus, "campaigns/a/schedule.md", f"# Schedule\n\n- {APPROVED}\n")
        await _ingest(
            client,
            corpus,
            "campaigns/a/ideas.md",
            f"---\nstatus: draft\n---\n\n# Ideas\n\n- {DRAFT}\n",
        )
        await _ingest(
            client,
            corpus,
            "campaigns/ab/schedule.md",
            "# Schedule\n\n- The partner email goes out on Monday afternoons.\n",
        )
        body = await _query(
            client,
            corpus,
            "When does the launch email go out?",
            path_prefix=["campaigns/a"],
        )
    assert DRAFT not in str(body)
    assert "Monday afternoons" not in str(body)
    assert APPROVED in _texts(body)


def test_sdk_query_passes_include_states(monkeypatch):
    from verilore.sdk import Verilore

    seen: dict = {}

    def fake_execute(self, operation, corpus, query, **fields):
        seen.update(operation=operation, **fields)
        return "response"

    monkeypatch.setattr(Verilore, "_execute", fake_execute)
    client = Verilore.__new__(Verilore)
    assert Verilore.query(client, "When?", "brand", include_states=["draft"]) == "response"
    assert seen["operation"] == "query"
    assert seen["include_states"] == ["draft"]
