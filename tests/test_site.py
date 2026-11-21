"""The landing page claims nothing the tool does not do (SITE-1).

`site/index.html` drifted behind the product: its code exhibit called
`pack()` beside a step that said "Ask for a brief", its demo answered "What is
the spring headline?" with an abstention `recall` does not print, and it
promised "about a tenth of a second" measured for `pack` in v0.10. A page is
read as a promise, so it is held to the same standard as the docs:

* every terminal output it shows is recorded from the command it names, by
  `scripts/site_record.py`, and re-run here;
* every command and flag it names exists, and the `--help` lines are the
  CLI's own;
* the benchmark sentence states the numbers in `measures.json`;
* the version is the package's, and the tags a search engine and a share card
  read are still there;
* the demo is out of the keyboard's reach while it is closed, and its faint
  text is readable (WCAG AA, 4.5:1).
"""

from __future__ import annotations

import html
import json
import re
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "index.html"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _recorded() -> dict:
    match = re.search(
        r'<script type="application/json" id="recorded">(.*?)</script>', _page(), re.DOTALL
    )
    assert match, 'site/index.html has no <script type="application/json" id="recorded">'
    return json.loads(match.group(1))


def _cli():
    from typer.main import get_command

    from verilore.cli.main import app

    return get_command(app)


def test_the_version_is_the_packages():
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    assert f"Verilore v{version.group(1)} · Apache-2.0" in _page()


@pytest.mark.parametrize(
    "tag",
    [
        '<meta name="google-site-verification"',
        '<link rel="canonical" href="https://verilore.vercel.app/">',
        '<meta property="og:type" content="website">',
        '<meta property="og:url" content="https://verilore.vercel.app/">',
        '<meta property="og:site_name" content="Verilore">',
        '<meta name="twitter:card"',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
    ],
)
def test_the_tags_search_engines_and_share_cards_read_are_kept(tag):
    assert tag in _page()


def test_the_description_says_what_the_hero_says():
    page = _page()
    lead = re.search(r'<p class="hero-lead">(.*?)</p>', page).group(1)
    assert f'<meta name="description" content="{lead} Open source, on PyPI.">' in page
    assert f'<meta property="og:description" content="{lead}">' in page


def test_no_api_the_page_names_is_gone():
    page = _page()
    for gone in ("memory.pack(", "pack.current_memories", "about a tenth of a second"):
        assert gone not in page, gone


def _commands(page: str) -> list[list[str]]:
    """Every `verilore ...` command line the page shows, split as a shell would."""
    text = html.unescape(re.sub(r"<[^>]+>", "", page))
    found = []
    for line in re.findall(r"verilore [a-z][^\n'\"]*(?:\"[^\"\n]*\"[^\n'\"]*)*", text):
        line = line.split(" | ")[0].strip().rstrip("',;)")
        try:
            found.append(shlex.split(line))
        except ValueError:
            continue
    commands = [c for c in found if len(c) > 1 and c[0] == "verilore"]
    for run in _recorded().values():
        commands.append(shlex.split(run["cmd"].split(" | ")[-1]))
    return commands


def test_every_command_and_flag_the_page_names_exists():
    cli = _cli()
    commands = _commands(_page())
    assert len(commands) >= 8, commands
    for argv in commands:
        name = argv[1]
        if name.startswith("-") or name in {"command"}:
            continue
        assert name in cli.commands, f"verilore {name} does not exist"
        options = {o for p in cli.commands[name].params for o in getattr(p, "opts", [])}
        for word in argv[2:]:
            if word.startswith("--"):
                assert word in options, f"verilore {name} has no {word}"


def test_the_help_lines_are_the_clis_own():
    cli = _cli()
    shown = re.findall(r"<dt>([a-z-]+)</dt><dd>(.*?)</dd>", _page())
    assert [name for name, _text in shown] == [
        "brief",
        "check",
        "review",
        "recall",
        "history",
        "verify",
    ]
    for name, text in shown:
        own = (cli.commands[name].help or "").strip().splitlines()[0]
        assert html.unescape(text) == own, (name, text, own)


def test_the_benchmark_sentence_states_the_measured_numbers():
    measures = json.loads(
        (ROOT / "benchmarks" / "governed_context" / "hard" / "measures.json").read_text()
    )
    at = measures["coverage"]["500"]
    sentence = re.sub(
        r"<[^>]+>",
        "",
        re.search(r'<p class="note" id="measured">(.*?)</p>', _page(), re.S).group(1),
    )
    expected = (
        f"a 500-token brief carried {at['brief']['carried']} of {at['brief']['applicable']} "
        f"rules and leaked nothing; the kit cut to that size carried {at['dump']['carried']} "
        f"and leaked {at['dump']['leaks']} times (measured without a model"
    )
    assert at["brief"]["leaks"] == 0
    assert expected in sentence, sentence


def test_the_search_comparison_is_the_kits_own_lines():
    """`grep "Our voice"` on the kit finds these three lines; only the approved one is served."""
    kit = ROOT / "examples" / "trailhead"
    found = {}
    for path in kit.rglob("*.md"):
        for line in path.read_text().splitlines():
            if line.startswith("- Our voice"):
                found[line[2:]] = path.relative_to(kit).as_posix()
    page = _page()
    for line, path in found.items():
        assert line in page and path in page, (line, path)
    assert re.search(r'<span class="held">Our voice is bold, cheeky and loud\.</span>', page)
    assert re.search(r'<span class="held">Our voice is warm, plain and confident\.</span>', page)


def test_the_closed_demo_is_out_of_the_keyboards_reach():
    page = _page()
    assert re.search(r'<section id="try"[^>]*\binert\b', page)
    assert "trySection.inert = !open" in page
    for gone in ("LIMIT", "questions left", "sessionStorage", "scrollToId('install'"):
        assert gone not in page, gone


def test_copy_works_where_the_clipboard_api_is_refused():
    assert "document.execCommand('copy')" in _page()


def _luminance(colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def test_faint_text_is_readable():
    tokens = dict(re.findall(r"--([a-z]+): (#[0-9A-Fa-f]{6});", _page()))
    for text in ("dim", "faint", "muted"):
        for ground in ("bg", "panel"):
            high, low = sorted((_luminance(tokens[text]), _luminance(tokens[ground])), reverse=True)
            ratio = (high + 0.05) / (low + 0.05)
            assert ratio >= 4.5, f"--{text} on --{ground} is {ratio:.2f}:1"


def test_every_terminal_output_is_what_the_command_prints():
    """Re-runs every command the page shows, on a new corpus, with the model."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import site_record
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    problems = site_record.differences(site_record.shown(), site_record.record())
    assert not problems, "\n\n".join(problems)
