"""Every line under `must` that fits is kept, and one that does not is named as such (BRIEF-4).

Team 052 marked eight lines `must` and asked for a 150-token brief. Three were
cut, among them "Never claim health benefits", and the brief said only "24
more approved lines, 5 of them rules": nothing told the app or the model that
a line it had required was missing. And the brief stopped at the first line
that did not fit, so a shorter required line after a long one was lost while
there was room for it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

LONG = (
    "Never claim that coffee cures, prevents or treats any illness, or that it boosts "
    "immunity, energy or focus, in any caption, email, post, banner or reply, in any season, "
    "and never quote a study, a doctor or a customer who says so, even in a reply to a question."
)


def _claim(n: int, text: str, path: str) -> dict:
    return {"id": f"c{n}", "claim": text, "path": path, "status": "CURRENT"}


def _response(claims) -> dict:
    return {"corpus": "kaveri", "current_memories": list(claims), "conflicts": []}


def _lines(brief) -> list[str]:
    return [line[2:] for line in brief.text.splitlines() if line.startswith("- ")]


def _brief(claims, **kwargs):
    from verilore.brief import render_brief

    return render_brief(_response(claims), **kwargs)


def test_a_required_line_that_fits_is_kept_after_one_that_does_not():
    claims = [
        _claim(1, LONG, "brand/voice.md"),
        _claim(2, "Use Indian English spelling.", "brand/voice.md"),
        *[
            _claim(10 + n, f"The Coorg blend is roasted in batch {n}.", "brand/c.md")
            for n in range(9)
        ],
    ]
    brief = _brief(claims, max_chars=400, must=["brand/voice.md"])
    assert len(brief.text) <= 400
    assert "Use Indian English spelling." in _lines(brief)
    assert LONG not in _lines(brief)
    assert brief.omitted_must == 1
    assert brief.text.splitlines()[-1] == (
        f"Left out for length: {brief.omitted} more approved lines, "
        f"{brief.omitted_rules} of them rules, including 1 marked must."
    )


def test_a_shorter_line_after_one_that_did_not_fit_is_still_offered_the_room():
    claims = [
        _claim(1, LONG, "brand/voice.md"),
        _claim(2, "Our café opened in Coorg.", "brand/story.md"),
    ]
    brief = _brief(claims, max_chars=400)
    assert "Our café opened in Coorg." in _lines(brief)
    assert brief.omitted == brief.omitted_rules == 1 and brief.omitted_must == 0
    assert brief.text.splitlines()[-1] == (
        "Left out for length: 1 more approved lines, 1 of them rules."
    )


def test_when_every_required_line_fits_nothing_is_said_about_must():
    claims = [
        _claim(1, "Never claim health benefits.", "brand/voice.md"),
        *[
            _claim(10 + n, f"The Coorg blend is roasted in batch {n}.", "brand/c.md")
            for n in range(40)
        ],
    ]
    brief = _brief(claims, max_chars=600, must=["brand/voice.md"])
    assert "Never claim health benefits." in _lines(brief)
    assert brief.omitted > 0 and brief.omitted_must == 0
    assert "marked must" not in brief.text


def test_the_count_and_the_size_hold_at_every_budget():
    """Across budgets, in characters and in tokens: never over the limit, every
    claim kept or counted, and `omitted_must` is exactly the required claims
    that are not in the text."""
    from verilore.brief import approx_tokens

    claims = [
        _claim(1, LONG, "brand/voice.md"),
        _claim(2, "Never use the word premium.", "brand/voice.md"),
        _claim(3, LONG.replace("coffee", "tea"), "brand/voice.md"),
        _claim(4, "Use Indian English spelling.", "brand/voice.md"),
        *[
            _claim(10 + n, f"The {name} blend is roasted in batch {n}." + " Slowly." * (n % 7), p)
            for n, (name, p) in enumerate(
                [("Araku", "brand/c.md"), ("Coorg", "brand/d.md"), ("Nilgiri", "campaigns/x.md")]
                * 30
            )
        ],
    ]
    required = {"c1", "c2", "c3", "c4"}
    for limit in range(400, 4000, 61):
        brief = _brief(claims, max_chars=limit, must=["brand/voice.md"])
        assert len(brief.text) <= limit
        assert brief.kept + brief.omitted == len(claims)
        assert brief.omitted_must == len(required - set(brief.claim_ids))
    for limit in range(100, 1000, 17):
        brief = _brief(claims, max_tokens=limit, must=["brand/voice.md"])
        assert approx_tokens(brief.text) <= limit
        assert brief.omitted_must == len(required - set(brief.claim_ids))


def test_the_cli_reports_required_lines_that_did_not_fit(monkeypatch):
    import verilore.cli.main as cli

    claims = [
        _claim(1, LONG, "brand/voice.md"),
        _claim(2, "Use Indian English spelling.", "brand/voice.md"),
    ]

    def brief(corpus, *, path_prefix=None, **options):
        from verilore.brief import render_brief

        return render_brief(_response(claims), path_prefix=path_prefix, **options)

    client = SimpleNamespace(memory=SimpleNamespace(brief=brief))
    monkeypatch.setattr(cli, "_client", lambda base_url, runtime=True: client)
    runner = CliRunner()
    args = ["brief", "--must", "brand/voice.md", "--max-chars", "400"]
    plain = runner.invoke(cli.app, args)
    assert plain.exit_code == 0, plain.output
    assert (
        "1 line under --must did not fit. Raise --max-tokens or --max-chars, or narrow --must."
        in plain.output
    )
    as_json = runner.invoke(cli.app, [*args, "--json"])
    body = json.loads(as_json.stdout if hasattr(as_json, "stdout") else as_json.output)
    assert body["omitted_must"] == 1
