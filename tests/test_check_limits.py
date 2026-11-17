"""A draft longer than its channel allows, or with more hashtags, is a finding (LIMIT-1).

A brand kit's channel table is the most exact rule in it ("Instagram: Length:
150 characters; Hashtags: 3 at most") and the one a model breaks most: it
writes 300 characters and five hashtags. Counting is exact, so `check` counts,
for the channel the draft is for.
"""

from __future__ import annotations

import pytest

TABLE = [
    "Instagram: Length: 150 characters; Emojis: 2 at most; Hashtags: 3 at most",
    "Email: Length: 200 words; Emojis: none; Hashtags: none",
    "Keep LinkedIn posts under 120 words.",
    "Blog posts run about 800 words.",
    "Always end an Instagram caption with the estate name in capitals.",
]


def _current(lines=TABLE):
    return {
        "corpus": "saffron",
        "current_memories": [
            {"id": f"row-{n}", "claim": line, "path": "brand/channels.md"}
            for n, line in enumerate(lines)
        ],
    }


def _check(draft, channel=None):
    from verilore.check import check_draft

    return check_draft(draft, _current(), channel=channel, unsupported=False)


@pytest.mark.parametrize(
    "line,expected",
    [
        (TABLE[0], ("Instagram", {"characters": 150, "emojis": 2, "hashtags": 3})),
        (TABLE[1], ("Email", {"words": 200, "emojis": 0, "hashtags": 0})),
        (TABLE[2], ("LinkedIn", {"words": 120})),
        ("Use at most 2 emojis on Instagram.", ("Instagram", {"emojis": 2})),
        # A habit, not a limit; a rule with no number; a line with no channel.
        (TABLE[3], (None, {})),
        (TABLE[4], (None, {})),
        ("Price: Rs 520 for a 250 g tin.", (None, {})),
        ("Each channel has its own length and its own limits.", (None, {})),
    ],
)
def test_what_a_line_limits_is_read_only_when_it_says_so(line, expected):
    from verilore.check import channel_limits

    assert channel_limits(line) == expected


def test_a_caption_over_the_channel_limits_gets_one_finding_per_limit():
    caption = "Saffron season is here. " * 7 + "#tea #kahwa #winter #saffron 🍵🍵🍵"
    result = _check(caption, channel="Instagram")
    assert [(f.kind, f.quote, f.expected) for f in result.findings] == [
        ("limit", f"{len(caption)} characters", "150"),
        ("limit", "3 emojis", "2"),
        ("limit", "4 hashtags", "3"),
    ]
    assert result.findings[0].detail == (
        f"The draft has {len(caption)} characters; Instagram allows at most 150."
    )
    within = "Saffron season is here. 15% off Kahwa. #tea #kahwa 🍵 HALMARI"
    assert _check(within, channel="Instagram").ok


def test_limits_are_for_the_channel_named_and_only_when_one_is():
    long_post = " ".join(["word"] * 150)
    assert [f.quote for f in _check(long_post, channel="LinkedIn post").findings] == ["150 words"]
    assert _check(long_post, channel="Email newsletter").ok
    # Without a channel there is nothing to count against.
    assert _check(long_post).ok
    email = "Hello #winter 🍵"
    assert sorted(f.quote for f in _check(email, channel="Email").findings) == [
        "1 emoji",
        "1 hashtag",
    ]


def test_the_instructions_say_how_much_to_cut():
    from verilore.check import render_feedback

    caption = "x" * 180 + " #a #b #c #d"
    lines = render_feedback(_check(caption, channel="Instagram")).splitlines()
    assert lines[1] == (
        f"- Shorten the draft to at most 150 characters; it has {len(caption)}. "
        f"Approved: {TABLE[0]}"
    )
    assert lines[2] == f"- Use at most 3 hashtags; it has 4. Approved: {TABLE[0]}"
    email = render_feedback(_check("Hi 🍵", channel="Email"))
    assert f"- Remove every emoji; it has 1. Approved: {TABLE[1]}" in email


def test_a_ban_on_a_kind_of_mark_asks_for_every_one_to_go():
    """Told "remove #tea", a model removes #tea and keeps the other three."""
    from verilore.check import check_draft, render_feedback

    current = _current(["We never use hashtags on LinkedIn."])
    feedback = render_feedback(check_draft("New tin. #tea #kahwa", current, channel="LinkedIn"))
    assert "- Remove every hashtag (such as #tea)." in feedback
