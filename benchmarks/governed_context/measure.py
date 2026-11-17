# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""Two measures that need no model, on a kit that is hard on purpose.

The hard kit (`hard/kit/`) is what a brand hands over: a voice guide written as
paragraphs, a channel table, product facts, legal lines, a draft proposing a
different voice, a campaign that has ended, and old notes that disagree with the
current prices. `hard/rules.json` marks, by hand and before anything was
measured, the 47 lines a writer needs and the 13 that must never reach a model.

1. **Extraction.** Of the rules a person marked, how many become current,
   approved lines once the folder is synced; and how many of the lines that must
   not be served are served anyway.
2. **Coverage at a fixed size.** For each of eight writing tasks, the rules that
   apply to it (marked by hand) and three contexts cut to the same size: the kit
   dumped whole, the lines `grep` finds for the task's keywords, and
   `verilore brief --task`. How many applicable rules each one carries, and how
   many lines that must not be served it lets through.

A rule is carried by a context when one line of it matches every pattern the rule
lists. No model, no key, no network: the numbers are the same on every run, and
`tests/test_governed_context_measures.py` fails if `hard/measures.json` stops
being what this computes.

    DATABASE_URL=... python -m benchmarks.governed_context.measure
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

from benchmarks.governed_context import run as bench

HERE = Path(__file__).resolve().parent
HARD = HERE / "hard"
KIT = HARD / "kit"
RULES = HARD / "rules.json"
TASKS = HARD / "tasks.json"
OUT_JSON = HARD / "measures.json"
OUT_MD = HARD / "measures.md"
#: The brief each task gets in a model run (`run.py --suite hard`), at this size.
BRIEFS = HARD / "briefs"
RUN_BUDGET = 500
#: The corpus name the committed briefs carry on their first line.
CORPUS = "saffron-lane"
#: The approved lines in scope, which `run.py`'s `checked` condition checks
#: drafts against without a database.
APPROVED = HARD / "approved.json"
#: Token budgets, by the same estimate `verilore brief` uses: a short prompt
#: section, a generous one, and one that holds most of the kit.
BUDGETS = (250, 500, 1000)
METHODS = ("dump", "grep", "brief")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def carries(text: str, rule: dict) -> bool:
    """Whether one line of `text` matches every pattern of `rule`."""
    patterns = [re.compile(p, re.IGNORECASE) for p in rule["match"]]
    return any(all(p.search(line) for p in patterns) for line in text.splitlines())


def cut(text: str, budget: int) -> str:
    """The first lines of `text` that fit `budget` tokens, whole lines only."""
    from verilore.brief import approx_tokens

    kept: list[str] = []
    for line in text.splitlines():
        if approx_tokens("\n".join([*kept, line])) > budget:
            break
        kept.append(line)
    return "\n".join(kept)


def contexts(vl, task: dict, scope: list[str], budget: int) -> dict[str, str]:
    return {
        "dump": cut(bench.dump_context(KIT), budget),
        "grep": cut(bench.grep_context(task["keywords"], KIT), budget),
        "brief": vl.memory.brief(path_prefix=scope, task=task["prompt"], max_tokens=budget).text,
    }


def measure(vl) -> dict:
    """Both measures for a client whose corpus holds the synced hard kit."""
    spec, tasks = load(RULES), load(TASKS)
    rules = {rule["id"]: rule for rule in spec["rules"]}
    scope = spec["scope"]
    current = vl.memory.current()
    lines = "\n".join(claim.claim for claim in current.current_memories)
    in_scope = "\n".join(
        claim.claim
        for claim in current.current_memories
        if any(claim.path.startswith(prefix.rstrip("/") + "/") for prefix in scope)
    )
    extracted = [rule["id"] for rule in spec["rules"] if carries(lines, rule)]
    served_in_error = [rule["id"] for rule in spec["not_rules"] if carries(in_scope, rule)]
    coverage: dict[str, dict] = {}
    for budget in BUDGETS:
        per_method: dict[str, dict] = {
            method: {"carried": 0, "applicable": 0, "leaks": 0, "missed": {}} for method in METHODS
        }
        for task in tasks["tasks"]:
            for method, text in contexts(vl, task, scope, budget).items():
                row = per_method[method]
                missed = [rid for rid in task["applies"] if not carries(text, rules[rid])]
                row["applicable"] += len(task["applies"])
                row["carried"] += len(task["applies"]) - len(missed)
                row["leaks"] += sum(carries(text, rule) for rule in spec["not_rules"])
                if missed:
                    row["missed"][task["id"]] = missed
        coverage[str(budget)] = per_method
    return {
        "rules": len(spec["rules"]),
        "extracted": len(extracted),
        "not_extracted": [rid for rid in rules if rid not in extracted],
        "not_rules": len(spec["not_rules"]),
        "served_in_error": served_in_error,
        "coverage": coverage,
    }


def briefs(vl) -> dict[str, str]:
    """The brief for each task at `RUN_BUDGET` tokens, as `run.py --suite hard` sends it.

    The first line names the corpus; it is written as `CORPUS`, so the files do
    not depend on the scratch corpus a run happened to use.
    """
    spec, tasks = load(RULES), load(TASKS)
    out = {}
    for task in tasks["tasks"]:
        text = vl.memory.brief(
            path_prefix=spec["scope"], task=task["prompt"], max_tokens=RUN_BUDGET
        ).text
        first, _, rest = text.partition("\n")
        first = re.sub(r'^Approved memory for "[^"]*"', f'Approved memory for "{CORPUS}"', first)
        out[task["id"]] = f"{first}\n{rest}\n"
    return out


def approved(vl) -> dict:
    """The current, approved lines in scope, as `check_draft` reads them.

    Ids are positions, not the archive's ids, so the file is the same on every
    run; `check` needs a claim's text, path and section, not its identity.
    """
    spec = load(RULES)
    current = vl.memory.current(path_prefix=spec["scope"])
    headings = {e.claim_id: e.heading for e in current.evidence if e.heading}
    lines = sorted({(c.path, c.claim, headings.get(c.id) or "") for c in current.current_memories})
    return {
        "corpus": CORPUS,
        "current_memories": [
            {"id": f"line-{n:03d}", "claim": claim, "path": path}
            for n, (path, claim, _heading) in enumerate(lines, start=1)
        ],
        "evidence": [
            {"claim_id": f"line-{n:03d}", "heading": heading}
            for n, (_path, _claim, heading) in enumerate(lines, start=1)
            if heading
        ],
    }


def render(result: dict) -> str:
    out = [
        "# Hard kit: what reaches the model, measured without one",
        "",
        "Computed by `python -m benchmarks.governed_context.measure`; held equal to",
        "`measures.json` by `tests/test_governed_context_measures.py`. Rules and tasks",
        "were marked by hand in `rules.json` and `tasks.json` before this was run.",
        "",
        "## Extraction",
        "",
        f"- Rules a person marked that became current, approved lines: "
        f"**{result['extracted']} of {result['rules']}**.",
        f"- Lines that must not be served (a draft, an ended campaign, old notes) that "
        f"were served in scope: **{len(result['served_in_error'])} of {result['not_rules']}**.",
    ]
    if result["not_extracted"]:
        out.append(f"- Not extracted: {', '.join(result['not_extracted'])}.")
    out += [
        "",
        "## Applicable rules carried, at the same size",
        "",
        "Eight writing tasks. Each context is cut to the budget; a rule counts when",
        "one line of the context states it. Leaks are lines that must not be served.",
        "",
        "| Budget (tokens) | Kit dumped whole | `grep` for the task | `verilore brief --task` |",
        "|---|---|---|---|",
    ]
    for budget, methods in result["coverage"].items():
        cells = []
        for method in METHODS:
            row = methods[method]
            share = 100 * row["carried"] / row["applicable"]
            cells.append(
                f"{row['carried']}/{row['applicable']} ({share:.0f}%), {row['leaks']} leaked"
            )
        out.append(f"| {budget} | " + " | ".join(cells) + " |")
    out += ["", "## What the brief missed", ""]
    for budget, methods in result["coverage"].items():
        missed = methods["brief"]["missed"]
        listed = "; ".join(f"{task}: {', '.join(ids)}" for task, ids in missed.items())
        out.append(f"- {budget} tokens: {listed or 'nothing'}.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="Write measures.json and .md.")
    args = parser.parse_args(argv)
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set: the measure syncs the kit into a scratch corpus.")
        return 2
    # Nothing here needs the model; lexical mode also keeps it from loading one.
    os.environ.setdefault("VERILORE_LEXICAL", "1")
    roots = os.environ.get("VERILORE_INGEST_ROOTS")
    os.environ["VERILORE_INGEST_ROOTS"] = os.pathsep.join(filter(None, [roots, str(KIT)]))
    from verilore import Verilore

    vl = Verilore(f"{CORPUS}-{uuid.uuid4().hex[:8]}")
    vl.sync(str(KIT), delete_removed=False)
    result = measure(vl)
    text = render(result)
    print(text)
    if args.write:
        OUT_JSON.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        OUT_MD.write_text(text, encoding="utf-8")
        BRIEFS.mkdir(exist_ok=True)
        for task_id, brief in briefs(vl).items():
            (BRIEFS / f"{task_id}.txt").write_text(brief, encoding="utf-8")
        APPROVED.write_text(
            json.dumps(approved(vl), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
