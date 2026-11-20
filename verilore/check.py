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
* **Values past a limit.** "Do not promise delivery in under 48 hours" allows
  48 hours or more; a draft that says "delivered in 24 hours" is a finding.

Every finding names the claim it breaks, by id, with the quote from the draft,
so a reviewer can see why and an app can link to the source. Tone, voice and
whether a claim is implied are judgement, and are left to the reviewer: a
check that guesses would be ignored after its first wrong flag.

Standard library only, like `verilore.brief`. Feed it the JSON of a `current`
response, or use `vl.memory.check(draft, ...)`.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Iterable

__all__ = [
    "Bound",
    "Finding",
    "Check",
    "bound_rule",
    "channel_limits",
    "channel_minimums",
    "check_draft",
    "render_check",
    "render_feedback",
]


@dataclass(frozen=True)
class Finding:
    """One way a draft breaks one approved claim."""

    #: "banned", "number" (differs from an approved value), "bound" (past a
    #: limit a rule sets, such as "under 48 hours"), "unsupported" (a price,
    #: percentage or date no approved line states) or "limit" (longer, or with
    #: more hashtags or emojis, than the channel allows).
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
    #: For a "number" finding, the value approved memory states, as written
    #: there; for "bound", what the rule allows ("48 hours or more").
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
    #: Approved rules no exact check can test ("Never claim health benefits"),
    #: as `{"id", "claim", "path"}`: a clean result says nothing about them.
    #: Rules for another channel than `channel` are not among them.
    untested: tuple[dict[str, str], ...] = ()

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
            "needs_review": list(self.untested),
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


#: The period a price is for, written after it: "£9 a month", "$20 per month",
#: "Rs 999/year", "£3 monthly". A price for another period is another price.
_PERIOD = re.compile(
    r"^\s*(?:(?:a|an|per|each|every|/)\s*(month|mo|year|yr|annum|week|wk|day)\b|"
    r"(monthly|annually|yearly|weekly|daily)\b)",
    re.IGNORECASE,
)
_PERIOD_NAME = {
    "month": "month",
    "mo": "month",
    "monthly": "month",
    "year": "year",
    "yr": "year",
    "annum": "year",
    "annually": "year",
    "yearly": "year",
    "week": "week",
    "wk": "week",
    "weekly": "week",
    "day": "day",
    "daily": "day",
}


def _period(sentence: str, exact: str) -> tuple[str, str]:
    """The period a money value is for, and the words that say it: ("month", " a month")."""
    at = sentence.find(exact)
    if at < 0:
        return "", ""
    match = _PERIOD.match(sentence[at + len(exact) :])
    if not match:
        return "", ""
    word = (match.group(1) or match.group(2)).lower()
    return _PERIOD_NAME[word], match.group(0).rstrip()


@dataclass(frozen=True)
class _Fact:
    """An approved line with values, and what it is about."""

    claim: dict[str, str]
    #: `(kind, normalised value, exact text, period)` for each value it states.
    values: tuple[tuple[str, str, str, str], ...]
    subject: frozenset[str]


def _fact(claim: dict[str, str]) -> _Fact | None:
    text = claim["claim"]
    if _NEGATION.search(text):
        # "Do not promise delivery in under 48 hours" is a limit, not a value;
        # comparing 48 with a draft's 24 would get the direction wrong half the time.
        return None
    remembered = _values(text)
    if not remembered:
        return None
    subject = _subject(f'{claim.get("section", "")} {text}', [kind for kind, _v, _t in remembered])
    if not subject:
        return None
    values = tuple(
        (kind, value, exact, _period(text, exact)[0] if kind == "money" else "")
        for kind, value, exact in remembered
    )
    return _Fact(claim, values, subject)


def _weights(facts: list[_Fact]) -> dict[str, dict[str, float]]:
    """How much each subject word tells facts of one kind apart, per kind.

    A word every price line shares ("Monzo", "month") says little about which
    plan a draft means; a word only one has ("Perks") says it. A word's weight
    is `log((n + 1) / df)`: `n` facts state a value of the kind, `df` of them
    have the word. With one fact every word weighs the same.
    """
    by_kind: dict[str, dict[str, frozenset[str]]] = {}
    for fact in facts:
        for kind in {kind for kind, *_rest in fact.values}:
            # One line stated in two documents is one fact, not two.
            by_kind.setdefault(kind, {})[fact.claim["claim"].casefold()] = fact.subject
    weights: dict[str, dict[str, float]] = {}
    for kind, subjects in by_kind.items():
        count: dict[str, int] = {}
        for subject in subjects.values():
            for word in subject:
                count[word] = count.get(word, 0) + 1
        n = len(subjects)
        weights[kind] = {word: math.log((n + 1) / df) for word, df in count.items()}
    return weights


def _about(fact: _Fact, words: frozenset[str], weights: dict[str, float]) -> float:
    """How well a statement's words name a fact's subject: 0 when they do not.

    About the same thing: at least two of the fact's subject words (or its only
    one), and at least half of the subject's weight. Returns the share of the
    weight the statement names, so the best-named fact can be told apart.
    """
    shared = fact.subject & words
    if len(shared) < min(2, len(fact.subject)):
        return 0.0
    total = sum(weights.get(word, 0.0) for word in fact.subject)
    named = sum(weights.get(word, 0.0) for word in shared)
    if total <= 0 or named * 2 < total:
        return 0.0
    return named / total


def _agrees(kind: str, fact_value: tuple[str, str, str, str], value: str, period: str) -> bool:
    _kind, mine, _exact, my_period = fact_value
    if kind == "date":
        return _same_date(mine, value)
    if mine != value:
        return False
    # "£9" agrees with "£9 a month"; "£9 a year" does not.
    return not (my_period and period and my_period != period)


def _number_findings(draft: str, claims: list[dict[str, str]]) -> list[Finding]:
    """Values in the draft that differ from what approved memory says about their subject.

    A statement can be about several approved lines: "Monzo Perks costs £9 a
    month" shares words with the Extra line and the Perks line. A value any of
    them states is correct. Otherwise the finding is against the line the
    statement names best, once per quote.
    """
    facts = [fact for fact in (_fact(claim) for claim in claims) if fact is not None]
    if not facts:
        return []
    weights = _weights(facts)
    units = [u.strip() for u in _UNIT_BREAK.split(draft) if u and u.strip()]
    findings: list[Finding] = []
    for index, statement in enumerate(units):
        written = _values(statement)
        if not written:
            continue
        alone = _subject(statement)
        before = units[index - 1] if index else ""
        with_before = _subject(f"{before} {statement}") if before else frozenset()
        earlier = {k for k, _v, _t in _values(before)} if before else set()
        for kind, value, exact in written:
            # A statement says what its subject is, or the one before it does
            # when that one has no value of its own kind: "Our gift box is
            # back. Now just Rs 999."
            windows = [alone] + ([with_before] if with_before and kind not in earlier else [])
            period, period_text = _period(statement, exact) if kind == "money" else ("", "")
            # A fact can state two values of one kind ("Orders below Rs 999 pay
            # Rs 79"): a statement that repeats either one agrees with it.
            stated = [
                (v, _period(statement, t)[0] if kind == "money" else "")
                for k, v, t in written
                if k == kind
            ]
            matched: list[tuple[float, _Fact]] = []
            agreed = False
            for fact in facts:
                mine = [v for v in fact.values if v[0] == kind]
                if not mine:
                    continue
                score = max(_about(fact, words, weights.get(kind, {})) for words in windows)
                if not score:
                    continue
                if any(_agrees(kind, v, said, when) for v in mine for said, when in stated):
                    agreed = True
                    break
                matched.append((score, fact))
            if agreed or not matched:
                continue
            top = max(score for score, _fact in matched)
            best = next(fact for score, fact in matched if score == top)
            same = [v for v in best.values if v[0] == kind]
            # Only the period differs ("£9 a year" for "£9 a month"): say both.
            only_period = any(v[1] == value for v in same)
            quote = exact + period_text if only_period else exact
            if any(f.quote == quote for f in findings):
                continue
            label = kind.split(":")[0]
            expected = " or ".join(
                t + (_period(best.claim["claim"], t)[1] if only_period else "")
                for _k, _v, t, _p in same
            )
            # The same line in two documents (a kit synced as Word and as PDF)
            # is one finding that names both; `check_draft` merges them.
            for _score, fact in matched:
                if fact.claim["claim"].casefold() != best.claim["claim"].casefold():
                    continue
                findings.append(
                    Finding(
                        "number",
                        fact.claim["id"],
                        fact.claim["claim"],
                        fact.claim["path"],
                        quote,
                        f"The draft says {quote} where approved memory says {expected} "
                        f"({label}).",
                        expected=expected,
                    )
                )
    return findings


# ------------------------------------------------------------------ limits on values

#: The comparison a phrase before a value states, and the phrases that state a
#: limit on their own ("up to 25%"), without a "not" or "never" before them.
_BOUND_PHRASES = [
    ("lt", r"under|less than|fewer than|below|faster than|sooner than|shorter than"),
    ("le", r"within|at most|no more than|up to|maximum of"),
    ("gt", r"over|more than|above|exceeds?|exceeding|longer than|beyond|slower than"),
    ("ge", r"at least|no less than|minimum of"),
]
_BOUND = re.compile(
    r"(?<![\w'])(?:"
    + "|".join(f"(?P<{op}>{words})" for op, words in _BOUND_PHRASES)
    + r")(?![\w'])\s+(?:a\s+|of\s+)?",
    re.IGNORECASE,
)
_CAP_ON_ITS_OWN = re.compile(
    r"^(?:at most|no more than|up to|maximum of|at least|no less than|minimum of)$", re.I
)
_RULE_NEGATION = re.compile(
    r"(?<![\w'])(?:not|never|don't|cannot|can't|mustn't|no(?!\s+(?:more|less|fewer)\b))"
    r"(?![\w'])",
    re.IGNORECASE,
)
_OPPOSITE = {"lt": "ge", "le": "gt", "gt": "le", "ge": "lt"}
_BOUND_KINDS = ("money", "percent", "duration")
_HOURS = {"hour": 1, "day": 24, "week": 168, "month": 720, "year": 8760}
#: Words a limit is phrased with, not what it is about.
_BOUND_GLUE = frozenset(
    """do not never no don dont must should always promise say state claim mention
    write use under over than least most more less fewer up within exceed exceeding
    beyond above below faster sooner longer shorter slower maximum minimum any take
    takes""".split()
)


@dataclass(frozen=True)
class Bound:
    """What an approved rule allows a value to be: `op` against `limit`."""

    kind: str
    op: str
    limit: float
    #: The rule's own value, as written ("48 hours").
    text: str
    subject: frozenset[str]

    @property
    def allowed(self) -> str:
        return {
            "lt": f"under {self.text}",
            "le": f"{self.text} or less",
            "gt": f"over {self.text}",
            "ge": f"{self.text} or more",
        }[self.op]

    def admits(self, value: float) -> bool:
        return {
            "lt": value < self.limit,
            "le": value <= self.limit,
            "gt": value > self.limit,
            "ge": value >= self.limit,
        }[self.op]


def _magnitude(kind: str, value: str) -> tuple[str, float] | None:
    """A value as a number comparable with others of its kind: durations in hours."""
    try:
        number = float(value.split()[0])
    except (ValueError, IndexError):
        return None
    if kind.startswith("duration:"):
        hours = _HOURS.get(kind.split(":", 1)[1])
        return ("duration", number * hours) if hours else None
    return (kind, number) if kind in _BOUND_KINDS else None


def _prefixes(words: Iterable[str]) -> frozenset[str]:
    return frozenset(word[:5] for word in words if not word.isdigit())


def bound_rule(rule: str, section: str = "") -> Bound | None:
    """The limit a rule puts on a price, a percentage or a duration, if it puts one.

    "Do not promise delivery in under 48 hours" allows 48 hours or more, and
    "Discounts never exceed 30%" allows 30% or less. A rule bounds a value only
    when it forbids one side ("not", "never") or caps it on its own ("up to",
    "at least"): "Orders below Rs 999 pay Rs 79" states a condition, not a
    limit. Lengths and counts of marks are a channel's limits, not these.
    """
    for match in _BOUND.finditer(rule):
        value = next(
            (
                found
                for found in _values(rule[match.end() :])
                if rule[match.end() :].startswith(found[2])
            ),
            None,
        )
        if value is None:
            continue
        measured = _magnitude(value[0], value[1])
        if measured is None:
            continue
        op = next(name for name in ("lt", "le", "gt", "ge") if match.group(name))
        phrase = match.group(op)
        negated = bool(_RULE_NEGATION.search(rule[: match.start()]))
        if not negated and not _CAP_ON_ITS_OWN.match(phrase):
            continue
        subject = _prefixes(
            word for word in _subject(f"{section} {rule}") if word not in _BOUND_GLUE
        )
        if not subject:
            continue
        return Bound(
            kind=measured[0],
            op=_OPPOSITE[op] if negated else op,
            limit=measured[1],
            text=value[2],
            subject=subject,
        )
    return None


def _bound_findings(draft: str, claim: dict[str, str]) -> list[Finding]:
    """Values in the draft on the wrong side of the claim's limit, about its subject."""
    bound = bound_rule(claim["claim"], claim.get("section", ""))
    if bound is None:
        return []
    findings: list[Finding] = []
    for context, statement in _windows(draft):
        shared = bound.subject & _prefixes(_subject(f"{context} {statement}"))
        if not shared or (len(bound.subject) >= 3 and len(shared) < 2):
            continue
        for kind, value, exact in _values(statement):
            measured = _magnitude(kind, value)
            if measured is None or measured[0] != bound.kind or bound.admits(measured[1]):
                continue
            if any(f.quote == exact for f in findings):
                continue
            findings.append(
                Finding(
                    "bound",
                    claim["id"],
                    claim["claim"],
                    claim["path"],
                    exact,
                    f"The draft says {exact}, and an approved rule allows only {bound.allowed}.",
                    expected=bound.allowed,
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
    r"|less than|between|at least|min(?:imum)?|no fewer than|no less than)\b",
    re.I,
)
_UNIT = {
    "characters": r"(?:characters?|chars?)",
    "words": r"words?",
    "hashtags": r"hashtags?",
    "emojis": r"emojis?",
}
_N = r"(\d[\d,]*)"
_TO = r"\s*(?:-|–|—|to|and)\s*"


def _range(part: str, kind: str) -> tuple[int, int] | None:
    """`(least, most)` when a part states a range for `kind`: "Hashtags: 5 to 8",
    "5–8 hashtags", "between 100 and 150 characters"."""
    unit = _UNIT[kind]
    for pattern in (
        rf"\b{unit}\s*:?\s*(?:between\s+)?{_N}{_TO}{_N}\b",
        rf"(?:\bbetween\s+)?\b{_N}{_TO}{_N}\s*{unit}\b",
    ):
        match = re.search(pattern, part, re.I)
        if match:
            least, most = (int(group.replace(",", "")) for group in match.groups())
            if least <= most:
                return least, most
    return None


def _minimum(part: str, kind: str) -> int | None:
    """The least a part asks for: "at least 3 hashtags", "Hashtags: 3 or more"."""
    unit = _UNIT[kind]
    for pattern in (
        rf"(?:at least|min(?:imum)?(?: of)?|no fewer than|no less than)\s*{_N}\s*{unit}\b",
        rf"\b{unit}\s*:?\s*(?:at least|min(?:imum)?(?: of)?)\s*{_N}\b",
        rf"\b{unit}\s*:?\s*{_N}\s*or more\b",
        rf"\b{_N}\s*{unit}\s*or more\b",
    ):
        match = re.search(pattern, part, re.I)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


#: A channel's own line: "Instagram: Length: 150 characters; Hashtags: 3 at most".
_CHANNEL_ROW = re.compile(r"^([A-Z][\w-]*(?: [A-Z][\w-]*){0,2}):\s")
#: A channel named inside a sentence: "on LinkedIn", "Instagram captions".
_CHANNEL_NAMED = re.compile(
    r"\b(Instagram|LinkedIn|WhatsApp|Facebook|Twitter|TikTok|YouTube|Threads|Email|SMS)\b"
)


def _channel_bounds(claim: str) -> tuple[str | None, dict[str, tuple[int, int | None]]]:
    """The channel a line limits, and for each kind its `(least, most)`; `most`
    is None when the line sets only a minimum. Kinds keep the line's order."""
    row = _CHANNEL_ROW.match(claim)
    channel = row.group(1) if row else None
    if channel is None:
        named = _CHANNEL_NAMED.search(claim)
        channel = named.group(1) if named else None
    if channel is None:
        return None, {}
    bounds: dict[str, tuple[int, int | None]] = {}
    for part in claim.split(";"):
        for kind in ("characters", "words", "hashtags", "emojis"):
            if kind in bounds:
                continue
            length = kind in ("characters", "words")
            if length and not (row or _LENGTH_IS_LIMIT.search(part)):
                continue
            span = _range(part, kind)
            if span:
                bounds[kind] = span
                continue
            match = _LIMITS[kind].search(part)
            if match and length:
                bounds[kind] = (0, int(match.group(1).replace(",", "")))
                continue
            least = _minimum(part, kind)
            if match and not length:
                number = next((g for g in match.groups() if g and g.isdigit()), None)
                bounds[kind] = (least or 0, int(number) if number else 0)
            elif least is not None:
                bounds[kind] = (least, None)
    # A length in characters or words with a minimum and no maximum comes from
    # "at least 50 words", which `_LIMITS` reads as at most 50: the minimum wins.
    for kind in ("characters", "words"):
        if kind in bounds:
            for part in claim.split(";"):
                least = _minimum(part, kind)
                if least is not None and _range(part, kind) is None:
                    bounds[kind] = (least, None)
    bounds = {kind: span for kind, span in bounds.items() if span != (0, None)}
    return (channel, bounds) if bounds else (None, {})


def channel_limits(claim: str) -> tuple[str | None, dict[str, int]]:
    """The channel a line limits and its limits: ("Instagram", {"characters": 150}).

    Read from a table row ("Instagram: Length: 150 characters; Hashtags: 5 to
    8") or a sentence naming the channel ("Keep LinkedIn posts under 120
    words"). A range gives its upper end here; `channel_minimums` gives the
    lower. A line with no channel, or no limit, gives `(None, {})`.
    """
    channel, bounds = _channel_bounds(claim)
    most = {kind: high for kind, (_low, high) in bounds.items() if high is not None}
    return (channel, most) if most else (None, {})


def channel_minimums(claim: str) -> tuple[str | None, dict[str, int]]:
    """The least a channel line asks for: ("Instagram", {"hashtags": 5}) from
    "Hashtags: 5 to 8" or "at least 5 hashtags". `(None, {})` when none."""
    channel, bounds = _channel_bounds(claim)
    least = {kind: low for kind, (low, _high) in bounds.items() if low}
    return (channel, least) if least else (None, {})


def _counts(draft: str) -> dict[str, int]:
    text = draft.strip()
    return {
        "characters": len(text),
        "words": len(text.split()),
        "hashtags": len(_HASHTAG.findall(text)),
        "emojis": sum(1 for char in text if _is_emoji(char)),
    }


def _limit_findings(draft: str, claims: list[dict[str, str]], channel: str) -> list[Finding]:
    """Where the draft is longer or shorter, or has more or fewer hashtags or
    emojis, than its channel allows."""
    counts = _counts(draft)
    findings: list[Finding] = []
    seen: set[str] = set()
    for claim in claims:
        named, bounds = _channel_bounds(claim["claim"])
        if not named or named.lower().rstrip("s") not in channel.lower():
            continue
        for kind, (least, most) in bounds.items():
            count = counts[kind]
            over = most is not None and count > most
            under = count < least
            if not (over or under) or kind in seen:
                continue
            seen.add(kind)
            unit = kind if count != 1 else kind[:-1]
            if most is not None and least:
                allows = f"{least} to {most}"
            elif most is not None:
                allows = f"at most {most}" if most else f"no {kind}"
            else:
                allows = f"at least {least}"
            verb = "allows" if over else "asks for"
            findings.append(
                Finding(
                    "limit",
                    claim["id"],
                    claim["claim"],
                    claim["path"],
                    f"{count} {unit}",
                    f"The draft has {count} {unit}; {named} {verb} {allows}.",
                    expected=str(most if over else least),
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
    headings: dict[str, str] = {}
    for evidence in _get(current, "evidence", []) or []:
        heading = str(_get(evidence, "heading", "") or "")
        headings.setdefault(str(_get(evidence, "claim_id", "")), heading)
        parts = heading.split(" > ")
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
        if finding.kind == "banned" and len(finding.quote) > 1 and finding.quote[0] != "#":
            # One word banned by two rules worded differently ('the word
            # "premium"' and 'the word premium') is one thing to remove.
            same = ("banned", "", finding.quote.casefold())
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
    for finding in _number_findings(draft, claims):
        add(finding)
    for claim in claims:
        for finding in _bound_findings(draft, claim):
            if not any(f.quote == finding.quote for f in findings if f.kind == "number"):
                add(finding)
    if channel:
        for finding in _limit_findings(draft, claims, channel):
            add(finding)
    if unsupported:
        # A value already shown to differ from an approved one, or to break a
        # limit, is not reported twice; that finding says what it should be.
        differing = {f.quote.lower() for f in findings if f.kind in ("number", "bound")}
        for finding in _unsupported_findings(draft, claims, supported_by):
            if finding.quote.lower() not in differing:
                add(finding)
    return Check(
        corpus=str(_get(current, "corpus", "")),
        findings=tuple(findings),
        checked=len(claims),
        banned_rules=banned_rules,
        unsupported_checked=unsupported,
        untested=tuple(_untested(claims, headings, channel)),
    )


def _untested(
    claims: list[dict[str, str]], headings: dict[str, str], channel: str | None
) -> list[dict[str, str]]:
    """The rules among `claims` that no check here can test exactly.

    A rule is what a brief calls one (`verilore.brief.is_rule`), or a line that
    opens with an instruction ("Use Indian English spelling", "Keep sentences
    under 20 words"). It is tested when it bans text or a kind of mark, sets a
    limit on a value, or states values a draft is compared with. A channel's
    line ("Instagram: Length: 150 characters") is tested when `channel` names
    it, and untested without `channel`. A rule for another channel than
    `channel` is not listed: it cannot apply.
    """
    from verilore.brief import is_rule
    from verilore.review import _instruction

    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for claim in claims:
        text = claim["claim"]
        if text.casefold() in seen:
            continue
        named, _bounds = _channel_bounds(text)
        mentioned = named or rule_channel(text) or _channel_in(text)
        if channel and mentioned and mentioned.lower().rstrip("s") not in channel.lower():
            continue
        if named:
            if channel:
                continue
        elif not (is_rule(text, headings.get(claim["id"])) or _instruction(text)):
            continue
        elif banned_text(text) or bound_rule(text, claim.get("section", "")):
            continue
        elif _values(text) and not _NEGATION.search(text):
            continue
        seen.add(text.casefold())
        found.append({"id": claim["id"], "claim": text, "path": claim["path"]})
    return found


_CHANNEL_IN = re.compile(
    r"\b(Instagram|LinkedIn|WhatsApp|Facebook|Twitter|TikTok|YouTube|Threads|emails?|"
    r"newsletters?|blogs?|SMS|websites?)\b",
    re.IGNORECASE,
)


def _channel_in(text: str) -> str | None:
    """The first channel a line names anywhere, "Instagram" or "emails"."""
    match = _CHANNEL_IN.search(text)
    return match.group(1) if match else None


def _needs_review(check: Check) -> list[str]:
    if not check.untested:
        return []
    count = len(check.untested)
    lines = [
        f"Needs a reviewer: check cannot test {'these' if count != 1 else 'this'} "
        f"{count} rule{'s' if count != 1 else ''} exactly."
    ]
    lines += [f'- {line["claim"]}  [{line["path"]}]' for line in check.untested]
    return lines


def render_check(check: Check) -> str:
    """The result for a person: the findings, then the rules nothing tested."""
    if check.ok:
        return "\n".join(
            [
                f"No problems found against {check.checked} approved lines "
                f"({check.banned_rules} name banned text). Tone and voice are a reviewer's call.",
                *_needs_review(check),
            ]
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
    return "\n".join(out + _needs_review(check))


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
            wanted = plural if finding.expected != "1" else plural[:-1]
            fewer = int(count) < int(finding.expected)
            if plural in ("characters", "words"):
                change = (
                    f"Lengthen the draft to at least {finding.expected} {wanted}"
                    if fewer
                    else f"Shorten the draft to at most {finding.expected} {wanted}"
                )
            elif finding.expected == "0":
                change = f"Remove every {plural[:-1]}"
            else:
                change = f"Use {'at least' if fewer else 'at most'} {finding.expected} {wanted}"
            lines.append(f"- {change}; it has {count}. Approved: {finding.claim}")
        elif finding.kind == "bound":
            lines.append(
                f"- Remove {finding.quote}, or change it to a value the rule allows "
                f"({finding.expected}). Approved rule: {finding.claim}"
            )
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
