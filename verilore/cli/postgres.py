# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""Local PostgreSQL (podman/docker) recovery helpers for the CLI."""

from __future__ import annotations

from pathlib import Path

import json
import os
import shutil
import socket
import subprocess
import time
from urllib.parse import urlparse

#: How long to wait for a (re)started container to accept TCP connections.
READY_TIMEOUT_SECONDS = 5.0

#: How long a **fresh** container gets: the first run downloads the image once
#: and runs initdb, which alone is slower than the 5 s ready timeout.
FIRST_RUN_READY_TIMEOUT_SECONDS = 90.0

#: The container name init provisions. Named, so a restart finds it and pulls
#: nothing; `--restart unless-stopped` started is what survives a reboot.
DEFAULT_CONTAINER_NAME = "verilore-postgres"

#: The name the old compose checkout used. Keep recognising it as ours so an
#: existing container is restarted instead of replaced with a second copy.
LEGACY_CONTAINER_NAME = "verilore_postgresql_1"

#: Every name a container of ours has had, including the old compose names.
_OUR_NAMES = frozenset({DEFAULT_CONTAINER_NAME, LEGACY_CONTAINER_NAME, "mindpalace_postgresql_1"})

#: The named volume the data lives in, so removing the container removes
#: nothing: memory survives `podman rm verilore-postgres`.
DEFAULT_VOLUME_NAME = "verilore-pgdata"

#: The image used when provisioning a fresh local container. Fully qualified
#: (Podman on Fedora enforces short-name resolution and cannot prompt) and
#: the official `pgvector/pgvector`, which superseded `ankane/pgvector`.
DEFAULT_IMAGE = "docker.io/pgvector/pgvector:pg15"

#: The port the local development database lives on.
#:
#: Provisioning is limited to this one. Creating a container on whatever port
#: `DATABASE_URL` happens to name is a surprise with a lasting consequence --
#: a container nobody asked for, on a port that was chosen for something else
#: -- and it is not what the local setup documents. A database on any other
#: port is one the operator runs, and the CLI leaves it alone.
DEFAULT_POSTGRES_PORT = 5432


def database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://mpadmin:secret@localhost:5432/verilore")


def db_host_port(url: str | None = None) -> tuple[str, int]:
    parsed = urlparse(url or database_url())
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    return host, port


def db_ready(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP plus an actual SELECT 1, so we don't race Postgres startup.

    Postgres accepts TCP connections before it will answer a query, so a TCP
    check alone reports a container as ready while it is still replaying its
    WAL. The first command after an auto-start would then fail with "the
    database system is starting up".

    The probe uses its own engine rather than the application's shared one:
    this runs before any client exists, and an engine bound to a different
    event loop is a class of failure this code should not be able to cause.
    """
    if not tcp_open(host, port, timeout=0.5):
        return False
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        url = database_url()
        parsed = urlparse(url)
        # Probe the host and port asked for, not whatever the URL happens to
        # name: the caller may have been told to look somewhere else.
        userinfo = ""
        if "@" in parsed.netloc:
            userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"
        host_for_url = f"[{host}]" if ":" in host else host
        probe_url = parsed._replace(netloc=f"{userinfo}{host_for_url}:{port}").geturl()
        engine = create_async_engine(
            probe_url.replace("postgresql://", "postgresql+asyncpg://"),
            poolclass=NullPool,
        )

        async def _ping():
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        try:
            _run_blocking(_ping(), timeout=timeout)
        finally:
            _dispose(engine)
        return True
    except Exception:  # noqa: BLE001 - readiness is a question, not a verdict
        return False


def _run_blocking(coro, timeout: float) -> None:
    """Run a coroutine to completion, from either kind of caller.

    `asyncio.run` refuses to nest, so a command driven from inside a running
    loop -- an embedding application, an in-process test -- has to do the work
    on a worker thread with a loop of its own. Getting that wrong would make
    the probe always report "not ready", and a false negative here is what
    makes the CLI restart a database that is already running.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(asyncio.wait_for(coro, timeout=timeout))
        return

    import threading

    outcome: list = []

    def worker():
        try:
            asyncio.run(asyncio.wait_for(coro, timeout=timeout))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            outcome.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    if outcome:
        raise outcome[0]


def _dispose(engine) -> None:
    """Dispose an engine, wherever it was created."""

    async def _close():
        await engine.dispose()

    try:
        _run_blocking(_close(), timeout=5.0)
    except Exception:  # noqa: BLE001 - disposal is best-effort
        pass


def is_local_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def speaks_postgres(host: str, port: int, timeout: float = 1.0) -> bool:
    """Whether whatever listens on ``host:port`` is a PostgreSQL server.

    Sends the protocol's SSLRequest packet, to which every PostgreSQL server
    answers with a single ``S`` or ``N`` before any authentication. It needs no
    credentials, so a PostgreSQL that rejects ours -- a distro's own install on
    5432, say -- is still recognised as one, and the precise "password
    authentication failed" guidance applies instead of a wrong "another program".
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall((8).to_bytes(4, "big") + (80877103).to_bytes(4, "big"))
            return conn.recv(1) in (b"S", b"N")
    except OSError:
        return False


def _container_clis() -> list[str]:
    found = []
    for name in ("podman", "docker"):
        if shutil.which(name):
            found.append(name)
    # Prefer podman on Fedora-style setups, but docker is fine.
    return found


def _run_cli(cli: str, args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [cli, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class ProvisioningError(Exception):
    """Provisioning the local database failed, with the engine's own words.

    `detail` is the last five lines of the engine's stderr; `engine` is the
    CLI that failed (`podman`/`docker`), and `hint` is the fix to print.
    """

    def __init__(self, detail: str, *, engine: str = "", hint: str = "") -> None:
        super().__init__(detail or "could not provision the local database")
        self.detail = detail
        self.engine = engine
        self.hint = hint


def last_provision_error() -> ProvisioningError | None:
    """The last provisioning failure in this process, if one happened."""
    return globals().get("_LAST_PROVISION_ERROR")


def _record_error(error: ProvisioningError) -> ProvisioningError:
    globals()["_LAST_PROVISION_ERROR"] = error
    return error


def _last_lines(text: str, count: int = 5) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[-count:])


def _port_is_taken_by_something_else(host: str, port: int) -> bool:
    """The port accepts TCP and is not a PostgreSQL server: another program."""
    return tcp_open(host, port, timeout=0.5) and not speaks_postgres(host, port)


def port_conflict_remediation_for(port: int) -> str:
    return (
        f"Port {port} is already in use by another program that is not PostgreSQL.\n"
        "Either stop it, or point Verilore at a different database (init records it\n"
        "for every later command):\n"
        "  verilore init --database-url postgresql://<user>:<pass>@127.0.0.1:<port>/verilore"
    )


def _normalize_container(raw: dict, cli: str) -> dict:
    names = raw.get("Names") or raw.get("Name") or raw.get("names") or raw.get("name")
    if isinstance(names, list):
        names = names[0] if names else ""
    state = raw.get("State") or raw.get("state") or ""
    status = raw.get("Status") or raw.get("status") or ""
    image = raw.get("Image") or raw.get("image") or ""
    ports = raw.get("Ports") or raw.get("ports") or raw.get("ExposedPorts") or []
    return {
        "cli": cli,
        "name": str(names).strip().strip("[]'\""),
        "state": str(state).strip().lower(),
        "status": str(status).strip(),
        "image": str(image).strip().lower(),
        "ports": ports,
        "raw": raw,
    }


def _publishes_port(container: dict, port: int) -> bool:
    """Does this container publish ``port`` on the host?

    The *host* port is what matters, because that is the port a client
    connects to. Matched exactly rather than by substring: "5432" is a
    substring of "15432", and a container publishing 15432 is not the one
    publishing 5432. Starting it because its port number happens to contain
    the right digits would be a worse failure than not starting it at all.
    """
    ports = container.get("ports")
    if isinstance(ports, list):
        for entry in ports:
            if isinstance(entry, dict):
                host_port = entry.get("host_port", entry.get("HostPort", entry.get("hostPort")))
                if host_port is None:
                    continue
                if int(host_port) == port:
                    return True
                # A published range starts at `host_port` and spans `range`
                # ports, so 5432 is inside a range that starts at 5430.
                span = entry.get("range")
                if span and int(host_port) <= port < int(host_port) + int(span):
                    return True
            elif isinstance(entry, int) and entry == port:
                return True
            elif isinstance(entry, str) and _host_port_in(entry, port):
                return True
    if isinstance(ports, dict):
        for key, value in ports.items():
            if str(key) == str(port):
                return True
            if _host_port_in(str(value), port):
                return True
    if isinstance(ports, str):
        return _host_port_in(ports, port)
    return False


def _host_port_in(rendered: str, port: int) -> bool:
    """Is ``port`` the host port in a rendered ports field?

    The rendered form is "0.0.0.0:5432->5432/tcp": the host port is the one
    before the arrow, and the one after it is the container's own port. A
    client connects to the host port, so the container port is not a match --
    a container publishing 15432 is not the one publishing 5432.
    """
    import re

    for chunk in rendered.split(","):
        host_part = chunk.split("->")[0]
        numbers = re.findall(r"\d+", host_part)
        if numbers and int(numbers[-1]) == port:
            return True
    return False


def _is_postgres(container: dict) -> bool:
    blob = " ".join(
        str(x)
        for x in (
            container.get("name", ""),
            container.get("image", ""),
            container.get("status", ""),
        )
    ).lower()
    return ("postgres" in blob) or ("pgvector" in blob) or ("verilore" in blob)


def _is_stopped(container: dict) -> bool:
    state = (container.get("state") or "").lower()
    status = (container.get("status") or "").lower()
    if state in {"exited", "created", "dead", "stopped", "paused"}:
        return True
    if status.startswith("exited") or status.startswith("created") or status.startswith("dead"):
        return True
    return False


def list_containers() -> list[dict]:
    """Return all containers visible to any available container CLI."""
    result = []
    for cli in _container_clis():
        # Prefer JSON output.
        try:
            proc = _run_cli(cli, ["ps", "-a", "--format", "json"])
            text = (proc.stdout or "").strip()
            if text:
                parsed = None
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    # Some CLIs emit one JSON object per line.
                    objs = []
                    for line in text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            objs.append(json.loads(line))
                        except json.JSONDecodeError:
                            objs = None
                            break
                    if objs is not None:
                        parsed = objs
                if isinstance(parsed, list):
                    for raw in parsed:
                        if isinstance(raw, dict):
                            result.append(_normalize_container(raw, cli))
                    if result:
                        continue
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

        # Fallback: tab-separated format.
        try:
            proc = _run_cli(
                cli,
                [
                    "ps",
                    "-a",
                    "--format",
                    "{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}",
                ],
            )
            for line in (proc.stdout or "").splitlines():
                parts = line.split("\t")
                if not parts or not parts[0].strip():
                    continue
                raw = {
                    "Names": parts[0].strip(),
                    "State": parts[1].strip() if len(parts) > 1 else "",
                    "Status": parts[2].strip() if len(parts) > 2 else "",
                    "Ports": parts[3].strip() if len(parts) > 3 else "",
                    "Image": parts[4].strip() if len(parts) > 4 else "",
                }
                result.append(_normalize_container(raw, cli))
        except (OSError, subprocess.SubprocessError):
            pass
    return result


def find_stopped_postgres_container(port: int = 5432) -> dict | None:
    """Find a stopped local Postgres/pgvector container publishing ``port``."""
    candidates = []
    for c in list_containers():
        if not _is_postgres(c):
            continue
        if not _publishes_port(c, port):
            continue
        if not _is_stopped(c):
            continue
        candidates.append(c)
    if not candidates:
        return None
    # Prefer verilore-named containers; the legacy compose name counts as ours
    # too, so an existing container is restarted rather than replaced.
    for container in candidates:
        if _is_ours(container):
            return container
    return candidates[0]


def start_container(container: dict, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    cli = container["cli"]
    name = container["name"]
    try:
        proc = _run_cli(cli, ["start", name], timeout=30.0)
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    host, port = db_host_port()
    # Wait up to timeout for readiness.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if db_ready(host, port, timeout=1.0):
            return True
        time.sleep(0.25)
    return db_ready(host, port, timeout=1.0)


def provision_local_postgres(
    timeout: float = READY_TIMEOUT_SECONDS, *, first_run: bool = False
) -> bool:
    """Provision and start a fresh local pgvector container.

    Only for the standard local port. A database on any other port is one the
    operator runs, and creating a container for it is a surprise with a
    lasting consequence.

    A container that already exists under our name (or the old compose name) is
    started rather than recreated, so the data in the named volume survives.
    A failure is recorded in `last_provision_error()` and raised as part of
    `ensure_local_postgres`: nothing about a broken provision is silent here.
    """
    clis = _container_clis()
    if not clis:
        return False
    cli = clis[0]
    host, port = db_host_port()
    if port != DEFAULT_POSTGRES_PORT:
        return False
    # If something is already listening, nothing to do.
    if db_ready(host, port, timeout=1.0):
        return True
    if _port_is_taken_by_something_else(host, port):
        raise _record_error(
            ProvisioningError(
                port_conflict_remediation_for(port),
                engine=cli,
                hint=port_conflict_remediation_for(port),
            )
        )
    name = DEFAULT_CONTAINER_NAME
    # Localhost-only binding: the mpadmin password is fine on a loopback-socket
    # laptop and must never be reachable off it. The named volume outlives the
    # container, so `rm` of the container deletes no memory.
    cmd = [
        "run",
        "-d",
        "--name",
        name,
        "-e",
        "POSTGRES_DB=verilore",
        "-e",
        "POSTGRES_USER=mpadmin",
        "-e",
        "POSTGRES_PASSWORD=secret",
        "-p",
        f"127.0.0.1:{port}:5432",
        "-v",
        f"{DEFAULT_VOLUME_NAME}:/var/lib/postgresql/data",
        "--restart",
        "unless-stopped",
        DEFAULT_IMAGE,
        "postgres",
        "-c",
        "log_error_verbosity=terse",
    ]
    try:
        proc = _run_cli(cli, cmd, timeout=120.0)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _record_error(ProvisioningError(str(exc), engine=cli, hint=str(exc))) from exc
    if proc.returncode != 0:
        # Maybe an old container already has our name; start it instead.
        try:
            started = _run_cli(cli, ["start", name], timeout=30.0)
        except (OSError, subprocess.SubprocessError) as exc:
            raise _record_error(
                ProvisioningError(_last_lines(proc.stderr), engine=cli, hint=str(exc))
            ) from exc
        if started.returncode != 0:
            raise _record_error(
                ProvisioningError(
                    _last_lines(started.stderr or proc.stderr),
                    engine=cli,
                    hint=_last_lines(started.stderr or proc.stderr),
                )
            )
    budget = FIRST_RUN_READY_TIMEOUT_SECONDS if first_run else timeout
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        if db_ready(host, port, timeout=1.0):
            return True
        time.sleep(0.25)
    return db_ready(host, port, timeout=1.0)


def ensure_local_postgres(
    *,
    auto_provision: bool = False,
    timeout: float = READY_TIMEOUT_SECONDS,
) -> bool:
    """Try to make a local Postgres reachable.

    Returns True if the port is open afterwards. Only acts for localhost
    targets -- a deployment whose database is elsewhere must not have a local
    container started for it.

    The healthy path costs one TCP connect and nothing else. A query is only
    sent after something has actually been started, because that is the only
    time the answer is in doubt: Postgres accepts a connection before it will
    serve one, so a container that was just started has to be asked a
    question, not merely a socket.
    """
    host, port = db_host_port()
    if not is_local_host(host):
        return tcp_open(host, port, timeout=0.5)
    if tcp_open(host, port, timeout=0.5):
        if auto_provision and not speaks_postgres(host, port):
            # The port answers TCP but is not PostgreSQL: another program owns
            # it, and a generic "storage unavailable" is not the answer. A
            # PostgreSQL that rejects our login is left to init's connection
            # check, whose message names the credentials. `init` is the only
            # caller that asked for a fix.
            raise _record_error(
                ProvisioningError(
                    port_conflict_remediation_for(port),
                    hint=port_conflict_remediation_for(port),
                )
            )
        return True
    if not _container_clis():
        raise _record_error(
            ProvisioningError(
                missing_runtime_remediation_hint(),
            )
        )
    # Try to start a stopped container.
    container = find_stopped_postgres_container(port)
    if container is not None:
        if start_container(container, timeout=timeout):
            return True
    if auto_provision:
        if provision_local_postgres(timeout=timeout, first_run=is_first_run()):
            return True
    return tcp_open(host, port, timeout=0.5)


def _is_ours(container: dict) -> bool:
    name = (container.get("name") or "").lower()
    return name in _OUR_NAMES or "verilore" in name


def is_first_run() -> bool:
    """Whether `init` is about to create the database: the slow, once-only case.

    True only for a local URL with nothing listening, an engine to create the
    container with, and no container of ours in any state. A database that is
    already up, or a stopped container that only needs starting, is not a
    first run, so the "downloads the image once" line is not printed for it.
    """
    host, port = db_host_port()
    if not is_local_host(host) or tcp_open(host, port, timeout=0.5):
        return False
    if not _container_clis():
        return False
    return not any(_is_ours(container) for container in list_containers())


def missing_runtime_remediation_hint() -> str:
    """The install command for the detected distro, as one line."""
    cmd = runtime_install_command()
    return (
        "No container engine (podman or docker) was found on PATH.\n"
        f"Install one with: {cmd}\n"
        "Then re-run: verilore init"
    )


#: Filesystem locations inspected for Linux/WSL2 detection. Module-level so tests
#: can point them at fixtures without monkeypatching `Path`.
PROC_VERSION_PATH = Path("/proc/version")
OS_RELEASE_PATH = Path("/etc/os-release")


def _read_proc_version() -> str:
    try:
        return PROC_VERSION_PATH.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _read_os_release_text() -> str:
    try:
        return OS_RELEASE_PATH.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def is_wsl2() -> bool:
    """Whether this process is running under WSL2.

    Detection inspects ``/proc/version`` for ``microsoft`` or ``WSL``, as the
    kernel reports for a WSL2 guest.
    """
    text = _read_proc_version().lower()
    return ("microsoft" in text) or ("wsl" in text)


# Aliases covering the names callers and tests are likely to reach for.
is_wsl = is_wsl2
detect_wsl2 = is_wsl2
wsl2_detected = is_wsl2


def read_os_release() -> dict[str, str]:
    """Parse ``/etc/os-release`` into a mapping."""
    result: dict[str, str] = {}
    for line in _read_os_release_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key.strip()] = value
    return result


os_release = read_os_release


def linux_distro_id() -> str:
    """The ``ID`` field from ``/etc/os-release`` (e.g. ``fedora``)."""
    return (read_os_release().get("ID") or "").strip().lower()


distro_id = linux_distro_id
distro = linux_distro_id


def linux_distro_family() -> str:
    """The ``ID_LIKE`` field, falling back to ``ID``."""
    data = read_os_release()
    like = (data.get("ID_LIKE") or "").strip().lower()
    if like:
        return like
    return linux_distro_id()


distro_family = linux_distro_family
distro_like = linux_distro_family


def linux_distro() -> str:
    """A human-readable distro label, preferring PRETTY_NAME."""
    data = read_os_release()
    return data.get("PRETTY_NAME") or data.get("ID") or ""


def _distro_haystack(distro_id: str | None = None, family: str | None = None) -> str:
    if distro_id is None:
        distro_id = linux_distro_id()
    if family is None:
        family = linux_distro_family()
    return " ".join([distro_id or "", family or ""]).lower()


def runtime_install_command(distro_id: str | None = None, family: str | None = None) -> str:
    """Distro-appropriate command to install a container runtime."""
    hay = _distro_haystack(distro_id, family)
    if any(token in hay for token in ("fedora", "rhel", "centos", "rocky", "alma", "ol")):
        return "sudo dnf install -y podman"
    if any(token in hay for token in ("debian", "ubuntu", "mint", "pop")):
        return "sudo apt update && sudo apt install -y podman"
    if "arch" in hay:
        return "sudo pacman -S podman"
    # Sensible default for unknown Linux.
    return "sudo dnf install -y podman"


install_runtime_command = runtime_install_command
distro_install_command = runtime_install_command
container_runtime_install_command = runtime_install_command


def missing_container_runtime_remediation(
    distro_id: str | None = None, family: str | None = None
) -> str:
    cmd = runtime_install_command(distro_id, family)
    return (
        "No container runtime (podman or docker) was found on PATH.\n"
        "Install one for your distribution, then re-run verilore init:\n"
        f"  {cmd}\n"
        "On Debian/Ubuntu, `docker.io` is an alternative to podman: "
        "sudo apt update && sudo apt install -y docker.io"
    )


missing_runtime_remediation = missing_container_runtime_remediation
missing_runtime_message = missing_container_runtime_remediation
runtime_missing_message = missing_container_runtime_remediation


def docker_socket_permission_denied_remediation() -> str:
    return (
        "Permission denied on /var/run/docker.sock.\n"
        "Your user is not in the docker group. Add it and re-open your shell:\n"
        "  sudo usermod -aG docker $USER && newgrp docker\n"
        "Alternatively, use rootless Podman (no group change required)."
    )


socket_permission_remediation = docker_socket_permission_denied_remediation
permission_denied_remediation = docker_socket_permission_denied_remediation
docker_socket_permission_message = docker_socket_permission_denied_remediation


def stopped_docker_daemon_remediation(wsl2: bool | None = None) -> str:
    if wsl2 is None:
        wsl2 = is_wsl2()
    if wsl2:
        cmd = "sudo service docker start"
    else:
        cmd = "sudo systemctl start docker"
    return (
        "The container runtime daemon is stopped.\n"
        "Start it, then re-run verilore init:\n"
        f"  {cmd}"
    )


stopped_daemon_remediation = stopped_docker_daemon_remediation
stopped_docker_daemon_message = stopped_docker_daemon_remediation
daemon_stopped_remediation = stopped_docker_daemon_remediation


def host_postgres_port_conflict_remediation() -> str:
    return (
        "A host or foreign PostgreSQL instance is bound to localhost:5432, so the "
        "default mpadmin credentials were rejected.\n"
        "Either point Verilore at a different database:\n"
        "  export DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/verilore\n"
        "Or stop the conflicting host service and re-run init:\n"
        "  sudo systemctl stop postgresql\n"
        "  sudo service postgresql stop\n"
        "  verilore init"
    )


port_conflict_remediation = host_postgres_port_conflict_remediation
host_postgres_remediation = host_postgres_port_conflict_remediation
port_5432_conflict_remediation = host_postgres_port_conflict_remediation


def _container_runtime_available() -> bool:
    return bool(_container_clis())


def remediation_for_exception(exc: BaseException | None) -> str | None:
    """Best-effort remediation text for a CLI failure, or None."""
    if exc is None:
        return None
    chain_text = " ".join(str(e) for e in _exception_chain_list(exc)).lower()
    if "/var/run/docker.sock" in chain_text and "permission denied" in chain_text:
        return docker_socket_permission_denied_remediation()
    if (
        "cannot connect to the docker daemon" in chain_text
        or "is the docker daemon running" in chain_text
        or "docker daemon is not running" in chain_text
    ):
        return stopped_docker_daemon_remediation()
    if (
        "podman: not found" in chain_text
        or "docker: not found" in chain_text
        or "not found" in chain_text
        and "podman" in chain_text
    ):
        return missing_container_runtime_remediation()
    return None


def _exception_chain_list(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        nxt = current.__cause__ or current.__context__
        if nxt is None:
            original = getattr(current, "orig", None)
            nxt = original if isinstance(original, BaseException) else None
        current = nxt
    return chain
