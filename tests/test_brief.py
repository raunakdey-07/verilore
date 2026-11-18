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


def _claim(n: int, text: str, path: str, **extra) -> dict:
    return {"id": f"c{n}", "claim": text, "path": path, "status": "CURRENT", **extra}


def _response(claims, *, conflicts=(), withheld=None, evidence=()) -> dict:
    return {
        "corpus": "trailhead",
        "current_memories": list(claims),
        "conflicts": list(conflicts),
        "withheld_counts": withheld or {},
        "evidence": list(evidence),
    }


def _lines(brief) -> list[str]:
    """The statements a brief carries, without the leading dash."""
    return [line[2:] for line in brief.text.splitlines() if line.startswith("- ")]


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
    # Each document is named once, above its lines, not on every line.
    assert lines[2:] == [
        "",
        "brand/guide.md",
        "- Our voice is warm, plain and direct.",
        "",
        "brand/specs.md",
        "- The Trailhead 2 bike weighs 9.8 kilograms.",
    ]
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
    assert brief.text.splitlines()[3:] == ["a.md", "- A one.", "- A two.", "", "b.md", "- B one."]
    assert brief.claim_ids == ("c1", "c3", "c2")


def test_the_same_sentence_in_two_documents_is_one_line_carrying_both_claims():
    brief = render_brief(
        _response([_claim(1, "Ship on Fridays.", "a.md"), _claim(2, "Ship on  Fridays.", "b.md")])
    )
    assert _lines(brief) == ["Ship on Fridays."]
    assert "b.md" not in brief.text
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
    rules = _lines(brief)
    assert rules and all(line.endswith(" everywhere.") for line in rules), "a line was cut mid-way"
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


# ------------------------------------------------- what is kept when it is cut

BIG = [
    *[
        _claim(n, f"The {name} blend is roasted in batch {n}.", "brand/catalogue.md")
        for n, name in enumerate(["Araku", "Coorg", "Nilgiri", "Wayanad"] * 28)
    ],
    _claim(900, 'Never use the word "premium".', "brand/rules.md"),
    _claim(901, "Do not promise delivery in under 48 hours.", "brand/rules.md"),
    _claim(902, "Prices must include GST.", "brand/rules.md"),
    _claim(903, "We sound like a friend who knows coffee.", "brand/voice.md"),
    _claim(
        904, "Instagram captions run to 150 characters and three hashtags.", "brand/channels.md"
    ),
    _claim(905, "Blog posts run to 800 words and take no hashtags.", "brand/channels.md"),
    _claim(906, "Orders for Diwali close on 5 November 2026.", "campaigns/diwali/brief.md"),
]


def test_rules_are_kept_first_however_far_down_the_corpus_they_are():
    """128 lines, room for sixteen: every never, do not and must is among them."""
    brief = render_brief(_response(BIG), max_chars=2000)
    assert len(brief.text) <= 2000 and brief.omitted > 60
    kept = _lines(brief)
    assert 'Never use the word "premium".' in kept
    assert "Do not promise delivery in under 48 hours." in kept
    assert "Prices must include GST." in kept
    assert brief.omitted_rules == 0
    assert brief.text.splitlines()[-1] == (
        f"Left out for length: {brief.omitted} more approved lines."
    )


def test_a_must_path_is_kept_whole_before_anything_else():
    brief = render_brief(_response(BIG), max_chars=1000, must=["brand/voice.md"])
    assert "We sound like a friend who knows coffee." in _lines(brief)
    # Without it, a line with no rule word waits its turn behind the catalogue.
    assert "We sound like a friend who knows coffee." not in _lines(
        render_brief(_response(BIG), max_chars=1000)
    )


def test_a_task_keeps_the_lines_about_it_and_drops_the_others():
    instagram = render_brief(
        _response(BIG), max_chars=1000, task="Instagram caption for the Diwali launch"
    )
    kept = _lines(instagram)
    assert "Instagram captions run to 150 characters and three hashtags." in kept
    assert "Orders for Diwali close on 5 November 2026." in kept
    assert "Blog posts run to 800 words and take no hashtags." not in kept
    assert instagram.task == "Instagram caption for the Diwali launch"
    assert instagram.text.endswith("The lines least related to the task went first.")

    blog = _lines(render_brief(_response(BIG), max_chars=1000, task="A blog post"))
    assert "Blog posts run to 800 words and take no hashtags." in blog
    assert "Instagram captions run to 150 characters and three hashtags." not in blog


def test_a_task_changes_nothing_when_everything_fits():
    small = BIG[-7:]
    plain = render_brief(_response(small))
    ranked = render_brief(_response(small), task="Instagram caption")
    assert ranked.text == plain.text and ranked.claim_ids == plain.claim_ids


def test_a_heading_can_make_its_lines_rules():
    claims = [
        *[_claim(n, f"Filler line number {n} about the catalogue.", "a.md") for n in range(40)],
        _claim(500, "Superlatives such as best or finest.", "voice.md"),
    ]
    evidence = [{"claim_id": "c500", "heading": "Voice > Never write"}]
    brief = render_brief(_response(claims, evidence=evidence), max_chars=700)
    assert "Superlatives such as best or finest." in _lines(brief)
    assert "Superlatives such as best or finest." not in _lines(
        render_brief(_response(claims), max_chars=700)
    )


def test_when_even_the_rules_do_not_fit_the_brief_says_so():
    rules = [
        _claim(n, f"Never do forbidden thing number {n} in any copy.", "r.md") for n in range(60)
    ]
    brief = render_brief(_response(rules), max_chars=800)
    assert brief.omitted_rules == brief.omitted > 0
    assert brief.text.splitlines()[-1] == (
        f"Left out for length: {brief.omitted} more approved lines, "
        f"{brief.omitted_rules} of them rules."
    )


def test_remembered_statements_sit_under_one_plain_label_and_labels_stay_small():
    claims = [
        _claim(1, "Our voice is warm, plain and direct.", "brand/guide.md"),
        _claim(
            2, "Do not open captions with a question.", "memory/text-0f3a9c1b2d4e-1a2b3c4d5e6f.md"
        ),
        _claim(
            3, "Lead with the ritual, not the discount.", "memory/text-77aa11bb22cc-9f8e7d6c5b4a.md"
        ),
        _claim(
            4,
            "The Diwali hashtag is #BrewTogether.",
            "campaigns/diwali/memory/diwali-hashtag-5c6d7e8f9a0b.md",
        ),
    ]
    brief = render_brief(_response(claims))
    assert "text-0f3a9c1b2d4e" not in brief.text
    assert brief.text.splitlines()[3:] == [
        "brand/guide.md",
        "- Our voice is warm, plain and direct.",
        "",
        "Saved decisions",
        "- Do not open captions with a question.",
        "- Lead with the ritual, not the discount.",
        "",
        "Saved decisions (campaigns/diwali)",
        "- The Diwali hashtag is #BrewTogether.",
    ]
    # On a brief of ordinary size the labels are a small share of the text.
    # With a path on every line they were 44% of one that mixed both kinds.
    many = [
        _claim(100 + n, f"Saved decision number {n} about how we write captions.", path)
        for n, path in enumerate(
            [f"memory/text-{n:012x}-{n * 7919:012x}.md" for n in range(12)]
            + ["brand/guide.md"] * 12
        )
    ]
    body = render_brief(_response(many)).text.split("\n\n", 1)[1]
    labels = sum(len(line) for line in body.splitlines() if line and not line.startswith("- "))
    assert labels / len(body) < 0.15


def test_an_expired_line_is_counted_and_never_quoted():
    from datetime import datetime, timezone

    claims = [
        _claim(1, "Orders close on 5 November 2026.", "d.md", valid_until="2026-11-06T00:00:00Z"),
        _claim(2, "The gift box costs Rs 1,499.", "d.md", valid_until="2027-01-01T00:00:00Z"),
        _claim(3, "We never discount the house blend.", "d.md"),
    ]
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    brief = render_brief(_response(claims, withheld={"draft": 1}), now=now)
    assert _lines(brief) == ["The gift box costs Rs 1,499.", "We never discount the house blend."]
    assert brief.expired == 1 and brief.claim_ids == ("c2", "c3")
    assert brief.text.splitlines()[-1] == "Not included: 1 draft, 1 expired."


def test_a_token_budget_needs_no_tokenizer_and_errs_towards_fitting():
    from verilore.brief import approx_tokens

    assert approx_tokens("abcd" * 10) == 10
    # A character outside ASCII counts as a whole token: an overestimate, on purpose.
    assert approx_tokens("\u0915\u0949\u092b\u093c\u0940") == 5
    brief = render_brief(_response(BIG), max_tokens=300)
    assert brief.approx_tokens <= 300 and brief.omitted > 0
    assert len(brief.text) <= 1200
    with pytest.raises(ValueError, match="not both"):
        render_brief(_response(BIG), max_chars=2000, max_tokens=300)
    with pytest.raises(ValueError, match="max_tokens"):
        render_brief(_response(BIG), max_tokens=10)


def test_the_cli_prints_the_text_and_json_carries_the_ids(monkeypatch):
    import verilore.cli.main as cli

    seen = {}

    def brief(corpus, *, path_prefix=None, **options):
        seen.update(corpus=corpus, path_prefix=path_prefix, **options)
        return render_brief(
            _response([_claim(1, "Our voice is warm.", "brand/guide.md")], withheld={"draft": 1}),
            path_prefix=path_prefix,
            **options,
        )

    client = SimpleNamespace(memory=SimpleNamespace(brief=brief))
    monkeypatch.setattr(cli, "_client", lambda base_url, runtime=True: client)
    runner = CliRunner()

    args = ["brief", "--corpus", "trailhead", "--path-prefix", "brand", "--path-prefix", "x/y"]
    plain = runner.invoke(cli.app, args)
    assert plain.exit_code == 0, plain.output
    assert seen == {
        "corpus": "trailhead",
        "path_prefix": ["brand", "x/y"],
        "max_chars": None,
        "max_tokens": None,
        "task": None,
        "must": None,
    }
    assert plain.output.splitlines()[0] == 'Approved memory for "trailhead", scope brand + x/y.'
    assert "brand/guide.md\n- Our voice is warm.\n" in plain.output

    options = ["--task", "Instagram caption", "--must", "brand", "--max-tokens", "500"]
    assert runner.invoke(cli.app, [*args, *options]).exit_code == 0
    assert (seen["task"], seen["must"], seen["max_tokens"]) == ("Instagram caption", ["brand"], 500)

    as_json = runner.invoke(cli.app, [*args, "--json"])
    assert as_json.exit_code == 0, as_json.output
    body = json.loads(as_json.output)
    assert set(body) == {
        "text",
        "corpus",
        "scope",
        "claim_ids",
        "omitted",
        "omitted_rules",
        "omitted_must",
        "withheld",
        "conflicts",
        "expired",
        "approx_tokens",
        "possible_conflicts",
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


async def test_the_mcp_tool_passes_the_task_and_the_must_paths(service):
    import verilore.mcp_server as mcp_server

    service.execute.return_value = MemoryResponse.model_validate(
        {
            "query": "",
            "corpus": "docs",
            "state": {"as_of": "2026-01-01T00:00:00Z"},
        }
    )
    tools = {tool.name: tool for tool in await mcp_server.mcp.list_tools()}
    tool = tools["memory_brief"]
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")
    assert {"task", "must", "max_chars", "path_prefix"} <= set(schema["properties"])
    result = await mcp_server.mcp.call_tool(
        "memory_brief", {"corpus": "docs", "task": "Instagram caption", "must": "brand"}
    )
    assert "(no approved memory in this scope)" in result.content[0].text


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
    lines = brief.text.splitlines()
    assert "brand/guide.md" in lines and "brand/specs.md" in lines
    assert "- Our voice is warm, plain and confident." in lines
    assert "- The Trailhead 2 bike weighs 9.8 kilograms." in lines
    assert "14 March 2027" in brief.text
    assert "autumn" not in brief.text.lower(), "a campaign outside the scope leaked in"
    assert "irreverent" not in brief.text, "a draft reached the prompt"
    assert brief.withheld.get("draft", 0) >= 1
    assert brief.text.splitlines()[-1].startswith("Not included: ")

    # The same claims the pack vouches for, at a fraction of the size.
    assert set(brief.claim_ids) == {claim.id for claim in pack.current_memories}
    assert len(brief.text) * 5 < len(pack.canonical_json())


# --------------------------------------------- sections and task ranking (BRIEF-3)

#: A product sheet and a channel guide, as a brand writes them: facts under the
#: name of what they are about, and rules for one channel under its name.
SECTIONED = [
    _claim(1, "Price: Rs 520 for a 250 g tin.", "brand/products.md"),
    _claim(2, "Steep Assam Gold for 4 minutes at 95 °C.", "brand/products.md"),
    _claim(3, "Price: Rs 890 for a 100 g tin.", "brand/products.md"),
    _claim(4, "Never tag a competitor brand on Instagram.", "brand/channels.md"),
    _claim(5, "Every WhatsApp message must include the word STOP.", "brand/channels.md"),
    _claim(6, 'We never use the word "premium".', "brand/voice.md"),
    _claim(7, "The spring launch date is 14 March 2027.", "campaigns/spring.md"),
    _claim(8, "Our voice is warm, knowledgeable and unhurried.", "brand/voice.md"),
    _claim(9, "We write in Indian English.", "brand/voice.md"),
    _claim(10, "Send WhatsApp messages only to customers who opted in.", "brand/channels.md"),
]
SECTION_EVIDENCE = [
    {"claim_id": "c1", "heading": "Products > Assam Gold"},
    {"claim_id": "c2", "heading": "Products > Assam Gold"},
    {"claim_id": "c3", "heading": "Products > Darjeeling First Flush"},
    {"claim_id": "c4", "heading": "Channel rules > Instagram"},
    {"claim_id": "c5", "heading": "Channel rules > WhatsApp"},
    {"claim_id": "c6", "heading": "Voice > Words we do not use"},
    {"claim_id": "c7", "heading": "Spring > Facts"},
    {"claim_id": "c8", "heading": "Voice"},
    {"claim_id": "c9", "heading": "Voice"},
    {"claim_id": "c10", "heading": "Channel rules > WhatsApp"},
]


def test_a_line_that_leaves_out_its_subject_is_printed_with_it():
    """Out of its document, "Price: Rs 520 for a 250 g tin." is a price for
    nothing, and two such lines are two prices for nothing."""
    lines = _lines(render_brief(_response(SECTIONED, evidence=SECTION_EVIDENCE)))
    assert "Assam Gold: Price: Rs 520 for a 250 g tin." in lines
    assert "Darjeeling First Flush: Price: Rs 890 for a 100 g tin." in lines
    # Said already, or a section that is a topic and not a name: left as written.
    assert "Steep Assam Gold for 4 minutes at 95 °C." in lines
    assert "The spring launch date is 14 March 2027." in lines
    assert 'We never use the word "premium".' in lines


def test_with_a_task_a_rule_for_another_channel_waits_for_rules_that_hold_everywhere():
    """For an email, "never tag a competitor on Instagram" cannot be broken and
    "never use the word premium" can. The first used to win room because it is
    a rule; now the rule that can be broken does."""
    response = _response(SECTIONED, evidence=SECTION_EVIDENCE)
    brief = render_brief(response, task="Write an email about the spring launch", max_chars=420)
    lines = _lines(brief)
    assert "The spring launch date is 14 March 2027." in lines
    assert 'We never use the word "premium".' in lines
    assert "Never tag a competitor brand on Instagram." not in lines
    assert "Every WhatsApp message must include the word STOP." not in lines
    # For the channel it names, the same rules come first.
    whatsapp = _lines(render_brief(response, task="Write a WhatsApp message", max_chars=460))
    assert "Every WhatsApp message must include the word STOP." in whatsapp
    assert "Send WhatsApp messages only to customers who opted in." in whatsapp
    assert "Never tag a competitor brand on Instagram." not in whatsapp


def test_the_line_that_says_it_beats_lines_that_only_share_its_file_name():
    """Every line of voice.md shares "voice" with "describe our brand voice" by
    file name. The one line that says what the voice is must not lose to them."""
    response = _response(SECTIONED, evidence=SECTION_EVIDENCE)
    brief = render_brief(
        response,
        task="Describe our brand voice in one sentence, using the exact adjectives",
        max_chars=MIN_MAX_CHARS,
    )
    assert "Our voice is warm, knowledgeable and unhurried." in _lines(brief)
    assert "We write in Indian English." not in _lines(brief)
