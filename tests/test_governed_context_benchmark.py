"""The governed-context benchmark measures what it says, before any model runs.

Three things can make a benchmark like this dishonest without anyone noticing:
a `brief` condition that is not what Verilore really returns, a scorer that
passes the answer it should fail, and a runner that loses or double-counts
calls. Each is held here, with no network: the model is a fake transport.
"""

from __future__ import annotations

import argparse
import io
import json
import re

import httpx
import pytest

from benchmarks.governed_context import run as bench
from live_server import live_server  # noqa: F401,F811  module-scoped server fixture
from verilore import Verilore

SPEC = bench.load_tasks()
TASKS = {task["id"]: task for task in SPEC["tasks"]}


def _args(tmp_path, **overrides):
    values = {
        "model": "test/model:free",
        "conditions": "dump,grep,brief",
        "out": str(tmp_path),
        "delay": 0.0,
        "max_calls": 100,
        "dry_run": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _client(reply):
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return reply(len(calls))

    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def _answer(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_the_committed_brief_is_what_verilore_returns_for_this_kit(live_server):  # noqa: F811
    corpus, key = live_server.corpora["globex"], live_server.keys["globex"]
    for path, text in bench.kit_files():
        resp = httpx.post(
            f"{live_server.url}/api/ingest/file",
            json={"content": text, "path": path, "corpus": corpus},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text
    vl = Verilore(corpus, base_url=live_server.url, api_key=key, timeout=5, retries=1)
    live = vl.memory.brief(path_prefix=SPEC["scope"]).text.splitlines()
    committed = bench.brief_context().splitlines()
    # Line 1 names the corpus, which is this test's own; everything after is the kit.
    assert live[1:] == committed[1:]
    assert committed[0] == 'Approved memory for "trailhead", scope brand + campaigns/spring.'


def test_the_three_contexts_differ_in_exactly_the_way_the_benchmark_claims():
    dump = bench.dump_context()
    brief = bench.brief_context()
    for unapproved in ("Ride Into Spring", "bold, cheeky and loud", "10.4 kilograms", "September"):
        assert unapproved in dump, f"the dump should hold everything, and lacks {unapproved!r}"
        assert unapproved not in brief, f"the brief leaked {unapproved!r}"
    for approved in ("warm, plain and direct", "9.8 kilograms", "14 March 2027", "free helmet"):
        assert approved in dump and approved in brief
    # grep answers the keyword, whatever the state of the file it found it in.
    weigh = bench.grep_context(TASKS["bike-weight"]["keywords"])
    assert weigh.splitlines() == [
        "brand/specs.md:3:- The Trailhead 2 bike weighs 9.8 kilograms.",
        "notes/kickoff-2026.md:4:- The Trailhead 2 bike weighs 10.4 kilograms.",
    ]
    assert bench.grep_context(["zzz-no-such-word"]) == "(no matching lines)"


@pytest.mark.parametrize(
    "task,answer,passed",
    [
        ("bike-weight", "The Trailhead 2 weighs 9.8 kilograms.", True),
        ("bike-weight", "It weighs 10.4 kilograms.", False),
        ("bike-weight", "Sources say 9.8 kg, though older notes say 10.4 kg.", False),
        ("brand-voice", "Our voice is warm, plain and direct.", True),
        ("brand-voice", "Our voice is warm, plain and confident.", False),
        ("approved-headline", "Spring starts on two wheels.", True),
        ("approved-headline", "Ride Into Spring.", False),
        ("spring-caption", "Launching 14 March 2027! A free helmet with every bike.", True),
        ("spring-caption", "Launching March 14 with a free helmet and free shipping.", False),
        ("launch-date", "14 March 2027", True),
        ("launch-date", "9 September 2027", False),
        ("never-list", 'Never use "curated".\nNever promise free shipping.', True),
        ("never-list", "curated\nfree shipping\nAlways open with a pun", False),
    ],
)
def test_the_scorer_passes_and_fails_the_answers_it_should(task, answer, passed):
    result = bench.score(answer, TASKS[task])
    assert result["passed"] is passed, result


def test_every_check_is_a_valid_pattern_and_every_task_can_fail():
    assert len(TASKS) == 8
    for task in TASKS.values():
        for pattern in task["must"] + task["must_not"]:
            re.compile(pattern)
        assert task["keywords"], task["id"]
        assert task["must"] or task["must_not"], f"{task['id']} cannot fail"


def test_a_run_asks_once_per_task_and_condition_and_resumes_without_asking_again(tmp_path):
    client, calls = _client(lambda n: _answer("14 March 2027, free helmet, 9.8, five-year"))
    out = io.StringIO()
    assert bench.run(_args(tmp_path), client=client, sleep=lambda s: None, out=out) == 0
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert len(calls) == len(rows) == 24
    assert {(r["condition"], r["task"]) for r in rows} == {
        (c, t) for c in bench.CONDITIONS for t in TASKS
    }
    assert all(call["temperature"] == 0 and call["model"] == "test/model:free" for call in calls)
    # The context really is the condition's, and the task is in the prompt.
    first = calls[0]["messages"]
    assert first[0] == {"role": "system", "content": SPEC["system"]}
    assert first[1]["content"].startswith("CONTEXT\n===== brand/drafts/voice-refresh.md =====")
    assert "| brief | " in (tmp_path / "summary.md").read_text()

    assert bench.run(_args(tmp_path), client=client, sleep=lambda s: None, out=out) == 0
    assert len(calls) == 24, "a finished run asked the model again"


def test_a_refusal_keeps_what_was_answered_and_the_next_run_continues(tmp_path):
    def reply(n):
        return _answer("ok") if n <= 5 else httpx.Response(429, json={"error": {"code": 429}})

    client, calls = _client(reply)
    out = io.StringIO()
    assert bench.run(_args(tmp_path), client=client, sleep=lambda s: None, out=out) == 3
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 5
    assert "HTTP 429" in out.getvalue() and "run again to resume" in out.getvalue()

    client, calls = _client(lambda n: _answer("ok"))
    assert bench.run(_args(tmp_path), client=client, sleep=lambda s: None, out=out) == 0
    assert len(calls) == 19
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 24


def test_a_dry_run_and_a_run_without_a_key_never_touch_the_network(tmp_path, monkeypatch):
    client, calls = _client(lambda n: _answer("never"))
    out = io.StringIO()
    assert bench.run(_args(tmp_path, dry_run=True), client=client, out=out) == 0
    assert "| bike-weight | " in out.getvalue()
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert bench.run(_args(tmp_path), client=client, out=out) == 2
    assert bench.run(_args(tmp_path, conditions="dump,rag"), client=client, out=out) == 2
    assert calls == [] and not (tmp_path / "results.jsonl").exists()


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
