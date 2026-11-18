# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""What a person should look at before memory reaches a model.

Verilore detects a conflict only when two claims share a key, and two lines
from two different documents never do. So "Use Indian English spelling" in the
brand rules and "Use American spelling in all copy" in old workshop notes were
both served as approved, under a header that tells the model not to contradict
either. Deciding which is right is not something to guess at. Finding the pair
is, and that is what this module does:

* `likely_pairs` finds approved lines from different documents that are about
  the same thing and differ: two numbers for one fact, one line saying "not"
  where the other does not, the same instruction with different details, or
  nearly the same words twice. Each pair says why it was flagged.
* `render_review` lists those pairs with the drafts waiting for approval and the
  keyed conflicts, as plain text or as one static HTML page a brand owner can
  open without installing anything.

Nothing here resolves anything. A person settles each pair: reject or
supersede a line, or record that the two agree. Until then a brief prints a
pair that states a difference (two values of one kind for the same thing, or
nearly the same line with "not" in one) apart from its other lines, and tells
the model not to choose; see `verilore.brief._disagree`. The other pairs, such
as the same instruction with other details, stay in its list for a person.

Lexical and deterministic, like the brief: no model, the same answer on every
machine. That bounds what it finds. "Ship in two days" and "Delivery takes 48
hours" share no word and are not paired; with the embedding model loaded,
`remember` already reports such near neighbours when a line is written.

Standard library only, so it can run on the JSON of a `current` response.
"""

from __future__ import annotations

import html
import math
import posixpath
import re
from dataclasses import dataclass
from typing import Any, Iterable

__all__ = [
    "Pair",
    "Review",
    "build_review",
    "likely_pairs",
    "pair_id",
    "render_review",
    "render_review_html",
]

#: Words that carry no subject. A sentence's subject is what is left.
_STOP = frozenset("""a about after again all also always an and any are as at avoid be been before
    being both but by can can't cannot could did do does doesn't don't done each every
    few for from had has have here how i if in into is it its just may me might more
    most must my never no nor not now of on once only or other our over own per same
    shall should so some such than that the their them then there these they this those
    to too under us use used uses very was we well were what when where which who whom
    whose why will with within without won't would yes you your
    copy body content text word words phrase term""".split())
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_NEGATION = re.compile(
    r"(?<![\w'])(?:not|no|never|nor|don't|doesn't|cannot|can't|won't|avoid|without)(?![\w'])",
    re.IGNORECASE,
)
#: Verbs a brand or style rule opens with. "Use Indian English spelling" and
#: "Use American spelling" are one instruction given twice; "The gift box costs"
#: and "The gift box ships" are two facts, and "None of them" is neither.
_INSTRUCTION_VERBS = frozenset(
    """use write keep avoid include mention say call refer spell capitalise capitalize
    address add show put lead open close end start sign link tag post describe quote
    cite list mark send reply respond format limit prefer name credit translate
    publish price offer promise ship deliver mention""".split()
)
#: Words that may come before the verb of an instruction.
_LEAD_INS = frozenset("always never please do don't not only".split())

#: How much of two lines' combined informative weight they must share.
NEARLY_SAME = 0.6
NUMBERS_DIFFER = 0.4
POLARITY_DIFFERS = 0.35
SAME_INSTRUCTION = 0.15
#: A word in more claims than this says nothing about which two are related,
#: and pairing on it would make the work quadratic in the size of the corpus.
COMMON_WORD = 50
#: A line longer than this is a paragraph, not one rule, and two paragraphs
#: always share words. They are not paired.
MAX_WORDS = 40


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> frozenset[str]:
    return frozenset(
        _stem(word)
        for word in (match.group(0).casefold() for match in _WORD.finditer(text))
        if word not in _STOP and len(word) > 1
    )


def _numbers(text: str) -> frozenset[str]:
    return frozenset(number.replace(",", "") for number in _NUMBER.findall(text))


def _label(text: str) -> str | None:
    """The row label of a table claim ("Instagram: Length: ..."), if it has one."""
    head, colon, _rest = text.partition(":")
    if colon and 0 < len(head.split()) <= 4:
        return head.strip().casefold()
    return None


def _instruction(text: str) -> str:
    """The verb an instruction opens with ("use" in "Never use ..."), or ""."""
    for match in _WORD.finditer(text):
        word = match.group(0).casefold()
        if word in _LEAD_INS:
            continue
        return word if word in _INSTRUCTION_VERBS else ""
    return ""


def _template_siblings(left: str, right: str) -> bool:
    """`campaigns/diwali/brief.md` and `campaigns/ny/brief.md`: one template, two uses.

    Two campaign briefs are meant to give different dates and offers. Pairing
    them would flag every field of every campaign against every other.
    """
    return (
        posixpath.basename(left) == posixpath.basename(right)
        and posixpath.dirname(left) != posixpath.dirname(right)
        and posixpath.dirname(posixpath.dirname(left))
        == posixpath.dirname(posixpath.dirname(right))
    )


def pair_id(left_id: str, right_id: str) -> str:
    """A stable name for a pair, the same whichever side is given first."""
    first, second = sorted((left_id, right_id))
    return f"{first[:12]}~{second[:12]}"


@dataclass(frozen=True)
class Pair:
    """Two approved lines a person should compare, and why."""

    id: str
    left: dict[str, str]
    right: dict[str, str]
    reasons: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class Review:
    """Everything waiting for a person, for one corpus and scope."""

    corpus: str
    scope: tuple[str, ...] = ()
    pairs: tuple[Pair, ...] = ()
    drafts: tuple[dict[str, str], ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    #: Pairs a person already marked as agreeing, by `pair_id`; not listed again.
    settled: int = 0
    approved: int = 0

    @property
    def open_items(self) -> int:
        return len(self.pairs) + len(self.drafts) + len(self.conflicts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "scope": list(self.scope),
            "approved": self.approved,
            "pairs": [
                {
                    "id": p.id,
                    "left": p.left,
                    "right": p.right,
                    "reasons": list(p.reasons),
                    "score": p.score,
                }
                for p in self.pairs
            ],
            "drafts": list(self.drafts),
            "conflicts": list(self.conflicts),
            "settled": self.settled,
        }


def _get(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _line(claim: Any) -> dict[str, str]:
    return {
        "id": str(_get(claim, "id", "")),
        "claim": " ".join(str(_get(claim, "claim", "")).split()),
        "path": str(_get(claim, "path", "")),
    }


def likely_pairs(
    claims: Iterable[Any], *, settled: Iterable[str] = (), limit: int = 200
) -> tuple[list[Pair], int]:
    """Pairs of lines from different documents that a person should compare.

    Returns `(pairs, settled_count)`: the pairs, most alike first, at most
    `limit` of them, and how many were left out because `settled` names them.

    A pair is flagged only when the two lines share a subject word and also
    differ in a way that can be stated: different numbers for the same fact,
    one saying "not" where the other does not, the same instruction (same first
    word) with different details, or nearly the same words (a duplicate).
    Lines from one document are never paired: a document disagreeing with
    itself is its author's to fix, and the reader reads them together. Nor are
    lines from two uses of one template, such as two campaign briefs.
    """
    lines = [_line(claim) for claim in claims]
    lines = [line for line in lines if line["claim"] and len(line["claim"].split()) <= MAX_WORDS]
    words = [_terms(line["claim"]) for line in lines]
    frequency: dict[str, int] = {}
    for bag in words:
        for word in bag:
            frequency[word] = frequency.get(word, 0) + 1
    # At least a hundred, so a pair is flagged the same way in a five-line scope
    # as in the whole corpus: with a handful of lines every word is "rare" and
    # the weights swing. Below a hundred this is close to plain word overlap.
    total = max(len(lines), 100)

    def weight(word: str) -> float:
        return math.log((total + 1) / (frequency.get(word, 0) + 1)) + 1.0

    index: dict[str, list[int]] = {}
    for position, bag in enumerate(words):
        for word in bag:
            if frequency[word] <= COMMON_WORD:
                index.setdefault(word, []).append(position)
    candidates: set[tuple[int, int]] = set()
    for members in index.values():
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                candidates.add((left, right))

    settled_ids = set(settled)
    found: list[Pair] = []
    skipped = 0
    for left, right in sorted(candidates):
        a, b = lines[left], lines[right]
        if a["path"] == b["path"] or _template_siblings(a["path"], b["path"]):
            continue
        label_a, label_b = _label(a["claim"]), _label(b["claim"])
        if label_a and label_b and label_a != label_b:
            # Two rows of a table, about two different things.
            continue
        shared = words[left] & words[right]
        union = words[left] | words[right]
        if not shared:
            continue
        score = sum(weight(w) for w in shared) / sum(weight(w) for w in union)
        reasons: list[str] = []
        if score >= NEARLY_SAME:
            reasons.append("nearly the same words")
        numbers_a, numbers_b = _numbers(a["claim"]), _numbers(b["claim"])
        if numbers_a and numbers_b and numbers_a != numbers_b and score >= NUMBERS_DIFFER:
            only_a = ", ".join(sorted(numbers_a - numbers_b)) or "-"
            only_b = ", ".join(sorted(numbers_b - numbers_a)) or "-"
            reasons.append(f"different numbers: {only_a} / {only_b}")
        if bool(_NEGATION.search(a["claim"])) != bool(_NEGATION.search(b["claim"])) and (
            score >= POLARITY_DIFFERS
        ):
            reasons.append('one says "not" and the other does not')
        verb = _instruction(a["claim"])
        if not reasons and verb and verb == _instruction(b["claim"]) and score >= SAME_INSTRUCTION:
            reasons.append("the same instruction with different details")
        if not reasons:
            continue
        identity = pair_id(a["id"], b["id"])
        if identity in settled_ids:
            skipped += 1
            continue
        found.append(Pair(identity, a, b, tuple(reasons), round(score, 3)))
    found.sort(key=lambda pair: (-pair.score, pair.id))
    return found[:limit], skipped


def build_review(
    current: Any,
    with_drafts: Any = None,
    *,
    path_prefix: str | Iterable[str] | None = None,
    settled: Iterable[str] = (),
) -> Review:
    """A `Review` from a `current` response, and optionally one that kept drafts.

    `current` is what a brief is built from: approved, in scope. `with_drafts`
    is the same request with `include_states=["draft"]`, so the drafts waiting
    for a person can be listed. Either may be the model or its JSON.
    """
    scope = (path_prefix,) if isinstance(path_prefix, str) else tuple(path_prefix or ())
    approved = list(_get(current, "current_memories", []) or [])
    pairs, skipped = likely_pairs(approved, settled=settled)
    drafts: list[dict[str, str]] = []
    if with_drafts is not None:
        for claim in _get(with_drafts, "current_memories", []) or []:
            if str(_get(claim, "info_state", "")) == "draft":
                drafts.append(_line(claim))
    conflicts = [
        {
            "key": str(_get(group, "key", "")),
            "sides": [_line(claim) for claim in _get(group, "claims", []) or []],
        }
        for group in _get(current, "conflicts", []) or []
    ]
    return Review(
        corpus=str(_get(current, "corpus", "")),
        scope=scope,
        pairs=tuple(pairs),
        drafts=tuple(drafts),
        conflicts=tuple(conflicts),
        settled=skipped,
        approved=len(approved),
    )


# ----------------------------------------------------------------- rendering


def render_review(review: Review) -> str:
    """The review as plain text, for a terminal or a message."""
    where = f', scope {" + ".join(review.scope)}' if review.scope else ""
    out = [f'Review for "{review.corpus}"{where}: {review.open_items} to look at.']
    if review.conflicts:
        out += ["", f"Conflicts on one key ({len(review.conflicts)}): the brief shows both sides."]
        for group in review.conflicts:
            out.append(f'  key {group["key"]}')
            for side in group["sides"]:
                out.append(f'    - {side["claim"]}  [{side["path"]}, {side["id"][:12]}]')
    if review.pairs:
        out += [
            "",
            f"Lines that may disagree ({len(review.pairs)}): a brief prints the ones that "
            "state a difference apart, and tells the model not to choose.",
        ]
        for pair in review.pairs:
            out.append(f'  {pair.id}  ({"; ".join(pair.reasons)})')
            for side in (pair.left, pair.right):
                out.append(f'    - {side["claim"]}  [{side["path"]}, {side["id"][:12]}]')
    if review.drafts:
        out += ["", f"Drafts waiting for approval ({len(review.drafts)}): not served."]
        for draft in review.drafts:
            out.append(f'  - {draft["claim"]}  [{draft["path"]}, {draft["id"][:12]}]')
    if not review.open_items:
        out += ["", "Nothing to review."]
    if review.pairs or review.conflicts:
        out += [
            "",
            "To settle one: give the wrong document `status: rejected` (or remove the line)",
            "and sync, or record the replacement with `verilore remember ... --supersedes",
            "<claim-id>`. A pair that agrees can be left, or listed by its id in",
            "`review(settled=[...])` so it is not shown again.",
        ]
    if review.settled:
        out += ["", f"{review.settled} pair(s) already marked as agreeing are not listed."]
    return "\n".join(out)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Memory review: {corpus}</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6a65; --line:#e3e0d8; --warn:#9a3412; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#161614; --fg:#ecebe6; --muted:#a3a29b; --line:#33322e; --warn:#fb923c; }}
}}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:780px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }} h2 {{ font-size:1.1rem; margin:32px 0 8px; }}
p.note {{ color:var(--muted); margin:0 0 8px; }}
ol, ul {{ padding-left:0; list-style:none; margin:0; }}
li.item {{ border-top:1px solid var(--line); padding:12px 0; }}
.why {{ color:var(--warn); font-size:.9rem; }}
.side {{ margin:6px 0 0; }} .src {{ color:var(--muted); font-size:.85rem; }}
code {{ font:.85rem ui-monospace, SFMono-Regular, Menlo, monospace; }}
</style></head><body><main>
<h1>Memory review: {corpus}</h1>
<p class="note">{summary}</p>
{sections}
<p class="note" style="margin-top:32px">Nothing on this page has been changed or resolved.
Each item needs a person: reject or replace the wrong line, approve a draft, or mark a
pair as agreeing.</p>
</main></body></html>
"""


def _side(side: dict[str, str]) -> str:
    return (
        f'<p class="side">{html.escape(side["claim"])}<br>'
        f'<span class="src">{html.escape(side["path"])} &middot; '
        f'<code>{html.escape(side["id"][:12])}</code></span></p>'
    )


def render_review_html(review: Review) -> str:
    """The review as one self-contained page: no script, no network, safe to email."""
    sections: list[str] = []
    if review.conflicts:
        items = "".join(
            f'<li class="item"><span class="why">key {html.escape(group["key"])}</span>'
            + "".join(_side(side) for side in group["sides"])
            + "</li>"
            for group in review.conflicts
        )
        sections.append(
            "<h2>Conflicts on one key</h2><p class='note'>The brief shows both sides.</p>"
            f"<ol>{items}</ol>"
        )
    if review.pairs:
        items = "".join(
            f'<li class="item"><span class="why">{html.escape("; ".join(pair.reasons))}</span>'
            f"{_side(pair.left)}{_side(pair.right)}"
            f'<span class="src">pair <code>{html.escape(pair.id)}</code></span></li>'
            for pair in review.pairs
        )
        sections.append(
            "<h2>Lines that may disagree</h2><p class='note'>A brief prints the ones that "
            "state a difference apart, and tells the model not to choose between them, "
            f"until one is rejected or replaced.</p><ol>{items}</ol>"
        )
    if review.drafts:
        items = "".join(f'<li class="item">{_side(draft)}</li>' for draft in review.drafts)
        sections.append(
            "<h2>Drafts waiting for approval</h2><p class='note'>Not served.</p>"
            f"<ul>{items}</ul>"
        )
    if not sections:
        sections.append("<p>Nothing to review.</p>")
    where = f' in {" + ".join(review.scope)}' if review.scope else ""
    summary = (
        f"{review.open_items} item(s) to look at{where}, across {review.approved} "
        "approved lines."
    )
    return _PAGE.format(
        corpus=html.escape(review.corpus), summary=html.escape(summary), sections="".join(sections)
    )
