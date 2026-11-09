"""An authored `claims:` block takes its document's status (#140).

Extracted claims already took the frontmatter `status`. Authored ones did not, so
a brand document marked `status: draft` with a `claims:` block served every one
of its claims as approved through current and pack. These tests go through the
HTTP API, the way an app reads memory.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from verilore.api.main import app

API_BASE = "http://test"
TONE = "The brand tone is warm and direct."
COLOUR = "The accent colour is deep navy."


def document(status: str | None = None, tone_state: str | None = None) -> str:
    """A brand document with two authored claims and an optional status."""
    lines = ["---\n"]
    if status:
        lines.append(f"status: {status}\n")
    lines += [
        "claims:\n",
        "  - key: brand.tone\n",
        f'    claim: "{TONE}"\n',
        "    value: warm\n",
        f'    evidence: "{TONE}"\n',
    ]
    if tone_state:
        lines.append(f"    info_state: {tone_state}\n")
    lines += [
        "  - key: brand.colour\n",
        f'    claim: "{COLOUR}"\n',
        "    value: navy\n",
        f'    evidence: "{COLOUR}"\n',
        "---\n",
        "\n",
        "# Brand basics\n",
        "\n",
        f"{TONE}\n",
        "\n",
        f"{COLOUR}\n",
    ]
    return "".join(lines)


async def _corpus(client) -> str:
    name = f"t{uuid4().hex[:12]}"
    response = await client.post("/api/corpora", json={"name": name})
    assert response.status_code == 201, response.text
    return name


async def _ingest(client, corpus: str, content: str, path: str = "brand/basics.md") -> dict:
    response = await client.post(
        "/api/ingest/file", json={"content": content, "path": path, "corpus": corpus}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _memory(client, operation: str, corpus: str, **fields) -> dict:
    # `budget` belongs to pack only; current refuses it with a 422.
    if operation == "pack":
        fields.setdefault("budget", 16000)
    response = await client.post(
        f"/api/memory/{operation}", json={"corpus": corpus, "query": "", **fields}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _claims(body: dict) -> dict[str, dict]:
    return {c["claim"]: c for c in body.get("current_memories", [])}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,state", [("draft", "draft"), ("rejected", "rejected")])
async def test_unapproved_document_withholds_its_authored_claims(status, state):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _ingest(client, corpus, document(status=status))
        for operation in ("current", "pack"):
            body = await _memory(client, operation, corpus)
            assert TONE not in str(body), operation
            assert COLOUR not in str(body), operation
            assert body.get("withheld_counts", {}).get(state) == 2, operation
        shown = _claims(await _memory(client, "pack", corpus, include_states=[state]))
    assert shown[TONE]["info_state"] == state
    assert shown[COLOUR]["info_state"] == state


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, "approved"])
async def test_approved_or_absent_status_is_unchanged(status):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _ingest(client, corpus, document(status=status))
        body = await _memory(client, "pack", corpus)
    shown = _claims(body)
    assert set(shown) >= {TONE, COLOUR}
    assert "info_state" not in shown[TONE]
    assert not body.get("withheld_counts")


@pytest.mark.asyncio
async def test_the_most_restrictive_state_wins():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _ingest(client, corpus, document(status="approved", tone_state="rejected"))
        body = await _memory(client, "pack", corpus)
    shown = _claims(body)
    assert TONE not in shown
    assert COLOUR in shown
    assert body.get("withheld_counts", {}).get("rejected") == 1


@pytest.mark.asyncio
async def test_publishing_the_document_releases_its_claims():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _ingest(client, corpus, document(status="draft"))
        await _ingest(client, corpus, document(status="approved"))
        shown = _claims(await _memory(client, "current", corpus))
    assert TONE in shown and COLOUR in shown


@pytest.mark.asyncio
async def test_a_document_without_status_still_reingests_as_unchanged():
    # The state is only written when the document is stricter than the claim, so
    # an existing authored document's fingerprint does not move on upgrade.
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API_BASE) as client:
        corpus = await _corpus(client)
        await _ingest(client, corpus, document())
        again = await _ingest(client, corpus, document())
    assert again["message"] == "Document unchanged, skipped"
