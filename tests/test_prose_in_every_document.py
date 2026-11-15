"""Ordinary paragraphs become memory, in every document (#158).

A brand's voice and a campaign's message are written as sentences. Before
v0.12 a paragraph was read only when the document had no bullet at all, and
then only for sentences holding a word such as "must" or "never"; in a document
with one bullet every paragraph was dropped without a word. The lines a team
cared about most were the ones that never reached a prompt.

What is held here: every sentence that states something is a claim and its own
evidence; a question, a lead-in and a fragment are not; a paragraph takes the
state its heading declares; a document or a server can opt out.
"""

from __future__ import annotations

import httpx
import pytest

from live_server import live_server  # noqa: F401,F811  module-scoped server fixture
from verilore import Verilore
from verilore.api.services.markdown_claims import _chunks, extract

DIWALI = """# Diwali brief

## Facts

- Orders close on 5 November 2026.
- The gift box costs Rs 1,499.

## Message

We are selling the ritual of brewing together, and the discount is not the headline.
"""

VOICE = """# Voice

We sound like a friend who happens to know a lot about coffee. We let the facts carry
the feeling, so there are no superlatives and no exclamation marks in body copy.
They care where the coffee comes from but they are not experts.

What do our customers want most? They want to be told plainly, e.g. the roast date
and the farm. Dr. Rao signs off every origin note.

The rules below apply to every channel:

Thanks, team.
"""


def _read(body: str, **kwargs):
    claims, warnings = extract(body, _chunks(body), **kwargs)
    return [claim["claim"] for claim in claims], claims, warnings


def test_a_paragraph_beside_bullets_is_memory_too():
    texts, _claims, warnings = _read(DIWALI)
    assert texts == [
        "Orders close on 5 November 2026.",
        "The gift box costs Rs 1,499.",
        "We are selling the ritual of brewing together, and the discount is not the headline.",
    ]
    assert warnings == []


def test_every_sentence_that_states_something_is_a_claim_and_a_question_is_not():
    texts, claims, warnings = _read(VOICE)
    assert texts == [
        "We sound like a friend who happens to know a lot about coffee.",
        "We let the facts carry the feeling, so there are no superlatives and no "
        "exclamation marks in body copy.",
        "They care where the coffee comes from but they are not experts.",
        # "e.g." and "Dr." do not end a sentence.
        "They want to be told plainly, e.g. the roast date and the farm.",
        "Dr. Rao signs off every origin note.",
    ]
    # The question, the lead-in that ends in a colon and the two-word sign-off
    # state nothing, and nothing was lost by leaving them out.
    assert warnings == []
    # A claim is one line; its evidence is the sentence exactly as written,
    # line break included, so it can be found byte for byte in the source.
    wrapped = claims[1]
    assert "\n" not in wrapped["claim"] and "\n" in wrapped["evidence"]
    assert all(claim["evidence"] in VOICE for claim in claims)
    assert all(claim["extraction_mode"] == "prose" for claim in claims)


def test_a_paragraph_takes_the_state_its_heading_declares():
    body = (
        "# Voice\n\nOur voice is warm, plain and direct.\n\n"
        "## Draft\n\nLead every caption with the discount.\n"
    )
    _texts, claims, _warnings = _read(body)
    states = {claim["claim"]: claim.get("info_state") for claim in claims}
    assert states == {
        "Our voice is warm, plain and direct.": None,
        "Lead every caption with the discount.": "draft",
    }


def test_rules_mode_matches_phrases_whole():
    """ "do not" is one signal. Neither "do" nor "not" is one by itself."""
    body = (
        "# Voice\n\nThey care where the coffee comes from but they are not experts.\n"
        "Do not open captions with a question. We never use the word premium.\n"
    )
    texts, _claims, warnings = _read(body, prose="rules")
    assert texts == [
        "Do not open captions with a question.",
        "We never use the word premium.",
    ]
    assert [(w.code, w.count) for w in warnings] == [("prose_not_extracted", 1)]


def test_a_document_or_a_server_can_turn_prose_off(monkeypatch):
    assert _read(DIWALI, prose="off")[0] == _read(DIWALI, prose=False)[0]
    assert len(_read(DIWALI, prose="off")[0]) == 2
    monkeypatch.setenv("VERILORE_PROSE", "off")
    assert len(_read(DIWALI)[0]) == 2
    # The document's own setting wins over the server's.
    assert len(_read(DIWALI, prose="all")[0]) == 3


def test_an_unknown_mode_is_named_and_reads_as_the_default():
    texts, _claims, warnings = _read(DIWALI, prose="sometimes")
    assert len(texts) == 3
    assert [(w.code, w.field) for w in warnings] == [("unknown_prose_mode", "prose")]


def test_a_field_after_a_finished_sentence_is_still_a_field():
    body = "# Launch\n\nThe launch details are below.\nDate: 14 March 2027\nOffer: a free helmet\n"
    texts, _claims, _warnings = _read(body)
    assert texts == ["Date: 14 March 2027", "Offer: a free helmet", "The launch details are below."]


@pytest.mark.parametrize(
    "sentence,kept",
    [
        ("हम ग्राहक से कभी झूठ नहीं बोलते।", True),  # a danda ends a sentence
        ("क्या आपको कॉफ़ी पसंद है?", False),
        ("Never use emojis.", True),
        ("See below.", False),
        ("A caption with no full stop is read when it is long enough", True),
        ("Short tagline here", False),
    ],
)
def test_what_counts_as_a_statement(sentence, kept):
    texts, _claims, _warnings = _read(f"# Notes\n\n{sentence}\n")
    assert texts == ([sentence] if kept else [])


def test_a_run_on_is_not_one_statement_and_is_reported():
    """Sixty words is the limit: past it a "sentence" is a block nobody can check."""
    run_on = " ".join(["word"] * 61) + "."
    texts, _claims, warnings = _read(f"# Notes\n\nOur voice is warm and plain.\n\n{run_on}\n")
    assert texts == ["Our voice is warm and plain."]
    assert [(w.code, w.count) for w in warnings] == [("prose_not_extracted", 1)]
    assert "too long" in warnings[0].hint


def test_the_message_reaches_the_brief_and_a_new_sentence_keeps_every_other_key(
    live_server,  # noqa: F811
):
    corpus, key = live_server.corpora["globex"], live_server.keys["globex"]

    def ingest(content: str) -> None:
        resp = httpx.post(
            f"{live_server.url}/api/ingest/file",
            json={"content": content, "path": "campaigns/diwali/brief.md", "corpus": corpus},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text

    vl = Verilore(corpus, base_url=live_server.url, api_key=key, timeout=5, retries=1)
    ingest(DIWALI)
    brief = vl.memory.brief(path_prefix="campaigns/diwali")
    assert (
        "- We are selling the ritual of brewing together, and the discount is not the "
        "headline." in brief.text.splitlines()
    )
    before = {claim.claim: claim.key for claim in vl.memory.current().current_memories}

    ingest(DIWALI.replace("## Message\n\n", "## Message\n\nGifting is the reason to buy. "))
    after = {claim.claim: claim.key for claim in vl.memory.current().current_memories}
    assert "Gifting is the reason to buy." in after
    assert {text: after[text] for text in before} == before
