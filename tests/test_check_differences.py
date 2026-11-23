"""A difference or a discount is checked as one, not as a wrong price (NUM-2).

Team 052 found that "Save £3 on Monzo Perks" and "£2 cheaper than Monzo Max"
were compared with Perks's price and called wrong. Two designs were compared
on the drafts below, written before either was run:

* a window of three words either side of a value, with the cue words "save",
  "off", "extra", "plus", "cashback", "more", "cheaper" and others;
* only the words right beside the value, with "extra" and "plus" read in lower
  case: "Monzo Extra £3" and "Monzo Plus: £5" are names and prices.

On these drafts main scored 20 of 32 (13 false findings), the window 13 and
the adjacent words 18: the window read "Monzo Extra", "Monzo Plus" and "1%
cashback" as discounts and stopped checking their prices. With the adjacent
reading and what was then found missing (each side of a "than" checked on its
own, a limit on discounts read as one, a difference compared with the two
lines it compares, a price's own clause as its subject) the score is 32 of 32,
and 23 of 25 on a held-out set of two other kits, written afterwards; main
scored 18 of 25 there. The two held-out misses are still reported, as a value
no line states.
"""

from __future__ import annotations

import pytest

from verilore.check import check_draft

MONZO = [
    "Monzo Extra costs £3 a month.",
    "Monzo Plus costs £5 a month.",
    "Monzo Perks costs £9 a month.",
    "Monzo Max costs £19 a month, with a 3-month minimum term.",
    "Monzo Max includes 1% cashback on groceries.",
    "Never offer more than 10% off any plan.",
]
SAAS = [
    "The Free plan costs $0 a month and sends up to 500 emails a month.",
    "The Essentials plan costs $13 a month and sends up to 5,000 emails a month.",
    "The Standard plan costs $20 a month and sends up to 6,000 emails a month.",
    "The Premium plan costs $350 a month and sends up to 150,000 emails a month.",
    "Annual billing saves 15% on any paid plan.",
    "Never promise a discount above 20%.",
]
TEA = [
    "Assam Gold costs Rs 520 for a 250 g tin.",
    "Darjeeling First Flush costs Rs 780 for a 100 g tin.",
    "Shipping is free on orders above Rs 999.",
    "Orders below Rs 999 pay Rs 79 for shipping.",
    "Never discount the house blend by more than 15%.",
]


def _found(draft, lines):
    current = {
        "corpus": "kit",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": "kit.md"} for n, claim in enumerate(lines)
        ],
    }
    return {(f.kind, f.quote) for f in check_draft(draft, current).findings}


TRUE = [
    # Differences and discounts that are true.
    "Monzo Perks is £10 cheaper than Monzo Max.",
    "Monzo Perks (£9) is £10 cheaper than Monzo Max (£19).",
    "Upgrade to Monzo Max for just £10 more a month than Perks.",
    "Monzo Extra costs £3 a month, £6 less than Perks.",
    "It's an extra £6 a month to go from Extra to Perks.",
    "Monzo Plus is £2 more than Monzo Extra.",
    "Get 10% off Monzo Perks this month.",
    "Save 10% on Monzo Max this spring.",
    # Prices that are true, beside words that can also mean a difference.
    "Monzo Extra costs £3 a month.",
    "Monzo Plus: £5 a month.",
    "Monzo Extra, now just £3 a month.",
    "Monzo Plus costs £5 a month and Monzo Perks costs £9 a month.",
    "Monzo Max costs £19 a month and includes 1% cashback on groceries.",
    "Meet Monzo Perks, our favourite tier. It costs £9 a month.",
    "Monzo Perks costs £9 a month, plus you get a railcard.",
]


@pytest.mark.parametrize("draft", TRUE)
def test_a_true_difference_or_price_passes(draft):
    assert _found(draft, MONZO) == set()


WRONG = [
    ("Monzo Perks costs £8 a month.", {("number", "£8")}),
    # The pin from the third review: the wrong price in brackets is caught, and
    # the difference beside it is left alone.
    ("Monzo Perks (£8) is £10 cheaper than Monzo Max (£19).", {("number", "£8")}),
    ("Monzo Perks (£9) is £10 cheaper than Monzo Max (£21).", {("number", "£21")}),
    # A limit on discounts that names no plan is about every discount.
    ("Save 25% on Monzo Perks.", {("bound", "25%")}),
    ("Get 20% off Monzo Max.", {("bound", "20%")}),
    ("Monzo Extra costs £4 a month.", {("number", "£4")}),
    ("Monzo Extra, now just £4 a month.", {("number", "£4")}),
    ("Monzo Plus: £6 a month.", {("number", "£6")}),
    ("Monzo Plus £6 a month, Monzo Extra £3.", {("number", "£6")}),
    # A discount no line approves is made up, and says so.
    ("Save £7 on Monzo Perks.", {("unsupported", "£7")}),
    ("Save 5% on Monzo Max.", {("unsupported", "5%")}),
    ("Monzo Max includes 2% cashback on groceries.", {("number", "2%")}),
    # Team 052's #9 and #10, kept.
    ("Monzo Extra costs £9 and Monzo Perks costs £3.", {("number", "£9"), ("number", "£3")}),
    ("Meet Monzo Perks, our favourite tier. It costs £5 a month.", {("number", "£5")}),
    ("Monzo Perks costs £9 a year.", {("number", "£9 a year")}),
    # A difference that is wrong: Max is £10 more than Perks.
    ("Monzo Max is £12 more than Monzo Perks.", {("number", "£12")}),
    ("Monzo Perks is £7 cheaper than Monzo Max.", {("number", "£7")}),
]


@pytest.mark.parametrize("draft,found", WRONG)
def test_a_wrong_price_difference_or_discount_is_found(draft, found):
    assert _found(draft, MONZO) == found


def test_a_wrong_difference_says_what_the_two_lines_give():
    current = {
        "corpus": "kit",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": "kit.md"} for n, claim in enumerate(MONZO)
        ],
    }
    (finding,) = check_draft("Monzo Max is £12 more than Monzo Perks.", current).findings
    assert finding.expected == "£10"
    assert "£19" in finding.detail and "£9" in finding.detail


HELD_OUT = [
    (SAAS, "Standard is $7 more a month than Essentials.", set()),
    (SAAS, "Go Premium for $330 more than Standard each month.", set()),
    (SAAS, "Pay annually and save 15% on Standard.", set()),
    (SAAS, "Essentials costs $13 a month, which is $7 less than Standard.", set()),
    (SAAS, "Standard plan: $20 a month for up to 6,000 emails.", set()),
    (SAAS, "Upgrade from Free to Essentials for an extra $13 a month.", set()),
    (SAAS, "Save 20% with our spring offer on Essentials.", set()),
    (SAAS, "Premium sends up to 150,000 emails a month.", set()),
    (SAAS, "Standard is $9 more a month than Essentials.", {("number", "$9")}),
    (SAAS, "The Essentials plan costs $15 a month.", {("number", "$15")}),
    (SAAS, "Annual billing saves 25% on any paid plan.", {("number", "25%")}),
    (SAAS, "Get Premium for $300 a month.", {("number", "$300")}),
    (SAAS, "Save $50 on Premium this month.", {("unsupported", "$50")}),
    (SAAS, "Essentials, now just $11 a month.", {("number", "$11")}),
    (SAAS, "Our Standard plan is great. It's $25 a month.", {("number", "$25")}),
    # One word names Premium; two are needed, so the difference is reported
    # as a value no line states rather than as the wrong difference.
    (SAAS, "Premium is $300 more than Standard.", {("unsupported", "$300")}),
    (TEA, "Darjeeling First Flush is Rs 260 more than Assam Gold.", set()),
    (TEA, "Free shipping on orders above Rs 999.", set()),
    (TEA, "Assam Gold: Rs 520 for 250 g.", set()),
    (TEA, "Take 10% off the house blend this week.", {("unsupported", "10%")}),
    (TEA, "Assam Gold costs Rs 560 for a 250 g tin.", {("number", "Rs 560")}),
    (TEA, "Free shipping on orders above Rs 799.", {("number", "Rs 799")}),
    (TEA, "Darjeeling First Flush is Rs 300 more than Assam Gold.", {("number", "Rs 300")}),
    (TEA, "Take 25% off the house blend.", {("bound", "25%")}),
    # A third price beside one the line states is a price no line states
    # (`test_a_fact_with_two_values_agrees_with_a_draft_that_repeats_either`).
    (TEA, "Orders below Rs 999 pay Rs 99 for shipping.", {("unsupported", "Rs 99")}),
]


@pytest.mark.parametrize("lines,draft,found", HELD_OUT)
def test_two_kits_the_design_was_not_tuned_on(lines, draft, found):
    assert _found(draft, lines) == found


def test_a_price_is_about_its_own_clause():
    """ "Monzo Max costs £19 a month, with a 3-month minimum term": "minimum" and
    "term" outweighed "Max", and "Monzo Max costs £21 a month" named no line."""
    found = _found("Monzo Max costs £21 a month.", MONZO)
    assert found == {("number", "£21")}


def test_a_long_plan_name_does_not_pull_a_price_to_another_plan():
    """Team 052's #11, kept: each line's score is the share of its own words."""
    lines = [
        "Acme Basic costs £5 a month.",
        "Acme Pro costs £12 a month.",
        "Acme Pro student plan costs £6 a month.",
        "Acme Team costs £20 a month.",
        "Acme Enterprise costs £50 a month.",
    ]
    assert _found("Acme Pro student plan costs £6 a month.", lines) == set()
    assert _found("Acme Pro costs £12 a month.", lines) == set()
