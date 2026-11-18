"""`review` lists lines that name a date already past, for a person to end (REVIEW-2).

"Orders close on 5 November 2026" was in Team 052's brief on 17 November. A
line stops being served on its `valid_until`, but a real campaign brief rarely
has one. Nothing should end a line on its own, because "Founded on 12 June
1998" is history, not a deadline. `review` now lists every approved line whose
latest full date has passed, so a person can give it an end, reject it, or mark
it settled.
"""

from __future__ import annotations

import json
from datetime import date

TODAY = date(2026, 11, 17)

LINES = [
    ("campaigns/diwali/brief.md", "Orders close on 5 November 2026."),
    ("campaigns/diwali/brief.md", "The offer ends on 30 November 2026."),
    ("campaigns/winter/brief.md", "The offer runs from 1 November 2026 to 30 November 2026."),
    ("campaigns/launch/brief.md", "Launch: 2026-10-01"),
    ("campaigns/winter/brief.md", "The sale ends on 31 January."),
    ("brand/story.md", "Kaveri was founded in 1998."),
    ("brand/story.md", "Kaveri opened its first café on 12 June 1998."),
    ("campaigns/new-year/brief.md", "Orders close on 28 December 2026."),
]


def _claims(lines=LINES, **extra):
    return [
        {"id": f"c{n:02d}" + "0" * 10, "claim": text, "path": path, **extra}
        for n, (path, text) in enumerate(lines)
    ]


def test_a_line_whose_latest_date_has_passed_is_listed_with_that_date():
    from verilore.review import past_dates

    assert [(line["claim"], line["date"]) for line in past_dates(_claims(), today=TODAY)] == [
        ("Orders close on 5 November 2026.", "5 November 2026"),
        ("Launch: 2026-10-01", "2026-10-01"),
        ("Kaveri opened its first café on 12 June 1998.", "12 June 1998"),
    ]


def test_a_line_that_already_has_an_end_is_not_listed():
    from verilore.review import past_dates

    ended = _claims(LINES[:1], valid_until="2026-11-06T00:00:00Z")
    assert past_dates(ended, today=TODAY) == []


def test_the_review_lists_them_counts_them_and_lets_a_person_settle_one():
    from verilore.review import build_review, render_review, render_review_html

    current = {"corpus": "kaveri", "current_memories": _claims()}
    review = build_review(current, today=TODAY)
    assert len(review.past) == 3 and review.open_items == 3
    text = render_review(review)
    assert "Dates that have passed (3): still served as approved." in text
    assert "  - Orders close on 5 November 2026.  [campaigns/diwali/brief.md, c00000000000]" in text
    assert "valid_until" in text
    assert "Dates that have passed" in render_review_html(review)
    assert json.loads(json.dumps(review.as_dict()))["past"][0]["date"] == "5 November 2026"

    history = review.past[2]["id"]
    settled = build_review(current, today=TODAY, settled=[history])
    assert [line["id"] for line in settled.past] == [line["id"] for line in review.past[:2]]
    assert settled.settled == 1 and settled.open_items == 2
