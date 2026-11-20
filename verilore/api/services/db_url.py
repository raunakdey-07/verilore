# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""One rewrite of a PostgreSQL URL to the driver a caller needs.

Standard library only, so the CLI can use it before anything connects.
"""

from __future__ import annotations

import re

__all__ = ["async_url", "sync_url", "with_driver"]

#: `postgresql://`, `postgres://` (as Neon and Heroku write it), or either with
#: a driver: `postgresql+asyncpg://`, `postgresql+psycopg://`, `+psycopg2`.
_SCHEME = re.compile(r"^postgres(?:ql)?(?:\+\w+)?://")


def with_driver(url: str, driver: str) -> str:
    """`url` with its scheme set to `postgresql+<driver>://`, whatever it said before.

    The application reads with asyncpg and migrations write with psycopg2, and a
    `DATABASE_URL` may name either driver, or none. Each caller rewrote the
    forms it thought of, and a `postgresql+asyncpg://` URL reached the sync
    driver in some of them. A URL that is not PostgreSQL is returned unchanged.
    """
    return _SCHEME.sub(f"postgresql+{driver}://", url, count=1)


def async_url(url: str) -> str:
    """`url` for SQLAlchemy's asyncpg driver."""
    return with_driver(url, "asyncpg")


def sync_url(url: str) -> str:
    """`url` for SQLAlchemy's psycopg2 driver."""
    return with_driver(url, "psycopg2")
