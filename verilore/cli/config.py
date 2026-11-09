# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""The local config file: `~/.verilore/config.toml`, mode 0600.

Written by `verilore init` so a new laptop needs nothing exported, and read at
the start of every `verilore` command and `verilore-mcp`, so the database
`init` set up is the one every later command uses. Precedence is

    command-line flag  >  environment variable  >  config file  >  built-in default

Local mode needs no secrets (`server_mode_errors` requires them only for a
server deployment), so the file holds the database URL and nothing else. A
server deployment never reads it: it keeps requiring real environment variables.

The loader is deliberately small: `tomllib` to read, a tiny TOML writer, no new
dependency.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

#: The environment names the config file may set, and the key each becomes in
#: the file (TOML keys are the snake-case of the environment name). `init`
#: writes only `database_url`; the other two are read if a person adds them.
_KEYS = {
    "DATABASE_URL": "database_url",
    "VERILORE_RUNTIME_PASSWORD": "verilore_runtime_password",
    "VERILORE_CURSOR_SECRET": "verilore_cursor_secret",
}

DEFAULT_LOCAL_DATABASE_URL = "postgresql://mpadmin:secret@localhost:5432/verilore"


def data_dir() -> Path:
    """The directory configuration and logs live in, under VERILORE_DATA_DIR."""
    return Path(os.getenv("VERILORE_DATA_DIR", "~/.verilore")).expanduser()


def config_path() -> Path:
    return data_dir() / "config.toml"


def _server_mode() -> bool:
    return os.getenv("VERILORE_DEPLOYMENT", "").strip().lower() == "server"


def load_config(path: Path | None = None) -> dict[str, str]:
    """Read the config file, or return `{}` when there is none.

    A malformed or unreadable file is treated as empty rather than an error:
    a broken config must never be the reason `init` cannot tell you that the
    database is down.
    """
    here = path or config_path()
    try:
        raw = here.read_bytes()
    except OSError:
        return {}
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 - a broken config is not fatal
        return {}
    return {str(key): str(value) for key, value in data.items()}


def apply_to_environ() -> None:
    """Fill unset environment variables from the config file. Local mode only.

    Called before any command imports the database module, which reads
    `DATABASE_URL` once at import. An exported variable always wins, and a
    server deployment is never configured from this file.
    """
    if _server_mode():
        return
    config = load_config()
    for env_name, key in _KEYS.items():
        if env_name not in os.environ and key in config:
            os.environ[env_name] = config[key]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_config(entries: dict[str, str], path: Path | None = None) -> Path:
    """Serialize the given entries to the config file with mode 0600."""
    here = path or config_path()
    here.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Verilore local configuration, written by `verilore init`.",
        "# Every `verilore` command reads it; an exported variable still wins.",
        "# Edit this file, or run `verilore init --database-url ...`, to change it.",
        "",
    ]
    for env_name, key in _KEYS.items():
        if env_name in entries:
            lines.append(f'{key} = "{_escape(entries[env_name])}"')
    # Created private, not chmod-ed after: the URL carries a password.
    fd = os.open(here, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.chmod(here, 0o600)
    return here


def resolve(name: str, default: str = "", *, flag: str | None = None) -> str:
    """Resolve one name: flag > environment variable > config file > default."""
    if flag is not None:
        return flag
    if name in os.environ:
        return os.environ[name]
    key = _KEYS.get(name, name)
    config = load_config()
    if key in config:
        return config[key]
    return default


def ensure_config(
    *,
    database_url: str | None,
    flag_url: str | None = None,
    path: Path | None = None,
) -> Path:
    """Record the database URL `init` used; a second `init` changes nothing.

    A `--database-url` flag replaces the stored URL, because that is how a
    person moves Verilore to another database. Otherwise an existing URL stays.
    Other keys a person added to the file are kept as they are.
    """
    here = path or config_path()
    existing = load_config(here)

    entries = {env_name: existing[key] for env_name, key in _KEYS.items() if key in existing}
    if flag_url is not None:
        entries["DATABASE_URL"] = flag_url
    elif "database_url" not in existing:
        entries["DATABASE_URL"] = database_url or DEFAULT_LOCAL_DATABASE_URL

    changed = any(entries.get(env_name) != existing.get(key) for env_name, key in _KEYS.items())
    if changed or not here.exists():
        write_config(entries, here)
    else:
        os.chmod(here, 0o600)
    return here
