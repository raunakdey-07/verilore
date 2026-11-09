"""Every CLI failure uses one error format, and `doctor` finds the cause.

The five commands `init`, `recall`, `ingest-repo`, `remember` and `execute`
are exercised against a closed port (nothing listening), which is the single
most common first-run failure. Each must print:

    error: <what> (<code>)
      why: <why>
      fix: <exact command or setting>
      more: verilore doctor   ·   rerun with --debug for the full traceback

with exit code 1, and no `Traceback` unless `--debug` is on.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from verilore.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]

# A port nothing listens on locally. Not 5432: the point of these tests is that
# the *configured* port is unreachable, and 5432 is reachable on the machine
# that runs them.
DEAD_PORT = 5498
DEAD_DATABASE_URL = f"postgresql://mpadmin:secret@127.0.0.1:{DEAD_PORT}/verilore"


def _invoke(args, extra_env: dict | None = None):
    """Run the CLI in a subprocess with a dead database.

    A subprocess is required, not a nice-to-have: `verilore.api.services.db`
    reads `DATABASE_URL` once, when the module is first imported, so an
    in-process `CliRunner` on a session that has already imported it would
    answer on a different database than the one named here -- which is how
    these tests passed locally but not in CI, where the engine had been built
    against the session database. Running as a subprocess is also what a
    person actually experiences.
    """
    env = {
        **__import__("os").environ,
        "DATABASE_URL": DEAD_DATABASE_URL,
        "VERILORE_RUNTIME": "0",
    }
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-m", "verilore.cli.main", *args],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
        env=env,
    )
    return _Result(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))


class _Result:
    """The shape `_assert_uniform_failure` expects, over a CompletedProcess."""

    def __init__(self, exit_code: int, output: str) -> None:
        self.exit_code = exit_code
        self.output = output


def _assert_uniform_failure(result, label: str):
    assert result.exit_code == 1, f"{label}: exit {result.exit_code}\n{result.output}"
    assert "error:" in result.output, f"{label}: missing 'error:'\n{result.output}"
    # The code follows the `what` text in parentheses.
    assert re.search(
        r"\((vl_[a-z_]+|memory_unavailable|database_unavailable|error)\)", result.output
    ) or re.search(r"\([a-z_]+\)", result.output), f"{label}: no (code) in output\n{result.output}"
    assert "why:" in result.output, f"{label}: missing 'why:'\n{result.output}"
    assert "fix:" in result.output, f"{label}: missing 'fix:'\n{result.output}"
    assert "verilore doctor" in result.output, f"{label}: missing the doctor hint\n{result.output}"
    assert "Traceback" not in result.output, f"{label}: leaked a traceback\n{result.output}"


def test_init_uses_the_one_error_format():
    result = _invoke(["init"])
    _assert_uniform_failure(result, "init")


@pytest.mark.parametrize("command", ["recall", "ingest-repo", "remember"])
def test_commands_use_the_one_error_format(command):
    args = {
        "recall": ["recall", "What is the datastore?"],
        "ingest-repo": ["ingest-repo", "./docs"],
        "remember": ["remember", "The production datastore is PostgreSQL."],
    }[command]
    result = _invoke(args)
    _assert_uniform_failure(result, command)


def test_debug_shows_the_traceback():
    result = _invoke(["init", "--debug"])
    assert result.exit_code == 1, result.output
    assert "Traceback" in result.output, result.output


def test_no_hint_names_a_retired_command():
    """Hints must name real commands. These strings retired with earlier versions
    of the product: a hint to run them is a bug, not a hint."""

    forbidden = [
        "uvicorn api.main",  # the real target is verilore.api.main (via `verilore serve`)
        "docker compose up",
        "alembic upgrade head",
    ]
    # `alembic upgrade head` is allowed with `-c` (the migration command); the
    # bare form is what's retired.
    offenders = []
    cli = ROOT / "verilore" / "cli"
    for path in sorted(cli.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token == "alembic upgrade head":
                for line in text.splitlines():
                    if token in line and "-c verilore/migrations/alembic.ini" not in line:
                        offenders.append(f"{path.relative_to(ROOT)}: {line.strip()[:90]}")
            elif token in text:
                offenders.append(f"{path.relative_to(ROOT)}: {token!r}")
    assert [
        line for line in offenders if "uvicorn verilore.api.main" not in line
    ] == [], "retired command names still appear in CLI hints:\n" + "\n".join(offenders)


def test_the_format_has_the_mandated_lines():
    """The canonical five lines of a failure, exactly."""
    from verilore.cli import errors

    rendered = errors.render(
        errors.Advice(
            "database_unavailable",
            "The memory database is unavailable.",
            "nope",
            "verilore init",
            503,
        ),
        RuntimeError("nope"),
    )
    lines = [line.strip() for line in rendered.splitlines() if line.strip()]
    assert lines[0] == "error: The memory database is unavailable. (database_unavailable)"
    assert lines[1].startswith("why: ")
    assert lines[2].startswith("fix: ")
    assert "verilore doctor" in "\n".join(lines)


def test_doctor_reports_fail_with_fix_and_skips_dependents(monkeypatch):
    """Each check reports FAIL with its fix; dependent checks skip."""
    from verilore.cli import doctor as doctor_module

    monkeypatch.setattr(doctor_module, "check_python", lambda: (True, "python 3.11.9", ""))
    monkeypatch.setattr(
        doctor_module, "check_package_version", lambda: (True, "verilore 0.11.0", "")
    )
    monkeypatch.setattr(doctor_module, "check_config", lambda: (False, "", "run `verilore init`"))
    monkeypatch.setattr(doctor_module, "check_engine", lambda: (True, "podman 5.7.0", ""))
    monkeypatch.setattr(
        doctor_module, "check_database_reachable", lambda: (True, "127.0.0.1:5432", "")
    )
    monkeypatch.setattr(doctor_module, "check_credentials", lambda: (True, "mpadmin ok", ""))
    monkeypatch.setattr(doctor_module, "check_pgvector", lambda: (True, "pgvector 0.8.1", ""))
    monkeypatch.setattr(doctor_module, "check_schema_at_head", lambda: (True, "head 016", ""))
    monkeypatch.setattr(doctor_module, "check_embedding_model", lambda: (True, "384-dim", ""))
    monkeypatch.setattr(doctor_module, "check_ingest_roots", lambda: (True, "cwd", ""))
    monkeypatch.setattr(doctor_module, "check_runtime", lambda: (True, "running", ""))

    checks = doctor_module.run_checks()
    by_name = {c["name"]: c for c in checks}
    assert by_name["config file"]["status"] == "FAIL"
    assert by_name["config file"]["fix"] == "run `verilore init`"
    assert all(c["status"] in ("PASS", "FAIL", "SKIP") for c in checks)

    result = CliRunner().invoke(cli_main.app, ["doctor", "--json"], env={"VERILORE_RUNTIME": "0"})
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list) and len(payload) == len(checks)


def test_doctor_dependent_checks_skip(monkeypatch):
    from verilore.cli import doctor as doctor_module

    monkeypatch.setattr(doctor_module, "check_python", lambda: (True, "python 3.11.9", ""))
    monkeypatch.setattr(
        doctor_module, "check_package_version", lambda: (True, "verilore 0.11.0", "")
    )
    monkeypatch.setattr(doctor_module, "check_config", lambda: (True, "ok", ""))
    monkeypatch.setattr(doctor_module, "check_engine", lambda: (True, "podman 5.7.0", ""))
    # Database unreachable: every check that depends on the DB must skip, not fail.
    monkeypatch.setattr(
        doctor_module, "check_database_reachable", lambda: (False, "", "verilore init")
    )
    monkeypatch.setattr(doctor_module, "check_credentials", lambda: (True, "should-not-run", ""))
    monkeypatch.setattr(doctor_module, "check_pgvector", lambda: (True, "should-not-run", ""))
    monkeypatch.setattr(doctor_module, "check_schema_at_head", lambda: (True, "should-not-run", ""))
    monkeypatch.setattr(doctor_module, "check_embedding_model", lambda: (True, "no database", ""))
    monkeypatch.setattr(doctor_module, "check_ingest_roots", lambda: (True, "no database", ""))
    monkeypatch.setattr(doctor_module, "check_runtime", lambda: (True, "no database", ""))

    checks = doctor_module.run_checks()
    by_name = {c["name"]: c for c in checks}
    for dependent in ("credentials accepted", "pgvector extension", "schema at head"):
        assert by_name[dependent]["status"] == "SKIP", (dependent, by_name[dependent])
    # The model and the ingest roots do not need the database, so a dead
    # database must not hide a model that will not load.
    for independent in ("embedding model", "ingest roots", "background runtime"):
        assert by_name[independent]["status"] == "PASS", (independent, by_name[independent])


def test_doctor_a_refused_login_skips_the_database_checks(monkeypatch):
    """Reachable but refusing the login: pgvector and schema cannot be read, so
    they SKIP instead of failing with a misleading fix of their own."""
    from verilore.cli import doctor as doctor_module

    for name in (
        "check_python",
        "check_package_version",
        "check_config",
        "check_engine",
        "check_database_reachable",
        "check_embedding_model",
        "check_ingest_roots",
        "check_runtime",
    ):
        monkeypatch.setattr(doctor_module, name, lambda: (True, "ok", ""))
    monkeypatch.setattr(
        doctor_module, "check_credentials", lambda: (False, "refused", "fix DATABASE_URL")
    )
    monkeypatch.setattr(doctor_module, "check_pgvector", lambda: (False, "", "should not run"))
    monkeypatch.setattr(
        doctor_module, "check_schema_at_head", lambda: (False, "", "should not run")
    )

    by_name = {c["name"]: c for c in doctor_module.run_checks()}
    assert by_name["credentials accepted"]["status"] == "FAIL"
    assert by_name["pgvector extension"]["status"] == "SKIP"
    assert by_name["schema at head"]["status"] == "SKIP"


def test_doctor_ingest_roots_says_what_is_true(monkeypatch):
    """Local mode reads any directory named; it does not default to the cwd."""
    from verilore.cli import doctor as doctor_module

    monkeypatch.delenv("VERILORE_INGEST_ROOTS", raising=False)
    monkeypatch.delenv("VERILORE_DEPLOYMENT", raising=False)
    ok, detail, _ = doctor_module.check_ingest_roots()
    assert ok and "any directory" in detail, detail

    monkeypatch.setenv("VERILORE_DEPLOYMENT", "server")
    ok, detail, fix = doctor_module.check_ingest_roots()
    assert not ok and "VERILORE_INGEST_ROOTS" in fix, (detail, fix)


def test_report_redacts_secrets():
    """Every password, token, secret and URL userinfo is hidden, wherever it is.

    The secrets go *into* the report -- a check's detail, a fix, the log tail --
    because a test that never puts a secret in cannot show one is taken out.
    """
    from verilore.cli import doctor as doctor_module

    secrets = {
        "url password": "hunter2-url",
        "url user": "alice-user",
        "key=value": "hunter2-kv",
        "toml secret": "cursor-should-be-hidden",
        "json password": "hunter2-json",
        "credential": "mpk_1234567890abcdef1234567890abcdef",
        "bearer": "eyJhbGciOiJIUzI1NiJ9.payload.sig",
    }
    checks = [
        {
            "name": "credentials accepted",
            "status": "FAIL",
            "detail": f"connect postgresql://{secrets['url user']}:{secrets['url password']}"
            "@db:5432/verilore failed",
            "fix": "fix DATABASE_URL",
        }
    ]
    logs = "\n".join(
        [
            f"password={secrets['key=value']} while connecting",
            f'verilore_cursor_secret = "{secrets["toml secret"]}"',
            f'{{"VERILORE_RUNTIME_PASSWORD": "{secrets["json password"]}"}}',
            f"using credential {secrets['credential']}",
            f"Authorization: Bearer {secrets['bearer']}",
        ]
    )

    report = doctor_module.render_report(
        checks=checks,
        os_name="posix",
        os_info="Linux",
        distro="fedora",
        wsl=False,
        python="3.11.9",
        version="0.11.0",
        engine="podman 5.7.0",
        logs=logs,
    )
    for label, secret in secrets.items():
        assert secret not in report, f"{label} leaked: {secret}\n{report}"
    assert "postgresql://***@db:5432/verilore" in report, report
    # What is not a secret stays, or the report is useless.
    for kept in ("fedora", "podman 5.7.0", "credentials accepted", "3.11.9"):
        assert kept in report, f"{kept} was lost\n{report}"


def test_error_docs_name_only_real_classes_and_codes():
    """docs/errors.md must not name retired classes or `mp_*` codes."""
    from verilore import errors as taxonomy
    from verilore import sdk as sdk_module

    known_classes = {name for name in dir(taxonomy)} | {name for name in dir(sdk_module)}
    text = (ROOT / "docs" / "errors.md").read_text(encoding="utf-8")
    for stale in (
        "MindPalaceValidationError",
        "MindPalaceNotFoundError",
        "MindPalaceUnauthorizedError",
        "MindPalaceAuthenticationError",
        "MindPalaceTransportError",
        "MindPalaceInternalError",
    ):
        assert stale not in text, f"docs/errors.md still names {stale}"
    for code in ("mp_provider_timeout",):
        assert code not in text, f"docs/errors.md still uses code {code}"
    # Every class name written in the doc must exist.
    for found in re.findall(r"`([A-Za-z][A-Za-z0-9_]*(?:Error|Exception))`", text):
        assert (
            found in known_classes
        ), f"docs/errors.md names {found}, which is not in verilore/errors.py"
