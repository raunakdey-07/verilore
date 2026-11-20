# SPDX-License-Identifier: Apache-2.0
"""The runtime is reachable from a long home folder, and says why when it stops (v0.12.1).

Team 052's evaluation set HOME to a path longer than about 71 characters.
`verilore runtime start` printed "Runtime starting" and exited 0;
`verilore runtime status` said "Runtime is not running", every time. The socket
path did not fit in a socket address, so it fell back to
`/tmp/mp-<pid>-<random>.sock`: a different name in every process, so no client
found the server, and every start left a socket behind. The runtime's errors
went to /dev/null, so nothing said so.

Now the fallback is one name per state folder, in a private folder, and what a
background runtime prints goes to a log that `runtime status` and `doctor` show.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def long_state(tmp_path, monkeypatch):
    state = tmp_path / ("a-long-home-folder-name-" * 5) / ".cache" / "verilore"
    monkeypatch.setenv("VERILORE_STATE_DIR", str(state))
    monkeypatch.delenv("TMPDIR", raising=False)
    from verilore.api import runtime as runtime_module

    return runtime_module, state


def test_a_long_state_folder_gets_one_short_socket_every_process_agrees_on(long_state):
    runtime_module, state = long_state
    assert len(str(state / "runtime.sock").encode()) > 100
    path = runtime_module.socket_path()
    assert len(str(path).encode()) <= 100
    assert path == runtime_module.socket_path()
    assert path.parent.name == f"verilore-{os.getuid()}"
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # Another process, as `runtime start` and `recall` are, computes the same name.
    other = subprocess.run(
        [sys.executable, "-c", "from verilore.api import runtime; print(runtime.socket_path())"],
        env=dict(os.environ, PYTHONPATH=str(ROOT)),
        capture_output=True,
        text=True,
        check=True,
    )
    assert other.stdout.strip() == str(path)


def test_a_short_state_folder_keeps_its_socket(tmp_path, monkeypatch):
    monkeypatch.setenv("VERILORE_STATE_DIR", str(tmp_path / "s"))
    from verilore.api import runtime as runtime_module

    assert runtime_module.socket_path() == tmp_path / "s" / "runtime.sock"


def test_a_folder_others_can_write_to_is_not_used(long_state, tmp_path, monkeypatch):
    runtime_module, _state = long_state
    shared = tmp_path / "t"
    (shared / f"verilore-{os.getuid()}").mkdir(parents=True)
    os.chmod(shared / f"verilore-{os.getuid()}", 0o777)
    monkeypatch.setenv("TMPDIR", str(shared))
    path = runtime_module.socket_path()
    assert shared not in path.parents


def test_spawn_sends_what_the_runtime_prints_to_a_log(tmp_path, monkeypatch):
    monkeypatch.setenv("VERILORE_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.delenv("VERILORE_RUNTIME", raising=False)
    from verilore.api import runtime as runtime_module

    seen = {}

    class FakePopen:
        def __init__(self, argv, **kwargs):
            seen["stderr"] = kwargs["stderr"]
            seen["same"] = os.path.samestat(
                os.fstat(kwargs["stderr"].fileno()), runtime_module.log_path().stat()
            )
            kwargs["stderr"].write(b"verilore runtime: OSError: AF_UNIX path too long\n")

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(runtime_module, "reachable", lambda: False)
    assert runtime_module.spawn()
    assert seen["same"], "the runtime's stderr is not the log"
    assert stat.S_IMODE(runtime_module.log_path().stat().st_mode) == 0o600
    assert runtime_module.last_error() == "verilore runtime: OSError: AF_UNIX path too long"


def test_a_runtime_that_fails_says_why_in_one_line(monkeypatch, capsys):
    from verilore import runtime as entry
    from verilore.api import runtime as runtime_module

    async def fail():
        raise OSError("AF_UNIX path too long")

    monkeypatch.setattr(runtime_module, "serve", fail)
    assert entry.main([]) == 1
    assert capsys.readouterr().err.strip() == "verilore runtime: OSError: AF_UNIX path too long"


def test_status_and_doctor_show_the_last_error(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from verilore.api import runtime as runtime_module
    from verilore.cli import doctor
    from verilore.cli.main import app

    monkeypatch.setenv("VERILORE_STATE_DIR", str(tmp_path / "s"))
    (tmp_path / "s").mkdir()
    runtime_module.log_path().write_text(
        "--- start 2026-11-20 10:00:00\nverilore runtime: OSError: AF_UNIX path too long\n"
    )
    assert runtime_module.last_error() == "verilore runtime: OSError: AF_UNIX path too long"
    status = CliRunner().invoke(app, ["runtime", "status"])
    assert "last error: verilore runtime: OSError: AF_UNIX path too long" in status.output
    ok, detail, _fix = doctor.check_runtime()
    assert ok and "it last stopped with: verilore runtime: OSError" in detail

    # A start that printed nothing has no error to show.
    with runtime_module.log_path().open("a") as log:
        log.write("--- start 2026-11-20 11:00:00\n")
    assert runtime_module.last_error() is None


def test_the_log_keeps_only_its_tail(tmp_path, monkeypatch):
    monkeypatch.setenv("VERILORE_STATE_DIR", str(tmp_path / "s"))
    (tmp_path / "s").mkdir()
    from verilore.api import runtime as runtime_module

    runtime_module.log_path().write_bytes(b"x" * 100_000)
    runtime_module._open_log().close()
    assert runtime_module.log_path().stat().st_size < 20_000


@pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") or os.getenv("MEMORY_TEST_DATABASE_URL")),
    reason="needs a real PostgreSQL for a runtime to serve reads from",
)
def test_a_runtime_started_from_a_long_home_folder_is_reachable(long_state, monkeypatch):
    runtime_module, _state = long_state
    monkeypatch.delenv("VERILORE_RUNTIME", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    assert runtime_module.spawn()
    try:
        deadline = time.monotonic() + 30
        while runtime_module.status().state != "ready" and time.monotonic() < deadline:
            time.sleep(0.2)
        assert runtime_module.status().state == "ready", runtime_module.last_error()
    finally:
        runtime_module.call({"op": "shutdown"}, timeout=10.0)
    deadline = time.monotonic() + 20
    while runtime_module.socket_path().exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not runtime_module.socket_path().exists()
