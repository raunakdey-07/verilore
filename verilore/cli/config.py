# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""The local config file: `~/.verilore/config.toml`, mode 0600.

Written by `verilore init` so a new laptop needs no exported environment:
the database URL and the secrets local mode wants live in one file, beneath
the data directory the logs already use. Precedence everywhere this resolves
a value is:

    command-line flag  >  environment variable  >  config file  >  built-in default

The loader is deliberately small: `tomllib` to read, a tiny TOML writer, no new
dependency. Server mode never reads this file for secrets -- it keeps requiring
real environment variables.
"""

from __future__ import annotations

import os
import secrets
import tomllib
from pathlib import Path

from verilore.api.services.authz import LOCAL_ONLY_SECRETS

#: The environment names `init` writes to the config file, and the key each
#: becomes in the file (TOML keys are the snake-case of the environment name).
_KEYS = {
    "DATABASE_URL": "database_url",
    "VERILORE_RUNTIME_PASSWORD": "verilore_runtime_password",
    "VERILORE_CURSOR_SECRET": "verilore_cursor_secret",
}

#: The two secrets that only ever needed an invented placeholder locally, so
#: `init` generates a real value once instead.
_GENERATED = ("VERILORE_RUNTIME_PASSWORD", "VERILORE_CURSOR_SECRET")

DEFAULT_LOCAL_DATABASE_URL = "postgresql://mpadmin:secret@localhost:5432/verilore"


def data_dir() -> Path:
    """The directory configuration and logs live in, under VERILORE_DATA_DIR."""
    return Path(os.getenv("VERILORE_DATA_DIR", "~/.verilore")).expanduser()


def config_path() -> Path:
    return data_dir() / "config.toml"


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


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_config(entries: dict[str, str], path: Path | None = None) -> Path:
    """Serialize the given entries to the config file with mode 0600."""
    here = path or config_path()
    here.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Verilore local configuration, written by `verilore init`.",
        "# The values here let a new laptop run with nothing exported.",
        "# `init` never overwrites an existing key; edit this file to change one.",
        "",
    ]
    for env_name, key in _KEYS.items():
        if env_name in entries:
            lines.append(f'{key} = "{_escape(entries[env_name])}"')
    here.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
    """Write any missing `init` keys; never overwrite an existing key.

    A second `init` is a no-op: secrets are generated once and reused, the URL
    already in the file stays, and the file is still made private first.
    """
    here = path or config_path()
    existing = load_config(here)

    entries: dict[str, str] = {}
    if flag_url is not None:
        entries["DATABASE_URL"] = flag_url
    elif "DATABASE_URL" in os.environ:
        entries["DATABASE_URL"] = os.environ["DATABASE_URL"]
    elif "database_url" in existing:
        entries["DATABASE_URL"] = existing["database_url"]
    else:
        entries["DATABASE_URL"] = database_url or DEFAULT_LOCAL_DATABASE_URL

    for env_name in _GENERATED:
        key = _KEYS[env_name]
        if key in existing:
            entries[env_name] = existing[key]
        elif env_name in os.environ:
            entries[env_name] = os.environ[env_name]
        else:
            entries[env_name] = secrets.token_urlsafe(32)
        # The placeholder a server deployment must never ship is never written:
        # `init` generates a real value instead.
        if entries[env_name] == LOCAL_ONLY_SECRETS.get(env_name):
            entries[env_name] = secrets.token_urlsafe(32)

    changed = any(entries[env_name] != existing.get(key, "") for env_name, key in _KEYS.items())
    if changed or not here.exists():
        write_config(entries, here)
    else:
        os.chmod(here, 0o600)
    return here
