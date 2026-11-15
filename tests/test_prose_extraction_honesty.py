"""Prose extraction neither truncates a sentence nor drops prose silently.

The failure this covers: a brand kit written as paragraphs, wrapped the way a
writer wraps a long line, was read one physical line at a time. "We never
shout or use slang in any" was archived as a claim, and "of our launch copy."
was not archived at all. Worse, the structural reader dropped prose lines that
were not part of a statement without saying so, so an author could ingest a
brand kit, see `success=True`, and hold no memory of the sentence they cared
about.

What is asserted here:

* a sentence wrapped over two physical lines extracts as ONE claim whose text
  is the whole sentence, with the internal line break kept verbatim;
* a paragraph is read in every document, beside bullets or alone: each
  sentence that states something is a claim (#158);
* a sentence that was left out is reported once with the code
  `prose_not_extracted`, a count and a hint, through the same warning list the
  frontmatter warnings use. In the default mode that is only a sentence with
  no checkable evidence; in `prose: rules` it is every sentence with no rule
  word;
* the ingest HTTP response carries those warnings, and carries nothing at all
  when there is nothing to say;
* bullet, field and table extraction is unchanged, byte for byte.
"""

from __future__ import annotations

from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from verilore.api.main import app
from verilore.api.services.markdown_claims import extract
from verilore.api.services.parser import (
    chunk_with_heading_paths,
    extract_sections_with_paths,
)

WRAPPED = (
    "# Guide\n"
    "\n"
    "## Voice\n"
    "\n"
    "Our voice is warm, plain and confident.\n"
    "We never shout or use slang in any\n"
    "of our launch copy.\n"
)

BULLET_AND_PROSE = (
    "# Guide\n"
    "\n"
    "## Voice\n"
    "\n"
    "- Our voice is warm.\n"
    "\n"
    "This is a prose sentence that must be extracted too.\n"
)

PROSE_ONLY = "# Specs\n\n## Facts\n\nThe Trailhead 2 bike weighs 9.8 kilograms.\n"

WRAPPED_BULLET = (
    "# Guide\n"
    "\n"
    "## Do not use\n"
    "\n"
    "- Never promise free shipping\n"
    "  in any of our ads.\n"
)

UNRECOGNISED_STATUS = (
    "---\n"
    "status: maybe-later\n"
    "---\n"
    "\n"
    "# Note A\n"
    "\n"
    "- Our voice is warm and steady.\n"
)


def chunks_for(body: str) -> list[dict]:
    return [
        {**chunk, "order_index": index}
        for index, chunk in enumerate(chunk_with_heading_paths(extract_sections_with_paths(body)))
    ]


def prose_warnings(warnings: list) -> list:
    return [w for w in warnings if getattr(w, "code", None) == "prose_not_extracted"]


async def ingest(client: AsyncClient, corpus: str, content: str, path: str):
    response = await client.post(
        "/api/ingest/file",
        json={"content": content, "path": path, "corpus": corpus},
    )
    return response


async def make_corpus(client: AsyncClient) -> str:
    name = f"t{uuid4().hex[:12]}"
    response = await client.post("/api/corpora", json={"name": name})
    assert response.status_code == 201, response.text
    return name


# ---------------------------------------------------------------------------
# 1: a wrapped sentence is one claim, whole
# ---------------------------------------------------------------------------


def test_a_wrapped_sentence_extracts_whole():
    claims, _warnings = extract(WRAPPED, chunks_for(WRAPPED), path="guide.md")
    collapsed = [" ".join(claim["claim"].split()) for claim in claims]
    assert "We never shout or use slang in any of our launch copy." in collapsed
    assert all(claim["claim"] != "We never shout or use slang in any" for claim in claims)


# ---------------------------------------------------------------------------
# 2: prose beside a bullet is extracted, and nothing is left to report
# ---------------------------------------------------------------------------


def test_prose_beside_bullets_is_extracted():
    """The second case in #158: the paragraph under the bullet is memory too."""
    claims, warnings = extract(BULLET_AND_PROSE, chunks_for(BULLET_AND_PROSE), path="guide.md")
    texts = [claim["claim"] for claim in claims]
    assert texts.count("Our voice is warm.") == 1, claims
    assert "This is a prose sentence that must be extracted too." in texts, claims
    assert prose_warnings(warnings) == []


# ---------------------------------------------------------------------------
# 3: a plain fact in a paragraph is a claim; `rules` mode still reports it
# ---------------------------------------------------------------------------


def test_a_fact_with_no_rule_word_is_a_claim():
    """The first case in #158: a sentence needs no must/never/always to count."""
    claims, warnings = extract(PROSE_ONLY, chunks_for(PROSE_ONLY), path="specs.md")
    assert [claim["claim"] for claim in claims] == ["The Trailhead 2 bike weighs 9.8 kilograms."]
    assert claims[0]["evidence"] in PROSE_ONLY
    assert warnings == []


def test_rules_mode_keeps_the_old_reading_and_reports_what_it_skipped():
    claims, warnings = extract(PROSE_ONLY, chunks_for(PROSE_ONLY), path="specs.md", prose="rules")
    assert claims == [], claims
    skipped = prose_warnings(warnings)
    assert len(skipped) == 1
    assert skipped[0].count == 1


# ---------------------------------------------------------------------------
# 4: a wrapped bullet is unchanged, and earns no warning
# ---------------------------------------------------------------------------


def test_a_wrapped_bullet_is_unchanged_and_reports_nothing():
    claims, warnings = extract(WRAPPED_BULLET, chunks_for(WRAPPED_BULLET), path="guide.md")
    assert len(claims) == 1
    assert claims[0]["claim"] == "Never promise free shipping\n  in any of our ads."
    assert prose_warnings(warnings) == []


# ---------------------------------------------------------------------------
# 5: the ingest response carries the warning
# ---------------------------------------------------------------------------


async def test_ingest_response_carries_prose_warnings():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await make_corpus(client)
        # A document with no bullets at all takes the memory path once the
        # corpus holds an archive; seed one so the test exercises what a
        # brand corpus looks like after its first memory lands.
        seed = await ingest(client, corpus, WRAPPED_BULLET, "brand/seed.md")
        assert seed.status_code == 200, seed.text
        rules_only = "---\nprose: rules\n---\n\n" + PROSE_ONLY
        response = await ingest(client, corpus, rules_only, "brand/specs.md")
    assert response.status_code == 200, response.text
    warnings = response.json().get("warnings", [])
    assert any(w.get("code") == "prose_not_extracted" for w in warnings), response.text


# ---------------------------------------------------------------------------
# 6: a document with nothing to say omits the field entirely
# ---------------------------------------------------------------------------


async def test_ingest_response_omits_warnings_when_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await make_corpus(client)
        response = await ingest(client, corpus, WRAPPED_BULLET, "brand/guide.md")
    assert response.status_code == 200, response.text
    assert "warnings" not in response.json()


# ---------------------------------------------------------------------------
# 7: the response carries the existing frontmatter warnings too
# ---------------------------------------------------------------------------


async def test_ingest_response_carries_frontmatter_warnings():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        corpus = await make_corpus(client)
        response = await ingest(client, corpus, UNRECOGNISED_STATUS, "notes/note-a.md")
    assert response.status_code == 200, response.text
    warnings = response.json().get("warnings", [])
    assert any(w.get("code") == "unknown_status" for w in warnings), response.text
