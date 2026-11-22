# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""One rewrite of a PostgreSQL URL to the driver a caller needs.

Standard library only at import, so the CLI can use it before anything
connects; `async_engine_for` imports SQLAlchemy when it is called.

The sync driver (psycopg2) is libpq, and reads a URL's query string the way
PostgreSQL documents it. The async driver (asyncpg) is not: SQLAlchemy hands
it every query key as a keyword argument, so a hosted database's URL, such as
Neon's `...?sslmode=require&channel_binding=require`, failed with
`TypeError: connect() got an unexpected keyword argument 'sslmode'`. asyncpg
has its own reader for libpq's keys, the one it uses for a DSN, so the async
URL hands them to it unchanged (`dsn=`), and libpq's meaning is kept:
`sslrootcert` is still checked, `verify-full` still checks the host name.
"""

from __future__ import annotations

import re
import shlex
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "async_connect_args",
    "async_engine_for",
    "async_url",
    "async_url_notes",
    "sync_url",
    "with_driver",
]

#: `postgresql://`, `postgres://` (as Neon and Heroku write it), or either with
#: a driver: `postgresql+asyncpg://`, `postgresql+psycopg://`, `+psycopg2`.
_SCHEME = re.compile(r"^postgres(?:ql)?(?:\+\w+)?://")

#: libpq keys asyncpg's own DSN reader understands, with libpq's meaning.
_ASYNCPG_DSN_KEYS = frozenset(
    {
        "sslmode",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "sslcrl",
        "sslpassword",
        "sslnegotiation",
        "ssl_min_protocol_version",
        "ssl_max_protocol_version",
        "krbsrvname",
        "gsslib",
        "passfile",
        "service",
    }
)
#: Keys SQLAlchemy's asyncpg dialect already passes to `asyncpg.connect`.
_ASYNCPG_KEYWORDS = frozenset({"ssl", "target_session_attrs", "prepared_statement_cache_size"})
#: libpq client settings asyncpg has no way to honour. Left in, asyncpg would
#: send them to the server as settings, and the server would refuse to start
#: the session. `async_url_notes` names the ones that matter.
_CLIENT_ONLY = frozenset(
    {
        "channel_binding",
        "gssencmode",
        "gssdelegation",
        "keepalives",
        "keepalives_idle",
        "keepalives_interval",
        "keepalives_count",
        "tcp_user_timeout",
        "sslcompression",
        "sslcertmode",
        "sslsni",
        "requiressl",
        "require_auth",
        "load_balance_hosts",
        "hostaddr",
        "connect_timeout",
    }
)


def with_driver(url: str, driver: str) -> str:
    """`url` with its scheme set to `postgresql+<driver>://`, whatever it said before.

    The application reads with asyncpg and migrations write with psycopg2, and a
    `DATABASE_URL` may name either driver, or none. Each caller rewrote the
    forms it thought of, and a `postgresql+asyncpg://` URL reached the sync
    driver in some of them. A URL that is not PostgreSQL is returned unchanged.
    """
    return _SCHEME.sub(f"postgresql+{driver}://", url, count=1)


def sync_url(url: str) -> str:
    """`url` for SQLAlchemy's psycopg2 driver: libpq reads the query as written."""
    return with_driver(url, "psycopg2")


def _query(url: str) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(url).query, keep_blank_values=True)


def _server_options(value: str) -> dict[str, str]:
    """libpq's `options=-c name=value ...` as server settings."""
    try:
        words = shlex.split(value)
    except ValueError:
        return {}
    settings: dict[str, str] = {}
    for index, word in enumerate(words):
        if word == "-c" and index + 1 < len(words):
            name, sep, setting = words[index + 1].partition("=")
        elif word.startswith("-c") and len(word) > 2:
            name, sep, setting = word[2:].partition("=")
        elif word.startswith("--"):
            name, sep, setting = word[2:].partition("=")
            name = name.replace("-", "_")
        else:
            continue
        if sep and name:
            settings[name] = setting
    return settings


def async_url(url: str) -> str:
    """`url` for SQLAlchemy's asyncpg driver.

    Host, port, user, password and database stay where SQLAlchemy reads them.
    libpq's TLS and connection keys go to asyncpg's DSN reader, as `dsn=`, so
    they mean what libpq means. Server settings (`application_name`, and
    `options=-c name=value`) go with them; asyncpg starts the session with
    them. Keys asyncpg cannot honour are left out: see `async_url_notes`. The
    password is never copied into `dsn`.
    """
    rewritten = with_driver(url, "asyncpg")
    if not rewritten.startswith("postgresql+asyncpg://"):
        return rewritten
    parts = urlsplit(rewritten)
    if not parts.query:
        return rewritten
    keywords: list[tuple[str, str]] = []
    dsn: list[tuple[str, str]] = []
    settings: dict[str, str] = {}
    for key, value in _query(rewritten):
        if key in _ASYNCPG_DSN_KEYS:
            dsn.append((key, value))
        elif key in _ASYNCPG_KEYWORDS:
            keywords.append((key, value))
        elif key == "options":
            settings.update(_server_options(value))
        elif key in _CLIENT_ONLY or key == "dsn":
            continue
        else:
            settings[key] = value
    dsn += list(settings.items())
    if dsn:
        keywords.append(("dsn", "postgresql://?" + urlencode(dsn)))
    return urlunsplit(parts._replace(query=urlencode(keywords)))


def async_connect_args(url: str) -> dict[str, Any]:
    """What `async_url` cannot carry in a URL: pass as `connect_args`.

    * `connect_timeout=N` as asyncpg's `timeout` (a number, which a URL can't
      give it; libpq's minimum of two seconds is kept, and 0 means asyncpg's
      default).
    * `sslrootcert=system` (libpq 16) as a TLS context that checks the server
      against the operating system's certificate authorities and its host
      name. asyncpg reads only a file there; without this the connection
      fails, which is safe, but not what was asked.
    * No statement cache (`statement_cache_size=0`), so asyncpg prepares each
      statement unnamed. A pooler in transaction mode (PgBouncer before 1.21,
      or with `max_prepared_statements = 0`) hands one server connection to
      many clients, and asyncpg's numbered names (`__asyncpg_stmt_1__`)
      collide there: "prepared statement already exists". Unique names stop
      the collisions but are never deallocated: 600 sessions left 604
      statements on one server connection. Unnamed ones leave none and give
      the same output at the same speed. Each engine here opens a new
      connection per session (`NullPool`), so a cache kept nothing anyway.
    """
    if not with_driver(url, "asyncpg").startswith("postgresql+asyncpg://"):
        return {}
    args: dict[str, Any] = {"statement_cache_size": 0}
    query = dict(_query(url))
    timeout = query.get("connect_timeout", "").strip()
    if timeout:
        try:
            seconds = float(timeout)
        except ValueError:
            seconds = 0.0
        if seconds > 0:
            args["timeout"] = max(seconds, 2.0)
    if (
        query.get("sslrootcert") == "system"
        and query.get("sslmode", "verify-full") == "verify-full"
    ):
        import ssl

        args["ssl"] = ssl.create_default_context()
    return args


def async_url_notes(url: str) -> list[str]:
    """What the async driver connects without, in a sentence each (for `doctor`)."""
    query = dict(_query(url))
    notes = []
    if query.get("channel_binding") == "require":
        verified = query.get("sslmode") == "verify-full"
        notes.append(
            "channel_binding=require: the async driver (asyncpg) cannot bind the "
            "login to the TLS channel, so it connects without it"
            + (
                "; sslmode=verify-full still checks the server"
                if verified
                else "; add sslmode=verify-full&sslrootcert=system to check the server instead"
            )
        )
    if (
        query.get("sslrootcert") == "system"
        and query.get("sslmode", "verify-full") != "verify-full"
    ):
        notes.append("sslrootcert=system needs sslmode=verify-full, as libpq requires")
    return notes


def async_engine_for(url: str, **kwargs: Any):
    """`create_async_engine` for `url`, with what a URL cannot say passed as well.

    Every engine Verilore opens is made here (a test holds it to that), so a
    hosted database's URL works the same for the CLI, the SDK and the server.
    A caller's own `connect_args` win over the URL's.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    connect_args = {**async_connect_args(url), **kwargs.pop("connect_args", {})}
    return create_async_engine(async_url(url), connect_args=connect_args, **kwargs)
