"""A chunk boundary never falls inside a list item.

The chunker cuts a long run of bullets at the start of a statement, so each bullet
lands whole in one chunk and its claim has quotable evidence. It then trimmed a
trailing conjunction or preposition off every cut -- including a cut that already
sat on a statement boundary -- so a bullet ending "is for." was cut after "is",
split across two chunks, and its claim was lost with `claim_extraction_no_quote`.
The README and CHANGELOG both lost claims that way.
"""

from verilore.api.services.markdown_claims import claims_for
from verilore.api.services.parser import (
    chunk_with_heading_paths,
    extract_sections_with_paths,
    parse_markdown,
)

ENDINGS = ["what it is for.", "what it was built on.", "who it is with.", "the extra is for."]


def _bullets(count: int = 16) -> list[str]:
    return [
        f"- **Limit number {n} is written here.** This line is long enough to wrap\n"
        f"  onto a second line, and it ends by saying {ENDINGS[n % len(ENDINGS)]}"
        for n in range(count)
    ]


def _document(bullets: list[str]) -> str:
    return "# What it does not do\n\n" + "\n".join(bullets) + "\n"


def _chunks(document: str) -> list[str]:
    _, body = parse_markdown(document)
    return [c["text"] for c in chunk_with_heading_paths(extract_sections_with_paths(body))]


def test_the_list_is_long_enough_to_be_split():
    assert len(_chunks(_document(_bullets()))) > 1


def test_every_bullet_lands_whole_in_one_chunk():
    bullets = _bullets()
    chunks = _chunks(_document(bullets))
    for bullet in bullets:
        assert any(bullet in chunk for chunk in chunks), bullet


def test_no_claim_is_lost_to_a_boundary():
    metadata, body = parse_markdown(_document(_bullets()))
    records = [
        {**chunk, "order_index": i}
        for i, chunk in enumerate(chunk_with_heading_paths(extract_sections_with_paths(body)))
    ]
    derived, warnings = claims_for(metadata, body, records, path="limits.md")
    assert [w.as_dict() for w in warnings] == []
    assert len(derived["claims"]) == 16
