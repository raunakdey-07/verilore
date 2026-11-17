# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""Check a draft against approved memory: a draft in, the rules it breaks out.

A brief controls what a model is given. Nothing controlled what it wrote. A
reviewer at Team 052 reads every generated post against the brand kit by eye;
this does the part a machine can do exactly, and nothing more:

* **Banned words.** An approved rule that says `Never use the word "premium"`,
  `Do not say "cheap"` or `Avoid "world-class"` names text the draft must not
  contain. So do rules about emojis, exclamation marks and hashtags.
* **Numbers that disagree.** An approved fact with a price, a weight, a
  percentage, a duration or a date ("The gift box costs Rs 1,499.") and a
  sentence of the draft about the same thing with a different value of the
  same kind ("Gift box, now Rs 999") is a finding.

Every finding names the claim it breaks, by id, with the quote from the draft,
so a reviewer can see why and an app can link to the source. Tone, voice and
whether a claim is implied are judgement, and are left to the reviewer: a
check that guesses would be ignored after its first wrong flag.

Standard library only, like `verilore.brief`. Feed it the JSON of a `current`
response, or use `vl.memory.check(draft, ...)`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Iterable

__all__ = [
    "Finding",
    "Check",
    "channel_limits",
    "check_draft",
    "render_check",
    "render_feedback",
]


@dataclass(frozen=True)
class Finding:
    """One way a draft breaks one approved claim."""

    #: "banned", "number" (differs from an approved value), "unsupported"
    #: (a price, percentage or date no approved line states) or "limit" (longer,
    #: or with more hashtags or emojis, than the channel allows).
    kind: str
    claim_id: str
    claim: str
    path: str
    #: What in the draft broke it, quoted exactly.
    quote: str
    #: One sentence a reviewer can act on.
    detail: str
    #: Other documents that state the same rule, word for word. A kit synced as
    #: Word and as PDF states every rule twice; the draft broke it once.
    also: tuple[str, ...] = ()
    #: For a "number" finding, the value approved memory states, as written there.
    expected: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "claim_id": self.claim_id,
            "claim": self.claim,
            "path": self.path,
            "quote": self.quote,
            "detail": self.detail,
            "also": list(self.also),
            "expected": self.expected,
        }


@dataclass(frozen=True)
class Check:
    """The findings for one draft, and what was checked."""

    corpus: str
    findings: tuple[Finding, ...] = ()
    #: Approved claims the draft was checked against.
    checked: int = 0
    #: Rules that name banned text, among those claims.
    banned_rules: int = 0
    #: Whether prices, percentages and dates were required to be in memory.
    unsupported_checked: bool = False

    @property
    def ok(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "ok": self.ok,
            "checked": self.checked,
            "banned_rules": self.banned_rules,
            "unsupported_checked": self.unsupported_checked,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def _get(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


# ------------------------------------------------------------- banned text

_QUOTED = re.compile(r"[\"“”'‘’`]([^\"“”'‘’`]{1,60})[\"“”'‘’`]")
#: An instruction not to use something. The rest of the sentence names it.
_PROHIBITION = re.compile(
    r"(?<![\w'])(?:never|do not|don't|must not|should not|avoid|no)\s+"
    r"(?:(?:use|say|write|include|mention|call\s+\w+)\s+)?",
    re.IGNORECASE,
)
_WORD_LEAD = re.compile(
    r"^(?:the\s+)?(?:words?|phrases?|terms?)\s+(.+)$",
    re.IGNORECASE,
)
_CLASS_WORDS = {
    "emoji": "emoji",
    "emojis": "emoji",
    "emoticons": "emoji",
    "exclamation mark": "exclamation",
    "exclamation marks": "exclamation",
    "exclamation points": "exclamation",
    "exclamation point": "exclamation",
    "hashtag": "hashtag",
    "hashtags": "hashtag",
}
_HASHTAG = re.compile(r"(?<![\w&])#\w+")


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return (
        0x1F300 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x1F000 <= code <= 0x1F2FF
        or unicodedata.category(char) == "So"
        and code > 0x2000
    )


def banned_text(rule: str) -> list[tuple[str, str]]:
    """What a rule bans: `[("text", "premium"), ("class", "emoji")]`, or [].

    Only rules that say so: a prohibition (never, do not, avoid, no) followed
    by quoted text, by "the word X", or by emojis, exclamation marks or
    hashtags. "Never discount the house blend" bans an action, not a word, and
    gives nothing: a check that guessed would flag every draft that mentions a
    discount.
    """
    prohibition = _PROHIBITION.search(rule)
    if not prohibition:
        return []
    rest = rule[prohibition.end() :].strip()
    found: list[tuple[str, str]] = []
    quoted = _QUOTED.findall(rest)
    if quoted:
        found += [("text", text.strip()) for text in quoted if text.strip()]
        return found
    head = rest.rstrip(" .;:!").lower()
    for words, kind in _CLASS_WORDS.items():
        if head == words or head.startswith(words + " "):
            return [("class", kind)]
    lead = _WORD_LEAD.match(rest.rstrip(" .;:!"))
    if lead:
        # "the word premium in any copy": the word is the first token.
        first = re.match(r"[\w'-]+", lead.group(1))
        if first:
            found.append(("text", first.group(0)))
    return found


#: "on LinkedIn", "for Instagram": a rule for one channel, named with a capital,
#: or one of the channels a brand writes in lower case ("in emails").
_QUALIFIER = re.compile(
    r"\b(?:on|in|for)\s+(?:the\s+)?([A-Z][\w-]+|emails?|newsletters?|blogs?|sms|websites?)\b"
)


def rule_channel(rule: str) -> str | None:
    """The channel a ban is limited to ("LinkedIn" in "...hashtags on LinkedIn"), if any."""
    prohibition = _PROHIBITION.search(rule)
    if not prohibition:
        return None
    match = _QUALIFIER.search(rule, prohibition.end())
    return match.group(1) if match else None


def _find_text(draft: str, text: str) -> str | None:
    """The first occurrence of `text` in the draft as a whole word, quoted exactly."""
    pattern = r"(?<![\w])" + re.escape(text) + r"(?![\w])"
    match = re.search(pattern, draft, re.IGNORECASE)
    return match.group(0) if match else None


def _find_class(draft: str, kind: str) -> str | None:
    if kind == "emoji":
        for char in draft:
            if _is_emoji(char):
                return char
        return None
    if kind == "exclamation":
        return "!" if "!" in draft else None
    if kind == "hashtag":
        match = _HASHTAG.search(draft)
        return match.group(0) if match else None
    return None


# ------------------------------------------------------------- numbers

_MONTHS = (
    "january february march april may june july august september october november december"
).split()
_MONTH = r"(?:" + "|".join(m[:3] + r"(?:" + m[3:] + r")?" for m in _MONTHS) + r")\.?"
_AMOUNT = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?"
#: A value with the kind it is: the unit decides what it can be compared with.
_VALUES = [
    (
        "date",
        re.compile(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})(?:,?\s+(\d{{4}}))?\b|"
            rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "money",
        re.compile(
            rf"(?:(?:rs\.?|inr|₹|\$|usd|€|eur|£|gbp)\s?({_AMOUNT}))|(?:({_AMOUNT})\s?"
            r"(?:rupees|dollars|euros|pounds|inr|usd|eur|gbp)\b)",
            re.IGNORECASE,
        ),
    ),
    ("percent", re.compile(rf"({_AMOUNT})\s?(?:%|percent\b|per cent\b)", re.IGNORECASE)),
    (
        "weight",
        re.compile(rf"({_AMOUNT})\s?(?:kg|kilograms?|kilos?|g|grams?|lbs?|pounds)\b", re.I),
    ),
    (
        "duration",
        re.compile(rf"({_AMOUNT})\s?(?:hours?|hrs?|days?|weeks?|months?|years?)\b", re.I),
    ),
    (
        "length",
        re.compile(rf"({_AMOUNT})\s?(?:characters?|chars?|words?|ml|l|litres?|liters?)\b", re.I),
    ),
]
_UNIT_FAMILY = {
    "hour": "hour",
    "hours": "hour",
    "hr": "hour",
    "hrs": "hour",
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "year": "year",
    "years": "year",
}
_STOP = frozenset(
    """a an and are as at be by for from has have in is it its of on or our the their this
    to was we with will your you all any every now just only new more most""".split()
)
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_NEGATION = re.compile(r"(?<![\w'])(?:not|no|never|don't|cannot|can't|under|over)(?![\w'])", re.I)


def _norm_amount(text: str) -> str:
    return text.replace(",", "").rstrip("0").rstrip(".") if "." in text else text.replace(",", "")


def _values(sentence: str) -> list[tuple[str, str, str]]:
    """`(kind, normalised value, exact text)` for each value in a sentence."""
    found: list[tuple[str, str, str]] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in _VALUES:
        for match in pattern.finditer(sentence):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            taken.append(span)
            text = match.group(0).strip()
            if kind == "date":
                day = match.group(1) or match.group(5)
                month = (match.group(2) or match.group(4) or "").lower()[:3]
                year = match.group(3) or match.group(6) or ""
                value = f"{int(day)} {month} {year}".strip()
            elif kind == "duration":
                unit = re.search(r"[a-z]+$", text.lower())
                family = _UNIT_FAMILY.get(unit.group(0) if unit else "", "")
                kind = f"duration:{family}"
                value = _norm_amount(match.group(1))
            else:
                amount = next(group for group in match.groups() if group)
                value = _norm_amount(amount)
            found.append((kind, value, text))
    return found


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


#: Words a value's kind already says. "The Trail 2 costs Rs 24,999" is about
#: the Trail 2; "costs" and "price" are what the rupees say, and a draft that
#: names the product and a price ("Trail 2, now Rs 22,999") need not repeat them.
_IMPLIED = {
    "money": frozenset({"cost", "price", "pric", "mrp", "priced"}),
    "weight": frozenset({"weigh", "weight"}),
    "date": frozenset({"date"}),
}
#: A number that is not a value: a model number, as in "Trail 2".
_BARE_NUMBER = re.compile(r"(?<![\w.,])\d+(?![\w.,])")


def _subject(text: str, kinds: Iterable[str] = ()) -> frozenset[str]:
    """The words a sentence is about, without the values and the glue.

    A bare number left once the values are gone is part of the subject, so the
    Trail 2 and the Trail 3 are different things. `kinds` drops the words that
    the remembered value's kind already implies.
    """
    stripped = text
    for _kind, pattern in _VALUES:
        stripped = pattern.sub(" ", stripped)
    implied = frozenset().union(*(_IMPLIED.get(kind.split(":")[0], ()) for kind in kinds))
    words = {
        _stem(word.lower())
        for word in _WORD.findall(stripped)
        if word.lower() not in _STOP and len(word) > 1
    }
    return frozenset(words - implied) | frozenset(_BARE_NUMBER.findall(stripped))


#: Where one statement ends: a sentence break (. ! or ? then space; "9.8" and
#: "Rs. 999" do not end one), a line break, a semicolon, or a comma or "and" /
#: "but" that joins two clauses. "The gift box costs Rs 1,499 and orders close
#: on 5 November" is two statements, and the price belongs to the first.
_UNIT_BREAK = re.compile(
    r"(?<=[.!?])\s+(?=[^\s\d])|\n+|;\s*|,\s+(?=[^\d])|\s+(?:and|but)\s+",
    re.IGNORECASE,
)


def _windows(draft: str) -> list[tuple[str, str]]:
    """`(context, statement)`: each statement alone, and with the one before it.

    "Our gift box is back. Now just Rs 999." states the gift box's price across
    two statements, so the earlier one may supply the subject. The value must
    come from the later one, and only when the earlier one has no value of its
    own: "Shipping is Rs 99. Gift box delivery in 24 hours" says nothing about
    what the gift box costs.
    """
    units = [u.strip() for u in _UNIT_BREAK.split(draft) if u and u.strip()]
    return [("", u) for u in units] + [(a, b) for a, b in zip(units, units[1:])]


def _same_date(memory: str, draft: str) -> bool:
    """`5 nov` matches `5 nov 2026`: a draft often leaves the year out."""
    m, d = memory.split(), draft.split()
    return m[:2] == d[:2] and (len(m) < 3 or len(d) < 3 or m[2] == d[2])


def _number_findings(draft: str, claim: dict[str, str]) -> list[Finding]:
    """Values in the draft that differ from the claim's, about the claim's subject."""
    text = claim["claim"]
    if _NEGATION.search(text):
        # "Do not promise delivery in under 48 hours" is a limit, not a value;
        # comparing 48 with a draft's 24 would get the direction wrong half the time.
        return []
    remembered = _values(text)
    if not remembered:
        return []
    subject = _subject(f'{claim.get("section", "")} {text}', [kind for kind, _v, _t in remembered])
    if not subject:
        return []
    findings: list[Finding] = []
    for context, statement in _windows(draft):
        shared = subject & _subject(f"{context} {statement}")
        # About the same thing: most of the fact's subject words, and at least
        # two of them unless the fact has only one.
        if len(shared) < min(2, len(subject)) or len(shared) * 2 < len(subject):
            continue
        written = _values(statement)
        earlier = {k for k, _v, _t in _values(context)}
        # A fact can state two values of one kind ("Orders below Rs 999 pay Rs
        # 79"): a draft that repeats either one agrees with it.
        kinds = {
            kind: [(v, t) for k, v, t in remembered if k == kind] for kind, _v, _t in remembered
        }
        for kind, values in kinds.items():
            same_kind = [(v, t) for k, v, t in written if k == kind]
            if not same_kind or kind in earlier:
                continue
            matches = (
                any(_same_date(mine, v) for mine, _t in values for v, _t2 in same_kind)
                if kind == "date"
                else any(mine == v for mine, _t in values for v, _t2 in same_kind)
            )
            if matches:
                continue
            quote = same_kind[0][1]
            if any(f.quote == quote for f in findings):
                continue
            label = kind.split(":")[0]
            expected = " or ".join(t for _v, t in values)
            findings.append(
                Finding(
                    "number",
                    claim["id"],
                    text,
                    claim["path"],
                    quote,
                    f"The draft says {quote} where approved memory says {expected} ({label}).",
                    expected=expected,
                )
            )
    return findings


# ------------------------------------------------------------- unsupported values

#: The kinds of value a draft must not state unless approved memory does. A
#: made-up price, discount or date is the error a reader acts on, and the one a
#: model makes most when its context is silent. Weights, durations and lengths
#: are left out: "a 2-minute read" or "250 g of leaves" are rarely claims.
UNSUPPORTED_KINDS = ("money", "percent", "date")


def _supported(kind: str, value: str, known: list[tuple[str, str]]) -> bool:
    if kind == "date":
        return any(k == "date" and (_same_date(v, value) or _same_date(value, v)) for k, v in known)
    return any(k == kind and v == value for k, v in known)


def _unsupported_findings(
    draft: str, claims: list[dict[str, str]], also: Iterable[str]
) -> list[Finding]:
    """Prices, percentages and dates in the draft that no approved line states."""
    known = [
        (kind, value)
        for text in [*(claim["claim"] for claim in claims), *also]
        for kind, value, _exact in _values(text)
    ]
    findings: list[Finding] = []
    seen: set[str] = set()
    # In the order the draft says them, so the instructions read top to bottom.
    for kind, value, exact in sorted(_values(draft), key=lambda found: draft.find(found[2])):
        if kind not in UNSUPPORTED_KINDS or _supported(kind, value, known):
            continue
        if exact.lower() in seen:
            continue
        seen.add(exact.lower())
        label = {"money": "price", "percent": "percentage", "date": "date"}[kind]
        findings.append(
            Finding(
                "unsupported",
                "",
                "",
                "",
                exact,
                f"The draft states the {label} {exact}, and no approved line does.",
            )
        )
    return findings


# ------------------------------------------------------------- channel limits

#: What a channel line limits, and how to find the number.
_LIMITS = {
    "characters": re.compile(r"(\d[\d,]*)\s*(?:characters?|chars?)\b", re.I),
    "words": re.compile(r"(\d[\d,]*)\s*words?\b", re.I),
    "hashtags": re.compile(
        r"hashtags?\s*:?\s*(?:(\d+)\s*(?:at most|max(?:imum)?)|(?:at most|up to|max(?:imum)?)"
        r"\s*(\d+)|(none|no|0)\b)|(?:at most|up to|no more than)\s*(\d+)\s*hashtags?"
        r"|\bno hashtags\b",
        re.I,
    ),
    "emojis": re.compile(
        r"emojis?\s*:?\s*(?:(\d+)\s*(?:at most|max(?:imum)?)|(?:at most|up to|max(?:imum)?)"
        r"\s*(\d+)|(none|no|0)\b)|(?:at most|up to|no more than)\s*(\d+)\s*emojis?"
        r"|\bno emojis\b",
        re.I,
    ),
}
#: A length is a limit only when the line says so: "Length: 150 characters",
#: "at most 150 characters". "Blog posts run about 800 words" is a habit.
_LENGTH_IS_LIMIT = re.compile(
    r"\blength\s*:|\b(?:at most|up to|under|no more than|max(?:imum)?|within|fewer than"
    r"|less than)\b",
    re.I,
)
#: A channel's own line: "Instagram: Length: 150 characters; Hashtags: 3 at most".
_CHANNEL_ROW = re.compile(r"^([A-Z][\w-]*(?: [A-Z][\w-]*){0,2}):\s")
#: A channel named inside a sentence: "on LinkedIn", "Instagram captions".
_CHANNEL_NAMED = re.compile(
    r"\b(Instagram|LinkedIn|WhatsApp|Facebook|Twitter|TikTok|YouTube|Threads|Email|SMS)\b"
)


def channel_limits(claim: str) -> tuple[str | None, dict[str, int]]:
    """The channel a line limits and its limits: ("Instagram", {"characters": 150}).

    Read from a table row ("Instagram: Length: 150 characters; Hashtags: 3 at
    most") or a sentence naming the channel ("Keep LinkedIn posts under 120
    words"). A line with no channel, or no limit, gives `(None, {})`.
    """
    row = _CHANNEL_ROW.match(claim)
    channel = row.group(1) if row else None
    if channel is None:
        named = _CHANNEL_NAMED.search(claim)
        channel = named.group(1) if named else None
    if channel is None:
        return None, {}
    limits: dict[str, int] = {}
    for part in claim.split(";"):
        for kind in ("characters", "words"):
            match = _LIMITS[kind].search(part)
            if match and (row or _LENGTH_IS_LIMIT.search(part)):
                limits.setdefault(kind, int(match.group(1).replace(",", "")))
        for kind in ("hashtags", "emojis"):
            match = _LIMITS[kind].search(part)
            if match:
                number = next((g for g in match.groups() if g and g.isdigit()), None)
                limits.setdefault(kind, int(number) if number else 0)
    return (channel, limits) if limits else (None, {})


def _counts(draft: str) -> dict[str, int]:
    text = draft.strip()
    return {
        "characters": len(text),
        "words": len(text.split()),
        "hashtags": len(_HASHTAG.findall(text)),
        "emojis": sum(1 for char in text if _is_emoji(char)),
    }


def _limit_findings(draft: str, claims: list[dict[str, str]], channel: str) -> list[Finding]:
    """Where the draft is longer, or has more hashtags or emojis, than its channel allows."""
    counts = _counts(draft)
    findings: list[Finding] = []
    seen: set[str] = set()
    for claim in claims:
        named, limits = channel_limits(claim["claim"])
        if not named or named.lower().rstrip("s") not in channel.lower():
            continue
        for kind, most in limits.items():
            if counts[kind] <= most or kind in seen:
                continue
            seen.add(kind)
            unit = kind if counts[kind] != 1 else kind[:-1]
            allows = f"at most {most}" if most else f"no {kind}"
            findings.append(
                Finding(
                    "limit",
                    claim["id"],
                    claim["claim"],
                    claim["path"],
                    f"{counts[kind]} {unit}",
                    f"The draft has {counts[kind]} {unit}; {named} allows {allows}.",
                    expected=str(most),
                )
            )
    return findings


# ------------------------------------------------------------- the check


def check_draft(
    draft: str,
    current: Any,
    *,
    channel: str | None = None,
    extra_rules: Iterable[Any] = (),
    unsupported: bool = True,
    supported_by: Iterable[str] = (),
) -> Check:
    """Check a draft against the approved claims of a `current` response.

    `current` is the model or its JSON; its `current_memories` are approved and
    in scope already. Returns every finding, banned text first, each once per
    claim and quote.

    `channel` is where the draft will appear ("Instagram", "LinkedIn post"). A
    ban limited to one channel ("Never use hashtags on LinkedIn") is skipped
    for a draft for another one. Without `channel` such a ban is still checked,
    and its finding names the channel so a reviewer can dismiss it. With
    `channel`, the channel's own limits are checked too: its length in
    characters or words, and how many hashtags and emojis it allows.

    With `unsupported` (the default), a price, percentage or date in the draft
    that no approved line states is a finding too: memory is silent on it, so
    the draft made it up. `supported_by` adds text whose values count as
    stated, such as the task a person typed ("announce 20% off").
    """
    # The section a claim sits under names what it is about when the claim does
    # not: "Price: Rs 520 for a 250 g tin." under "Products > Assam Gold".
    sections: dict[str, str] = {}
    for evidence in _get(current, "evidence", []) or []:
        parts = str(_get(evidence, "heading", "") or "").split(" > ")
        if len(parts) > 1:
            sections.setdefault(str(_get(evidence, "claim_id", "")), " ".join(parts[1:]))
    claims = [
        {
            "id": str(_get(claim, "id", "")),
            "claim": " ".join(str(_get(claim, "claim", "")).split()),
            "path": str(_get(claim, "path", "")),
            "section": sections.get(str(_get(claim, "id", "")), ""),
        }
        for claim in [*(_get(current, "current_memories", []) or []), *extra_rules]
    ]
    claims = [claim for claim in claims if claim["claim"]]
    findings: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()
    # One finding per rule and quote, however many documents state the rule.
    by_text: dict[tuple[str, str, str], int] = {}

    def add(finding: Finding) -> None:
        same = (finding.kind, finding.claim.casefold(), finding.quote.casefold())
        if same in by_text:
            index = by_text[same]
            first = findings[index]
            if finding.path != first.path and finding.path not in first.also:
                findings[index] = replace(first, also=(*first.also, finding.path))
            return
        by_text[same] = len(findings)
        findings.append(finding)

    banned_rules = 0
    for claim in claims:
        banned = banned_text(claim["claim"])
        if banned:
            banned_rules += 1
        limited_to = rule_channel(claim["claim"]) if banned else None
        if limited_to and channel and limited_to.lower().rstrip("s") not in channel.lower():
            continue
        for kind, target in banned:
            quote = _find_text(draft, target) if kind == "text" else _find_class(draft, target)
            if quote is None:
                continue
            key = ("banned", claim["id"], quote.lower())
            if key in seen:
                continue
            seen.add(key)
            what = f'"{quote}"' if kind == "text" else f"{target} ({quote})"
            where = f" (the rule is for {limited_to})" if limited_to and not channel else ""
            add(
                Finding(
                    "banned",
                    claim["id"],
                    claim["claim"],
                    claim["path"],
                    quote,
                    f"The draft uses {what}, which an approved rule bans{where}.",
                )
            )
    for claim in claims:
        for finding in _number_findings(draft, claim):
            key = ("number", finding.claim_id, finding.quote)
            if key not in seen:
                seen.add(key)
                add(finding)
    if channel:
        for finding in _limit_findings(draft, claims, channel):
            add(finding)
    if unsupported:
        # A value already shown to differ from an approved one is not reported
        # twice; the "number" finding says what it should be.
        differing = {f.quote.lower() for f in findings if f.kind == "number"}
        for finding in _unsupported_findings(draft, claims, supported_by):
            if finding.quote.lower() not in differing:
                add(finding)
    return Check(
        corpus=str(_get(current, "corpus", "")),
        findings=tuple(findings),
        checked=len(claims),
        banned_rules=banned_rules,
        unsupported_checked=unsupported,
    )


def render_check(check: Check) -> str:
    if check.ok:
        return (
            f"No problems found against {check.checked} approved lines "
            f"({check.banned_rules} name banned text). Tone and voice are a reviewer's call."
        )
    out = [f"{len(check.findings)} problem(s) against {check.checked} approved lines:"]
    for finding in check.findings:
        also = f"; also {', '.join(finding.also)}" if finding.also else ""
        out.append(f"- {finding.detail}")
        if finding.claim_id:
            out.append(
                f"    rule: {finding.claim}  [{finding.path}, {finding.claim_id[:12]}{also}]"
            )
        else:
            out.append("    rule: none; state it only if a person approves it")
    return "\n".join(out)


_CLASS_NAMES = {
    "emoji": "every emoji",
    "exclamation": "every exclamation mark",
    "hashtag": "every hashtag",
}


def render_feedback(check: Check) -> str:
    """The findings as an instruction a model can follow to revise its draft.

    One line per problem, each saying what to change and the approved line that
    says so, and nothing else: a weak model given a vague "fix the problems"
    rewrites everything, and a model told exactly what to change mostly changes
    only that. Empty when the draft has no findings.
    """
    if check.ok:
        return ""
    lines = [
        "Revise the draft. Change only what is listed below and keep everything else as it is."
    ]
    for finding in check.findings:
        if finding.kind == "banned":
            what = f'"{finding.quote}"'
            if len(finding.quote) == 1 or finding.quote.startswith("#"):
                kind = (
                    "exclamation"
                    if finding.quote == "!"
                    else ("hashtag" if finding.quote.startswith("#") else "emoji")
                )
                # Every one, not only the one quoted: told "remove #tea", a
                # model removes #tea and keeps the other three.
                what = f"{_CLASS_NAMES[kind]} (such as {finding.quote})"
            lines.append(f"- Remove {what}. Approved rule: {finding.claim}")
        elif finding.kind == "limit":
            count, unit = finding.quote.split(" ", 1)
            plural = unit if unit.endswith("s") else unit + "s"
            if plural in ("characters", "words"):
                change = f"Shorten the draft to at most {finding.expected} {plural}"
            elif finding.expected == "0":
                change = f"Remove every {plural[:-1]}"
            else:
                change = f"Use at most {finding.expected} {plural}"
            lines.append(f"- {change}; it has {count}. Approved: {finding.claim}")
        elif finding.kind == "number":
            lines.append(
                f"- Replace {finding.quote} with {finding.expected}. Approved: {finding.claim}"
            )
        else:
            lines.append(
                f"- Remove {finding.quote}: no approved line states it. Do not replace it "
                "with another value unless an approved line states that value."
            )
    lines.append("Return only the revised draft.")
    return "\n".join(lines)
