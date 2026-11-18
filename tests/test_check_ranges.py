"""A channel limit written as a range or a minimum is read (LIMIT-2).

"Hashtags: 5 to 8" is how channel tables are written, and `check` read only
"at most" and "up to": an Instagram draft with twelve hashtags passed. A range
is now a maximum and a minimum, "at least" is a minimum, and a draft with too
few is a finding too, with an instruction to add.
"""

from __future__ import annotations

import pytest

ROW = "Instagram: Length: 100–150 characters; Emojis: 1 to 2; Hashtags: 5 to 8"


def _current(lines):
    return {
        "corpus": "kaveri",
        "current_memories": [
            {"id": f"row-{n}", "claim": line, "path": "brand/channels.md"}
            for n, line in enumerate(lines)
        ],
    }


def _check(draft, lines=(ROW,), channel="Instagram"):
    from verilore.check import check_draft

    return check_draft(draft, _current(list(lines)), channel=channel, unsupported=False)


@pytest.mark.parametrize(
    "line,most",
    [
        (ROW, ("Instagram", {"characters": 150, "emojis": 2, "hashtags": 8})),
        ("Instagram: Hashtags: 5-8", ("Instagram", {"hashtags": 8})),
        ("Use between 3 and 5 hashtags on Instagram.", ("Instagram", {"hashtags": 5})),
        ("Instagram: Hashtags: 0 to 3", ("Instagram", {"hashtags": 3})),
        ("Keep LinkedIn posts between 80 and 120 words.", ("LinkedIn", {"words": 120})),
        # A minimum alone has no maximum to report here.
        ("Use at least 3 hashtags on Instagram.", (None, {})),
        # A range in a sentence that does not say it is a limit is a habit.
        ("Blog posts run 600 to 800 words.", (None, {})),
    ],
)
def test_the_maximum_of_a_range_is_the_channels_limit(line, most):
    from verilore.check import channel_limits

    assert channel_limits(line) == most


@pytest.mark.parametrize(
    "line,least",
    [
        (ROW, ("Instagram", {"characters": 100, "emojis": 1, "hashtags": 5})),
        ("Use at least 3 hashtags on Instagram.", ("Instagram", {"hashtags": 3})),
        ("Instagram: Hashtags: 3 or more", ("Instagram", {"hashtags": 3})),
        ("Instagram: Hashtags: 0 to 3", (None, {})),
        ("Instagram: Length: 150 characters; Hashtags: 3 at most", (None, {})),
    ],
)
def test_a_range_or_at_least_is_also_a_minimum(line, least):
    from verilore.check import channel_minimums

    assert channel_minimums(line) == least


def test_too_many_and_too_few_are_findings_that_say_what_the_channel_asks_for():
    many = (
        "Brewed slowly in the hills of Coorg and poured for two this Diwali, and every "
        "evening after it. 🍵 " + " ".join(f"#tag{n}" for n in range(12))
    )
    assert len(many) > 150
    result = _check(many)
    assert [(f.kind, f.quote, f.expected) for f in result.findings] == [
        ("limit", f"{len(many.strip())} characters", "150"),
        ("limit", "12 hashtags", "8"),
    ]
    assert result.findings[1].detail == "The draft has 12 hashtags; Instagram allows 5 to 8."

    few = "Brewed slowly in Coorg. #coffee #diwali"
    result = _check(few)
    assert [(f.quote, f.expected) for f in result.findings] == [
        (f"{len(few)} characters", "100"),
        ("0 emojis", "1"),
        ("2 hashtags", "5"),
    ]
    assert result.findings[2].detail == "The draft has 2 hashtags; Instagram asks for 5 to 8."

    within = (
        "Brewed slowly in the hills of Coorg and poured for two, this Diwali and every "
        "evening after. 🍵 #coffee #diwali #coorg #brew #kaveri"
    )
    assert _check(within).ok, [f.detail for f in _check(within).findings]


def test_the_instructions_say_whether_to_add_or_to_cut():
    from verilore.check import render_feedback

    few = "Brewed slowly in Coorg. #coffee #diwali"
    lines = render_feedback(_check(few)).splitlines()
    assert lines[1] == (
        f"- Lengthen the draft to at least 100 characters; it has {len(few)}. Approved: {ROW}"
    )
    assert lines[2] == f"- Use at least 1 emoji; it has 0. Approved: {ROW}"
    assert lines[3] == f"- Use at least 5 hashtags; it has 2. Approved: {ROW}"
    many = render_feedback(_check("x" * 120 + " 🍵 " + "#a " * 9))
    assert f"- Use at most 8 hashtags; it has 9. Approved: {ROW}" in many
