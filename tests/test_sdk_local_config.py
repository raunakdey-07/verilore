"""A local SDK client uses the database `verilore init` recorded.

`verilore init --database-url ...` writes `config.toml`, and every CLI command
and `verilore-mcp` read it. The Python client did not: `Verilore("name")` went
to the built-in default address, so the README's own example failed on any
machine whose PostgreSQL is not the default container, with a driver traceback
that named no fix.

Each case runs in a child process, because the database module reads
DATABASE_URL once, at import.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: A port nothing listens on. Connecting is refused at once, on every system.
DEAD = "postgresql://mpadmin:secret@127.0.0.1:1/verilore"

PROBE = """
import sys
from verilore import Verilore, VeriloreError
try:
    Verilore("sdk-config-probe")
except VeriloreError as exc:
    print("CODE", exc.code)
    print("RETRYABLE", exc.retryable)
    print("MESSAGE", str(exc))
    print("CAUSE", type(exc.__cause__).__name__)
    sys.exit(0)
print("CONNECTED")
"""


def _probe(tmp_path: Path, *, config_url: str | None, **env: str) -> str:
    data = tmp_path / "data"
    data.mkdir()
    if config_url is not None:
        (data / "config.toml").write_text(f'database_url = "{config_url}"\n', encoding="utf-8")
    child = {
        k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "VERILORE_DEPLOYMENT"}
    }
    child.update(VERILORE_DATA_DIR=str(data), VERILORE_LEXICAL="1", PYTHONPATH=str(ROOT), **env)
    result = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, env=child, timeout=120
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def test_a_local_client_connects_where_the_config_file_says(tmp_path):
    out = _probe(tmp_path, config_url=DEAD)
    # It went to the address in the file, not to the built-in default ...
    assert "CODE database_unavailable" in out, out
    assert "127.0.0.1:1" in out, out


def test_an_unreachable_database_is_one_error_with_the_fix_not_a_driver_traceback(tmp_path):
    out = _probe(tmp_path, config_url=None, DATABASE_URL=DEAD)
    assert "CODE database_unavailable" in out, out
    assert "RETRYABLE True" in out
    message = next(line for line in out.splitlines() if line.startswith("MESSAGE"))
    assert "could not connect to PostgreSQL at 127.0.0.1:1" in message
    assert "Fix: " in message
    # The driver's exception is kept for whoever needs it.
    assert "CAUSE None" not in out


def test_an_exported_variable_still_wins_over_the_file(tmp_path):
    real = os.environ["DATABASE_URL"]
    out = _probe(tmp_path, config_url=DEAD, DATABASE_URL=real)
    assert out.strip() == "CONNECTED", out


def test_a_server_deployment_never_reads_the_file(tmp_path):
    # No variable exported and a file that points at the dead port: a server
    # deployment must ignore the file, so the dead port is never tried.
    out = _probe(tmp_path, config_url=DEAD, VERILORE_DEPLOYMENT="server")
    assert "127.0.0.1:1" not in out, out


def test_the_cli_explains_the_translated_error_exactly_as_it_explained_the_driver_error():
    from verilore.cli.errors import explain
    from verilore.sdk import _database_unavailable

    driver = ConnectionRefusedError(111, "Connect call failed ('127.0.0.1', 1)")
    translated = _database_unavailable(driver)
    assert translated is not None and translated.code == "database_unavailable"
    try:
        raise translated from driver
    except Exception as exc:  # noqa: BLE001
        assert explain(exc) == explain(driver)
    assert _database_unavailable(ValueError("a defect stays a defect")) is None


async def test_lexical_mode_never_asks_for_the_model_at_ingest(monkeypatch):
    """`VERILORE_LEXICAL=1` covers the claim-vector cache too, not only chunks."""
    from verilore.api.services import claim_embeddings
    from verilore.api.services.ingestion import IngestionService

    asked = []

    async def pending(*args, **kwargs):
        asked.append(args)
        return [], []

    monkeypatch.setattr(claim_embeddings, "pending", pending)
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    service = IngestionService()
    assert await service._cache_claim_vectors(None, "corpus", ["version"]) == 0
    assert asked == [], "lexical mode asked which claims need a vector"
