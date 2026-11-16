"""A line that ends stops being served (TIME-1).

A campaign brief says "Orders close on 5 November", and on 16 November it was
still in the brief, because nothing could say when a line stops being true:
only an authored `claims:` block could carry `valid_until`. Now a document's
frontmatter can, for every line in it, and so can `remember` on every surface.

What is held here: the window is read strictly (a time with no zone is refused,
not guessed); past `valid_until` a claim is not current and no brief, current
or pack serves it; what was left out is counted, without changing a byte of
what was answered; an expiry that cannot be read refuses the document instead
of serving it forever.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from verilore.api.main import app
from verilore.api.services import markdown_claims, remember

PAST = (date.today() - timedelta(days=10)).isoformat()
FUTURE = (date.today() + timedelta(days=30)).isoformat()


def _doc(window: str, line: str = "Orders close on 5 November 2026.") -> str:
    return f"---\nstatus: approved\n{window}---\n\n# Diwali\n\n- {line}\n"


# ------------------------------------------------------------- reading a bound


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-11-06", "2026-11-06"),
        (date(2026, 11, 6), "2026-11-06"),
        ("2026-11-06T00:00:00+05:30", "2026-11-06T00:00:00+05:30"),
        ("2026-11-06T00:00:00Z", "2026-11-06T00:00:00+00:00"),
        (datetime(2026, 11, 6, tzinfo=timezone.utc), "2026-11-06T00:00:00+00:00"),
        (None, None),
        ("  ", None),
    ],
)
def test_a_bound_is_a_date_or_a_time_with_its_zone(value, expected):
    assert markdown_claims.validity_value(value, "valid_until") == expected


@pytest.mark.parametrize(
    "value,message",
    [
        ("2026-11-06 10:00", "has no time zone"),
        (datetime(2026, 11, 6, 10, 0), "has no time zone"),
        ("next friday", "is not a date or a time"),
        (42, "is not a date or a time"),
    ],
)
def test_a_bound_that_cannot_be_read_is_refused_with_the_fix(value, message):
    with pytest.raises(ValueError, match=message):
        markdown_claims.validity_value(value, "valid_until")


def test_a_window_that_ends_before_it_begins_is_refused():
    with pytest.raises(ValueError, match="must not be before"):
        markdown_claims.document_validity({"valid_from": "2026-12-01", "valid_until": "2026-11-01"})
    # A date and a time on the same day compare as instants, not as text.
    assert markdown_claims.document_validity(
        {"valid_from": "2026-11-01", "valid_until": "2026-11-01T10:00:00+00:00"}
    ) == {"valid_from": "2026-11-01", "valid_until": "2026-11-01T10:00:00+00:00"}


def test_a_claim_with_its_own_window_keeps_all_of_it():
    claims = [{"key": "a"}, {"key": "b", "valid_from": "2026-01-01"}]
    applied = markdown_claims.apply_document_validity(claims, {"valid_until": "2026-11-06"})
    assert applied == [
        {"key": "a", "valid_until": "2026-11-06"},
        # Not the document's end glued to the claim's own start.
        {"key": "b", "valid_from": "2026-01-01"},
    ]
    assert markdown_claims.apply_document_validity(claims, {}) is claims


def test_a_statement_with_no_window_renders_exactly_as_before():
    plain = remember.render_statement("We never shout.", "k", "approved")
    assert "valid_" not in plain
    windowed = remember.render_statement(
        "We never shout.", "k", "approved", {"valid_until": "2026-11-06"}
    )
    assert windowed.replace('    valid_until: "2026-11-06"\n', "") == plain


# ------------------------------------------------------------- end to end


async def _post(client: AsyncClient, path: str, body: dict, status: int = 200) -> dict:
    response = await client.post(path, json=body)
    assert response.status_code == status, response.text
    return response.json()


async def _fresh(client: AsyncClient) -> str:
    corpus = f"t{uuid4().hex[:12]}"
    await _post(client, "/api/corpora", {"name": corpus}, 201)
    return corpus


async def _ingest(client, corpus, content, path="campaigns/diwali/brief.md", status=200) -> dict:
    response = await client.post(
        "/api/ingest/file", json={"content": content, "path": path, "corpus": corpus}
    )
    assert response.status_code == status, response.text
    return response.json()


async def test_past_its_end_a_line_is_not_served_and_is_counted():
    from verilore.api.models.memory import MemoryResponse
    from verilore.brief import render_brief

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await _fresh(client)
        await _ingest(client, corpus, _doc(f"valid_until: {PAST}\n"))
        await _ingest(client, corpus, _doc("", 'Never use the word "premium".'), "brand/rules.md")
        body = await _post(client, "/api/memory/current", {"corpus": corpus})
        pack = await _post(client, "/api/memory/pack", {"corpus": corpus, "budget": 16000})
    assert [c["claim"] for c in body["current_memories"]] == ['Never use the word "premium".']
    assert body["expired_count"] == 1 and pack["expired_count"] == 1
    assert [c["claim"] for c in pack["current_memories"]] == ['Never use the word "premium".']
    # A diagnostic: what was answered, and so every digest over it, is unchanged.
    assert "expired_count" not in MemoryResponse.model_validate(body).canonical_json()
    brief = render_brief(body)
    assert "Orders close" not in brief.text
    assert brief.expired == 1 and brief.text.endswith("Not included: 1 expired.")


async def test_moving_the_end_date_in_the_frontmatter_alone_brings_the_line_back():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await _fresh(client)
        await _ingest(client, corpus, _doc(f"valid_until: {PAST}\n"))
        await _ingest(client, corpus, _doc(f"valid_until: {FUTURE}\n"))
        body = await _post(client, "/api/memory/current", {"corpus": corpus})
    assert [c["claim"] for c in body["current_memories"]] == ["Orders close on 5 November 2026."]
    assert body["current_memories"][0]["valid_until"].startswith(FUTURE)
    assert body["expired_count"] == 0


async def test_a_line_that_has_not_started_is_not_served_and_is_not_expired():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await _fresh(client)
        await _ingest(client, corpus, _doc(f"valid_from: {FUTURE}\n"))
        body = await _post(client, "/api/memory/current", {"corpus": corpus})
    assert body["current_memories"] == [] and body["expired_count"] == 0


async def test_an_expiry_that_cannot_be_read_refuses_the_document():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await _fresh(client)
        result = await _ingest(client, corpus, _doc("valid_until: next friday\n"), status=422)
        body = await _post(client, "/api/memory/current", {"corpus": corpus})
    # A refused document, with the reason; not "Semantic model unavailable".
    assert result["detail"]["code"] == "invalid_document"
    assert result["detail"]["message"].startswith("invalid_validity: valid_until 'next friday'")
    assert body["current_memories"] == []


async def test_an_authored_claim_the_archive_refuses_is_an_input_error_not_a_503():
    bad = (
        "---\nclaims:\n  - key: k\n    claim: Not in the text.\n    value: v\n"
        "    evidence: Not in the text.\n---\n\n# Doc\n\nSomething else entirely.\n"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await _fresh(client)
        result = await _ingest(client, corpus, bad, "notes/bad.md", status=422)
    assert result["detail"]["code"] == "invalid_document"


async def test_remember_takes_a_window_on_the_http_route():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await _fresh(client)
        for statement, until in (("The gift box costs Rs 1,499.", FUTURE), ("Old offer.", PAST)):
            await _post(
                client,
                "/api/memory/remember",
                {"corpus": corpus, "statement": statement, "valid_until": until},
            )
        naive = await client.post(
            "/api/memory/remember",
            json={"corpus": corpus, "statement": "Bad.", "valid_until": "2026-11-06 10:00"},
        )
        backwards = await client.post(
            "/api/memory/remember",
            json={
                "corpus": corpus,
                "statement": "Backwards.",
                "valid_from": "2026-12-01",
                "valid_until": "2026-11-01",
            },
        )
        body = await _post(client, "/api/memory/current", {"corpus": corpus})
    assert [c["claim"] for c in body["current_memories"]] == ["The gift box costs Rs 1,499."]
    assert body["expired_count"] == 1
    for refused in (naive, backwards):
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "invalid_validity"


async def test_the_same_statement_with_a_new_end_is_a_new_version_and_the_same_end_is_not():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await _fresh(client)
        body = {"corpus": corpus, "statement": "The sale runs.", "key": "sale"}
        first = await _post(client, "/api/memory/remember", {**body, "valid_until": FUTURE})
        again = await _post(client, "/api/memory/remember", {**body, "valid_until": FUTURE})
        ended = await _post(client, "/api/memory/remember", {**body, "valid_until": PAST})
        current = await _post(client, "/api/memory/current", {"corpus": corpus})
    assert first["event"] == "NEW" and again["event"] == "UNCHANGED"
    assert ended["event"] != "UNCHANGED" and ended["version_id"] != first["version_id"]
    # Ending a fact early is how it is withdrawn: it is history now.
    assert current["current_memories"] == [] and current["expired_count"] == 1


# ------------------------------------------------------------- the other surfaces


def test_the_sdk_sends_a_date_as_text_and_refuses_a_window_with_a_file():
    from verilore.sdk import MemoryClient, _iso_bound

    assert _iso_bound(date(2026, 11, 6)) == "2026-11-06"
    assert _iso_bound(datetime(2026, 11, 6, tzinfo=timezone.utc)) == "2026-11-06T00:00:00+00:00"
    assert _iso_bound("2026-11-06") == "2026-11-06" and _iso_bound(None) is None
    client = MemoryClient.__new__(MemoryClient)
    with pytest.raises(ValueError, match="frontmatter"):
        client.remember(file="brief.md", valid_until="2026-11-06")


def test_the_cli_passes_the_window_and_says_when_it_has_already_passed(monkeypatch):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    import verilore.cli.main as cli

    seen = {}

    def write(statement, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            event="NEW", version_id="v" * 12, path="memory/x.md", related_active_claims=[]
        )

    client = SimpleNamespace(memory=SimpleNamespace(remember=write))
    monkeypatch.setattr(cli, "_client", lambda base_url, **kwargs: client)
    monkeypatch.setattr(cli, "_warm_runtime", lambda: None)
    runner = CliRunner()

    ok = runner.invoke(cli.app, ["remember", "The sale runs.", "--valid-until", FUTURE])
    assert ok.exit_code == 0, ok.output
    assert seen["valid_until"] == FUTURE and seen["valid_from"] is None
    assert "already passed" not in ok.output

    late = runner.invoke(cli.app, ["remember", "The sale ran.", "--valid-until", PAST])
    assert late.exit_code == 0, late.output
    assert "has already passed" in late.output


def test_the_mcp_tool_passes_the_window_and_notes_a_past_one(monkeypatch):
    import asyncio
    import contextlib

    import verilore.mcp_server as mcp_server
    from verilore.sdk import MemoryResult

    calls = []

    class Client:
        def remember(self, statement, **kwargs):
            calls.append(kwargs)
            return MemoryResult(corpus="docs", version_id="v1", event="NEW", path="p.md", key="k")

    monkeypatch.setattr(mcp_server, "_client", lambda corpus: Client())
    monkeypatch.setattr(mcp_server, "_caller", contextlib.nullcontext)
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            mcp_server.mcp.call_tool(
                "memory_remember",
                {"statement": "Old offer.", "corpus": "docs", "valid_until": PAST},
            )
        )
    finally:
        loop.close()
    payload = json.loads(result.content[0].text)
    assert calls[0]["valid_until"] == PAST and calls[0]["valid_from"] is None
    assert "has already passed" in payload["note"] and "draft" in payload["note"]
