"""A price, percentage or date nothing approved states is made up (CHECK-2).

`check` caught a value that contradicts an approved one. It did not catch a
value with nothing behind it: "Masala Chai costs Rs 300" passed, for a product
the kit never mentions. That is the error a weak model makes most, because its
context is silent and it fills the silence. And a finding was a report for a
person; a model told only "there are problems" rewrites everything. Now each
finding also reads as one exact instruction (`render_feedback`).
"""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

KIT = [
    ("brand/voice.md", 'We never use the word "premium".', ""),
    ("brand/voice.md", "Do not use exclamation marks in emails at all.", ""),
    ("brand/products.md", "Price: Rs 520 for a 250 g tin.", "Products > Assam Gold"),
    ("brand/products.md", "Orders below Rs 999 pay Rs 79 for shipping.", "Products > Shipping"),
    ("campaigns/winter.md", "The winter offer is 15% off the Kashmiri Kahwa tin.", ""),
    ("campaigns/winter.md", "The winter offer ends on 31 January 2027.", ""),
]


def _current():
    return {
        "corpus": "saffron",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": path}
            for n, (path, claim, _h) in enumerate(KIT)
        ],
        "evidence": [
            {"claim_id": f"line-{n}", "heading": heading}
            for n, (_p, _c, heading) in enumerate(KIT)
            if heading
        ],
    }


def _check(draft, **kwargs):
    from verilore.check import check_draft

    return check_draft(draft, _current(), **kwargs)


def _kinds(result):
    return [(f.kind, f.quote) for f in result.findings]


def test_a_value_nothing_approved_states_is_reported_and_one_that_is_stated_is_not():
    made_up = _check("Masala Chai costs Rs 300. Take 20% off until 15 February 2027.")
    assert _kinds(made_up) == [
        ("unsupported", "Rs 300"),
        ("unsupported", "20%"),
        ("unsupported", "15 February 2027"),
    ]
    assert made_up.findings[0].detail == (
        "The draft states the price Rs 300, and no approved line does."
    )
    assert made_up.findings[0].claim_id == "" and made_up.unsupported_checked
    stated = _check(
        "Assam Gold is Rs 520 a tin. 15 percent off Kahwa until 31 January. "
        "Free shipping from Rs 999."
    )
    assert stated.ok, _kinds(stated)


def test_a_value_that_differs_is_reported_once_as_differing():
    """Rs 450 for Assam Gold differs from Rs 520: one finding that says what it
    should be, not a second one saying nothing states it."""
    result = _check("Assam Gold is Rs 450 for a 250 g tin.")
    assert _kinds(result) == [("number", "Rs 450")]
    assert result.findings[0].expected == "Rs 520"


def test_a_fact_with_two_values_agrees_with_a_draft_that_repeats_either():
    """ "Orders below Rs 999 pay Rs 79 for shipping" states two prices. A draft
    that says shipping is free from Rs 999 repeats one of them; it was reported
    as "says Rs 999 where approved memory says Rs 999"."""
    assert _check("Shipping is free on orders above Rs 999.").ok
    assert _check("Shipping is Rs 79 below Rs 999.").ok
    # A third price beside one it states is still caught: nothing approved says it.
    assert _kinds(_check("Shipping is Rs 49 below Rs 999.")) == [("unsupported", "Rs 49")]
    # And a lone price that differs says what the fact states.
    wrong = _check("Orders below the free-shipping line pay Rs 49 for shipping.")
    assert _kinds(wrong) == [("number", "Rs 49")]
    assert wrong.findings[0].expected == "Rs 999 or Rs 79"


def test_values_the_task_states_count_as_stated_and_the_check_can_be_turned_off():
    task = "Announce the 25% off flash sale on 3 December 2026."
    draft = "Our flash sale: 25% off on 3 December 2026."
    assert _kinds(_check(draft)) == [("unsupported", "25%"), ("unsupported", "3 December 2026")]
    assert _check(draft, supported_by=[task]).ok
    assert _check(draft, unsupported=False).ok
    assert not _check(draft, unsupported=False).unsupported_checked


def test_a_ban_for_a_channel_written_in_lower_case_is_for_that_channel():
    """ "Do not use exclamation marks in emails" says nothing about Instagram."""
    draft = "Saffron season is here!"
    assert _check(draft, channel="Instagram").ok
    assert _kinds(_check(draft, channel="Email newsletter")) == [("banned", "!")]
    unnamed = _check(draft)
    assert unnamed.findings[0].detail.endswith("(the rule is for emails).")


def test_the_findings_read_as_exact_instructions_for_a_model():
    from verilore.check import render_check, render_feedback

    result = _check("Our premium Assam Gold is Rs 450. Masala Chai is Rs 300.", channel="Email")
    assert render_feedback(result) == "\n".join(
        [
            "Revise the draft. Change only what is listed below and keep everything else "
            "as it is.",
            '- Remove "premium". Approved rule: We never use the word "premium".',
            "- Replace Rs 450 with Rs 520. Approved: Price: Rs 520 for a 250 g tin.",
            "- Remove Rs 300: no approved line states it. Do not replace it with another "
            "value unless an approved line states that value.",
            "Return only the revised draft.",
        ]
    )
    assert "    rule: none; state it only if a person approves it" in render_check(result)
    assert render_feedback(_check("Assam Gold is Rs 520.")) == ""
    exclaim = render_feedback(_check("Order now!", channel="Email"))
    assert "- Remove the exclamation mark !." in exclaim


def test_the_cli_passes_the_choices_and_prints_the_instructions(monkeypatch, tmp_path):
    import verilore.cli.main as cli
    from verilore.check import check_draft

    seen = {}

    def check(draft, corpus, **kwargs):
        seen.clear()
        seen.update(kwargs)
        return check_draft(
            draft,
            _current(),
            unsupported=kwargs.get("unsupported", True),
            supported_by=kwargs.get("supported_by", ()),
        )

    monkeypatch.setattr(
        cli,
        "_client",
        lambda base_url, **kwargs: SimpleNamespace(memory=SimpleNamespace(check=check)),
    )
    runner = CliRunner()
    page = tmp_path / "draft.txt"
    page.write_text("Masala Chai is Rs 300.\n", encoding="utf-8")

    told = runner.invoke(cli.app, ["check", str(page), "--feedback"])
    assert told.exit_code == 1
    assert told.output.startswith("Revise the draft.")
    assert "- Remove Rs 300: no approved line states it." in told.output

    allowed = runner.invoke(cli.app, ["check", str(page), "--allow-unsupported"])
    assert allowed.exit_code == 0, allowed.output
    assert seen["unsupported"] is False

    tasked = runner.invoke(cli.app, ["check", str(page), "--task", "Mention Rs 300 chai"])
    assert tasked.exit_code == 0, tasked.output
    assert seen["supported_by"] == ["Mention Rs 300 chai"]


@pytest.fixture
def service(monkeypatch):
    """The MCP adapter's service, replaced: no database."""
    import sys

    from verilore.api.models.memory import MemoryResponse

    module = ModuleType("verilore.api.services.memory_public")

    class MemoryError(Exception):
        def __init__(self, code, message, status_code):
            super().__init__(message)
            self.code, self.message, self.status_code = code, message, status_code

    module.MemoryError = MemoryError
    module.execute = AsyncMock(return_value=MemoryResponse.model_validate(_current_response()))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


def _current_response():
    return {
        "query": "",
        "corpus": "saffron",
        "state": {"as_of": "2026-01-01T00:00:00Z"},
    }


@pytest.mark.asyncio
async def test_the_mcp_tool_ends_with_what_to_change(service):
    import verilore.mcp_server as mcp_server

    result = await mcp_server.mcp.call_tool(
        "memory_check", {"corpus": "saffron", "draft": "Masala Chai is Rs 300."}
    )
    text = result.content[0].text
    assert text.startswith("1 problem(s) against 0 approved lines:")
    assert text.endswith("Return only the revised draft.")
    tasked = await mcp_server.mcp.call_tool(
        "memory_check",
        {"corpus": "saffron", "draft": "Masala Chai is Rs 300.", "task": "Chai at Rs 300"},
    )
    assert tasked.content[0].text.startswith("No problems found")
