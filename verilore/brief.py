# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""A brief: approved memory as a few plain lines, ready for a model's prompt.

`pack` is the interchange format. It carries every id, offset and quote a
receiving system needs to verify a claim, and that costs room: fifty one-line
rules measured 98,644 characters as a pack and 5,066 as the lines themselves.
A model writing copy needs the lines, not the proof.

A brief is those lines. It asks no question, so there is no wording to get
wrong: it is everything current and approved inside the scope the caller named.
Drafts, rejected statements and replaced versions are already withheld by
`current`, which is where a brief gets its claims, so nothing here decides what
is true. This module only renders, and when the scope holds more than fits it
decides what to keep, in an order anyone can predict:

1. Rules first. A line that says never, must, always or do not, a line under a
   heading such as "Never" or "Legal", and every line under a path the caller
   named in `must`, are kept before anything else.
2. Then what the task is about. With `task="Instagram caption for Diwali"` the
   remaining lines are ranked by the words they share with the task, their
   heading and their file, and the least related are the ones left out.
3. Without a task, in the order the documents list them.

    from verilore import Verilore

    vl = Verilore("trailhead", base_url=URL, api_key=KEY)
    brief = vl.memory.brief(
        path_prefix=["brand", "campaigns/spring"],
        must=["brand"],
        task="Instagram caption for the spring launch",
    )
    prompt = f"{brief.text}\\n\\nWrite an Instagram caption for the spring launch."

The proof is not lost. `brief.claim_ids` names every claim the text carries, in
order, so the same answer can be fetched with evidence (`evidence`), frozen
(`snapshot`) or checked later (`revalidate`).

Standard library only, like `verilore.pack`, so it can be copied into another
project and fed the JSON of a `current` response.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

__all__ = [
    "Brief",
    "render_brief",
    "approx_tokens",
    "is_rule",
    "DEFAULT_MAX_CHARS",
    "MIN_MAX_CHARS",
]

#: Room for roughly sixty one-line rules. About 1,500 tokens of English.
DEFAULT_MAX_CHARS = 6000

#: Below this there is no room for the header, one line and the footer.
MIN_MAX_CHARS = 400

#: The label remembered statements are filed under, instead of a generated path.
SAVED = "Saved decisions"


@dataclass(frozen=True)
class Brief:
    """Approved memory, rendered. `str(brief)` is the text."""

    text: str
    corpus: str
    scope: tuple[str, ...] = ()
    #: The claims the text carries, in the order their lines appear.
    claim_ids: tuple[str, ...] = ()
    #: Current claims left out because the size limit was reached.
    omitted: int = 0
    #: How many of the omitted lines were rules. Not zero means the limit is too
    #: small for this scope: narrow the scope or raise the limit.
    omitted_rules: int = 0
    #: Claims the corpus holds but does not vouch for, by state.
    withheld: dict[str, int] = field(default_factory=dict)
    #: Keys whose sources disagree. Both sides are shown, neither is chosen.
    conflicts: int = 0
    #: Approved lines whose `valid_until` has passed. Counted, never quoted.
    expired: int = 0
    #: What the brief was ranked for, when a task was given.
    task: str | None = None

    @property
    def kept(self) -> int:
        return len(self.claim_ids)

    @property
    def approx_tokens(self) -> int:
        """An estimate of the text's size in model tokens. See `approx_tokens`."""
        return approx_tokens(self.text)

    def __str__(self) -> str:
        return self.text


def approx_tokens(text: str) -> int:
    """Roughly how many model tokens a text is. An estimate, on the safe side.

    Four characters to a token for ASCII, which is what English averages across
    current tokenizers, and one token for every other character, which
    overstates most scripts. No tokenizer is installed or needed: every model
    family counts differently, and a budget should err towards fitting.
    """
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return math.ceil(ascii_chars / 4) + (len(text) - ascii_chars)


def _get(item: Any, name: str, default: Any = None) -> Any:
    """Read a field from a pydantic model or from the JSON it serializes to."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _one_line(text: Any) -> str:
    """A claim is one sentence; a wrapped source line must not break the list."""
    return " ".join(str(text).split())


def _scope(path_prefix: str | Iterable[str] | None) -> tuple[str, ...]:
    if path_prefix is None:
        return ()
    if isinstance(path_prefix, str):
        return (path_prefix,)
    return tuple(path_prefix)


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    """Whether a path is one of these folders or files, or inside one."""
    for prefix in prefixes:
        clean = prefix.strip("/")
        if clean and (path == clean or path.startswith(clean + "/")):
            return True
    return False


# --------------------------------------------------------------------- rules

#: Words that make a sentence a rule rather than a fact or a remark. Matched
#: whole, so "do not" is one phrase and "notable" is nothing.
_RULE_WORDS = re.compile(
    r"(?<![\w'])(?:never|must(?: not)?|always|do not|don't|cannot|can't|may not|"
    r"not allowed|prohibited|forbidden|required|avoid)(?![\w'])",
    re.IGNORECASE,
)
#: A heading that opens with one of these puts every line under it first.
_RULE_HEADINGS = (
    "never",
    "must",
    "always",
    "do not",
    "don't",
    "dos and don'ts",
    "do's and don'ts",
    "rules",
    "mandatory",
    "required",
    "non-negotiable",
    "legal",
    "compliance",
)


def is_rule(text: str, heading: str | None = None) -> bool:
    """Whether a line is a rule: by its own words, or by the heading above it."""
    if _RULE_WORDS.search(text or ""):
        return True
    for part in (heading or "").split(" > "):
        low = " ".join(part.strip().lower().split())
        if any(low == word or low.startswith(word + " ") for word in _RULE_HEADINGS):
            return True
    return False


# ------------------------------------------------------------------- ranking

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
#: Words a task is phrased in, which say nothing about what it is about.
_STOP = frozenset(
    "a an and are as at be by for from i in into is it its me my of on or our "
    "please that the their them this to us we with you your "
    "write writing draft create make generate give new one some short long".split()
)


def _stem(word: str) -> str:
    """Enough to match "captions" to "caption" and "launching" to "launch"."""
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> set[str]:
    return {
        _stem(word)
        for word in (match.group(0).lower() for match in _WORD.finditer(text or ""))
        if word not in _STOP and (len(word) > 1 or word.isdigit())
    }


def _scores(task: str, entries: list[dict[str, Any]]) -> list[float]:
    """How much each entry has to do with the task: shared words, rare ones count more.

    An entry is its sentence, its heading and its path, so "Instagram" in the
    task finds the Instagram row of a channel table and every line of a file
    under `channels/instagram`. Lexical on purpose: it needs no model, runs
    where the brief is rendered, and is the same on every machine.
    """
    wanted = _terms(task)
    if not wanted or not entries:
        return [0.0] * len(entries)
    bags = [
        _terms(f'{entry["sentence"]} {entry["heading"] or ""} {" ".join(entry["paths"])}')
        for entry in entries
    ]
    frequency = {term: sum(1 for bag in bags if term in bag) for term in wanted}
    total = len(bags)
    weight = {term: math.log(1 + total / count) for term, count in frequency.items() if count}
    return [sum(weight[term] for term in wanted & bag if term in weight) for bag in bags]


# ----------------------------------------------------------------- rendering


def _label(path: str) -> str:
    """What a group of lines is headed with: the document, or "Saved decisions".

    A remembered statement lives in a generated file whose name is a hash. It
    is about eighty characters the model cannot use, so its lines are grouped
    under one plain label, with the scope it was filed under when it has one.
    """
    parts = path.split("/")
    if len(parts) >= 2 and parts[-2] == "memory":
        scope = "/".join(parts[:-2])
        return f"{SAVED} ({scope})" if scope else SAVED
    return path or "(no source)"


def _expired(claim: Any, now: datetime) -> bool:
    until = _get(claim, "valid_until")
    if until is None:
        return False
    if isinstance(until, str):
        try:
            until = datetime.fromisoformat(until.replace("Z", "+00:00"))
        except ValueError:
            return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until <= now


def render_brief(
    response: Any,
    *,
    path_prefix: str | Iterable[str] | None = None,
    max_chars: int | None = None,
    max_tokens: int | None = None,
    task: str | None = None,
    must: str | Iterable[str] | None = None,
    now: datetime | None = None,
) -> Brief:
    """Render a `current` response (the model, or its JSON as a dict) as a brief.

    `path_prefix` is only named in the header. Scoping already happened in the
    request that produced `response`; passing a different value here changes
    the label, not the contents.

    Lines are grouped under the document they come from, in the order the
    response lists them. The same sentence held by two documents is one line.
    The size limit is `max_chars` (6,000 by default) or `max_tokens`, an
    estimate (see `approx_tokens`); give one, not both. When the limit is
    reached the lines left out are counted and the last line says so: a brief
    never ends mid-sentence, and it never drops lines silently.

    What is kept when not everything fits: rules first (`is_rule`, and every
    line under a path in `must`), then the lines most related to `task`, then
    the rest in document order. A line whose `valid_until` has passed is left
    out and counted in `expired`.
    """
    if max_chars is not None and max_tokens is not None:
        raise ValueError("give max_chars or max_tokens, not both")
    if max_tokens is not None:
        limit = int(max_tokens)
        floor = math.ceil(MIN_MAX_CHARS / 4)
        if limit < floor:
            raise ValueError(f"max_tokens must be at least {floor}")
        size = approx_tokens
    else:
        limit = DEFAULT_MAX_CHARS if max_chars is None else int(max_chars)
        if limit < MIN_MAX_CHARS:
            raise ValueError(f"max_chars must be at least {MIN_MAX_CHARS}")
        size = len

    corpus = str(_get(response, "corpus", ""))
    scope = _scope(path_prefix)
    always = _scope(must)
    moment = now or datetime.now(timezone.utc)
    conflicts = list(_get(response, "conflicts", []) or [])
    disputed = {_get(claim, "id") for group in conflicts for claim in _get(group, "claims", [])}
    withheld = {
        str(state): int(count)
        for state, count in sorted((_get(response, "withheld_counts", None) or {}).items())
        if count
    }
    headings: dict[str, str] = {}
    for evidence in _get(response, "evidence", []) or []:
        heading = _get(evidence, "heading")
        if heading:
            headings.setdefault(str(_get(evidence, "claim_id")), str(heading))

    # One entry per distinct sentence, in first-seen order.
    entries: list[dict[str, Any]] = []
    by_sentence: dict[str, dict[str, Any]] = {}
    # The service leaves out what had expired when it answered and counts it;
    # anything that expired between then and now is counted here.
    expired = int(_get(response, "expired_count", 0) or 0)
    for claim in _get(response, "current_memories", []) or []:
        claim_id = str(_get(claim, "id"))
        if claim_id in disputed:
            continue
        sentence = _one_line(_get(claim, "claim", ""))
        if not sentence:
            continue
        if _expired(claim, moment):
            expired += 1
            continue
        entry = by_sentence.get(sentence)
        if entry is None:
            entry = by_sentence[sentence] = {
                "sentence": sentence,
                "paths": [],
                "ids": [],
                "heading": headings.get(claim_id),
                "position": len(entries),
            }
            entries.append(entry)
        path = str(_get(claim, "path", ""))
        if path and path not in entry["paths"]:
            entry["paths"].append(path)
        entry["ids"].append(claim_id)

    for entry in entries:
        entry["label"] = _label(entry["paths"][0] if entry["paths"] else "")
        entry["rule"] = is_rule(entry["sentence"], entry["heading"]) or any(
            _under(path, always) for path in entry["paths"]
        )

    # The order lines are offered room in. Not the order they are printed in.
    relevance = _scores(task, entries) if task else [0.0] * len(entries)
    offered = sorted(
        entries,
        key=lambda entry: (
            not entry["rule"],
            -relevance[entry["position"]],
            entry["position"],
        ),
    )

    where = f', scope {" + ".join(scope)}' if scope else ""
    header = [
        f'Approved memory for "{corpus}"{where}.',
        "Every line below is current and approved. Drafts, rejected and replaced "
        "statements are not included. Do not contradict these lines.",
    ]
    conflict_lines: list[str] = []
    if conflicts:
        conflict_lines = ["", "Sources disagree on these. Do not pick a side; say they disagree:"]
        for group in conflicts:
            sides = "  |  ".join(
                f'{_one_line(_get(claim, "claim", ""))} [{_get(claim, "path", "")}]'
                for claim in _get(group, "claims", [])
            )
            conflict_lines.append(f"- {sides}")

    total = sum(len(entry["ids"]) for entry in entries)
    total_rules = sum(len(entry["ids"]) for entry in entries if entry["rule"])

    def footer(kept: list[dict[str, Any]]) -> list[str]:
        kept_claims = sum(len(entry["ids"]) for entry in kept)
        kept_rules = sum(len(entry["ids"]) for entry in kept if entry["rule"])
        omitted = total - kept_claims
        parts = []
        if withheld or expired:
            held = [f"{count} {state}" for state, count in withheld.items()]
            if expired:
                held.append(f"{expired} expired")
            parts.append(f'Not included: {", ".join(held)}.')
        if omitted:
            rules = total_rules - kept_rules
            which = f", {rules} of them rules" if rules else ""
            least = " The lines least related to the task went first." if task else ""
            parts.append(f"Left out for length: {omitted} more approved lines{which}.{least}")
        return ["", " ".join(parts)] if parts else []

    def body(kept: list[dict[str, Any]]) -> list[str]:
        """The kept lines under their documents, both in the response's own order."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for entry in sorted(kept, key=lambda entry: entry["position"]):
            groups.setdefault(entry["label"], []).append(entry)
        lines: list[str] = []
        for label, members in groups.items():
            lines += ["", label]
            lines += [f'- {entry["sentence"]}' for entry in members]
        return lines

    def render(kept: list[dict[str, Any]]) -> str:
        lines = body(kept)
        if not lines and not conflict_lines:
            lines = ["", "(no approved memory in this scope)"]
        return "\n".join(header + lines + conflict_lines + footer(kept))

    kept: list[dict[str, Any]] = []
    for entry in offered:
        if size(render(kept + [entry])) > limit:
            break
        kept.append(entry)

    printed = sorted(kept, key=lambda entry: entry["position"])
    order: dict[str, list[dict[str, Any]]] = {}
    for entry in printed:
        order.setdefault(entry["label"], []).append(entry)
    kept_ids = [
        claim_id for members in order.values() for entry in members for claim_id in entry["ids"]
    ]
    return Brief(
        text=render(kept),
        corpus=corpus,
        scope=scope,
        claim_ids=tuple(kept_ids),
        omitted=total - len(kept_ids),
        omitted_rules=total_rules - sum(len(e["ids"]) for e in kept if e["rule"]),
        withheld=withheld,
        conflicts=len(conflicts),
        expired=expired,
        task=task or None,
    )
