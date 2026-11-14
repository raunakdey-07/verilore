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
is true. This module only renders.

    from verilore import Verilore

    vl = Verilore("trailhead", base_url=URL, api_key=KEY)
    brief = vl.memory.brief(path_prefix=["brand", "campaigns/spring"])
    prompt = f"{brief.text}\\n\\nWrite an Instagram caption for the spring launch."

The proof is not lost. `brief.claim_ids` names every claim the text carries, in
order, so the same answer can be fetched with evidence (`evidence`), frozen
(`snapshot`) or checked later (`revalidate`).

Standard library only, like `verilore.pack`, so it can be copied into another
project and fed the JSON of a `current` response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = ["Brief", "render_brief", "DEFAULT_MAX_CHARS", "MIN_MAX_CHARS"]

#: Room for roughly sixty one-line rules. About 1,500 tokens of English.
DEFAULT_MAX_CHARS = 6000

#: Below this there is no room for the header, one line and the footer.
MIN_MAX_CHARS = 400


@dataclass(frozen=True)
class Brief:
    """Approved memory, rendered. `str(brief)` is the text."""

    text: str
    corpus: str
    scope: tuple[str, ...] = ()
    #: The claims the text carries, in the order their lines appear.
    claim_ids: tuple[str, ...] = ()
    #: Current claims left out because `max_chars` was reached.
    omitted: int = 0
    #: Claims the corpus holds but does not vouch for, by state.
    withheld: dict[str, int] = field(default_factory=dict)
    #: Keys whose sources disagree. Both sides are shown, neither is chosen.
    conflicts: int = 0

    @property
    def kept(self) -> int:
        return len(self.claim_ids)

    def __str__(self) -> str:
        return self.text


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


def render_brief(
    response: Any,
    *,
    path_prefix: str | Iterable[str] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Brief:
    """Render a `current` response (the model, or its JSON as a dict) as a brief.

    `path_prefix` is only named in the header. Scoping already happened in the
    request that produced `response`; passing a different value here changes
    the label, not the contents.

    Lines are grouped by source path, in the order the response lists them, so
    a document's rules stay together. The same sentence held by two documents
    is one line naming both. When `max_chars` is reached the remaining claims
    are counted in `omitted` and the footer says so: a brief never ends
    mid-sentence, and it never drops rules silently.
    """
    if max_chars < MIN_MAX_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_MAX_CHARS}")

    corpus = str(_get(response, "corpus", ""))
    scope = _scope(path_prefix)
    conflicts = list(_get(response, "conflicts", []) or [])
    disputed = {_get(claim, "id") for group in conflicts for claim in _get(group, "claims", [])}
    withheld = {
        str(state): int(count)
        for state, count in sorted((_get(response, "withheld_counts", None) or {}).items())
        if count
    }

    # One entry per distinct sentence, in first-seen order, grouped by path.
    order: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    for claim in _get(response, "current_memories", []) or []:
        if _get(claim, "id") in disputed:
            continue
        sentence = _one_line(_get(claim, "claim", ""))
        if not sentence:
            continue
        entry = entries.get(sentence)
        if entry is None:
            entry = entries[sentence] = {"paths": [], "ids": []}
            order.append(sentence)
        path = str(_get(claim, "path", ""))
        if path and path not in entry["paths"]:
            entry["paths"].append(path)
        entry["ids"].append(str(_get(claim, "id")))

    def first_path(sentence: str) -> str:
        paths = entries[sentence]["paths"]
        return paths[0] if paths else ""

    # Stable: paths in the order the response first names them, and within a
    # path the response's own order.
    rank: dict[str, int] = {}
    for sentence in order:
        rank.setdefault(first_path(sentence), len(rank))
    order.sort(key=lambda sentence: rank[first_path(sentence)])

    where = f', scope {" + ".join(scope)}' if scope else ""
    header = [
        f'Approved memory for "{corpus}"{where}.',
        "Every line below is current and approved. Drafts, rejected and replaced "
        "statements are not included. Do not contradict these lines.",
        "",
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

    def footer(omitted: int) -> list[str]:
        parts = []
        if withheld:
            held = ", ".join(f"{count} {state}" for state, count in withheld.items())
            parts.append(f"Not included: {held}.")
        if omitted:
            parts.append(f"Left out for length: {omitted} more approved lines.")
        return ["", " ".join(parts)] if parts else []

    lines: list[str] = []
    kept_ids: list[str] = []
    total = sum(len(e["ids"]) for e in entries.values())
    kept_claims = 0
    fixed = len("\n".join(header + conflict_lines))
    for sentence in order:
        entry = entries[sentence]
        line = f'- {sentence} [{", ".join(entry["paths"])}]'
        remaining = total - kept_claims - len(entry["ids"])
        projected = fixed + len("\n".join(lines + [line])) + 1 + len("\n".join(footer(remaining)))
        if projected > max_chars:
            break
        lines.append(line)
        kept_ids.extend(entry["ids"])
        kept_claims += len(entry["ids"])
    omitted = total - kept_claims

    if not lines and not conflict_lines:
        body = ["(no approved memory in this scope)"]
    else:
        body = lines
    text = "\n".join(header + body + conflict_lines + footer(omitted))
    return Brief(
        text=text,
        corpus=corpus,
        scope=scope,
        claim_ids=tuple(kept_ids),
        omitted=omitted,
        withheld=withheld,
        conflicts=len(conflicts),
    )
