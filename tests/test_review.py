"""What a person should settle before memory reaches a model (REVIEW-1).

Conflicts were detected only between claims sharing a key, and lines from two
documents never share one. So "Use Indian English spelling" and "Use American
spelling in all copy" were both served as approved. `likely_pairs` finds such
pairs for a person; nothing here resolves them, and the brief's text does not
change.

The cases come from a real review of a brand kit. The lines that must NOT be
paired matter as much as the ones that must: a review that flags every two
lines sharing a word is a review nobody reads.
"""

from __future__ import annotations

import json
import time

import httpx
from typer.testing import CliRunner

from live_server import live_server  # noqa: F401,F811  module-scoped server fixture
from verilore import Verilore

KIT = [
    ("brand/rules.md", "Use Indian English spelling."),
    ("notes/workshop.md", "Use American spelling in all copy."),
    ("brand/rules.md", "Do not promise delivery in under 48 hours."),
    ("notes/workshop.md", "Delivery is guaranteed within 24 hours in Bengaluru."),
    ("brand/rules.md", 'Never use the word "premium".'),
    ("memory/text-0f3a9c1b2d4e.md", "Do not use the word premium in any copy."),
    ("brand/specs.md", "The Trailhead 2 bike weighs 9.8 kilograms."),
    ("notes/workshop.md", "The Trailhead 2 bike weighs 10.4 kilograms."),
    # Must not be paired:
    ("campaigns/diwali/brief.md", "The gift box costs Rs 1,499."),
    ("brand/gifts.md", "The gift box ships in a cloth wrap."),
    ("campaigns/diwali/brief.md", "Orders close on 5 November 2026."),
    ("campaigns/new-year/brief.md", "Orders close on 28 December 2026."),
    ("brand/channels.md", "Instagram: Length: 150 characters; Hashtags: 3"),
    ("brand/blog.md", "Blog: Length: 800 words; Hashtags: 0"),
    ("brand/rules.md", "Never use emojis in body copy."),
    ("brand/voice.md", "Our voice is warm, plain and direct."),
]


def _claims(rows=KIT):
    return [
        {"id": f"c{n:02d}" + "0" * 10, "claim": text, "path": path}
        for n, (path, text) in enumerate(rows)
    ]


def _pairs(rows=KIT, **kwargs):
    from verilore.review import likely_pairs

    return likely_pairs(_claims(rows), **kwargs)


def _as_text(pairs):
    return {(p.left["claim"], p.right["claim"]): p.reasons for p in pairs}


def test_the_pairs_a_person_must_see_are_found_and_say_why():
    found, settled = _pairs()
    assert settled == 0
    assert _as_text(found) == {
        ("Use Indian English spelling.", "Use American spelling in all copy."): (
            "the same instruction with different details",
        ),
        (
            "Do not promise delivery in under 48 hours.",
            "Delivery is guaranteed within 24 hours in Bengaluru.",
        ): ('one says "not" and the other does not',),
        ('Never use the word "premium".', "Do not use the word premium in any copy."): (
            "nearly the same words",
        ),
        (
            "The Trailhead 2 bike weighs 9.8 kilograms.",
            "The Trailhead 2 bike weighs 10.4 kilograms.",
        ): ("nearly the same words", "different numbers: 9.8 / 10.4"),
    }
    # Most alike first, so a long list is read from its useful end.
    assert [p.score for p in found] == sorted((p.score for p in found), reverse=True)


def test_two_facts_about_one_thing_two_campaigns_and_two_table_rows_are_not_pairs():
    found, _ = _pairs()
    flagged = {text for pair in found for text in (pair.left["claim"], pair.right["claim"])}
    for line in (
        "The gift box costs Rs 1,499.",
        "Orders close on 5 November 2026.",
        "Instagram: Length: 150 characters; Hashtags: 3",
        "Never use emojis in body copy.",
        "Our voice is warm, plain and direct.",
    ):
        assert line not in flagged, line


def test_one_document_disagreeing_with_itself_is_its_authors_to_fix():
    rows = [
        ("brand/rules.md", "Use Indian English spelling."),
        ("brand/rules.md", "Use American spelling."),
    ]
    assert _pairs(rows)[0] == []


def test_a_settled_pair_is_counted_not_listed_and_its_id_is_the_same_either_way_round():
    from verilore.review import pair_id

    found, _ = _pairs()
    first = found[0]
    assert (
        pair_id(first.left["id"], first.right["id"])
        == pair_id(first.right["id"], first.left["id"])
        == first.id
    )
    again, settled = _pairs(settled=[first.id])
    assert settled == 1 and first.id not in {p.id for p in again}
    assert len(again) == len(found) - 1


def test_a_paragraph_is_not_paired_and_a_long_list_is_capped():
    paragraph = " ".join(["The delivery promise"] + ["word"] * 45) + "."
    rows = [("a.md", paragraph), ("b.md", "Do not promise delivery in under 48 hours.")]
    assert _pairs(rows)[0] == []
    many = [(f"doc{n}.md", f"The Trailhead {n} bike weighs {n}.5 kilograms.") for n in range(40)]
    assert len(_pairs(many, limit=7)[0]) == 7


def test_it_stays_fast_on_a_corpus_much_larger_than_a_brand_kit():
    rows = [
        (f"docs/{n % 97}.md", f"Rule {n}: the {w} channel uses {n % 13} hashtags and tone {w}.")
        for n, w in enumerate(["warm", "plain", "direct", "dry", "bold"] * 600)
    ]
    started = time.perf_counter()
    _pairs(rows)
    assert time.perf_counter() - started < 10


def test_the_review_lists_conflicts_drafts_and_pairs_and_resolves_nothing():
    from verilore.review import build_review, render_review

    current = {
        "corpus": "kaveri",
        "current_memories": _claims(KIT[:4]),
        "conflicts": [
            {"key": "tone", "claims": [_claims()[15], {**_claims()[14], "path": "x.md"}]}
        ],
    }
    drafts = {
        "current_memories": [
            *_claims(KIT[:1]),
            {
                "id": "d" * 12,
                "claim": "Our voice is bold and loud.",
                "path": "brand/refresh.md",
                "info_state": "draft",
            },
        ]
    }
    review = build_review(current, drafts, path_prefix="brand")
    assert (len(review.pairs), len(review.drafts), len(review.conflicts)) == (2, 1, 1)
    assert review.open_items == 4 and review.approved == 4 and review.scope == ("brand",)
    text = render_review(review)
    assert text.startswith('Review for "kaveri", scope brand: 4 to look at.')
    for heading in ("Conflicts on one key (1)", "Lines that may disagree (2)", "Drafts waiting"):
        assert heading in text
    assert "--supersedes" in text
    assert json.loads(json.dumps(review.as_dict()))["drafts"][0]["claim"] == (
        "Our voice is bold and loud."
    )
    empty = build_review({"corpus": "k", "current_memories": []})
    assert empty.open_items == 0 and "Nothing to review." in render_review(empty)


def test_the_page_is_self_contained_and_escapes_what_it_quotes():
    from verilore.review import build_review, render_review_html

    hostile = [
        ("brand/a.md", 'Use <script>alert("x")</script> spelling.'),
        ("notes/b.md", "Use American spelling in all copy."),
    ]
    page = render_review_html(
        build_review({"corpus": "k&co", "current_memories": _claims(hostile)})
    )
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "k&amp;co" in page
    assert "http://" not in page and "https://" not in page, "the page must not load anything"
    assert "prefers-color-scheme: dark" in page and 'name="viewport"' in page


def test_the_brief_carries_the_pairs_it_contains_but_does_not_tell_the_model():
    from verilore.brief import render_brief

    response = {"corpus": "kaveri", "current_memories": _claims(KIT[:4])}
    brief = render_brief(response)
    assert len(brief.possible_conflicts) == 2
    assert "disagree" not in brief.text and "review" not in brief.text


def test_the_cli_prints_writes_the_page_and_strict_exits_one(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import verilore.cli.main as cli
    from verilore.review import build_review

    review = build_review({"corpus": "kaveri", "current_memories": _claims(KIT[:4])})
    seen = {}

    def run(corpus, **kwargs):
        seen.update(corpus=corpus, **kwargs)
        return review

    monkeypatch.setattr(
        cli,
        "_client",
        lambda base_url, **kwargs: SimpleNamespace(memory=SimpleNamespace(review=run)),
    )
    runner = CliRunner()
    page = tmp_path / "review.html"
    plain = runner.invoke(
        cli.app, ["review", "--corpus", "kaveri", "--path-prefix", "brand", "--html", str(page)]
    )
    assert plain.exit_code == 0, plain.output
    assert seen == {"corpus": "kaveri", "path_prefix": ["brand"]}
    assert "Lines that may disagree (2)" in plain.output and page.read_text().startswith(
        "<!doctype html>"
    )
    as_json = runner.invoke(cli.app, ["review", "--corpus", "kaveri", "--json"])
    assert json.loads(as_json.output)["pairs"][0]["reasons"]
    assert runner.invoke(cli.app, ["review", "--corpus", "kaveri", "--strict"]).exit_code == 1


def test_end_to_end_the_review_reads_approved_lines_and_drafts(live_server):  # noqa: F811
    corpus, key = live_server.corpora["globex"], live_server.keys["globex"]
    kit = {
        "brand/rules.md": "---\nstatus: approved\n---\n\n# Rules\n\n"
        "- Use Indian English spelling.\n",
        "notes/workshop.md": "# Workshop\n\n- Use American spelling in all copy.\n",
        "brand/refresh.md": "---\nstatus: draft\n---\n\n# Refresh\n\n"
        "- Our voice is bold and loud.\n",
    }
    for path, content in kit.items():
        resp = httpx.post(
            f"{live_server.url}/api/ingest/file",
            json={"content": content, "path": path, "corpus": corpus},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text
    vl = Verilore(corpus, base_url=live_server.url, api_key=key, timeout=5, retries=1)
    review = vl.memory.review()
    assert [(p.left["claim"], p.right["claim"]) for p in review.pairs] == [
        ("Use Indian English spelling.", "Use American spelling in all copy.")
    ]
    assert [d["claim"] for d in review.drafts] == ["Our voice is bold and loud."]
    again = vl.memory.review(settled=[review.pairs[0].id])
    assert again.pairs == () and again.settled == 1
