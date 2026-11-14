"""A brief is approved memory as plain lines for a model's prompt.

The renderer decides nothing about what is true: `current` already withheld the
drafts, the rejected and the replaced. These tests pin what rendering promises:
every approved line once, grouped by source, no silent loss, and a size a small
model can afford.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from typer.testing import CliRunner

from live_server import live_server  # noqa: F401,F811  module-scoped server fixture
from verilore import Verilore
from verilore.api.models.memory import MemoryRequest, MemoryResponse, State

SCOPE = ["brand", "campaigns/spring"]

#: The smallest `max_chars` a brief accepts; held equal to the module's below.
MIN_MAX_CHARS = 400


def render_brief(*args, **kwargs):
    """`verilore.brief.render_brief`, imported when called.

    A checkout without the module then fails each test that needs it, instead
    of failing collection and hiding the result of every other test.
    """
    from verilore.brief import render_brief as real

    return real(*args, **kwargs)


#: The brand kit a content app keeps: path -> document.
KIT = {
    "brand/guide.md": (
        "---\nstatus: approved\n---\n\n# Trailhead brand guide\n\n## Voice\n\n"
        "- Our voice is warm, plain and confident.\n\n## Do not use\n\n"
        '- Never use the word "curated" in copy.\n'
    ),
    "brand/specs.md": (
        "# Trailhead product specs\n\n- The Trailhead 2 bike weighs 9.8 kilograms.\n"
    ),
    "brand/voice-refresh.md": (
        "---\nstatus: draft\n---\n\n# Voice refresh\n\n"
        "- Our voice is bold, loud and irreverent.\n"
    ),
    "campaigns/spring/brief.md": (
        "# Campaign brief\n\n## Facts\n\n- The spring launch date is 14 March 2027.\n"
    ),
    "campaigns/autumn/brief.md": (
        "# Campaign brief\n\n## Facts\n\n- The autumn launch date is 9 September 2027.\n"
    ),
}


def _claim(n: int, text: str, path: str) -> dict:
    return {"id": f"c{n}", "claim": text, "path": path, "status": "CURRENT"}


def _response(claims, *, conflicts=(), withheld=None) -> dict:
    return {
        "corpus": "trailhead",
        "current_memories": list(claims),
        "conflicts": list(conflicts),
        "withheld_counts": withheld or {},
    }


def test_every_approved_line_appears_once_with_its_source():
    brief = render_brief(
        _response(
            [
                _claim(1, "Our voice is warm, plain and direct.", "brand/guide.md"),
                _claim(2, "The Trailhead 2 bike weighs 9.8 kilograms.", "brand/specs.md"),
            ]
        ),
        path_prefix=["brand", "campaigns/spring"],
    )
    assert type(brief).__name__ == "Brief" and str(brief) == brief.text
    lines = brief.text.splitlines()
    assert lines[0] == 'Approved memory for "trailhead", scope brand + campaigns/spring.'
    assert "- Our voice is warm, plain and direct. [brand/guide.md]" in lines
    assert "- The Trailhead 2 bike weighs 9.8 kilograms. [brand/specs.md]" in lines
    assert brief.claim_ids == ("c1", "c2")
    assert (brief.kept, brief.omitted, brief.conflicts) == (2, 0, 0)


def test_lines_from_one_document_stay_together_in_the_order_given():
    brief = render_brief(
        _response(
            [
                _claim(1, "A one.", "a.md"),
                _claim(2, "B one.", "b.md"),
                _claim(3, "A two.", "a.md"),
            ]
        )
    )
    rules = [line for line in brief.text.splitlines() if line.startswith("- ")]
    assert rules == ["- A one. [a.md]", "- A two. [a.md]", "- B one. [b.md]"]
    assert brief.claim_ids == ("c1", "c3", "c2")


def test_the_same_sentence_in_two_documents_is_one_line_naming_both():
    brief = render_brief(
        _response([_claim(1, "Ship on Fridays.", "a.md"), _claim(2, "Ship on  Fridays.", "b.md")])
    )
    rules = [line for line in brief.text.splitlines() if line.startswith("- ")]
    assert rules == ["- Ship on Fridays. [a.md, b.md]"]
    assert brief.claim_ids == ("c1", "c2")


def test_what_is_withheld_is_counted_never_quoted():
    brief = render_brief(
        _response(
            [_claim(1, "Our voice is warm.", "guide.md")],
            withheld={"draft": 2, "rejected": 1, "superseded": 0},
        )
    )
    assert brief.text.splitlines()[-1] == "Not included: 2 draft, 1 rejected."
    assert brief.withheld == {"draft": 2, "rejected": 1}


def test_a_long_corpus_is_cut_at_a_line_and_says_how_much_is_missing():
    claims = [_claim(n, f"Rule number {n} is in force everywhere.", "r.md") for n in range(200)]
    brief = render_brief(_response(claims), max_chars=1000)
    assert len(brief.text) <= 1000
    rules = [line for line in brief.text.splitlines() if line.startswith("- ")]
    assert rules and all(line.endswith(" [r.md]") for line in rules), "a line was cut mid-way"
    assert brief.kept == len(rules) and brief.kept + brief.omitted == 200
    assert brief.text.splitlines()[-1] == (
        f"Left out for length: {brief.omitted} more approved lines."
    )


def test_a_conflict_shows_both_sides_and_neither_as_a_rule():
    left = _claim(1, "The datastore is PostgreSQL.", "a.md")
    right = _claim(2, "The datastore is MySQL.", "b.md")
    brief = render_brief(
        _response([left, right], conflicts=[{"id": "g", "key": "db", "claims": [left, right]}])
    )
    rules = [line for line in brief.text.splitlines() if line.startswith("- ")]
    assert rules == ["- The datastore is PostgreSQL. [a.md]  |  The datastore is MySQL. [b.md]"]
    assert "Sources disagree on these." in brief.text
    assert brief.claim_ids == () and brief.conflicts == 1


def test_an_empty_scope_says_so_instead_of_returning_nothing():
    brief = render_brief(_response([]), path_prefix="campaigns/winter")
    assert "(no approved memory in this scope)" in brief.text
    assert brief.kept == 0


def test_the_limits_are_the_documented_ones():
    import verilore.brief as module

    assert module.MIN_MAX_CHARS == MIN_MAX_CHARS
    assert module.DEFAULT_MAX_CHARS == 6000


def test_too_small_a_budget_is_refused_not_silently_emptied():
    with pytest.raises(ValueError, match=str(MIN_MAX_CHARS)):
        render_brief(_response([]), max_chars=MIN_MAX_CHARS - 1)


def test_the_cli_prints_the_text_and_json_carries_the_ids(monkeypatch):
    import verilore.cli.main as cli

    seen = {}

    def brief(corpus, *, path_prefix=None, max_chars=6000):
        seen.update(corpus=corpus, path_prefix=path_prefix, max_chars=max_chars)
        return render_brief(
            _response([_claim(1, "Our voice is warm.", "brand/guide.md")], withheld={"draft": 1}),
            path_prefix=path_prefix,
            max_chars=max_chars,
        )

    client = SimpleNamespace(memory=SimpleNamespace(brief=brief))
    monkeypatch.setattr(cli, "_client", lambda base_url, runtime=True: client)
    runner = CliRunner()

    args = ["brief", "--corpus", "trailhead", "--path-prefix", "brand", "--path-prefix", "x/y"]
    plain = runner.invoke(cli.app, args)
    assert plain.exit_code == 0, plain.output
    assert seen == {"corpus": "trailhead", "path_prefix": ["brand", "x/y"], "max_chars": 6000}
    assert plain.output.splitlines()[0] == 'Approved memory for "trailhead", scope brand + x/y.'
    assert "- Our voice is warm. [brand/guide.md]" in plain.output

    as_json = runner.invoke(cli.app, [*args, "--json"])
    assert as_json.exit_code == 0, as_json.output
    body = json.loads(as_json.output)
    assert set(body) == {
        "text",
        "corpus",
        "scope",
        "claim_ids",
        "omitted",
        "withheld",
        "conflicts",
    }
    assert body["claim_ids"] == ["c1"] and body["withheld"] == {"draft": 1}
    assert body["text"] + "\n" == plain.output

    small = runner.invoke(cli.app, ["brief", "--max-chars", "10"])
    assert small.exit_code == 2
    assert str(MIN_MAX_CHARS) in small.output


@pytest.fixture
def service(monkeypatch):
    """The MCP adapter's service, replaced: no database, no synchronous SDK."""
    module = ModuleType("verilore.api.services.memory_public")

    class MemoryError(Exception):
        def __init__(self, code, message, status_code):
            super().__init__(message)
            self.code, self.message, self.status_code = code, message, status_code

    module.MemoryError = MemoryError
    module.execute = AsyncMock(
        return_value=MemoryResponse(
            query="", corpus="docs", state=State(as_of="2026-01-01T00:00:00Z")
        )
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


async def test_the_mcp_tool_reads_current_and_returns_text(service):
    import verilore.mcp_server as mcp_server

    result = await mcp_server.mcp.call_tool(
        "memory_brief", {"corpus": "docs", "path_prefix": ["brand"]}
    )
    assert not result.is_error
    text = result.content[0].text
    assert text.splitlines()[0] == 'Approved memory for "docs", scope brand.'
    assert "(no approved memory in this scope)" in text
    service.execute.assert_awaited_once_with(
        "current", MemoryRequest(corpus="docs", path_prefix=["brand"])
    )


async def test_the_mcp_tool_reports_a_service_error_as_text_it_can_read(service):
    import verilore.mcp_server as mcp_server

    service.execute.side_effect = service.MemoryError("corpus_not_found", "no such corpus", 404)
    result = await mcp_server.mcp.call_tool("memory_brief", {"corpus": "nope"})
    assert json.loads(result.content[0].text) == {
        "detail": {"code": "corpus_not_found", "message": "no such corpus"}
    }

    service.execute.side_effect = None
    result = await mcp_server.mcp.call_tool("memory_brief", {"corpus": "docs", "max_chars": 10})
    detail = json.loads(result.content[0].text)["detail"]
    assert detail["code"] == "invalid_request" and str(MIN_MAX_CHARS) in detail["message"]


def test_a_brief_is_a_fraction_of_the_pack_and_withholds_the_same(live_server):  # noqa: F811
    """End to end over HTTP, on a brand kit: the scenario a content app runs."""
    corpus = live_server.corpora["globex"]
    key = live_server.keys["globex"]
    for path, content in KIT.items():
        resp = httpx.post(
            f"{live_server.url}/api/ingest/file",
            json={"content": content, "path": path, "corpus": corpus},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text
    vl = Verilore(corpus, base_url=live_server.url, api_key=key, timeout=5, retries=1)

    brief = vl.memory.brief(path_prefix=SCOPE)
    pack = vl.memory.pack(query="", budget=128000, path_prefix=SCOPE)

    assert brief.scope == tuple(SCOPE) and brief.corpus == corpus
    assert "- Our voice is warm, plain and confident. [brand/guide.md]" in brief.text
    assert "- The Trailhead 2 bike weighs 9.8 kilograms. [brand/specs.md]" in brief.text
    assert "14 March 2027" in brief.text
    assert "autumn" not in brief.text.lower(), "a campaign outside the scope leaked in"
    assert "irreverent" not in brief.text, "a draft reached the prompt"
    assert brief.withheld.get("draft", 0) >= 1
    assert brief.text.splitlines()[-1].startswith("Not included: ")

    # The same claims the pack vouches for, at a fraction of the size.
    assert set(brief.claim_ids) == {claim.id for claim in pack.current_memories}
    assert len(brief.text) * 5 < len(pack.canonical_json())
