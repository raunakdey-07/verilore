"""Lines from two documents that disagree are shown to the model as disagreeing (BRIEF-5).

Old workshop notes said "We guarantee delivery within 24 hours"; the brand
rules said "Do not promise delivery in under 48 hours". `review` found the
pair, but the brief printed both under "Every line below is current and
approved... Do not contradict these lines", and the only hint was on the
terminal, where a model cannot read it. Now a pair that states a difference,
two values of one kind for the same thing or nearly the same line with "not" in
one of them, is taken out of the list and printed in its own block, which tells
the model not to choose. A line under `must` is the one that holds: the line
that disagrees with it is left out and counted.

Words cannot tell "Use Indian English spelling" / "Use American spelling" (one
or the other) from "Mention the estate name" / "Mention the price" (both), so
the same verb with different details is left to `review` and stays in the list.
Neither is a rule repeated, two bans, two products or two channels.
"""

from __future__ import annotations

import pytest

BLOCK = (
    "These lines come from different documents and may disagree. Do not choose "
    "between them; where the task depends on one, leave that point out:"
)


def _claim(n, text, path):
    return {"id": f"c{n}", "claim": text, "path": path, "status": "CURRENT"}


def _response(claims, evidence=()):
    return {
        "corpus": "kaveri",
        "current_memories": list(claims),
        "conflicts": [],
        "evidence": list(evidence),
    }


def _brief(claims, evidence=(), **kwargs):
    from verilore.brief import render_brief

    return render_brief(_response(claims, evidence), **kwargs)


def _body(brief):
    """The lines of the list, not of the block."""
    text = brief.text.split(BLOCK)[0]
    return [line[2:] for line in text.splitlines() if line.startswith("- ")]


DELIVERY = [
    _claim(1, "Do not promise delivery in under 48 hours.", "brand/voice.md"),
    _claim(2, "We guarantee delivery within 24 hours.", "notes/workshop-2024.md"),
    _claim(3, "We sound like a friend who knows coffee.", "brand/voice.md"),
]


def test_a_pair_that_disagrees_is_printed_apart_with_what_to_do():
    brief = _brief(DELIVERY)
    assert _body(brief) == ["We sound like a friend who knows coffee."]
    assert brief.text.splitlines()[-2:] == [
        BLOCK,
        "- Do not promise delivery in under 48 hours. [brand/voice.md]  |  "
        "We guarantee delivery within 24 hours. [notes/workshop-2024.md]",
    ]
    assert len(brief.disagreements) == 1
    assert set(brief.claim_ids) == {"c1", "c2", "c3"} and brief.omitted == 0


@pytest.mark.parametrize(
    "left,right",
    [
        ("The Estate Blend costs Rs 1499.", "The Estate Blend costs Rs 1299."),
        ("The offer ends on 30 November 2026.", "The offer ends on 15 December 2026."),
        ("Free shipping on orders above Rs 999.", "Free shipping on orders above Rs 499."),
        (
            "The Trailhead 2 bike weighs 9.8 kilograms.",
            "The Trailhead 2 bike weighs 10.4 kilograms.",
        ),
        ("Do not use exclamation marks.", "Use exclamation marks in headlines."),
        ("Never use emojis in emails.", "Use two emojis in every email."),
    ],
)
def test_two_values_for_one_thing_or_a_not_is_a_disagreement(left, right):
    brief = _brief([_claim(1, left, "brand/a.md"), _claim(2, right, "notes/b.md")])
    assert _body(brief) == [] and len(brief.disagreements) == 1


@pytest.mark.parametrize(
    "left,right",
    [
        # The same rule, worded twice.
        ('Never use the word "premium".', "Never use the word premium."),
        # Two bans can both be kept.
        ("Do not promise delivery in under 48 hours.", "Never promise same-day delivery."),
        # A line that only says less than the other.
        (
            "Instagram: Length: 150 characters; Emojis: 2 at most; Hashtags: 3 at most",
            "Instagram: Length: 150 characters; Hashtags: 3",
        ),
        # Two channels.
        ("Use five hashtags on Instagram posts.", "Never use hashtags on LinkedIn posts."),
        # Two sizes: two things, each with its price.
        ("The 250 g tin costs Rs 520.", "The 100 g tin costs Rs 290."),
        # A rule and its exception.
        ("Never write in all capitals.", "Write the estate name in capitals."),
        # The same verb, details that go together.
        ("Mention the estate name in every caption.", "Mention the price in every caption."),
        # The same verb, details that do not; words cannot tell. `review` lists it.
        ("Use Indian English spelling.", "Use American spelling in all copy."),
    ],
)
def test_lines_that_words_cannot_show_to_disagree_stay_in_the_list(left, right):
    brief = _brief([_claim(1, left, "brand/a.md"), _claim(2, right, "notes/b.md")])
    assert BLOCK not in brief.text
    assert sorted(_body(brief)) == sorted([left, right]) and brief.disagreements == ()


def test_prices_of_two_products_are_not_a_disagreement_and_two_prices_of_one_are():
    claims = [
        _claim(1, "Price: Rs 520 for a 250 g tin.", "brand/products.md"),
        _claim(2, "Price: Rs 640 for a 100 g tin.", "brand/products.md"),
        _claim(3, "Price: Rs 450 for a 250 g tin of Assam Gold.", "notes/2025-pricing.md"),
    ]
    evidence = [
        {"claim_id": "c1", "heading": "Products > Assam Gold"},
        {"claim_id": "c2", "heading": "Products > Kashmiri Kahwa"},
    ]
    brief = _brief(claims, evidence)
    assert _body(brief) == ["Kashmiri Kahwa: Price: Rs 640 for a 100 g tin."]
    assert brief.text.splitlines()[-1] == (
        "- Assam Gold: Price: Rs 520 for a 250 g tin. [brand/products.md]  |  "
        "Price: Rs 450 for a 250 g tin of Assam Gold. [notes/2025-pricing.md]"
    )


def test_a_line_under_must_holds_and_the_line_that_disagrees_is_left_out_and_counted():
    brief = _brief(DELIVERY, must=["brand/voice.md"])
    assert BLOCK not in brief.text
    assert "We guarantee delivery within 24 hours." not in brief.text
    assert "Do not promise delivery in under 48 hours." in _body(brief)
    assert brief.overruled == 1 and "c2" not in brief.claim_ids
    assert brief.kept + brief.omitted + brief.overruled == 3
    assert brief.text.splitlines()[-1] == (
        "Not included: 1 that may disagree with a line marked must."
    )


def test_the_block_fits_the_limit_at_every_size():
    from verilore.brief import approx_tokens

    claims = [
        *DELIVERY,
        _claim(4, "The Estate Blend costs Rs 1499.", "brand/products.md"),
        _claim(5, "The Estate Blend costs Rs 1299.", "notes/workshop-2024.md"),
        *[
            _claim(10 + n, f"The Coorg blend is roasted in batch {n}.", "brand/c.md")
            for n in range(30)
        ],
    ]
    for limit in range(400, 2600, 23):
        brief = _brief(claims, max_chars=limit)
        assert len(brief.text) <= limit
        assert brief.kept + brief.omitted == len(claims)
    for limit in range(100, 700, 11):
        brief = _brief(claims, max_tokens=limit, task="Instagram caption")
        assert approx_tokens(brief.text) <= limit
        assert brief.kept + brief.omitted == len(claims)
    for limit in range(100, 700, 11):
        brief = _brief(claims, max_tokens=limit, must=["brand/voice.md"])
        assert approx_tokens(brief.text) <= limit
        assert brief.kept + brief.omitted + brief.overruled == len(claims)


def test_the_cli_json_names_the_pairs_printed_apart(monkeypatch):
    import json
    from types import SimpleNamespace

    from typer.testing import CliRunner

    import verilore.cli.main as cli

    def brief(corpus, *, path_prefix=None, **options):
        from verilore.brief import render_brief

        return render_brief(_response(DELIVERY), path_prefix=path_prefix, **options)

    client = SimpleNamespace(memory=SimpleNamespace(brief=brief))
    monkeypatch.setattr(cli, "_client", lambda base_url, runtime=True: client)
    result = CliRunner().invoke(cli.app, ["brief", "--json"])
    body = json.loads(result.stdout if hasattr(result, "stdout") else result.output)
    assert body["disagreements"] == [p["id"] for p in body["possible_conflicts"]]
    assert len(body["disagreements"]) == 1 and body["overruled"] == 0
