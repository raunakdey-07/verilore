"""What a rule bans, at its edges (RULES-2).

Team 052 found four ways `check` read a rule wrong. Each is decided here by
data where there was a choice:

* **"Write X, not Y".** "Use bold, not cold" banned "cold": a spelling
  similarity of 0.75 counted. The third review proposed banning Y only when it
  has X's letters once case, spaces, hyphens and full stops are gone. On 66
  pairs a rule should ban (GOV.UK's A to Z among them) and 57 it should not,
  the similarity banned 46 and 27 of the 57; the letters alone banned 25 and
  none; the letters or one listed spelling alternation (colour, organise,
  adviser, travelled) ban 57 and none. The last 28 of each list were written
  after the alternations were chosen; one pattern was then corrected
  (judgement), and the list is otherwise as first written.
* **"Such as".** A list names words to avoid only when the rule is about
  words, and then in any case; it ends where the rule goes on.
* **Plurals.** The review proposed no plural under five letters, so that
  "lead" does not find "leads". GOV.UK's own words to avoid include "land"
  ("lands" is the same word), and "leads", "works", "plans" and "costs" are
  forms of the word banned, not other words. The floor stays at four letters;
  a "y" now also finds "ies" (synergy, synergies).
* **Channel names.** "IG", "insta", "X", "LI", "FB", "YT" and "TT" name
  their channels where a channel is named: the channel a draft is for, and a
  channel's own line. Never in a sentence.
"""

from __future__ import annotations

import pytest

from verilore import check
from verilore.check import banned_text, check_draft, fallback_channel

SHOULD_BAN = [
    ("adviser", "advisor"),
    ("settlor", "settler"),
    ("curriculums", "curricula"),
    ("grams", "grammes"),
    ("USA", "US"),
    ("email", "e-mail"),
    ("checkbox", "check box"),
    ("data set", "dataset"),
    ("frontend", "front-end"),
    ("frontend", "front end"),
    ("per cent", "percent"),
    ("username", "user name"),
    ("webchat", "web chat"),
    ("web server", "webserver"),
    ("helpdesk", "help desk"),
    ("changelog", "change log"),
    ("metadata", "meta data"),
    ("life cycle", "lifecycle"),
    ("subdomain", "sub-domain"),
    ("GHz", "Ghz"),
    ("WhatsApp", "Whatsapp"),
    ("Mailchimp", "MailChimp"),
    ("OK", "okay"),
    ("colour", "color"),
    ("organise", "organize"),
    ("travelled", "traveled"),
    ("towards", "toward"),
    ("al-Qa'ida", "al-Qaeda"),
    ("zero-hours contract", "zero-hour contract"),
    ("cannot", "can't"),
    ("sign-up", "signup"),
    ("realise", "realize"),
    ("programme", "program"),
    ("catalogue", "catalog"),
    ("judgement", "judgment"),
    ("learnt", "learned"),
    ("fulfil", "fulfill"),
    ("enrol", "enroll"),
    # Written after the design was chosen.
    ("theatre", "theater"),
    ("analyse", "analyze"),
    ("behaviour", "behavior"),
    ("defence", "defense"),
    ("modelling", "modeling"),
    ("cancelled", "canceled"),
    ("dialogue", "dialog"),
    ("spelt", "spelled"),
    ("burnt", "burned"),
    ("mould", "mold"),
    ("licence", "license"),
    ("e.g.", "eg"),
    ("co-operate", "cooperate"),
    ("log in", "login"),
    ("Ltd.", "Ltd"),
    ("instalment", "installment"),
    ("skilful", "skillful"),
    ("centre", "center"),
    ("paediatric", "pediatric"),
    ("manoeuvre", "maneuver"),
    ("grey", "gray"),
    ("lite", "light"),
    ("organisation", "organization"),
    ("apologise", "apologize"),
    ("neighbour", "neighbor"),
    ("percent", "per-cent"),
    ("hashtag", "hash tag"),
    ("start-up", "startup"),
]
#: Missed, so the rule goes to "Needs a reviewer" (a miss is shown; a false
#: ban is not): plurals, contractions, abbreviations, other words.
MISSED = {
    ("curriculums", "curricula"),
    ("USA", "US"),
    ("OK", "okay"),
    ("al-Qa'ida", "al-Qaeda"),
    ("zero-hours contract", "zero-hour contract"),
    ("cannot", "can't"),
    ("manoeuvre", "maneuver"),
    ("grey", "gray"),
    ("lite", "light"),
}
SHOULD_NOT_BAN = [
    ("bold", "cold"),
    ("warm", "firm"),
    ("clear", "clever"),
    ("simple", "simplistic"),
    ("sentence case", "title case"),
    ("confident", "arrogant"),
    ("friendly", "familiar"),
    ("playful", "silly"),
    ("concise", "curt"),
    ("helpful", "pushy"),
    ("expert", "exclusive"),
    ("inform", "inflame"),
    ("direct", "blunt"),
    ("human", "humane"),
    ("smart", "smug"),
    ("calm", "clam"),
    ("proud", "loud"),
    ("bright", "brash"),
    ("witty", "wordy"),
    ("bold", "brash"),
    ("modern", "modish"),
    ("short", "shorter"),
    ("active", "passive"),
    ("fun", "funny"),
    ("kind", "kindly"),
    ("sell", "yell"),
    ("care", "dare"),
    ("plan", "plain"),
    ("serve", "sever"),
    # Written after the design was chosen.
    ("smart", "smarmy"),
    ("playful", "childish"),
    ("confident", "cocky"),
    ("warm", "soppy"),
    ("casual", "careless"),
    ("loud", "lewd"),
    ("sure", "surely"),
    ("plain", "plane"),
    ("lose", "loose"),
    ("advice", "advise"),
    ("practice", "practise"),
    ("complement", "compliment"),
    ("stationary", "stationery"),
    ("affect", "effect"),
    ("principal", "principle"),
    ("honest", "harsh"),
    ("brief", "abrupt"),
    ("clever", "cleverer"),
    ("crisp", "crispy"),
    ("kind", "unkind"),
    ("formal", "informal"),
    ("expert", "expat"),
    ("helpful", "hopeful"),
    ("useful", "used"),
    ("clear", "cleared"),
    ("simple", "sample"),
    ("trust", "truest"),
    ("bold", "boldly"),
]


@pytest.mark.parametrize("right,wrong", SHOULD_BAN)
def test_another_spelling_of_the_same_word_is_banned(right, wrong):
    assert check._spelled_alike(right, wrong) is ((right, wrong) not in MISSED)


@pytest.mark.parametrize("right,wrong", SHOULD_NOT_BAN)
def test_another_word_is_not(right, wrong):
    assert not check._spelled_alike(right, wrong)


@pytest.mark.parametrize(
    "rule",
    [
        "Use bold, not cold.",
        "Write warm, not firm.",
        "Sound clear, not clever.",
        "Keep it simple, not simplistic.",
        "Use sentence case, not title case.",
    ],
)
def test_a_tone_is_not_a_word_to_ban(rule):
    """Team 052's pins: these go to "Needs a reviewer"."""
    assert banned_text(rule) == []


@pytest.mark.parametrize(
    "rule,banned",
    [
        ("Write website, not web site.", [("text", "web site")]),
        ("Write per cent, not percent.", [("text", "percent")]),
        ("Write adviser, not advisor.", [("text", "advisor")]),
        ("Write colour, not color.", [("text", "color")]),
        (
            "Write frontend, not front-end or front end.",
            [("text", "front-end"), ("text", "front end")],
        ),
    ],
)
def test_a_spelling_rule_names_what_it_bans(rule, banned):
    assert banned_text(rule) == banned


@pytest.mark.parametrize(
    "rule,banned",
    [
        # Team 052: people and campaigns are not words to avoid.
        ("Never target vulnerable audiences, such as NHS patients.", []),
        ("Retire legacy campaigns, such as Summer Sale 2025, from the homepage.", []),
        # Words, in any case, to where the rule goes on.
        (
            "Retire clichés, such as leverage, synergy and game-changer, in customer emails.",
            [("text", "leverage"), ("text", "synergy"), ("text", "game-changer")],
        ),
        (
            "Retire overused puns, such as Eggcellent and Hey presto.",
            [("text", "Eggcellent"), ("text", "Hey presto")],
        ),
        (
            "Avoid jargon such as KPI, ROI and B2B — spell them out.",
            [("text", "KPI"), ("text", "ROI"), ("text", "B2B")],
        ),
        (
            "Never use words such as cheap or bargain; say affordable.",
            [("text", "cheap"), ("text", "bargain")],
        ),
        ("Retire overused puns, such as those about eggs.", []),
    ],
)
def test_such_as_lists_words_only_in_a_rule_about_words(rule, banned):
    assert banned_text(rule) == banned


@pytest.mark.parametrize(
    "rule,banned",
    [
        ("Do not use 'click'; use 'select'.", [("text", "click")]),
        ('Never say "cheap" - say "affordable".', [("text", "cheap")]),
        ("Don't write 'utilise', write 'use'.", [("text", "utilise")]),
        ("Avoid 'going forward'; say 'from now on' instead.", [("text", "going forward")]),
        ("Never use 'premium' or 'luxury'.", [("text", "premium"), ("text", "luxury")]),
    ],
)
def test_what_to_write_instead_is_not_banned(rule, banned):
    """Found by the false-positive suite: 'select' and 'affordable' were banned."""
    assert banned_text(rule) == banned


def _quotes(draft, lines, **kwargs):
    current = {
        "corpus": "kit",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": "brand/voice.md"}
            for n, claim in enumerate(lines)
        ],
    }
    result = check_draft(draft, current, unsupported=False, **kwargs)
    return [(f.kind, f.quote) for f in result.findings]


def test_a_y_word_finds_its_ies_plural():
    rule = ["Retire clichés, such as leverage, synergy and game-changer, in customer emails."]
    assert _quotes("Unlock synergies.", rule) == [("banned", "synergies")]


@pytest.mark.parametrize("draft,quote", [("The bill lands in May.", "lands"), ("Land it.", "Land")])
def test_a_four_letter_word_still_finds_its_plural(draft, quote):
    assert _quotes(draft, ["Never use the word 'land'."]) == [("banned", quote)]


def test_a_three_letter_word_does_not():
    assert _quotes("Weigh the pros and cons.", ["Never use the word 'pro'."]) == []


CHANNELS = [
    "Instagram: Length: 120 characters at most.",
    "Twitter: Length: 100 characters at most.",
    "LinkedIn: Length: 200 characters at most.",
    "When a channel is not listed here, follow the email rules.",
    "Email: Length: 400 characters at most.",
]
LONG = "word " * 100


@pytest.mark.parametrize(
    "channel,limit",
    [
        ("IG", "120"),
        ("insta", "120"),
        ("IG Reels", "120"),
        ("X", "100"),
        ("X (Twitter)", "100"),
        ("LI post", "200"),
        ("TikTok", "400"),
    ],
)
def test_a_short_channel_name_finds_its_channel(channel, limit):
    current = {
        "corpus": "kit",
        "current_memories": [
            {"id": f"c{n}", "claim": claim, "path": "brand/channels.md"}
            for n, claim in enumerate(CHANNELS)
        ],
    }
    result = check_draft(LONG, current, channel=channel, unsupported=False)
    assert [f.expected for f in result.findings if f.kind == "limit"] == [limit]
    assert bool(result.rules_from) is (channel == "TikTok")


def test_a_letter_in_a_sentence_is_not_a_channel():
    lines = ["X marks the spot on every map we print.", *CHANNELS]
    assert fallback_channel([{"claim": line} for line in lines], "TikTok") == "email"
    assert fallback_channel([{"claim": line} for line in lines], "Inbox") == "email"
