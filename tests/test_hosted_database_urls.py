"""A hosted database's URL works with both drivers, and keeps libpq's meaning (DB-1).

Neon gives `postgresql://...-pooler.../neondb?sslmode=require&channel_binding=require`.
psycopg2 is libpq and reads that as PostgreSQL documents it. SQLAlchemy's
asyncpg driver handed each query key to `asyncpg.connect` as a keyword, and
every command failed: `connect() got an unexpected keyword argument 'sslmode'`.

Turning `sslmode` into asyncpg's `ssl` (the first design) made that URL
connect, but it had to drop `sslrootcert`, and so it connected where libpq
refuses: `sslmode=require&sslrootcert=<a CA that did not sign the server>`.
Measured against libpq on 27 URLs (TLS modes, certificate checks, host names,
`application_name`, `options`, timeouts, a PgBouncer in transaction mode), it
matched 20; handing libpq's keys to asyncpg's own DSN reader matched 26, and
the 27th is channel binding, which asyncpg does not do.

These tests hold the rewrite to that: the keys reach a reader that knows
them, the password is never copied, and, where the test server speaks TLS, a
connection succeeds or fails exactly where libpq's does.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import ssl
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

# A module import, so that each test fails on its own where a name is missing.
from verilore.api.services import db_url

ROOT = Path(__file__).resolve().parents[1]
NEON = (
    "postgresql://alex:pw-secret@ep-cool-name-123456-pooler.eu-central-1.aws.neon.tech"
    "/neondb?sslmode=require&channel_binding=require"
)


def _keywords(url: str) -> dict:
    """What SQLAlchemy's asyncpg dialect will pass to `asyncpg.connect`."""
    from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
    from sqlalchemy.engine import make_url

    _args, kwargs = PGDialect_asyncpg().create_connect_args(make_url(db_url.async_url(url)))
    return kwargs


def _dsn(url: str) -> dict:
    return dict(parse_qsl(urlsplit(_keywords(url).get("dsn", "postgresql://")).query))


URLS = [
    NEON,
    "postgres://u:p@h/d?sslmode=verify-full&sslrootcert=/etc/ssl/rds.pem",
    "postgresql://u:p@h/d?sslmode=disable",
    "postgresql://u:p@h:6543/d?sslmode=require&connect_timeout=10&application_name=team052",
    "postgresql://u:p@h/d?options=-c%20statement_timeout%3D5000&gssencmode=disable",
    "postgresql://u:p@h/d?target_session_attrs=read-write&keepalives=1&keepalives_idle=30",
    "postgresql://u:p@h/d?sslmode=verify-full&sslrootcert=system",
    "postgresql+asyncpg://u:p@h/d?ssl=require",
]


@pytest.mark.parametrize("url", URLS)
def test_every_key_reaches_a_reader_that_knows_it(url):
    import asyncpg

    accepted = set(inspect.signature(asyncpg.connect).parameters)
    for key in _keywords(url):
        assert key in accepted, f"asyncpg.connect has no {key!r} ({url})"


def test_neons_url_works_both_ways():
    assert db_url.sync_url(NEON) == NEON.replace("postgresql://", "postgresql+psycopg2://")
    kwargs = _keywords(NEON)
    assert kwargs["host"] == "ep-cool-name-123456-pooler.eu-central-1.aws.neon.tech"
    assert kwargs["database"] == "neondb" and kwargs["user"] == "alex"
    assert _dsn(NEON) == {"sslmode": "require"}


def test_the_password_is_never_copied():
    assert "pw-secret" not in _keywords(NEON)["dsn"]
    assert db_url.async_url(NEON).count("pw-secret") == 1


def test_certificate_checks_keep_libpqs_meaning():
    url = "postgresql://u:p@h/d?sslmode=verify-full&sslrootcert=/etc/ssl/rds.pem"
    assert _dsn(url) == {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/rds.pem"}
    assert "ssl" not in _keywords(url)


def test_server_settings_start_the_session():
    url = (
        "postgresql://u:p@h/d?application_name=team052"
        "&options=-c%20statement_timeout%3D5000%20-c%20search_path%3Dapp"
    )
    assert _dsn(url) == {
        "application_name": "team052",
        "statement_timeout": "5000",
        "search_path": "app",
    }


@pytest.mark.parametrize(
    "key", ["channel_binding=require", "gssencmode=disable", "keepalives=1", "connect_timeout=9"]
)
def test_what_asyncpg_cannot_honour_is_not_sent_to_the_server(key):
    url = f"postgresql://u:p@h/d?sslmode=prefer&{key}"
    assert _dsn(url) == {"sslmode": "prefer"}


def test_a_timeout_is_a_number():
    assert db_url.async_connect_args("postgresql://u:p@h/d?connect_timeout=9")["timeout"] == 9.0
    # libpq waits at least two seconds, and 0 means "no limit": asyncpg's default.
    assert db_url.async_connect_args("postgresql://u:p@h/d?connect_timeout=1")["timeout"] == 2.0
    assert "timeout" not in db_url.async_connect_args("postgresql://u:p@h/d?connect_timeout=0")


def test_the_system_certificate_store_checks_the_server():
    args = db_url.async_connect_args("postgresql://u:p@h/d?sslmode=verify-full&sslrootcert=system")
    context = args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    # libpq refuses system with a weaker mode; so does this, by not helping.
    weaker = db_url.async_connect_args("postgresql://u:p@h/d?sslmode=require&sslrootcert=system")
    assert "ssl" not in weaker


def test_statements_are_prepared_unnamed_for_a_pooler():
    """PgBouncer in transaction mode without `max_prepared_statements` shares
    one server connection between clients, and asyncpg's numbered names
    (`__asyncpg_stmt_6__`) collide there: "prepared statement already exists".
    Measured on PgBouncer 1.24 with `max_prepared_statements = 0`, 600 short
    sessions of three statements each:

        asyncpg's names (an ingest of the Trailhead kit)  7 of 7 files failed
        unique names (SQLAlchemy's prepared_statement_name_func)
                                       0 errors, 604 statements left behind
        no statement cache (unnamed statements)  0 errors, none left behind

    Unique names are never deallocated in transaction mode, so a long-lived
    pooler grows without bound; unnamed statements gave the same ingest,
    `recall`, `brief` and `check` output as a direct connection, at the same
    speed."""
    args = db_url.async_connect_args("postgresql://u:p@h/d")
    assert args["statement_cache_size"] == 0
    assert "prepared_statement_name_func" not in args


def test_channel_binding_is_named_where_it_is_dropped():
    (note,) = db_url.async_url_notes(NEON)
    assert "channel_binding=require" in note and "sslmode=verify-full" in note
    assert db_url.async_url_notes("postgresql://u:p@h/d?sslmode=require") == []


def test_a_url_that_is_not_postgresql_is_left_alone():
    assert db_url.async_url("sqlite:///x.db?mode=ro") == "sqlite:///x.db?mode=ro"
    assert db_url.async_connect_args("sqlite:///x.db") == {}


def test_every_engine_verilore_opens_reads_the_url_this_way():
    """A new `create_async_engine` elsewhere would bring the `sslmode` error back."""
    package = ROOT / "verilore"
    found = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in package.rglob("*.py")
        if path.name != "db_url.py" and "migrations" not in path.parts
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"\bcreate_async_engine\(", line)
    ]
    assert not found, "use db_url.async_engine_for: " + ", ".join(found)


# --- Against the test server, when it speaks TLS --------------------------------


def _server_url() -> str:
    return os.environ["DATABASE_URL"]


def _tls_on() -> bool:
    import psycopg2

    try:
        conn = psycopg2.connect(db_url.sync_url(_server_url()).replace("+psycopg2", ""))
    except Exception:  # noqa: BLE001
        return False
    try:
        cur = conn.cursor()
        cur.execute("SHOW ssl")
        return cur.fetchone()[0] == "on"
    finally:
        conn.close()


def _with(url: str, query: str) -> str:
    base = url.split("?", 1)[0]
    return f"{base}?{query}"


def _libpq(url: str) -> bool:
    import psycopg2

    try:
        psycopg2.connect(url.replace("postgresql+asyncpg://", "postgresql://")).close()
        return True
    except psycopg2.OperationalError:
        return False


def _asyncpg(url: str) -> tuple[bool, tuple]:
    from sqlalchemy import text
    from sqlalchemy.pool import NullPool

    async def probe():
        engine = db_url.async_engine_for(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return tuple(
                    (
                        await conn.execute(
                            text(
                                "SELECT current_setting('application_name'),"
                                " current_setting('statement_timeout')"
                            )
                        )
                    ).one()
                )
        finally:
            await engine.dispose()

    try:
        return True, asyncio.run(probe())
    except Exception:  # noqa: BLE001
        return False, ()


def test_settings_in_the_url_reach_the_server():
    url = _with(
        _server_url(),
        "sslmode=prefer&connect_timeout=5&application_name=dbone"
        "&options=-c%20statement_timeout%3D4321&keepalives=1",
    )
    ok, row = _asyncpg(url)
    assert ok and row == ("dbone", "4321ms")


@pytest.fixture
def wrong_authority(tmp_path):
    """A certificate authority that signed nothing on the server."""
    pytest.importorskip("cryptography")
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "not-the-server")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "wrong-ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=disable",
        "sslmode=prefer",
        "sslmode=require",
        "sslmode=require&channel_binding=prefer",
        "sslmode=verify-ca",
        "sslmode=verify-full",
        "sslmode=require&sslrootcert={wrong}",
        "sslmode=verify-ca&sslrootcert={wrong}",
        "sslmode=verify-full&sslrootcert={wrong}",
    ],
)
def test_a_connection_succeeds_or_fails_where_libpqs_does(query, wrong_authority, monkeypatch):
    if not _tls_on():
        pytest.skip("the test server does not speak TLS")
    # No ~/.postgresql/root.crt from the machine running the tests.
    monkeypatch.setenv("HOME", str(wrong_authority.parent))
    monkeypatch.delenv("PGSSLROOTCERT", raising=False)
    url = _with(db_url.sync_url(_server_url()).replace("+psycopg2", ""), query)
    url = url.format(wrong=wrong_authority)
    assert _asyncpg(url)[0] == _libpq(url), url
