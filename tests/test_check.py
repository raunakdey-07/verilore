"""A draft in, the approved rules it breaks out (CHECK-1).

The brief controls what a model is given; nothing controlled what it wrote. A
check does the part a machine can do exactly: text a rule bans, and a price,
date, weight, percentage or duration that differs from an approved fact about
the same thing. Every finding names the claim it breaks.

What must NOT be flagged is held as carefully as what must: a check that
guesses is ignored after its first wrong flag.
"""

from __future__ import annotations

import json
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from typer.testing import CliRunner

from live_server import live_server  # noqa: F401,F811  module-scoped server fixture
from verilore import Verilore

RULES = [
    'Never use the word "premium".',
    "Never use emojis in body copy.",
    "No exclamation marks in body copy.",
    "Avoid “world-class” and “best-in-class”.",
    "Never discount the house blend.",
    "The gift box costs Rs 1,499.",
    "Orders close on 5 November 2026.",
    "The Trailhead 2 bike weighs 9.8 kilograms.",
    "Do not promise delivery in under 48 hours.",
    "We never use hashtags on LinkedIn.",
    "The spring launch date is 14 March 2027.",
    "Shipping costs Rs 99 for every order.",
]


def _current(rules=RULES):
    return {
        "corpus": "kaveri",
        "current_memories": [
            {"id": f"c{n:02d}" + "a" * 10, "claim": rule, "path": "brand/rules.md"}
            for n, rule in enumerate(rules)
        ],
    }


def _check(draft, **kwargs):
    from verilore.check import check_draft

    return check_draft(draft, _current(), **kwargs)


def _details(result):
    return [finding.detail for finding in result.findings]


@pytest.mark.parametrize(
    "rule,banned",
    [
        ('Never use the word "premium".', [("text", "premium")]),
        ("Do not use the word premium in any copy.", [("text", "premium")]),
        (
            "Avoid “world-class” and “best-in-class”.",
            [("text", "world-class"), ("text", "best-in-class")],
        ),
        ("Don't say 'cheap'.", [("text", "cheap")]),
        ("Never use emojis in body copy.", [("class", "emoji")]),
        ("No exclamation marks in body copy.", [("class", "exclamation")]),
        ("We never use hashtags on LinkedIn.", [("class", "hashtag")]),
        # An action, not a word: nothing to look for in the text.
        ("Never discount the house blend.", []),
        ("Do not promise delivery in under 48 hours.", []),
        ("Our voice is warm, plain and direct.", []),
    ],
)
def test_what_a_rule_bans_is_read_only_when_the_rule_names_it(rule, banned):
    from verilore.check import banned_text

    assert banned_text(rule) == banned


def test_a_draft_that_breaks_rules_gets_one_finding_per_problem_each_naming_its_rule():
    draft = (
        "Our premium gift box is back! \U0001f381 Now just Rs 999, and orders close on "
        "10 November.\nThe Trailhead 2 weighs only 8.5 kg. World-class coffee, every day."
    )
    result = _check(draft)
    assert not result.ok
    by_rule = {finding.claim: finding for finding in result.findings}
    assert set(by_rule) == {
        'Never use the word "premium".',
        "Never use emojis in body copy.",
        "No exclamation marks in body copy.",
        "Avoid “world-class” and “best-in-class”.",
        "The gift box costs Rs 1,499.",
        "Orders close on 5 November 2026.",
        "The Trailhead 2 bike weighs 9.8 kilograms.",
    }
    assert by_rule["The gift box costs Rs 1,499."].detail == (
        "The draft says Rs 999 where approved memory says Rs 1,499 (money)."
    )
    assert by_rule["Orders close on 5 November 2026."].quote == "10 November"
    assert by_rule["The Trailhead 2 bike weighs 9.8 kilograms."].quote == "8.5 kg"
    assert by_rule['Never use the word "premium".'].quote == "premium"
    # The quote is the draft's own text, so a reviewer can find it.
    assert all(finding.quote in draft for finding in result.findings)
    assert all(finding.claim_id.startswith("c") for finding in result.findings)


def test_a_draft_that_agrees_with_memory_has_no_findings():
    draft = (
        "The gift box costs Rs 1,499.00 and orders close on 5 November. "
        "The Trailhead 2 bike weighs 9.8 kilograms. Spring starts 14 March."
    )
    result = _check(draft)
    assert result.ok, _details(result)
    assert result.checked == len(RULES) and result.banned_rules == 5


def test_a_number_about_something_else_is_not_compared():
    # Rs 99 is the shipping fee, not the gift box's price, and 2 kg is not the
    # bike's weight. 24 hours is not compared as a value either, which would
    # get the direction backwards: it breaks "not under 48 hours" as a limit
    # (CHECK-3), and that finding says what the rule allows.
    result = _check("Shipping is Rs 99. Gift box delivery in 24 hours, 2 kg.")
    assert [(f.kind, f.quote, f.expected) for f in result.findings] == [
        ("bound", "24 hours", "48 hours or more")
    ], _details(result)


def test_a_price_is_compared_by_the_product_it_names_and_not_by_the_word_price():
    """A draft names the product, not the word "price": "Trail 2, now Rs 22,999"
    is about the Trail 2's price. A model number is part of the subject, so the
    Trail 3's price is not compared with the Trail 2's."""
    from verilore.check import check_draft

    current = _current(["Prices: The Trail 2 costs Rs 24,999."])
    wrong = check_draft("Meet the Trail 2: our lightest ride, now Rs 22,999.", current)
    assert _details(wrong) == [
        "The draft says Rs 22,999 where approved memory says Rs 24,999 (money)."
    ]
    # Not compared with the Trail 2's price. Memory states no price for the
    # Trail 3, so by default that price is reported as unsupported instead.
    assert check_draft("Meet the Trail 3, now Rs 34,999.", current, unsupported=False).ok
    assert [f.kind for f in check_draft("Meet the Trail 3, now Rs 34,999.", current).findings] == [
        "unsupported"
    ]
    assert check_draft("The Trail 2 is Rs 24,999.", current).ok


def test_a_price_under_a_product_heading_is_that_products_price():
    """ "Price: Rs 520 for a 250 g tin." names no product; its heading does. Read
    without it, every draft with a tin and a price was compared with every price
    in the sheet."""
    from verilore.check import check_draft

    current = {
        "corpus": "saffron",
        "current_memories": [
            {"id": "a" * 12, "claim": "Price: Rs 520 for a 250 g tin.", "path": "products.md"},
            {"id": "b" * 12, "claim": "Price: Rs 890 for a 100 g tin.", "path": "products.md"},
        ],
        "evidence": [
            {"claim_id": "a" * 12, "heading": "Products > Assam Gold"},
            {"claim_id": "b" * 12, "heading": "Products > Darjeeling First Flush"},
        ],
    }
    wrong = check_draft("Assam Gold is now Rs 480 for a 250 g tin.", current)
    assert [(f.claim_id, f.quote) for f in wrong.findings] == [("a" * 12, "Rs 480")]
    kahwa = "Our Kashmiri Kahwa tin is Rs 640."
    assert check_draft(kahwa, current, unsupported=False).ok
    assert [f.kind for f in check_draft(kahwa, current).findings] == ["unsupported"]
    assert check_draft("Darjeeling First Flush, Rs 890 a tin.", current).ok


def test_the_same_rule_in_two_documents_is_one_finding_that_names_both():
    """A brand guide synced as Word and as PDF states each rule twice. The draft
    broke one rule, once."""
    from verilore.check import check_draft, render_check

    current = {
        "corpus": "kaveri",
        "current_memories": [
            {"id": "a" * 12, "claim": "Never use the word premium.", "path": "guide.docx"},
            {"id": "b" * 12, "claim": "Never use the word premium.", "path": "guide.pdf"},
            {"id": "c" * 12, "claim": "Orders close on 5 November.", "path": "deck.pptx"},
            {"id": "d" * 12, "claim": "Orders close on 5 November.", "path": "brief.md"},
        ],
    }
    result = check_draft("Premium gifts. Orders close on 7 November.", current)
    assert [(f.kind, f.path, f.also) for f in result.findings] == [
        ("banned", "guide.docx", ("guide.pdf",)),
        ("number", "deck.pptx", ("brief.md",)),
    ]
    assert result.findings[0].as_dict()["also"] == ["guide.pdf"]
    assert "[guide.docx, aaaaaaaaaaaa; also guide.pdf]" in render_check(result)


def test_a_ban_for_one_channel_is_named_and_skipped_for_another():
    draft = "Brewing together this Diwali. #BrewTogether"
    unlabelled = _check(draft)
    assert _details(unlabelled) == [
        "The draft uses hashtag (#BrewTogether), which an approved rule bans "
        "(the rule is for LinkedIn)."
    ]
    assert _check(draft, channel="Instagram").ok
    assert not _check(draft, channel="LinkedIn post").ok


def test_whole_words_only_and_case_does_not_matter():
    assert _check("Premium is not a word we use.").findings[0].quote == "Premium"
    assert _check("Supremium beans.").ok, "part of a word is not the word"


def test_the_report_says_what_was_and_was_not_checked():
    from verilore.check import render_check

    clean = render_check(_check("Spring starts 14 March."))
    assert clean.startswith("No problems found against 12 approved lines (5 name banned text).")
    assert "Tone and voice are a reviewer's call." in clean
    broken = render_check(_check("Premium."))
    assert broken.splitlines()[0] == "1 problem(s) against 12 approved lines:"
    assert 'rule: Never use the word "premium".  [brand/rules.md, c00aaaaaaaaa]' in broken


def test_the_cli_reads_a_file_or_stdin_and_exits_one_on_a_finding(monkeypatch, tmp_path):
    import verilore.cli.main as cli
    from verilore.check import check_draft

    seen = {}

    def check(draft, corpus, **kwargs):
        seen.update(draft=draft, corpus=corpus, **kwargs)
        return check_draft(draft, _current())

    monkeypatch.setattr(
        cli,
        "_client",
        lambda base_url, **kwargs: SimpleNamespace(memory=SimpleNamespace(check=check)),
    )
    runner = CliRunner()
    page = tmp_path / "draft.txt"
    page.write_text("A premium gift.\n", encoding="utf-8")
    bad = runner.invoke(
        cli.app, ["check", str(page), "--corpus", "kaveri", "--channel", "Instagram"]
    )
    assert bad.exit_code == 1, bad.output
    assert seen == {
        "draft": "A premium gift.\n",
        "corpus": "kaveri",
        "path_prefix": None,
        "channel": "Instagram",
    }
    assert 'The draft uses "premium"' in bad.output
    good = runner.invoke(cli.app, ["check", "-", "--json"], input="Spring starts 14 March.")
    assert good.exit_code == 0, good.output
    assert json.loads(good.output)["ok"] is True


def test_the_cli_refuses_a_draft_it_should_not_read(monkeypatch, tmp_path):
    """A draft is a post or a page: over 1 MB is refused before anything is
    asked of memory, and so is a file that is not text."""
    import verilore.cli.main as cli

    def unreachable(*_args, **_kwargs):
        raise AssertionError("memory was asked about a draft that was refused")

    monkeypatch.setattr(cli, "_client", unreachable)
    runner = CliRunner()
    big = tmp_path / "book.txt"
    big.write_bytes(b"word " * 200_001)
    refused = runner.invoke(cli.app, ["check", str(big)])
    assert refused.exit_code == 2
    assert "over 1 MB" in refused.output
    binary = tmp_path / "photo.txt"
    binary.write_bytes(b"\xff\xd8\xff\xe0 not text")
    refused = runner.invoke(cli.app, ["check", str(binary)])
    assert refused.exit_code == 2
    assert "not UTF-8" in refused.output
    piped = runner.invoke(cli.app, ["check", "-"], input="x" * 1_000_001)
    assert piped.exit_code == 2


@pytest.fixture
def service(monkeypatch):
    """The MCP adapter's service, replaced: no database."""
    from verilore.api.models.memory import MemoryResponse, State

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
    import sys

    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


async def test_the_mcp_tool_reads_current_and_returns_the_report(service):
    import verilore.mcp_server as mcp_server
    from verilore.api.models.memory import MemoryRequest

    result = await mcp_server.mcp.call_tool(
        "memory_check", {"corpus": "docs", "draft": "Hello.", "path_prefix": ["brand"]}
    )
    assert result.content[0].text.startswith("No problems found against 0 approved lines")
    service.execute.assert_awaited_once_with(
        "current", MemoryRequest(corpus="docs", path_prefix=["brand"])
    )


def test_end_to_end_over_http_on_a_brand_kit(live_server):  # noqa: F811
    corpus, key = live_server.corpora["globex"], live_server.keys["globex"]
    kit = {
        "brand/rules.md": "---\nstatus: approved\n---\n\n# Rules\n\n"
        '- Never use the word "premium".\n',
        "campaigns/diwali/brief.md": "---\nstatus: approved\n---\n\n# Diwali\n\n"
        "- The gift box costs Rs 1,499.\n",
        "notes/old.md": "---\nstatus: draft\n---\n\n# Old\n\n- The gift box costs Rs 999.\n",
    }
    for path, content in kit.items():
        resp = httpx.post(
            f"{live_server.url}/api/ingest/file",
            json={"content": content, "path": path, "corpus": corpus},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text
    vl = Verilore(corpus, base_url=live_server.url, api_key=key, timeout=5, retries=1)
    result = vl.memory.check("Premium gift box, now Rs 999.")
    # The draft's Rs 999 matches a draft line, which is not memory: still a finding.
    assert sorted(f.claim for f in result.findings) == [
        'Never use the word "premium".',
        "The gift box costs Rs 1,499.",
    ]
    scoped = vl.memory.check("Premium gift box, now Rs 999.", path_prefix="campaigns")
    assert [f.claim for f in scoped.findings] == ["The gift box costs Rs 1,499."]
