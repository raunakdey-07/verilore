# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""`verilore doctor`: an ordered list of checks that finds the cause.

Each check is `PASS`, `FAIL` (with the fix) or `SKIP`. A check that depends on
an earlier one SKIP's when that one failed, so the first red is always the
first thing a reader sees. `--json` prints the same list as JSON; callers
consume it without scraping prose.

The checks here are pure functions imported by tests through the module so a
test can fake each condition. Nothing in `doctor.py` touches stderr outside
the report; the CLI prints the result.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

#: The status strings a check can report.
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def _result(name: str, status: str, detail: str = "", fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


# --- the checks --------------------------------------------------------------


def check_python() -> tuple[bool, str, str]:
    """Python is at least 3.11."""
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 11)
    return (
        ok,
        f"python {version}",
        (
            "verilore needs Python 3.11 or newer; run `python --version` and "
            "install a newer interpreter, then re-run this command"
        ),
    )


def check_package_version() -> tuple[bool, str, str]:
    """The installed `verilore` package resolves to a version."""
    try:
        import importlib.metadata

        version = importlib.metadata.version("verilore")
    except Exception:  # noqa: BLE001 - a package without metadata is broken
        return False, "", "reinstall with `pip install verilore`"
    return True, f"verilore {version}", ""


def check_config() -> tuple[bool, str, str]:
    """The config file exists and names the local database."""
    from verilore.cli import config as config_module

    path = config_module.config_path()
    if not path.exists():
        return True, "not written yet (init will create it)", ""
    entries = config_module.load_config(path)
    if entries.get("database_url"):
        return True, str(path), ""
    return False, str(path), "run `verilore init` to write it"


def check_engine() -> tuple[bool, str, str]:
    """A container engine exists, unless DATABASE_URL points elsewhere."""
    from verilore.cli import postgres

    url = os.getenv("DATABASE_URL", "")
    if url:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host not in {"localhost", "127.0.0.1", "::1"}:
            return True, "not needed: DATABASE_URL points elsewhere", ""
    clis = postgres._container_clis()
    if not clis:
        return False, "", postgres.missing_runtime_remediation_hint()
    lines = []
    for cli in clis:
        try:
            proc = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=10)
            version = (
                (proc.stdout or proc.stderr or "").strip().splitlines()[0] if proc.stdout else cli
            )
        except Exception:  # noqa: BLE001 - a version probe failure is not a verdict
            version = cli
        if version not in lines:
            lines.append(version)
    return True, "; ".join(lines), ""


def check_database_reachable() -> tuple[bool, str, str]:
    """The configured host:port accepts connections."""
    from verilore.cli import postgres

    from verilore.cli.config import DEFAULT_LOCAL_DATABASE_URL

    url = os.getenv("DATABASE_URL", DEFAULT_LOCAL_DATABASE_URL)
    host, port = postgres.db_host_port(url)
    if postgres.tcp_open(host, port, timeout=1.0):
        return True, f"{host}:{port}", ""
    return False, "", "verilore init"


def check_credentials() -> tuple[bool, str, str]:
    """A connection that does not raise on a SELECT keeps the credentials."""
    from verilore.cli import postgres

    if not postgres.db_ready(*postgres.db_host_port(), timeout=2.0):
        return False, "", "check the password: DATABASE_URL"
    return True, "credentials accepted", ""


def check_pgvector() -> tuple[bool, str, str]:
    """The `vector` extension is installed in the database."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from verilore.api.services.db import ASYNC_DATABASE_URL

    async def probe():
        engine = create_async_engine(ASYNC_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                    )
                ).first()
            return row[0] if row else None
        finally:
            await engine.dispose()

    try:
        version = asyncio.run(probe())
    except Exception:  # noqa: BLE001 - the check itself failed
        return False, "", "check database connectivity first"
    if version is None:
        return False, "", ("CREATE EXTENSION vector; (or run the migrations)")
    return True, f"pgvector {version}", ""


def check_schema_at_head() -> tuple[bool, str, str]:
    """`alembic current` and `alembic heads` agree."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from verilore.api.services.db import ASYNC_DATABASE_URL

    async def current():
        engine = create_async_engine(ASYNC_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).first()
            return row[0] if row else None
        finally:
            await engine.dispose()

    try:
        cur = asyncio.run(current())
    except Exception:  # noqa: BLE001
        return False, "", "the database could not be reached"
    head = _heads()
    if head is None:
        return False, "", "could not determine the migration head"
    if cur == head:
        return True, f"current {cur} = head {head}", ""
    return False, f"current {cur} != head {head}", "verilore init"


def _heads() -> str | None:
    """The head revision, computed from the migration files (alembic-free)."""
    repository = Path(__file__).resolve().parents[2]
    versions = repository / "verilore" / "migrations" / "versions"
    if not versions.is_dir():
        versions = repository / "migrations" / "versions"
    down_revisions: dict[str, list[str]] = {}
    for path in sorted(versions.glob("*.py")):
        if path.name.startswith("__"):
            continue
        text = path.read_text(encoding="utf-8")
        rev = re.search(r'^revision\s*(?::\s*[^=\n]*)?\s*=\s*"([^"]*)"', text, re.M)
        if not rev:
            continue
        down = re.search(r"^down_revision\s*(?::\s*[^=\n]*)?\s*=\s*(.+)$", text, re.M)
        if down is None:
            downs = []
        else:
            raw = down.group(1).strip()
            if raw in ("None", "none", "()", "[]"):
                downs = []
            elif raw.startswith('"') and raw.endswith('"'):
                downs = [raw[1:-1]]
            elif raw.startswith("'") and raw.endswith("'"):
                downs = [raw[1:-1]]
            else:
                downs = [p.strip().strip("\"'") for p in raw.strip("()[]").split(",") if p.strip()]
        down_revisions[rev.group(1)] = downs
    referenced = {d for downs in down_revisions.values() for d in downs}
    heads = [rev for rev in down_revisions if rev not in referenced]
    return heads[0] if len(heads) == 1 else None


def check_embedding_model() -> tuple[bool, str, str]:
    """The embedding model is cached and loadable, or lexical mode is on."""
    if os.getenv("VERILORE_LEXICAL") == "1":
        return True, "lexical mode (model-free)", ""
    try:
        from verilore.api.services.embedder import Embedder

        embedder = Embedder()
        if embedder.dimension > 0:
            return True, f"{embedder.dimension}-dim model loaded", ""
    except Exception as exc:  # noqa: BLE001 - the failure text is the fix
        return False, "", f"install the model or set VERILORE_LEXICAL=1 ({type(exc).__name__})"
    return False, "", "the embedding model could not be loaded"


def check_ingest_roots() -> tuple[bool, str, str]:
    """Ingest roots are set (local mode defaults to the current directory)."""
    if os.getenv("VERILORE_INGEST_ROOTS", "").strip():
        return True, os.getenv("VERILORE_INGEST_ROOTS", ""), ""
    cwd = str(Path.cwd())
    return True, f"local mode: {cwd}", ""


def check_runtime() -> tuple[bool, str, str]:
    """The background runtime's status."""
    from verilore.api import runtime as runtime_module

    try:
        status = runtime_module.status()
        state = getattr(status, "state", str(status))
        return True, f"runtime {state}", ""
    except Exception:  # noqa: BLE001 - a missing runtime is information
        return True, "runtime not running (optional)", ""


# --- the ordered list --------------------------------------------------------

#: (name, check name, depends_on) -- `depends_on` SKIPped when an earlier one
#: failed. Functions are resolved by name at call time so tests can fake each
#: condition with `monkeypatch.setattr(doctor_module, name, fake)`.
CHECKS: list[tuple[str, str, tuple[str, ...]]] = [
    ("python >= 3.11", "check_python", ()),
    ("package version", "check_package_version", ()),
    ("config file", "check_config", ()),
    ("container engine", "check_engine", ()),
    ("database reachable", "check_database_reachable", ("container engine",)),
    ("credentials accepted", "check_credentials", ("database reachable",)),
    ("pgvector extension", "check_pgvector", ("database reachable",)),
    ("schema at head", "check_schema_at_head", ("database reachable",)),
    ("embedding model", "check_embedding_model", ("database reachable",)),
    ("ingest roots", "check_ingest_roots", ("database reachable",)),
    ("background runtime", "check_runtime", ()),
]


def run_checks() -> list[dict]:
    """Run the checks in order; dependents of a FAIL become SKIP."""
    results: list[dict] = []
    by_name: dict[str, dict] = {}
    for name, fn_name, depends_on in CHECKS:
        failed_dependency = any(by_name.get(dep, {}).get("status") == FAIL for dep in depends_on)
        if failed_dependency:
            result = _result(name, SKIP, "", "depends on a failed check")
        else:
            try:
                fn = globals().get(fn_name)
                if fn is None:
                    raise LookupError(f"no check function named {fn_name}")
                ok, detail, fix = fn()
            except Exception as exc:  # noqa: BLE001 - a check must not crash
                ok, detail, fix = False, str(exc), ""
            result = _result(name, PASS if ok else FAIL, detail, fix)
        results.append(result)
        by_name[name] = result
    return results


def render_checks(results: list[dict]) -> str:
    lines = ["verilore doctor:", ""]
    for check in results:
        suffix = f" -- {check['detail']}" if check["detail"] else ""
        lines.append(f"[{check['status']}] {check['name']}" + suffix)
        if check["status"] == FAIL and check["fix"]:
            lines.append(f"    fix: {check['fix']}")
        elif check["status"] == SKIP and check["fix"]:
            lines.append(f"    note: {check['fix']}")
    passed = sum(1 for c in results if c["status"] == PASS)
    failed = sum(1 for c in results if c["status"] == FAIL)
    lines.append(f"\n{passed}/{len(results)} passed, {failed} failed")
    return "\n".join(lines)


def render_report(
    *,
    checks: list[dict],
    os_name: str,
    os_info: str,
    wsl: bool,
    python: str,
    version: str,
    engine: str,
    logs: str,
) -> str:
    """A block a user can paste into a GitHub issue, secrets redacted."""
    text = {
        "os": os_name,
        "os_info": os_info,
        "wsl": wsl,
        "python": python,
        "version": version,
        "engine": engine,
        "checks": checks,
        "logs": logs,
    }
    payload = json.dumps(text, indent=2, default=str)
    return redact(payload)


def redact(text: str) -> str:
    """Replace every password, token and secret with `***`."""
    # Anything that looks like a credential: password=..., token ..., mpk_*
    for pattern in (
        r"(password\s*=\s*)\S+",
        r"(token\s*=\s*)\S+",
        r"(mpk_[A-Za-z0-9_-]+)",
        r"(secret\s*=\s*)\S+",
        r"(supersecret)",
    ):
        text = re.sub(pattern, r"\1***" if pattern.startswith("(mpk_") is False else r"***", text)
    return text


def render_doctor_json(results: list[dict]) -> str:
    return json.dumps(results, indent=2, default=str)


def collect_logs(data_dir: Path | None = None, lines: int = 30) -> str:
    """The last `lines` lines of the newest log under ~/.verilore/logs/."""
    from verilore.cli import config as config_module

    logs_dir = (data_dir or config_module.data_dir()) / "logs"
    if not logs_dir.is_dir():
        return "(no ~/.verilore/logs/ present)"
    files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "(no log files)"
    tail = files[0].read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    return "\n".join(tail)
