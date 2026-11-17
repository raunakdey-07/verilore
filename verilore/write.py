# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""Write with a model, checked against approved memory, with one chance to fix.

A brief gives a model only the approved lines a task needs. A model still
writes what it writes: a weak one adds a price nobody approved, or keeps a word
a rule bans. `write()` closes the loop without Verilore calling any model
itself:

1. the brief for the task, and one prompt built from it (`compose`);
2. `generate(prompt)`, your model, however you call it;
3. `check` of the draft against the same approved lines;
4. on a finding, `generate` again with the draft and exactly what to change
   (`verilore.check.render_feedback`), up to `retries` times;
5. the draft with the fewest findings, and those findings, for a person.

Verilore stays model-free and costs nothing: `generate` is any function from a
prompt to text. Standard library only, so it imports wherever the SDK does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from verilore.check import Check, render_feedback

__all__ = ["Written", "Attempt", "compose", "revise", "write_with"]

#: How the model is told to use the brief. Every sentence is there because a
#: weak model got it wrong without it: inventing a value the lines do not
#: state, explaining instead of answering, or hedging on rules that are fine.
INSTRUCTIONS = (
    "Use only the approved lines above. If the task needs something they do not "
    "say, leave it out instead of guessing. Do not state a price, percentage or "
    "date unless an approved line states it. Follow every rule in the lines. "
    "Return only the text the task asks for, with no explanation."
)

#: At most this many second chances: each one is a model call, and a draft that
#: still breaks a rule after three is a person's to fix.
MAX_RETRIES = 3


def compose(brief_text: str, task: str) -> str:
    """The prompt for a task: the brief, the task, and how to use the brief."""
    return f"{brief_text.strip()}\n\nTask: {task.strip()}\n\n{INSTRUCTIONS}"


def revise(prompt: str, draft: str, check: Check) -> str:
    """The prompt for a second attempt: the first, the draft, and what to change."""
    return f"{prompt}\n\nYour draft:\n{draft.strip()}\n\n{render_feedback(check)}"


@dataclass(frozen=True)
class Attempt:
    """One call to the model and what the check found in its draft."""

    prompt: str
    draft: str
    check: Check


@dataclass(frozen=True)
class Written:
    """The draft to show a person, and how it was reached."""

    #: The draft with the fewest findings; the latest one on a tie.
    draft: str
    #: Its findings. Empty when the draft passed.
    check: Check
    #: Every call, in order: what the model was given, wrote, and broke.
    attempts: tuple[Attempt, ...]
    #: The brief the first prompt was built from.
    brief: Any = field(repr=False, default=None)

    @property
    def ok(self) -> bool:
        return self.check.ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "draft": self.draft,
            "check": self.check.as_dict(),
            "attempts": [
                {"prompt": a.prompt, "draft": a.draft, "findings": len(a.check.findings)}
                for a in self.attempts
            ],
            "claim_ids": list(getattr(self.brief, "claim_ids", []) or []),
        }


def write_with(
    task: str,
    generate: Callable[[str], str],
    *,
    brief: Any,
    check: Callable[[str], Check],
    retries: int = 1,
) -> Written:
    """The loop itself, given a brief and a `check(draft)` function.

    `MemoryClient.write` supplies both from memory; this is separate so the loop
    can be tested, and reused, without a database.
    """
    if not task or not task.strip():
        raise ValueError("task is required: the brief and the check both depend on it")
    if not callable(generate):
        raise TypeError("generate must be a function from a prompt to the model's text")
    if not 0 <= retries <= MAX_RETRIES:
        raise ValueError(f"retries must be between 0 and {MAX_RETRIES}")
    first = compose(brief.text, task)
    prompt = first
    attempts: list[Attempt] = []
    for _round in range(retries + 1):
        draft = generate(prompt)
        if not isinstance(draft, str):
            raise TypeError("generate returned something that is not text")
        checked = check(draft)
        attempts.append(Attempt(prompt, draft, checked))
        if checked.ok:
            break
        prompt = revise(first, draft, checked)
    best = min(reversed(attempts), key=lambda a: len(a.check.findings))
    return Written(draft=best.draft, check=best.check, attempts=tuple(attempts), brief=brief)
