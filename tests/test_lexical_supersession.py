"""Lexical recall answers a question about a decision that was replaced (RECALL-1).

Lexical relevance drops the words every candidate shares before it ranks: in a
corpus where every claim says the project's name, the name tells claims apart no
better than "the". But the candidates include the claims a decision replaced, and
a replaced claim shares its subject with its replacement by design. In a corpus
whose only live line was a replacement, the subject itself was dropped:
"How often does the support rota run?" ranked "The support rota now runs
fortnightly." at zero and answered that no memory matched. With any unrelated
second line in the corpus it answered.

Lexical relevance is what runs when the model cannot load, and what
`VERILORE_LEXICAL=1` chooses, so this is the path a low-memory host takes.
"""

from __future__ import annotations

import os
import uuid

import pytest
from typer.testing import CliRunner


def _cli(*args):
    from verilore.cli.main import app

    env = {**os.environ, "VERILORE_LEXICAL": "1", "VERILORE_RUNTIME": "0"}
    result = CliRunner().invoke(app, list(args), env=env)
    return result.exit_code, result.output


@pytest.fixture
def corpus():
    name = f"rota-{uuid.uuid4().hex[:10]}"
    code, out = _cli("corpus", "create", name)
    assert code == 0, out
    return name


def test_the_replacement_answers_when_it_is_the_only_live_line(corpus):
    _cli("remember", "The support rota runs weekly.", "--key", "rota", "--corpus", corpus)
    _cli(
        "remember",
        "The support rota now runs fortnightly.",
        "--key",
        "rota",
        "--corpus",
        corpus,
    )
    code, out = _cli("recall", "How often does the support rota run?", "--corpus", corpus)
    assert code == 0, out
    assert "fortnightly" in out
    assert "NO_RELEVANT_MEMORY" not in out


def test_a_question_about_something_else_still_abstains(corpus):
    _cli("remember", "The support rota runs weekly.", "--key", "rota", "--corpus", corpus)
    _cli(
        "remember",
        "The support rota now runs fortnightly.",
        "--key",
        "rota",
        "--corpus",
        corpus,
    )
    code, out = _cli("recall", "What is our refund window?", "--corpus", corpus)
    assert "fortnightly" not in out, out


def test_remember_does_not_suggest_replacing_the_line_it_just_replaced(corpus):
    _cli("remember", "The support rota runs weekly.", "--key", "rota", "--corpus", corpus)
    code, out = _cli(
        "remember",
        "The support rota now runs fortnightly.",
        "--key",
        "rota",
        "--corpus",
        corpus,
    )
    assert code == 0, out
    # The weekly line was retired by this write under the same key; offering it
    # as a "live claim that reads like this one" told the user to supersede a
    # line that was already history.
    assert "already read like this one" not in out, out
