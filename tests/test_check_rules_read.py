"""Rules `check` read as untestable, or not at all, now name what they ban (v0.12.1).

Team 052's evaluation planted 29 violations; `check` missed 8 of them because
it did not read the rule as a ban: "Retire overused puns, such as Eggcellent",
"Never more than one exclamation point at a time", "Write email, not e-mail",
"Write Mailchimp, not MailChimp", "Never use the wand emoji", "Write prices as
Rs 520, never as ₹520.00 or INR 520", a banned word in the plural ("premiums"),
and "When a channel is not listed here, follow the email rules" for a TikTok
draft. Each is exact, so each is now read; a rule that names a style rather
than text ("Use sentence case, not title case") still is not.
"""

from __future__ import annotations

import pytest

from verilore.check import banned_text, check_draft, render_check, render_feedback

RULES = [
    'Never use the word "premium".',
    "Retire overused puns, such as Eggcellent and Hey presto.",
    'Stop using the word "synergy".',
    "Never more than one exclamation point at a time.",
    "Write email, not e-mail.",
    "Write Mailchimp, not MailChimp.",
    "Never use the wand emoji.",
    "Write prices as Rs 520, never as ₹520.00 or INR 520.",
]


def _current(lines, path="brand/voice.md"):
    return {
        "corpus": "kit",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": path} for n, claim in enumerate(lines)
        ],
    }


def _quotes(draft, lines=RULES, **kwargs):
    result = check_draft(draft, _current(lines), unsupported=False, **kwargs)
    return [(f.kind, f.quote) for f in result.findings]


@pytest.mark.parametrize(
    "rule,banned",
    [
        (
            "Retire overused puns, such as Eggcellent and Hey presto.",
            [("text", "Eggcellent"), ("text", "Hey presto")],
        ),
        ('Retire overused puns, such as "Eggcellent".', [("text", "Eggcellent")]),
        ('Stop using the word "synergy".', [("text", "synergy")]),
        ("Stop saying the word synergy.", [("text", "synergy")]),
        ("Never more than one exclamation point at a time.", [("class", "exclamation-run")]),
        ("No double exclamation marks.", [("class", "exclamation-run")]),
        ("Write email, not e-mail.", [("text", "e-mail")]),
        ("Write Mailchimp, not MailChimp.", [("exact", "MailChimp")]),
        ("Never use the wand emoji.", [("text", "\U0001fa84")]),
        ("Never use \U0001f525 in a caption.", [("text", "\U0001f525")]),
        (
            "Write prices as Rs 520, never as ₹520.00 or INR 520.",
            [("currency", "₹"), ("currency", "inr")],
        ),
        # A style, or two words not spelled alike, names no text to look for.
        ("Use sentence case, not title case.", []),
        ("Use British spelling, not American.", []),
        ("Write Rs 520, not Rs 520.00.", []),
        # An emoji name that fits many emojis names none of them.
        ("Never use the face emoji.", []),
        # Retiring a thing is not banning a word.
        ("Retire the winter banner after 1 February.", []),
        ("Retire overused puns, such as those about eggs.", []),
    ],
)
def test_what_a_rule_bans(rule, banned):
    assert banned_text(rule) == banned


@pytest.mark.parametrize(
    "draft,found",
    [
        ("Our premiums are back.", [("banned", "premiums")]),
        ("Eggcellent news for tea lovers.", [("banned", "Eggcellent")]),
        ("Hey presto, the tin is here.", [("banned", "Hey presto")]),
        ("Real synergy.", [("banned", "synergy")]),
        ("It's here!! Order now.", [("banned", "!!")]),
        ("Send us an e-mail.", [("banned", "e-mail")]),
        ("MailChimp makes it easy.", [("banned", "MailChimp")]),
        ("A little magic \U0001fa84 for you.", [("banned", "\U0001fa84")]),
        ("Now ₹520 a tin.", [("banned", "₹520")]),
        ("Now INR 520 a tin.", [("banned", "INR 520")]),
    ],
)
def test_a_draft_that_breaks_one_of_them_is_a_finding(draft, found):
    assert _quotes(draft) == found


def test_the_right_forms_pass():
    draft = "Send us an email! Mailchimp makes it easy. Now Rs 520 a tin. \U0001f375"
    assert _quotes(draft) == []


def test_the_feedback_says_what_to_change_and_keeps_other_emojis():
    result = check_draft("It's here!! A little magic \U0001fa84 \U0001f375", _current(RULES))
    feedback = render_feedback(result)
    assert '- Replace "!!" with a single exclamation mark.' in feedback
    assert '- Remove "\U0001fa84".' in feedback
    assert "every emoji" not in feedback
    assert "two exclamation marks in a row (!!)" in result.findings[0].detail


def test_the_rules_it_reads_are_not_listed_for_a_reviewer():
    result = check_draft("Fine copy.", _current(RULES), unsupported=False)
    assert result.untested == ()


CHANNELS = [
    "Email: Length: at most 50 words.",
    "Never use exclamation marks in emails.",
    "Instagram: Length: 150 characters; Hashtags: at most 3.",
    "When a channel is not listed here, follow the email rules.",
]
LONG = "Big news! " + "word " * 60


def test_a_channel_no_line_names_follows_the_channel_the_kit_says():
    result = check_draft(LONG, _current(CHANNELS, "brand/channels.md"), channel="TikTok")
    assert [(f.kind, f.quote) for f in result.findings] == [
        ("banned", "!"),
        ("limit", "62 words"),
    ]
    assert result.rules_from == "email"
    assert result.as_dict()["rules_from"] == "email"
    assert "the email rules applied" in render_check(result)
    # The line that says so is read, not left for a reviewer.
    assert result.untested == ()


def test_a_listed_channel_keeps_its_own_rules():
    result = check_draft(LONG, _current(CHANNELS, "brand/channels.md"), channel="Instagram")
    assert [(f.kind, f.quote) for f in result.findings] == [("limit", "309 characters")]
    assert result.rules_from == ""


@pytest.mark.parametrize(
    "line",
    [
        "Other channels follow the email rules.",
        "Any channel not listed here uses the email rules.",
        "If a channel isn't listed, apply the email rules.",
    ],
)
def test_other_wordings_of_the_fallback(line):
    lines = [*CHANNELS[:3], line]
    assert check_draft(LONG, _current(lines), channel="TikTok").rules_from == "email"


def test_a_fallback_that_names_no_channel_is_ignored():
    lines = [*CHANNELS[:3], "All channels follow the house rules."]
    result = check_draft(LONG, _current(lines), channel="TikTok", unsupported=False)
    assert result.rules_from == "" and result.ok
