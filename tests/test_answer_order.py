"""The same kit gives the same answers, whatever database it was synced into (#38).

Claims that score the same and were stored in one transaction were put in the
order of their ids, which are random. A recall's answer is cut to a budget, so
the order decided which of them the reader got: synced twice, the hard kit
answered 6 of these 24 questions differently in lexical mode, one with a
different set of lines ("Who is the winter campaign for?"). Ties now follow
the claims' keys, paths and text, which follow the documents.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "What is the winter offer?",
    "Does the winter offer apply to gift boxes?",
    "What is the FSSAI licence number?",
    "Do prices include GST?",
    "How should we address the reader?",
    "What does our voice sound like?",
    "Which words must we never use?",
    "How much is shipping on small orders?",
    "When is shipping free?",
    "How long is an Instagram caption?",
    "How many hashtags can an Instagram post have?",
    "What must every WhatsApp message include?",
    "Who can we send WhatsApp messages to?",
    "Can we tag a competitor on Instagram?",
    "Can we compare our prices with a competitor?",
    "Can we use customer photos?",
    "What estate does Darjeeling First Flush come from?",
    "What is in Kashmiri Kahwa?",
    "How hot should the water be for Kashmiri Kahwa?",
    "Can we say tea cures illness?",
    "How do we write prices?",
    "What should the winter campaign lead with?",
    "Who is the winter campaign for?",
    "What is the headline?",
]


@pytest.fixture(scope="module")
def answers():
    from verilore import Verilore

    previous = {
        name: os.environ.get(name) for name in ("VERILORE_LEXICAL", "VERILORE_INGEST_ROOTS")
    }
    os.environ["VERILORE_LEXICAL"] = "1"
    os.environ["VERILORE_INGEST_ROOTS"] = str(ROOT)
    try:
        runs = []
        for _ in range(3):
            client = Verilore(f"answer-order-{uuid.uuid4().hex[:10]}")
            client.sync(str(ROOT / "benchmarks" / "governed_context" / "hard" / "kit"))
            runs.append(
                [[m.claim for m in client.memory.recall(q).current_memories] for q in QUESTIONS]
            )
        yield runs
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.mark.parametrize("index", range(len(QUESTIONS)), ids=QUESTIONS)
def test_three_databases_give_one_answer(answers, index):
    first, *others = (run[index] for run in answers)
    for other in others:
        assert other == first
