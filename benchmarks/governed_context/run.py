# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""Does a small model follow the rules better when it is given only approved memory?

One brand kit, eight writing tasks, three ways of handing the kit to a model:

    dump    every file in the kit, whole, the way an agent with file access reads it
    grep    the lines a keyword search finds, the way `grep -rn` answers
    brief   `verilore brief`: the current, approved lines in scope, and nothing else

The kit holds what a real one holds: an approved guide, a draft that proposes a
different voice, a rejected headline, another campaign, and old notes that
disagree with the specs. Each task is scored by regular expressions written
before any model was run: text the answer must contain, and text it must not
(a rejected headline, the other campaign's date, the draft's adjectives).

Nothing here is a claim until someone runs it. `--dry-run` prints the three
prompts' sizes without a network call; a real run needs OPENROUTER_API_KEY and a
model id, writes every raw answer to `results.jsonl`, and can be resumed.

    python -m benchmarks.governed_context.run --dry-run
    python -m benchmarks.governed_context.run --model <an id ending in :free>

Standard library and httpx only. No Verilore import: the brief is read from
`brief.txt`, which tests/test_governed_context_benchmark.py holds equal to what
Verilore returns for this kit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE / "kit"
TASKS = HERE / "tasks.json"
BRIEF = HERE / "brief.txt"
CONDITIONS = ("dump", "grep", "brief")
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

#: OpenRouter's free tier allows 20 requests a minute. 3.5 s keeps under it.
DEFAULT_DELAY = 3.5
#: And 50 requests a day without credits. One model is 24 calls.
DEFAULT_MAX_CALLS = 45


class Stop(Exception):
    """The provider refused (rate limit, quota, key). Results so far are kept."""


def load_tasks(path: Path = TASKS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def kit_files(kit: Path = KIT) -> list[tuple[str, str]]:
    """(relative path, text) for every Markdown file in the kit, sorted by path."""
    return [
        (file.relative_to(kit).as_posix(), file.read_text(encoding="utf-8"))
        for file in sorted(kit.rglob("*.md"))
    ]


def dump_context(kit: Path = KIT) -> str:
    """Every file, whole, under a header naming it. Frontmatter included."""
    return "\n\n".join(f"===== {path} =====\n{text.strip()}" for path, text in kit_files(kit))


def grep_context(keywords: list[str], kit: Path = KIT) -> str:
    """What `grep -rni -e k1 -e k2 kit/` prints: `path:line:text`, in path order."""
    pattern = re.compile("|".join(re.escape(word) for word in keywords), re.IGNORECASE)
    hits = []
    for path, text in kit_files(kit):
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path}:{number}:{line}")
    return "\n".join(hits) if hits else "(no matching lines)"


def brief_context(brief: Path = BRIEF) -> str:
    return brief.read_text(encoding="utf-8").strip()


def context_for(condition: str, task: dict, *, kit: Path = KIT, brief: Path = BRIEF) -> str:
    if condition == "dump":
        return dump_context(kit)
    if condition == "grep":
        return grep_context(task["keywords"], kit)
    if condition == "brief":
        return brief_context(brief)
    raise ValueError(f"unknown condition: {condition}")


def messages(system: str, context: str, prompt: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"CONTEXT\n{context}\n\nTASK\n{prompt}"},
    ]


def score(answer: str, task: dict) -> dict:
    """Which checks an answer failed. Passing means none: every `must`, no `must_not`."""
    missing = [p for p in task["must"] if not re.search(p, answer, re.IGNORECASE)]
    forbidden = [p for p in task["must_not"] if re.search(p, answer, re.IGNORECASE)]
    return {"passed": not missing and not forbidden, "missing": missing, "forbidden": forbidden}


def ask(client, model: str, key: str, chat: list[dict]) -> str:
    """One completion at temperature 0. Raises Stop when the provider refuses."""
    response = client.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {key}", "X-Title": "verilore governed-context"},
        json={"model": model, "messages": chat, "temperature": 0, "max_tokens": 300},
        timeout=120,
    )
    if response.status_code in (401, 402, 403, 429):
        raise Stop(f"HTTP {response.status_code}: {response.text[:300]}")
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise Stop(f"provider error: {json.dumps(body['error'])[:300]}")
    return body["choices"][0]["message"]["content"] or ""


def done_keys(results: Path) -> set[tuple[str, str, str]]:
    if not results.exists():
        return set()
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line]
    return {(row["model"], row["condition"], row["task"]) for row in rows}


def summarize(results: Path) -> str:
    """A Markdown table per model: tasks passed and context size, by condition."""
    rows = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line]
    out = []
    for model in sorted({row["model"] for row in rows}):
        out += [f"### {model}", "", "| Context | Tasks passed | Rule violations | Context chars |"]
        out.append("|---|---|---|---|")
        for condition in CONDITIONS:
            mine = [r for r in rows if r["model"] == model and r["condition"] == condition]
            if not mine:
                continue
            passed = sum(r["passed"] for r in mine)
            violations = sum(len(r["forbidden"]) for r in mine)
            chars = round(sum(r["context_chars"] for r in mine) / len(mine))
            out.append(f"| {condition} | {passed} of {len(mine)} | {violations} | {chars} |")
        out.append("")
    return "\n".join(out)


def run(args, client=None, sleep=time.sleep, out=sys.stdout) -> int:
    spec = load_tasks()
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown = [c for c in conditions if c not in CONDITIONS]
    if unknown:
        print(f"unknown condition: {', '.join(unknown)}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("| Task | " + " | ".join(f"{c} chars" for c in conditions) + " |", file=out)
        print("|---|" + "---|" * len(conditions), file=out)
        for task in spec["tasks"]:
            sizes = [str(len(context_for(c, task))) for c in conditions]
            print(f"| {task['id']} | " + " | ".join(sizes) + " |", file=out)
        return 0

    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not args.model or not key:
        print("a real run needs --model and OPENROUTER_API_KEY; try --dry-run", file=sys.stderr)
        return 2

    results = Path(args.out) / "results.jsonl"
    results.parent.mkdir(parents=True, exist_ok=True)
    done = done_keys(results)
    if client is None:
        import httpx

        client = httpx.Client()

    calls = 0
    status = 0
    try:
        for task in spec["tasks"]:
            for condition in conditions:
                if (args.model, condition, task["id"]) in done:
                    continue
                if calls >= args.max_calls:
                    print(f"stopped at --max-calls {args.max_calls}; run again to resume", file=out)
                    raise Stop("max calls")
                if calls:
                    sleep(args.delay)
                context = context_for(condition, task)
                answer = ask(
                    client, args.model, key, messages(spec["system"], context, task["prompt"])
                )
                calls += 1
                row = {
                    "model": args.model,
                    "condition": condition,
                    "task": task["id"],
                    "context_chars": len(context),
                    "answer": answer,
                    **score(answer, task),
                }
                with results.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                mark = "pass" if row["passed"] else "FAIL"
                print(f"{mark}  {condition:5}  {task['id']}", file=out)
    except Stop as stop:
        if str(stop) != "max calls":
            print(f"stopped: {stop}\nresults so far are kept; run again to resume", file=out)
        status = 3

    if results.exists():
        summary = summarize(results)
        (results.parent / "summary.md").write_text(summary + "\n", encoding="utf-8")
        print("\n" + summary, file=out)
    return status


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--model", help="an OpenRouter model id, for example one ending in :free")
    p.add_argument("--conditions", default=",".join(CONDITIONS))
    p.add_argument("--out", default="governed-context-results", help="directory for results")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="seconds between calls")
    p.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    p.add_argument("--dry-run", action="store_true", help="print context sizes; no network")
    return p


if __name__ == "__main__":
    sys.exit(run(parser().parse_args()))
