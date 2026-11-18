"""A value past an approved limit is a finding, and one ban is one instruction (CHECK-3).

"Do not promise delivery in under 48 hours" is the rule the v0.12 review found
broken: a draft said "delivered in 24 hours" and `check` passed it, because a
limit is not a value to match and durations are not checked as made up. A rule
that bounds a price, a percentage or a duration is now read as a limit, and a
draft value on the wrong side of it is a finding that says what the rule allows.
And a kit that bans "premium" in two documents, worded two ways, gave a model the
same instruction twice.
"""

from __future__ import annotations

import pytest

DELIVERY = "Do not promise delivery in under 48 hours."
DISCOUNT = "Discounts never exceed 30%."


def _current(lines):
    return {
        "corpus": "kaveri",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": path}
            for n, (path, claim) in enumerate(lines)
        ],
    }


def _check(draft, lines, **kwargs):
    from verilore.check import check_draft

    return check_draft(draft, _current(lines), **kwargs)


@pytest.mark.parametrize(
    "rule,allowed",
    [
        (DELIVERY, "48 hours or more"),
        (DISCOUNT, "30% or less"),
        ("Never charge more than Rs 99 for shipping.", "Rs 99 or less"),
        ("Save up to 25% on the Estate Blend.", "25% or less"),
        ("Delivery takes at least 3 days.", "3 days or more"),
        # A condition in a fact, not a limit: nothing to hold a draft to.
        ("Orders below Rs 999 pay Rs 79 for shipping.", None),
        ("Free shipping on orders over Rs 999.", None),
        # A channel's length is a channel limit, checked with `channel`.
        ("Keep LinkedIn posts under 120 words.", None),
        # A limit on a count of marks has no value after it.
        ("Use at most 2 emojis on Instagram.", None),
    ],
)
def test_a_rule_that_bounds_a_value_says_what_it_allows(rule, allowed):
    from verilore.check import bound_rule

    found = bound_rule(rule)
    assert (found.allowed if found else None) == allowed


def test_a_promise_past_the_limit_is_a_finding_in_any_unit():
    lines = [("brand/rules.md", DELIVERY)]
    late = _check("Order today and it is delivered in 24 hours.", lines)
    assert [(f.kind, f.quote, f.expected) for f in late.findings] == [
        ("bound", "24 hours", "48 hours or more")
    ]
    assert late.findings[0].detail == (
        "The draft says 24 hours, and an approved rule allows only 48 hours or more."
    )
    assert late.findings[0].claim_id == "line-0"
    assert [f.quote for f in _check("Delivered to your door in 1 day.", lines).findings] == [
        "1 day"
    ]
    assert _check("Delivered in 3 days.", lines).ok
    assert _check("Delivery in 48 hours.", lines).ok
    # Not about delivery: the rule says nothing about it.
    assert _check("Our new cafe opens in 24 hours.", lines).ok


def test_a_value_over_a_cap_is_one_finding_not_also_a_made_up_one():
    lines = [("brand/offers.md", DISCOUNT)]
    over = _check("A 40% discount on every bag.", lines)
    assert [(f.kind, f.quote) for f in over.findings] == [("bound", "40%")]
    assert _check("A 20% discount on every bag.", lines, supported_by=["20% off"]).ok


def test_the_instruction_says_what_the_rule_allows():
    from verilore.check import render_feedback

    feedback = render_feedback(
        _check("Delivered in 24 hours.", [("brand/rules.md", DELIVERY)])
    ).splitlines()
    assert feedback[1] == (
        "- Remove 24 hours, or change it to a value the rule allows (48 hours or more). "
        f"Approved rule: {DELIVERY}"
    )


def test_one_word_banned_in_two_documents_is_one_instruction():
    """A Word guide and a Markdown file both ban "premium", worded differently."""
    from verilore.check import render_feedback

    lines = [
        ("brand/rules.md", 'Never use the word "premium".'),
        ("brand/voice-guide.docx", "Never use the word premium."),
    ]
    result = _check("Our premium Estate Blend.", lines)
    assert [(f.kind, f.quote, f.path, f.also) for f in result.findings] == [
        ("banned", "premium", "brand/rules.md", ("brand/voice-guide.docx",))
    ]
    assert render_feedback(result).count('Remove "premium"') == 1
