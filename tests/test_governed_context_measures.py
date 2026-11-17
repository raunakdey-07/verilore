"""The hard kit's measures are what the kit measures, and the marking is honest.

`benchmarks/governed_context/hard/` holds a brand kit written the way brands
write, 47 rules a person marked in it, 13 lines that must never reach a model,
and eight writing tasks. `measure.py` reports, with no model, how many marked
rules become approved lines and how many applicable rules each way of handing
the kit to a model carries at a fixed size. The committed numbers and briefs are
held equal to what this code computes, so a number quoted from them is true of
the code it ships with.
"""

from __future__ import annotations

import io
import json
import re
import uuid

import pytest

from benchmarks.governed_context import run as bench


class _Measure:
    """`benchmarks.governed_context.measure`, imported when first used, so that a
    checkout without it fails these tests one by one instead of stopping the
    whole run at collection."""

    def __getattr__(self, name):
        from benchmarks.governed_context import measure as module

        return getattr(module, name)


measure = _Measure()


def _spec():
    return measure.load(measure.RULES), measure.load(measure.TASKS)


def test_every_marked_line_is_in_the_kit_and_every_task_names_real_rules():
    """A rule that matches nothing in its own file would count as 'not carried'
    forever, and make every context look worse than it is."""
    rules, tasks = _spec()
    ids = [rule["id"] for rule in rules["rules"] + rules["not_rules"]]
    assert len(ids) == len(set(ids)) == 60
    assert len(rules["rules"]) == 47 and len(rules["not_rules"]) == 13
    for rule in rules["rules"] + rules["not_rules"]:
        source = (measure.KIT / rule["path"]).read_text(encoding="utf-8")
        flat = " ".join(source.split())
        assert all(re.search(p, flat, re.IGNORECASE) for p in rule["match"]), rule["id"]
    known = {rule["id"] for rule in rules["rules"]}
    for task in tasks["tasks"]:
        assert task["applies"] and set(task["applies"]) <= known, task["id"]
        for pattern in task["must"] + task["must_not"]:
            re.compile(pattern)
    # What must never be served is really out of reach: a draft, an ended
    # campaign, or a note outside the scope.
    for rule in rules["not_rules"]:
        source = (measure.KIT / rule["path"]).read_text(encoding="utf-8")
        in_scope = any(rule["path"].startswith(p + "/") for p in rules["scope"])
        assert (
            not in_scope or "status: draft" in source or "valid_until: 2026-11-10" in source
        ), rule["id"]


def test_a_rule_is_carried_only_when_one_line_states_all_of_it():
    rule = {"match": ["instagram", "150 characters"]}
    assert measure.carries("Instagram: Length: 150 characters; Emojis: 2 at most", rule)
    assert not measure.carries("Instagram\nLength: 150 characters", rule)
    cut = measure.cut("one two three four\n" * 50, 20)
    assert cut.count("\n") < 49 and cut.endswith("four")


@pytest.fixture
def synced(tmp_path, monkeypatch):
    from verilore import Verilore

    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(measure.KIT))
    vl = Verilore(f"{measure.CORPUS}-{uuid.uuid4().hex[:8]}")
    vl.sync(str(measure.KIT), delete_removed=False)
    return vl


def test_the_committed_measures_and_briefs_are_what_the_code_computes(synced):
    result = measure.measure(synced)
    committed = json.loads(measure.OUT_JSON.read_text(encoding="utf-8"))
    assert result == committed
    assert measure.render(result) == measure.OUT_MD.read_text(encoding="utf-8")
    for task_id, brief in measure.briefs(synced).items():
        assert brief == (measure.BRIEFS / f"{task_id}.txt").read_text(encoding="utf-8"), task_id


def test_nothing_that_must_not_be_served_reaches_a_brief(synced):
    """The draft voice, the ended Diwali campaign and the 2025 prices are in the
    kit and in scope or beside it. None may reach a model through the brief, at
    any size; the dump and grep carry them, which is the point of comparing."""
    result = measure.measure(synced)
    assert result["served_in_error"] == []
    for budget, methods in result["coverage"].items():
        assert methods["brief"]["leaks"] == 0, budget
        assert methods["dump"]["leaks"] > 0 and methods["grep"]["leaks"] > 0, budget


def test_the_model_run_sends_each_task_its_own_brief(tmp_path):
    args = bench.parser().parse_args(["--suite", "hard", "--dry-run"])
    out = io.StringIO()
    assert bench.run(args, out=out) == 0
    lines = out.getvalue().splitlines()
    assert len(lines) == 2 + 8
    _rules, tasks = _spec()
    kit, _tasks, briefs = bench.SUITES["hard"]
    first = tasks["tasks"][0]
    brief = bench.context_for("brief", first, kit=kit, brief=briefs)
    assert brief.startswith(f'Approved memory for "{measure.CORPUS}"')
    assert brief == (briefs / f"{first['id']}.txt").read_text(encoding="utf-8").strip()
    assert "Rs 450" in bench.context_for("dump", first, kit=kit, brief=briefs)
    unknown = bench.parser().parse_args(["--dry-run"])
    unknown.suite = "nope"
    assert bench.run(unknown, out=io.StringIO()) == 2
