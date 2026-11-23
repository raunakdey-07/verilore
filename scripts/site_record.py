"""Record the terminal runs `site/index.html` shows, or check they are still true.

The landing page shows real output: what `verilore` prints for the Trailhead
kit in `examples/trailhead`. This script runs each command against a new
corpus and writes the output into the page's `<script id="recorded">` block,
or, with `--check`, fails when the page shows anything the commands no longer
print. `tests/test_site.py` runs the check, so the page cannot claim more than
the tool does.

    python scripts/site_record.py            # record (needs PostgreSQL and the model)
    python scripts/site_record.py --check    # compare; exit 1 on a difference

It records with the embedding model, as a person who installs Verilore gets
it: `VERILORE_LEXICAL` is removed from the commands' environment. Claim ids,
version hashes, times and scores are compared as placeholders; the words,
sources, findings and counts are compared exactly.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "index.html"
KIT = "examples/trailhead"
SCOPE = ["--path-prefix", "brand", "--path-prefix", "campaigns/spring"]

#: A draft that breaks three approved lines and leaves one for a reviewer.
DRAFT = "Meet the curated Trailhead 2: just 10.4 kg, launching 20 March 2027."

#: What the page shows, in order: (key, the command as the page prints it,
#: its arguments, standard input). `trailhead` is the corpus a reader creates.
RUNS: list[tuple[str, str, list[str], str | None]] = [
    (
        "ingest",
        f"verilore ingest-repo {KIT} --corpus trailhead",
        ["ingest-repo", KIT],
        None,
    ),
    ("review", "verilore review --corpus trailhead", ["review"], None),
    (
        "brief",
        "verilore brief --corpus trailhead --path-prefix brand --path-prefix campaigns/spring "
        '--task "Instagram post for the spring launch" --max-tokens 500',
        ["brief", *SCOPE, "--task", "Instagram post for the spring launch", "--max-tokens", "500"],
        None,
    ),
    (
        "check",
        f'echo "{DRAFT}" | verilore check --corpus trailhead '
        "--path-prefix brand --path-prefix campaigns/spring -",
        ["check", *SCOPE, "-"],
        DRAFT + "\n",
    ),
    (
        "recall-voice",
        'verilore recall --corpus trailhead "What does our brand voice sound like?"',
        ["recall", "What does our brand voice sound like?"],
        None,
    ),
    (
        "recall-ceo",
        'verilore recall --corpus trailhead "Who is our CEO?"',
        ["recall", "Who is our CEO?"],
        None,
    ),
]

_BLOCK = re.compile(r'(<script type="application/json" id="recorded">)(.*?)(</script>)', re.DOTALL)
#: Step 03's run, written into the page itself, so it is not blank before
#: (or without) its script.
_STATIC = re.compile(r'(<pre class="run" id="how-run">)(.*?)(</pre>)', re.DOTALL)


def static_brief(runs: dict) -> str:
    """The brief run as the page's HTML shows it before any script runs."""
    run = runs["brief"]
    return html.escape(f"$ {run['cmd']}\n{run['out']}", quote=False)


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("VERILORE_LEXICAL", None)
    env["VERILORE_RUNTIME"] = "off"
    env["VERILORE_INGEST_ROOTS"] = str(ROOT / "examples")
    env["COLUMNS"] = "100"
    return env


#: How far a recorded answer must have won by. A recall the page shows is an
#: answer a reader should get on any machine with the same model; one that won
#: by a hair could lose to the runner-up after a model or ranking change.
CLEAR_MARGIN = 0.15

#: What to run when the page no longer matches.
RERECORD = "python scripts/site_record.py   (needs PostgreSQL and the model)"


#: Asks one question the way `recall` does, and prints how clearly it was answered.
_ASK = """
import json, sys
from verilore import Verilore
response = Verilore(sys.argv[1]).memory.query(sys.argv[2])
print(json.dumps([response.match_status, response.match_margin]))
"""


def record(margins: dict | None = None) -> dict[str, dict[str, str]]:
    """Run every command against a new corpus and return what each printed.

    With `margins`, each recall the page shows is asked again through the SDK
    on the same corpus, and its `match_status` and `match_margin` are put there.
    `recall --json` prints the canonical pack, which leaves both out.
    """
    corpus = f"trailhead-site-{uuid.uuid4().hex[:10]}"
    env = _environment()
    runs: dict[str, dict[str, str]] = {}
    for key, shown, args, stdin in RUNS:
        argv = [sys.executable, "-m", "verilore.cli.main", args[0], "--corpus", corpus, *args[1:]]
        done = subprocess.run(
            argv, input=stdin, capture_output=True, text=True, env=env, cwd=ROOT, timeout=600
        )
        text = (done.stdout + done.stderr).replace(corpus, "trailhead")
        runs[key] = {"cmd": shown, "out": clean(text), "exit": done.returncode}
        if margins is not None and args[0] == "recall":
            # The page's recalls take a question and nothing else.
            asked = subprocess.run(
                [sys.executable, "-c", _ASK, corpus, args[-1]],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
                timeout=600,
            )
            try:
                margins[key] = tuple(json.loads(asked.stdout))
            except ValueError:  # it failed to run; the run above says why
                margins[key] = (None, None)
    return runs


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
#: A warning or note ONNX Runtime writes to stderr on some hosts and not others:
#: on a Hyper-V machine (a GitHub runner, WSL) every command prints
#: "[W:onnxruntime:Default, device_discovery.cc:95 GetPciBusId] Skipping
#: pci_bus_id ...". It is the host, not Verilore's output. Its errors ([E:...])
#: are kept: a run that hit one is not output to show.
_RUNTIME_NOTE = re.compile(r"^\S+ \S+ \[[WIV]:onnxruntime:")


def clean(text: str) -> str:
    """A command's output as the page shows it: no colour codes, no host notes."""
    lines = [
        line.rstrip()
        for line in _ANSI.sub("", text).splitlines()
        if not line.startswith("retrieval: ") and not _RUNTIME_NOTE.match(line)
    ]
    return "\n".join(lines).strip("\n")


def normalise(text: str) -> str:
    """What may differ between two honest runs: ids, hashes, times and scores.

    `recall` closes a clear answer with "clear answer (margin 0.554)" when it
    measured a margin, and with nothing when it did not; the same question on
    the same kit has done both, on two databases with the same model. Both mean
    the answer was not ambiguous: an ambiguous one prints its own lines, and
    those are compared. So the line is a score, and goes with the scores.
    """
    text = re.sub(r"\n*^clear answer \(margin [0-9.]+\)$", "", text, flags=re.M)
    text = re.sub(r"\b[0-9a-f]{12}\b", "<id>", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})? UTC", "<time>", text)
    return re.sub(r"\b\d\.\d{3}\b", "<score>", text)


def shown() -> dict[str, dict[str, str]]:
    """The runs the page shows."""
    match = _BLOCK.search(PAGE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f'{PAGE}: no <script type="application/json" id="recorded"> block')
    return json.loads(match.group(2))


def differences(page: dict, live: dict) -> list[str]:
    problems: list[str] = []
    for key, command, _args, _stdin in RUNS:
        if key not in page:
            problems.append(f"{key}: the page does not show it")
            continue
        if page[key]["cmd"] != command:
            problems.append(f"{key}: the page shows the command {page[key]['cmd']!r}")
        for field in ("out", "exit"):
            mine, theirs = page[key].get(field), live[key][field]
            if field == "out":
                mine, theirs = normalise(mine or ""), normalise(theirs)
            if mine != theirs:
                problems.append(f"{key}: {field} differs\n--- page\n{mine}\n--- live\n{theirs}")
    extra = sorted(set(page) - {key for key, *_rest in RUNS})
    problems += [f"{key}: the page shows a run this script does not make" for key in extra]
    static = _STATIC.search(PAGE.read_text(encoding="utf-8"))
    if not static or normalise(static.group(2)) != normalise(static_brief(live)):
        problems.append("brief: the step 03 text written into the page differs from the run")
    if problems:
        problems.append(f"If the change is intended, record the page again: {RERECORD}")
    return problems


def write(runs: dict) -> None:
    page = PAGE.read_text(encoding="utf-8")
    data = json.dumps(runs, ensure_ascii=False, indent=1).replace("</", "<\\/")
    if not _BLOCK.search(page):
        raise SystemExit(f'{PAGE}: no <script type="application/json" id="recorded"> block')
    page = _BLOCK.sub(lambda m: m.group(1) + "\n" + data + "\n" + m.group(3), page, count=1)
    if not _STATIC.search(page):
        raise SystemExit(f'{PAGE}: no <pre class="run" id="how-run"> block')
    page = _STATIC.sub(lambda m: m.group(1) + static_brief(runs) + m.group(3), page, count=1)
    PAGE.write_text(page, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare; exit 1 on a difference")
    options = parser.parse_args(argv)
    live = record()
    failed = [k for k, run in live.items() if re.search(r"^(error: |\[ERROR\])", run["out"], re.M)]
    if failed:
        # A database that is down, a model that cannot load: not output to show.
        for key in failed:
            print(f"$ {live[key]['cmd']}\n{live[key]['out']}\n", file=sys.stderr)
        print(f"site runs: {', '.join(failed)} failed to run; nothing written", file=sys.stderr)
        return 2
    if options.check:
        problems = differences(shown(), live)
        for problem in problems:
            print(problem, file=sys.stderr)
        print("site runs: " + ("OK" if not problems else f"{len(problems)} difference(s)"))
        return 1 if problems else 0
    write(live)
    for key, *_rest in RUNS:
        print(f"$ {live[key]['cmd']}\n{live[key]['out']}\n(exit {live[key]['exit']})\n")
    print(f"recorded {len(live)} runs into {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
