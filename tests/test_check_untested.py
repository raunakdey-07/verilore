"""`check` names the rules it cannot test, so "no problems" is not read as "all clear" (CHECK-4).

Team 052's bad draft said "Coffee boosts your immunity", and `check` answered
"No problems found against 29 approved lines": the most legally risky rule in
the kit, "Never claim health benefits", read as passed. It was never tested;
no exact check can test it. Every approved rule that `check` cannot test
exactly is now listed after the result, under "Needs a reviewer". And `verilore
check "some text"` said "No such file"; it now says the argument is a file.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

KIT = [
    ("brand/voice.md", 'Never use the word "premium".'),
    ("brand/voice.md", "Never claim health benefits."),
    ("brand/voice.md", 'Always end an Instagram caption with "Brewed in Coorg".'),
    ("brand/voice.md", "Never tag a competitor on LinkedIn."),
    ("brand/voice.md", "Do not promise delivery in under 48 hours."),
    ("brand/voice.md", "Keep sentences under 20 words."),
    ("brand/voice.md", "We sound like a friend who knows coffee."),
    ("brand/products.md", "Price: ₹1499 for a 500 g bag."),
    ("brand/channels.md", "Instagram: Length: 150 characters; Hashtags: 5 to 8"),
]


def _current():
    return {
        "corpus": "kaveri",
        "current_memories": [
            {"id": f"line-{n}", "claim": claim, "path": path} for n, (path, claim) in enumerate(KIT)
        ],
    }


def _check(draft, **kwargs):
    from verilore.check import check_draft

    return check_draft(draft, _current(), **kwargs)


def _claims(check):
    return [line["claim"] for line in check.untested]


def test_rules_no_exact_check_can_test_are_named_and_facts_are_not():
    result = _check("Coffee boosts your immunity. #a #b #c #d #e", channel="Instagram")
    assert result.ok
    # Not "premium" (a banned word), not the 48 hours (a limit), not the channel
    # row (counted), not the price (a value), not the voice line (not a rule),
    # and not the LinkedIn rule: the draft is for Instagram.
    assert _claims(result) == [
        "Never claim health benefits.",
        'Always end an Instagram caption with "Brewed in Coorg".',
        "Keep sentences under 20 words.",
    ]
    assert result.untested[0] == {
        "id": "line-1",
        "claim": "Never claim health benefits.",
        "path": "brand/voice.md",
    }


def test_without_a_channel_the_channel_lines_and_channel_rules_are_untested_too():
    result = _check("Coffee boosts your immunity.")
    assert "Instagram: Length: 150 characters; Hashtags: 5 to 8" in _claims(result)
    assert "Never tag a competitor on LinkedIn." in _claims(result)
    assert 'Always end an Instagram caption with "Brewed in Coorg".' in _claims(result)


def test_the_report_says_what_was_not_tested_after_a_clean_or_a_failed_result():
    from verilore.check import render_check, render_feedback

    tags = " #a #b #c #d #e"
    clean = render_check(_check("Coffee boosts your immunity." + tags, channel="Instagram"))
    lines = clean.splitlines()
    assert lines[0].startswith("No problems found against 9 approved lines")
    assert lines[1:] == [
        "Needs a reviewer: check cannot test these 3 rules exactly.",
        "- Never claim health benefits.  [brand/voice.md]",
        '- Always end an Instagram caption with "Brewed in Coorg".  [brand/voice.md]',
        "- Keep sentences under 20 words.  [brand/voice.md]",
    ]
    failed = _check("Our premium coffee boosts your immunity." + tags, channel="Instagram")
    report = render_check(failed)
    assert report.splitlines()[0] == "1 problem(s) against 9 approved lines:"
    assert "Needs a reviewer: check cannot test these 3 rules exactly." in report
    # The instruction to a model lists only what to change.
    assert "Needs a reviewer" not in render_feedback(failed)
    assert failed.as_dict()["needs_review"] == list(failed.untested)


def test_the_cli_says_a_draft_is_a_file_or_standard_input(monkeypatch, tmp_path):
    import verilore.cli.main as cli

    def check(draft, corpus, path_prefix=None, **kwargs):
        from verilore.check import check_draft

        return check_draft(draft, _current(), **kwargs)

    monkeypatch.setattr(
        cli,
        "_client",
        lambda base_url, **kwargs: SimpleNamespace(memory=SimpleNamespace(check=check)),
    )
    runner = CliRunner()
    text = runner.invoke(cli.app, ["check", "Coffee boosts your immunity."])
    assert text.exit_code == 2
    assert (
        '[ERROR] No file named "Coffee boosts your immunity.". `verilore check` reads the '
        "draft from a file: give its path, or - to read it from standard input."
    ) in text.output
    folder = runner.invoke(cli.app, ["check", str(tmp_path)])
    assert folder.exit_code == 2 and "is a folder, not a file" in folder.output

    piped = runner.invoke(cli.app, ["check", "-", "--json"], input="Coffee boosts immunity.")
    assert piped.exit_code == 0, piped.output
    body = json.loads(piped.stdout if hasattr(piped, "stdout") else piped.output)
    assert "Never claim health benefits." in [line["claim"] for line in body["needs_review"]]
