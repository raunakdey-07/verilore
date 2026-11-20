"""A correct price is not called wrong because a sibling line has another (v0.12.1).

Team 052's evaluation found that `check` compared "Monzo Perks costs £9 a
month." with "Monzo Extra costs £3 a month." and reported the £9 as wrong. A
statement counted as being about a line when it shared most of the line's
subject words, and "Monzo" and "month" outvoted "Perks" against "Extra". The
check never asked whether another approved line states the drafted value, and
it reported one quote once per sibling line. It flagged all three correct
prices Haiku wrote, and `write` would have told the model to change them.

Now a word every price line shares weighs little, a value any line about the
statement states is correct, and a wrong value is one finding, against the line
the statement names best.
"""

from __future__ import annotations

import pytest

from verilore.check import check_draft

MONZO = [
    "Monzo Extra costs £3 a month.",
    "Monzo Perks costs £9 a month.",
    "Monzo Max costs £19 a month, with a 3-month minimum term.",
]
MAILCHIMP = [
    "The Free plan costs $0 a month and sends up to 500 emails a month.",
    "The Essentials plan costs $13 a month and sends up to 5,000 emails a month.",
    "The Standard plan costs $20 a month and sends up to 6,000 emails a month.",
    "The Premium plan costs $350 a month and sends up to 150,000 emails a month.",
]


def _current(lines, path="brand/plans.md"):
    return {
        "corpus": "plans",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": path} for n, claim in enumerate(lines)
        ],
    }


def _check(draft, lines):
    return check_draft(draft, _current(lines))


def _kinds(result):
    return [(f.kind, f.quote) for f in result.findings]


@pytest.mark.parametrize("line", MONZO + MAILCHIMP)
def test_an_approved_line_repeated_word_for_word_passes(line):
    result = _check(line, MONZO + MAILCHIMP)
    assert result.ok, _kinds(result)


@pytest.mark.parametrize(
    "draft",
    [
        # The three correct prices Haiku wrote with Verilore's brief.
        "Upgrade to Standard: it's $20 a month and sends up to 6,000 emails a month.",
        "Get Monzo Perks for £9 a month.",
        "Monzo Max starts at £19 a month, with a 3-month minimum term.",
        "Perks is £9 a month. Extra is £3 a month.",
    ],
)
def test_a_correct_price_for_one_plan_is_not_compared_with_another(draft):
    result = _check(draft, MONZO + MAILCHIMP)
    assert result.ok, _kinds(result)


def test_an_old_price_is_one_finding_against_the_line_it_is_about():
    result = _check("Monzo Perks costs £5 a month.", MONZO)
    assert _kinds(result) == [("number", "£5")]
    assert result.findings[0].claim == "Monzo Perks costs £9 a month."
    assert result.findings[0].expected == "£9"


def test_another_plans_price_is_still_wrong_for_this_plan():
    result = _check("Monzo Perks costs £3 a month.", MONZO)
    assert _kinds(result) == [("number", "£3")]
    assert result.findings[0].claim == "Monzo Perks costs £9 a month."


def test_a_wrong_price_on_a_price_list_names_the_right_plan():
    result = _check("The Standard plan is now $14.99 a month.", MAILCHIMP)
    assert _kinds(result) == [("number", "$14.99")]
    assert result.findings[0].expected == "$20"


def test_a_price_for_another_period_is_another_price():
    result = _check("Monzo Perks costs £9 a year.", MONZO)
    assert _kinds(result) == [("number", "£9 a year")]
    assert result.findings[0].expected == "£9 a month"
    assert _check("Monzo Perks costs £9.", MONZO).ok


def test_a_statement_that_names_no_plan_is_not_compared_with_one():
    """'Monzo' and 'month' are on every line: they name no plan."""
    result = check_draft("Monzo costs £12 a month.", _current(MONZO), unsupported=False)
    assert result.ok, _kinds(result)
