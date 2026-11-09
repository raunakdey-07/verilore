"""Local laptop setup: `verilore init` is the whole setup, and it never fails silently.

The spec tests here fake the container CLI (`_run_cli` and `_container_clis`),
so they run on any machine with no podman/docker and no PostgreSQL.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from verilore.cli import main as cli_main
from verilore.cli import postgres

ROOT = Path(__file__).resolve().parents[1]


class _Proc:
    """A fake completed process, like `_run_cli` returns."""

    def __init__(self, argv, returncode=0, stdout="", stderr=""):
        self.args = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_container(monkeypatch):
    """Replace the container CLI with an in-memory fake.

    Returns a list that records every argv the fake was called with.
    """
    calls: list = []

    def fake_run(cli, args, timeout=30.0, **kw):
        calls.append([cli, *args])
        argv = list(args)
        # Simulate `podman ps -a --format json`: no existing containers, so
        # provisioning is exercised on every test that reaches it.
        if argv and argv[0] == "ps":
            return _Proc(argv, 0, "[]")
        return _Proc(argv, 0)

    monkeypatch.setattr(postgres, "_run_cli", fake_run)
    monkeypatch.setattr(postgres, "_container_clis", lambda: ["podman"])
    yield calls


def test_provision_uses_official_image_localhost_and_volume(fake_container, monkeypatch):
    """Provisioning uses the official fully-qualified image, binds locally,
    and mounts a named volume."""
    # Point db_host_port at the standard local port with a fresh URL.
    monkeypatch.setenv("DATABASE_URL", "postgresql://mpadmin:secret@localhost:5432/verilore")
    monkeypatch.setattr(postgres, "db_ready", lambda *a, **k: False)

    assert postgres.provision_local_postgres(timeout=0.1) is False
    run_cmd = next((c for c in fake_container if c[1] == "run"), None)
    assert run_cmd is not None, f"no container run in: {fake_container}"
    flat = " ".join(run_cmd)
    assert "docker.io/pgvector/pgvector:pg15" in flat, flat
    assert "127.0.0.1:5432:5432" in flat, flat
    assert "verilore-pgdata:/var/lib/postgresql/data" in flat, flat


def test_provision_failure_is_reported(fake_container, monkeypatch):
    """A failing provision is printed with its stderr and a fix, not swallowed."""

    def failing_run(cli, args, timeout=30.0, **kw):
        fake_container.append([cli, *args])
        return _Proc(args, 125, "", "short-name resolution failed")

    monkeypatch.setattr(postgres, "_run_cli", failing_run)
    monkeypatch.setattr(postgres, "db_ready", lambda *a, **k: False)

    result = CliRunner().invoke(cli_main.app, ["init"], env={"VERILORE_RUNTIME": "0"})
    assert result.exit_code == 1, result.output
    assert "short-name resolution" in result.output, result.output
    assert "fix:" in result.output.lower(), result.output
    assert "Traceback" not in result.output, result.output


def test_no_engine_prints_the_install_command(monkeypatch, tmp_path):
    """Without podman/docker, `init` prints the distro's install command."""

    def no_clis():
        return []

    monkeypatch.setattr(postgres, "_container_clis", no_clis)
    monkeypatch.setattr(postgres, "linux_distro_id", lambda: "fedora")
    monkeypatch.setattr(postgres, "db_ready", lambda *a, **k: False)

    result = CliRunner().invoke(cli_main.app, ["init"], env={"VERILORE_RUNTIME": "0"})
    assert result.exit_code == 1, result.output
    assert "sudo dnf install -y podman" in result.output, result.output


def test_port_taken_by_something_else(fake_container, monkeypatch):
    """A port that accepts TCP but is not PostgreSQL yields the conflict hint."""
    monkeypatch.setattr(
        postgres, "tcp_open", lambda host, port, timeout=1.0: True, raising=False
    )
    monkeypatch.setattr(postgres, "db_ready", lambda *a, **k: False)

    result = CliRunner().invoke(cli_main.app, ["init"], env={"VERILORE_RUNTIME": "0"})
    assert result.exit_code == 1, result.output
    assert "5432" in result.output, result.output
    assert "--database-url" in result.output, result.output


def test_config_precedence(monkeypatch, tmp_path):
    """Precedence: flag > env > config > built-in default, exactly.

    The loader must read the config file at ``<data>/config.toml`` and never
    override anything set through a flag or the environment.
    """
    from verilore.cli import config as config_module

    data = tmp_path / "data"
    data.mkdir()
    config_path = data / "config.toml"
    config_path.write_text(
        'database_url = "postgresql://config@db/config"\n'
        'verilore_runtime_password = "config-pw"\n'
    )

    monkeypatch.setenv("VERILORE_DATA_DIR", str(data))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Config beats the default.
    assert config_module.resolve("DATABASE_URL", "postgresql://d/d") == (
        "postgresql://config@db/config"
    )
    assert config_module.resolve("VERILORE_RUNTIME_PASSWORD", "") == "config-pw"

    # Environment beats the config.
    monkeypatch.setenv("DATABASE_URL", "postgresql://env@db/env")
    assert config_module.resolve("DATABASE_URL", "postgresql://d/d") == (
        "postgresql://env@db/env"
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # A command-line flag beats the environment.
    monkeypatch.setenv("DATABASE_URL", "postgresql://env@db/env")
    assert config_module.resolve(
        "DATABASE_URL", "postgresql://d/d", flag="postgresql://flag@db/flag"
    ) == "postgresql://flag@db/flag"

    # And when none is set, the built-in default wins.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("VERILORE_DATA_DIR", str(empty))
    assert config_module.resolve("DATABASE_URL", "postgresql://d/d") == "postgresql://d/d"


def test_config_is_private_and_reused(monkeypatch, tmp_path):
    """`init` writes config.toml with mode 0o600, then reuses it unchanged."""
    from verilore.cli import config as config_module

    data = tmp_path / "data"
    monkeypatch.setenv("VERILORE_DATA_DIR", str(data))
    # No database anywhere; init may fail at the connection check, but it must
    # have written the config first and made it private.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    CliRunner().invoke(cli_main.app, ["init"], env={"VERILORE_RUNTIME": "0"})

    path = data / "config.toml"
    assert path.exists(), f"no config written to {data}"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"config mode is {oct(mode)}, expected 0o600"

    before = path.read_bytes()
    CliRunner().invoke(cli_main.app, ["init"], env={"VERILORE_RUNTIME": "0"})
    assert path.read_bytes() == before, "second init rewrote the config"
