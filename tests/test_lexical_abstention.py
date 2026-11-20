"""Lexical recall does not answer a question about something the corpus never names (v0.12.1).

Team 052's evaluation ran in lexical mode (`VERILORE_LEXICAL=1`), and
`test_recall_returns_nothing_from_another_organisation` failed there. Asked
about beta's "Nimbus router", alpha's corpus answered with its own Kestrel
battery: the question shared `private`, `product` and `7q2` with alpha's canary,
and token overlap cannot tell scaffolding from a subject. It was not a leak --
the fact was the asker's own -- but it was an answer to a question the corpus
cannot answer. Semantic ranking abstains there.

Now, in lexical mode, a question that names something (a capitalised word
after the first, or an identifier) that no claim mentions abstains unless a
claim matched it strongly. Questions whose named things the corpus knows are
answered as before.
"""

from __future__ import annotations

import uuid

import pytest

FACTS = {
    "alpha_battery": "ALPHA_PRIVATE_PRODUCT_FACT_7Q2 the Kestrel battery lasts 41 hours.",
    "alpha_campaign": "ALPHA_PRIVATE_CAMPAIGN_FACT_9M4 the spring launch targets coastal schools.",
    "linkedin": "LinkedIn posts are at most 120 words.",
    "backups": "Backups run nightly at 02:00 UTC and are retained for 35 days.",
}


@pytest.mark.parametrize(
    "question,named",
    [
        ("How long can a LinkedIn post be?", {"linkedin"}),
        ("What is the X200 battery life?", {"x200"}),
        ("Can we use emojis?", set()),
        # The first word is capitalised because it starts the sentence.
        ("Kestrel battery life?", set()),
        ("BETA_7Q2 the Nimbus router", {"beta", "q2", "nimbu"}),
    ],
)
def test_the_words_that_name_something(question, named):
    from verilore.api.services.memory_relevance import named_terms

    assert named_terms(question) == named


@pytest.fixture(scope="module")
def memory():
    import os

    from verilore import Verilore

    previous = os.environ.get("VERILORE_LEXICAL")
    os.environ["VERILORE_LEXICAL"] = "1"
    try:
        client = Verilore(f"lexical-abstain-{uuid.uuid4().hex[:10]}")
        for key, fact in FACTS.items():
            client.memory.remember(fact, key=key, state="approved")
        yield client.memory
    finally:
        if previous is None:
            os.environ.pop("VERILORE_LEXICAL", None)
        else:
            os.environ["VERILORE_LEXICAL"] = previous


def _answer(memory, question):
    return [c.claim for c in memory.recall(question).current_memories]


def test_a_question_about_another_organisations_product_abstains(memory):
    question = "BETA_PRIVATE_PRODUCT_FACT_7Q2 the Nimbus router has four mesh bands."
    assert _answer(memory, question) == []


def test_a_question_about_something_the_corpus_names_is_still_answered(memory):
    assert FACTS["alpha_battery"] in _answer(memory, "How long does the Kestrel battery last?")
    assert FACTS["linkedin"] in _answer(memory, "How long can a LinkedIn post be?")
    assert FACTS["backups"] in _answer(memory, "How often do we run backups?")
