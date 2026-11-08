"""Claim keys survive edits around them (#160).

Extraction numbers claims by position. Before alignment, inserting one bullet at
the top of a section renumbered every bullet after it, so on re-ingest each of
them "superseded" its neighbour: adding one brand rule rewrote the history of
every rule below it. `align_keys` keeps a claim's key when its text is unchanged.

The first half tests the pure function. The second half ingests real documents
on the real schema (the `store` fixture: every migration, rolled back) and reads
`memory_claims` directly, so the assertions are about what the archive recorded.
"""

from sqlalchemy import text

from verilore.api.services import ingestion as ingestion_service
from verilore.api.services import markdown_claims
from verilore.api.services.memory import memory_document_id

BASE = "md:brand-voice"
A = "Headlines stay under sixty characters."
B = "Never use the word cheap in any copy."
C = "Every email ends with a single call to action."
X = "Subject lines never use exclamation marks."
D = "Product names are always written in full."


def align(previous, current, used):
    # Looked up at call time, so a missing function fails each test on its own
    # instead of failing the whole module at import.
    return markdown_claims.align_keys(previous, current, used)


def prev(*texts):
    return [(f"{BASE}:{i}", t) for i, t in enumerate(texts)]


def cur(*texts):
    return [{"key": f"{BASE}:{i}", "claim": t} for i, t in enumerate(texts)]


def keys(result):
    return {c["claim"]: c["key"] for c in result}


# ---------------------------------------------------------------- align_keys


def test_insert_at_top_keeps_following_keys():
    assert keys(align(prev(A, B, C), cur(X, A, B, C), {BASE: 2})) == {
        X: f"{BASE}:3",
        A: f"{BASE}:0",
        B: f"{BASE}:1",
        C: f"{BASE}:2",
    }


def test_edit_keeps_key():
    edited = "Never use the word cheap, anywhere."
    assert keys(align(prev(A, B, C), cur(A, edited, C), {BASE: 2}))[edited] == f"{BASE}:1"


def test_delete_retires_only_that_key():
    assert keys(align(prev(A, B, C), cur(A, C), {BASE: 2})) == {
        A: f"{BASE}:0",
        C: f"{BASE}:2",
    }


def test_move_keeps_keys():
    assert keys(align(prev(A, B, C), cur(C, A, B), {BASE: 2})) == {
        C: f"{BASE}:2",
        A: f"{BASE}:0",
        B: f"{BASE}:1",
    }


def test_insert_and_edit_together():
    edited = "Never use the word cheap, anywhere."
    assert keys(align(prev(A, B, C), cur(X, A, edited, C), {BASE: 2})) == {
        X: f"{BASE}:3",
        A: f"{BASE}:0",
        edited: f"{BASE}:1",
        C: f"{BASE}:2",
    }


def test_insert_next_to_an_edit_pairs_the_edit_by_similarity():
    edited = "Never use the word cheap in any of our copy."
    assert keys(align(prev(A, B, C), cur(A, X, edited, C), {BASE: 2})) == {
        A: f"{BASE}:0",
        X: f"{BASE}:3",
        edited: f"{BASE}:1",
        C: f"{BASE}:2",
    }


def test_removed_here_added_there_is_new_not_an_edit():
    assert keys(align(prev(A, B, C), cur(A, C, D), {BASE: 2})) == {
        A: f"{BASE}:0",
        C: f"{BASE}:2",
        D: f"{BASE}:3",
    }


def test_keys_are_never_reused():
    assert keys(align(prev(A, B, C), cur(A, B, C, D), {BASE: 5}))[D] == f"{BASE}:6"


def test_sections_align_independently_and_tables_too():
    previous = prev(A, B) + [
        ("md:colours:table:0", "Navy | primary"),
        ("md:colours:table:1", "White | background"),
    ]
    current = cur(A, B) + [
        {"key": "md:colours:table:0", "claim": "Gold | accent"},
        {"key": "md:colours:table:1", "claim": "Navy | primary"},
        {"key": "md:colours:table:2", "claim": "White | background"},
    ]
    assert keys(align(previous, current, {BASE: 1, "md:colours:table": 1})) == {
        A: f"{BASE}:0",
        B: f"{BASE}:1",
        "Navy | primary": "md:colours:table:0",
        "White | background": "md:colours:table:1",
        "Gold | accent": "md:colours:table:2",
    }


def test_first_version_and_authored_keys_pass_through():
    current = cur(A, B) + [{"key": "brand.tone", "claim": "Warm and direct."}]
    assert align([], current, {}) == current
    assert align(prev(A), current, {})[2]["key"] == "brand.tone"


def test_input_is_not_modified():
    current = cur(X, A)
    align(prev(A), current, {BASE: 0})
    assert current[0]["key"] == f"{BASE}:0"


def test_unchanged_text_always_keeps_its_key_and_keys_stay_unique():
    import random

    rng = random.Random(160)
    pool = [f"Brand rule number {i} is written here." for i in range(12)]
    for _ in range(500):
        old = rng.sample(pool, rng.randint(0, 8))
        new = rng.sample(pool, rng.randint(0, 8))
        out = align(prev(*old), cur(*new), {BASE: max(len(old) - 1, 0)})
        assigned = [c["key"] for c in out]
        assert len(assigned) == len(set(assigned))
        for claim in out:
            if claim["claim"] in old:
                assert claim["key"] == f"{BASE}:{old.index(claim['claim'])}"


# ---------------------------------------------------- on the real archive

PATH = "brand/voice.md"


def document(*bullets):
    return "# Brand voice\n\n" + "\n".join(f"- {b}" for b in bullets) + "\n"


async def ingest(store, body):
    await ingestion_service.IngestionService(
        memory_enabled=True, require_embeddings=False
    ).ingest_file(content=body, path=PATH, corpus_id=store.corpus)


async def latest(store):
    """The newest version's claims: text -> (key, text of the claim it supersedes)."""
    rows = (
        await store.db.execute(
            text("""
            SELECT c.key, c.claim, p.claim AS superseded
            FROM memory_claims c
            JOIN memory_versions v ON v.corpus_id = c.corpus_id AND v.id = c.version_id
            LEFT JOIN memory_claims p ON p.corpus_id = c.corpus_id AND p.id = c.supersedes_id
            WHERE c.corpus_id = :c AND v.memory_document_id = :d
              AND v.version_number = (
                  SELECT max(version_number) FROM memory_versions
                  WHERE corpus_id = :c AND memory_document_id = :d)
            """),
            {"c": store.corpus, "d": memory_document_id(store.corpus, PATH)},
        )
    ).all()
    return {row.claim: (row.key, row.superseded) for row in rows}


async def version_count(store):
    return (
        await store.db.execute(
            text("""
            SELECT count(*) FROM memory_versions
            WHERE corpus_id = :c AND memory_document_id = :d
            """),
            {"c": store.corpus, "d": memory_document_id(store.corpus, PATH)},
        )
    ).scalar_one()


async def test_inserting_a_rule_rewrites_no_history(store):
    await ingest(store, document(A, B, C))
    before = await latest(store)
    await ingest(store, document(X, A, B, C))
    after = await latest(store)
    for rule in (A, B, C):
        key, superseded = after[rule]
        assert key == before[rule][0], f"{rule!r} changed key"
        assert superseded in (None, rule), f"{rule!r} now supersedes {superseded!r}"
    assert after[X][1] is None, "the new rule supersedes nothing"
    assert after[X][0] not in {k for k, _ in before.values()}


async def test_editing_a_rule_supersedes_it_in_place(store):
    edited = "Never use the word cheap, anywhere."
    await ingest(store, document(A, B, C))
    before = await latest(store)
    await ingest(store, document(A, edited, C))
    after = await latest(store)
    assert after[edited] == (before[B][0], B)
    for rule in (A, C):
        assert after[rule][0] == before[rule][0]
        assert after[rule][1] in (None, rule)


async def test_deleting_a_rule_leaves_the_others_alone(store):
    await ingest(store, document(A, B, C))
    before = await latest(store)
    await ingest(store, document(A, C))
    after = await latest(store)
    assert set(after) == {A, C}
    for rule in (A, C):
        assert after[rule][0] == before[rule][0]
        assert after[rule][1] in (None, rule)


async def test_reingesting_the_same_text_after_an_insert_is_unchanged(store):
    await ingest(store, document(A, B, C))
    await ingest(store, document(X, A, B, C))
    await ingest(store, document(X, A, B, C))
    assert await version_count(store) == 2
