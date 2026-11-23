"""In lexical recall a day or a month is not a name (LEX-2).

LEX-1 abstains when a question names something no claim mentions, and reads a
name from a capital after the first word. "On Monday, can we post to LinkedIn
with hashtags?" named "Monday", which the kit never says, and abstained
(Team 052, #19).

Five ways to read a name were measured against the same corpora on forty
questions written first (eight groups of five: twenty to answer, twenty to
abstain on), sixteen held out on two other kits, and ten that open with an
ordinary noun ("Weight of the Trailhead 2?"):

    v0.12.1: a capital after the first word       32/40  13/16  10/10
    A: an absent word, and only common words met  34/40  14/16   9/10
    the first word too, days and months not       35/40  13/16   9/10
    B: not in an English word list, or a capital  36/40  13/16  10/10
    v0.12.1 with days and months not (this)       33/40  13/16  10/10

A abstained on "How heavy is the Trailhead 2?" and "Weight of the Trailhead
2?"; the first-word rule on the second. B, the third review's design with the
capitals and days kept, scored best, but the only English list on hand
(Hunspell's en_US, from SCOWL) lacks "discount", "delivery", "reset" and
"ads", so it would abstain where a kit says those words another way. It waits
for a list that has them, measured on these same questions. None of the 24
hard-kit questions LEX-1 was checked on changed its answer. Embedding mode is
not touched.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "question,named",
    [
        ("On Monday, can we post to LinkedIn?", {"linkedin"}),
        ("Is the offer on in March?", set()),
        ("Does the Kestrel battery ship on Friday?", {"kestrel"}),
        # Still names: a capital that is not a day or a month.
        ("Do UK prices include GST?", {"uk", "gst"}),
    ],
)
def test_a_day_or_a_month_is_not_a_name(question, named):
    from verilore.api.services.memory_relevance import named_terms

    assert named_terms(question) == named


@pytest.fixture(scope="module")
def memory():
    from verilore import Verilore

    previous = {
        name: os.environ.get(name) for name in ("VERILORE_LEXICAL", "VERILORE_INGEST_ROOTS")
    }
    os.environ["VERILORE_LEXICAL"] = "1"
    os.environ["VERILORE_INGEST_ROOTS"] = str(ROOT)
    try:
        client = Verilore(f"lexical-names-{uuid.uuid4().hex[:10]}")
        client.sync(str(ROOT / "benchmarks" / "governed_context" / "hard" / "kit"))
        yield client.memory
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.mark.parametrize(
    "question,claim",
    [
        ("On Monday, can we post to LinkedIn with hashtags?", "LinkedIn: Length: 120 words"),
        ("How long can a LinkedIn post be?", "LinkedIn: Length: 120 words"),
        ("Can I use emojis on Instagram?", "Instagram: Length: 150 characters"),
        ("Do UK prices include GST?", "Prices include GST"),
    ],
)
def test_a_question_with_a_day_in_it_is_answered(memory, question, claim):
    answers = [m.claim for m in memory.recall(question).current_memories]
    assert any(claim in answer for answer in answers), answers


@pytest.mark.parametrize(
    "question",
    [
        "Nimbus router pricing?",
        "What does the Kestrel battery cost on Monday?",
        "Who is our CEO?",
    ],
)
def test_a_name_the_kit_never_uses_still_abstains(memory, question):
    assert memory.recall(question).current_memories == []
