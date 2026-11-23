"""A false-positive suite: ordinary copy, a real style guide's rules (#37).

`check` is wrong in two ways. A miss is shown: the rule it could not test goes
to "Needs a reviewer". A false finding is not: it tells a writer, or the model
`write` drives, to change a correct sentence. So this suite holds copy that
follows the rules, written to sit close to them ("advise" beside "adviser",
"cold" beside "bold", "select" beside "click", NHS patients beside a rule that
names them), and copy that breaks them.

The rules are GOV.UK's, from its A to Z style guide and its words to avoid,
written as a kit would write them. Contains public sector information
licensed under the Open Government Licence v3.0. The brand rules are Team
052's. On main, the clean copy below drew 6 false findings ("select", "from
now on", "cold", "NHS patients", "Summer Sale 2025"), and 11 of the 19
breaches were missed; now none, and none. The suite was written alongside
the fixes, and found one of them: the word to write instead was banned too.

Copy under a licence that cannot be committed (Mailchimp's style guide is CC
BY-NC) can be run locally: `python scripts/check_copy.py KIT.md DRAFTS/`.
"""

from __future__ import annotations

import pytest

from verilore.check import check_draft

GOV_UK = [
    "Write adviser, not advisor.",
    "Write checkbox, not check box.",
    "Write data set, not dataset.",
    "Write frontend, not front-end or front end.",
    "Write per cent, not percent.",
    "Write username, not user name.",
    "Write webchat, not web chat.",
    "Write helpdesk, not help desk.",
    "Write metadata, not meta data.",
    "Write life cycle, not lifecycle or life-cycle.",
    "Write email, not e-mail.",
    "Write WhatsApp, not Whatsapp.",
    "Write GHz, not Ghz.",
    "Write colour, not color.",
    "Write organise, not organize.",
    "Write cannot, not can't.",
    "Do not use 'click'; use 'select'.",
    "Avoid 'going forward'; say 'from now on' instead.",
    (
        "Avoid words such as agenda, collaborate, empower, facilitate, leverage, robust, "
        "streamline and utilise."
    ),
    "Use sentence case, not title case.",
]
TEAM_052 = [
    "Use bold, not cold.",
    "Write warm, not firm.",
    "Sound clear, not clever.",
    "Keep it simple, not simplistic.",
    "Never target vulnerable audiences, such as NHS patients.",
    "Retire legacy campaigns, such as Summer Sale 2025, from the homepage.",
    "Retire clichés, such as leverage, synergy and game-changer, in customer emails.",
]
RULES = GOV_UK + TEAM_052

CLEAN = [
    "We advise you to ask an adviser at the helpdesk if you cannot sign in with your username.",
    "Tick the checkbox to confirm your email address, then select Continue.",
    "The data set covers the full life cycle of each service.",
    "Use webchat or WhatsApp to talk to us. Our frontend team updated the metadata.",
    "Interest rises by 2 per cent from April.",
    "On a cold morning, a firm handshake and a clever idea still count.",
    "NHS patients can claim help with travel costs.",
    "Summer Sale 2025 results are in the annual report.",
    "Choose the colour you want and organise your documents.",
    "The radio uses 5 GHz.",
    "Select the right option from the list, from now on.",
    "Our simple guide explains when to use title case for names.",
    "Plan your journey, check the costs and lead your team.",
    "Write to us at our helpdesk in plain, warm words.",
]


def _found(draft):
    current = {
        "corpus": "style",
        "current_memories": [
            {"id": f"rule-{n}", "claim": claim, "path": "style.md"} for n, claim in enumerate(RULES)
        ],
    }
    result = check_draft(draft, current, unsupported=False)
    return sorted(f.quote for f in result.findings)


@pytest.mark.parametrize("draft", CLEAN)
def test_copy_that_follows_the_rules_draws_nothing(draft):
    assert _found(draft) == []


BREACHES = [
    ("Contact an advisor at the help desk.", ["advisor", "help desk"]),
    ("Send us an e-mail or use web chat.", ["e-mail", "web chat"]),
    ("Tick the check box and click Continue.", ["check box", "click"]),
    ("Rates rise by 2 percent.", ["percent"]),
    ("Our robust plan will streamline delivery.", ["robust", "streamline"]),
    ("We leverage synergies to empower teams.", ["empower", "leverage", "synergies"]),
    ("Pick a color and organize your files.", ["color", "organize"]),
    ("Message us on Whatsapp.", ["Whatsapp"]),
    ("Going forward, enter your user name.", ["Going forward", "user name"]),
    ("It's a game-changer for our front-end.", ["front-end", "game-changer"]),
]


@pytest.mark.parametrize("draft,quotes", BREACHES)
def test_copy_that_breaks_them_is_found(draft, quotes):
    assert _found(draft) == sorted(quotes)


#: Four-letter words whose plural is the same word, beside the floor that lets a
#: banned four-letter word find its plural ("land", "lands"). No rule in these
#: kits bans them, and none of them is found.
HOMOGRAPHS = [
    "Our plans: one lead, two leads, three plans.",
    "Plan the work; the works team leads, and it costs less than it cost.",
    "Leads come from plans that work.",
]


@pytest.mark.parametrize("draft", HOMOGRAPHS)
def test_four_letter_words_and_their_plurals_draw_nothing(draft):
    assert _found(draft) == []


@pytest.mark.parametrize("draft", HOMOGRAPHS)
def test_nor_on_a_pricing_kit(draft):
    from verilore.check import check_draft

    lines = [
        "Monzo Extra costs £3 a month.",
        "Monzo Plus costs £5 a month.",
        "Never offer more than 10% off any plan.",
        "Never call a plan 'cheap'.",
    ]
    current = {
        "corpus": "pricing",
        "current_memories": [
            {"id": f"p{n}", "claim": c, "path": "pricing.md"} for n, c in enumerate(lines)
        ],
    }
    assert list(check_draft(draft, current, unsupported=False).findings) == []
