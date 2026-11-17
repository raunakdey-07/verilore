"""Write with any model, checked against approved memory, with a chance to fix (WRITE-1).

A brief gives a model only approved lines. A weak model still adds a price
nobody approved or keeps a banned word. `write` closes the loop without
Verilore calling a model: the caller's `generate(prompt)` writes, `check`
reads the draft against the same approved lines, and a draft with findings
goes back once with exactly what to change. The person gets the draft with the
fewest findings, and those findings.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

BRIEF = SimpleNamespace(
    text='Approved memory for "s".\n\nbrand/voice.md\n- We never use the word "premium".\n',
    claim_ids=["c1"],
)
CURRENT = {
    "corpus": "s",
    "current_memories": [
        {"id": "c1", "claim": 'We never use the word "premium".', "path": "brand/voice.md"},
        {"id": "c2", "claim": "Assam Gold costs Rs 520 a tin.", "path": "brand/products.md"},
    ],
}


def _check(draft):
    from verilore.check import check_draft

    return check_draft(draft, CURRENT)


class Model:
    """A model that writes what it is told to, in order, and remembers its prompts."""

    def __init__(self, *drafts):
        self.drafts, self.prompts = list(drafts), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.drafts.pop(0)


def test_a_draft_with_findings_goes_back_once_with_exactly_what_to_change():
    from verilore.write import INSTRUCTIONS, write_with

    model = Model("Our premium Assam Gold, Rs 450.", "Our Assam Gold, Rs 520.")
    written = write_with("A line about Assam Gold", model, brief=BRIEF, check=_check)
    assert written.ok and written.draft == "Our Assam Gold, Rs 520."
    assert len(written.attempts) == 2
    first, second = model.prompts
    assert first == f"{BRIEF.text.strip()}\n\nTask: A line about Assam Gold\n\n{INSTRUCTIONS}"
    assert second.startswith(first)
    assert "Your draft:\nOur premium Assam Gold, Rs 450." in second
    assert '- Remove "premium".' in second
    assert "- Replace Rs 450 with Rs 520." in second
    assert written.as_dict()["claim_ids"] == ["c1"]
    assert [a["findings"] for a in written.as_dict()["attempts"]] == [2, 0]


def test_a_clean_first_draft_costs_one_call():
    from verilore.write import write_with

    model = Model("Assam Gold, Rs 520 a tin.")
    written = write_with("Assam Gold", model, brief=BRIEF, check=_check, retries=3)
    assert written.ok and len(written.attempts) == 1 and len(model.prompts) == 1


def test_what_cannot_be_fixed_goes_to_a_person_as_the_best_draft_with_its_findings():
    from verilore.write import write_with

    model = Model("Premium, Rs 450, Rs 300.", "Premium tea.", "Premium!")
    written = write_with("Assam Gold", model, brief=BRIEF, check=_check, retries=2)
    assert not written.ok
    assert len(written.attempts) == 3
    # Fewest findings wins, and the latest of equals: a person sees the best try.
    assert written.draft == "Premium!"
    assert [f.kind for f in written.check.findings] == ["banned"]
    none = write_with("Assam Gold", Model("Premium tea."), brief=BRIEF, check=_check, retries=0)
    assert len(none.attempts) == 1 and not none.ok


@pytest.mark.parametrize(
    "task,generate,retries,error",
    [
        ("", lambda p: "x", 1, ValueError),
        ("   ", lambda p: "x", 1, ValueError),
        ("t", "not a function", 1, TypeError),
        ("t", lambda p: "x", 4, ValueError),
        ("t", lambda p: "x", -1, ValueError),
        ("t", lambda p: None, 1, TypeError),
    ],
)
def test_the_loop_refuses_what_it_cannot_run(task, generate, retries, error):
    from verilore.write import write_with

    with pytest.raises(error):
        write_with(task, generate, brief=BRIEF, check=_check, retries=retries)


@pytest.fixture
def kit(tmp_path, monkeypatch):
    from verilore import Verilore

    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    (tmp_path / "brand").mkdir()
    (tmp_path / "brand" / "voice.md").write_text(
        '# Voice\n\n- We never use the word "premium".\n- Our voice is warm.\n'
    )
    (tmp_path / "brand" / "products.md").write_text(
        "# Products\n\n## Assam Gold\n\n- Price: Rs 520 for a 250 g tin.\n"
    )
    (tmp_path / "notes.md").write_text("# Notes\n\n- Assam Gold was Rs 450 in 2025.\n")
    vl = Verilore(f"write-{uuid.uuid4().hex[:8]}")
    vl.sync(str(tmp_path), delete_removed=False)
    return vl


def test_end_to_end_the_brief_and_the_check_read_the_same_approved_lines(kit):
    task = "A one-line Instagram caption for Assam Gold, with 10% off"
    model = Model(
        "Premium Assam Gold, now Rs 450 with 10% off.",
        "Assam Gold, Rs 520 for a 250 g tin, with 10% off.",
    )
    written = kit.memory.write(task, model, path_prefix="brand")
    assert written.ok, written.check.as_dict()
    assert written.draft == "Assam Gold, Rs 520 for a 250 g tin, with 10% off."
    first = model.prompts[0]
    # Scoped: the 2025 note is neither in the prompt nor a source of support.
    assert "Assam Gold: Price: Rs 520 for a 250 g tin." in first
    assert "Rs 450" not in first
    assert written.brief.claim_ids
    # "10%" came from the task the person wrote, so it is not reported.
    assert all(f.quote != "10%" for a in written.attempts for f in a.check.findings)


# ------------------------------------------------- the benchmark's checked condition


def _ok(content):
    return SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"choices": [{"message": {"content": content}}]},
        text="",
    )


class FakeHttp:
    def __init__(self, answers):
        self.answers, self.bodies = list(answers), []

    def post(self, url, headers, json, timeout):  # noqa: A002 - httpx's own name
        self.bodies.append(json)
        return _ok(self.answers.pop(0))


def test_the_checked_condition_revises_once_and_records_it(tmp_path, monkeypatch):
    from benchmarks.governed_context import run as bench

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    args = bench.parser().parse_args(
        ["--suite", "hard", "--model", "m:free", "--conditions", "checked", "--out", str(tmp_path)]
    )
    args.delay = 0.0
    tasks = json.loads(bench.SUITES["hard"][1].read_text(encoding="utf-8"))["tasks"]
    first = [t for t in tasks if t["id"] == "assam-price"][0]
    answers = []
    for task in tasks:
        if task is first:
            answers += [
                "Assam Gold is a premium tea at Rs 450.",
                "Assam Gold is Rs 520 for a 250 g tin, prices include GST; steep it for "
                "4 minutes at 95 °C.",
            ]
        else:
            answers.append("Saffron season is here.")
    http = FakeHttp(answers)
    assert bench.run(args, client=http, sleep=lambda s: None, out=open(tmp_path / "log", "w")) == 0
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    row = [r for r in rows if r["task"] == "assam-price"][0]
    assert row["condition"] == "checked" and row["attempts"] == 2
    assert row["passed"] and row["findings_left"] == []
    revisions = [b["messages"][1]["content"] for b in http.bodies]
    revisions = [content for content in revisions if "Your draft:" in content]
    assert len(revisions) == 1
    assert "Your draft:\nAssam Gold is a premium tea at Rs 450." in revisions[0]
    assert len(http.bodies) == len(tasks) + 1
    # The basic suite has no approved lines to check against.
    basic = bench.parser().parse_args(["--conditions", "checked", "--dry-run"])
    assert bench.run(basic, out=open(tmp_path / "log2", "w")) == 2


def test_the_committed_approved_lines_are_what_the_kit_serves(tmp_path, monkeypatch):
    from benchmarks.governed_context import measure
    from verilore import Verilore

    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(measure.KIT))
    vl = Verilore(f"{measure.CORPUS}-{uuid.uuid4().hex[:8]}")
    vl.sync(str(measure.KIT), delete_removed=False)
    committed = json.loads(measure.APPROVED.read_text(encoding="utf-8"))
    assert measure.approved(vl) == committed
    claims = [line["claim"] for line in committed["current_memories"]]
    assert "Price: Rs 520 for a 250 g tin." in claims
    assert not any("Rs 450" in claim or "strainer" in claim for claim in claims)
