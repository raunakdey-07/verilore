"""The guidance a failed setup prints is right for the machine it runs on.

macOS has no /etc/os-release and no systemd, so every Linux answer is wrong
there: before this, a Mac with no container engine was told to run `dnf`, and a
Mac whose Docker Desktop was closed was told to run `systemctl`. The Linux and
WSL answers are in tests/test_linux_wsl_guided_remediation.py.
"""

from __future__ import annotations

import pytest

from verilore.cli import errors as cli_errors
from verilore.cli import main as cli_main
from verilore.cli import postgres as cli_postgres

LINUX_ONLY = ("dnf", "apt ", "pacman", "zypper", "systemctl", "service docker")


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(cli_postgres, "is_macos", lambda: True)
    monkeypatch.setattr(cli_postgres, "is_wsl2", lambda: False)


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(cli_postgres, "is_macos", lambda: False)
    monkeypatch.setattr(cli_postgres, "is_wsl2", lambda: False)


# -- macOS ------------------------------------------------------------------


def test_mac_without_an_engine_is_told_homebrew_and_the_podman_vm(mac):
    command = cli_postgres.runtime_install_command()
    assert command == "brew install podman && podman machine init && podman machine start"
    message = cli_postgres.missing_container_runtime_remediation()
    assert command in message
    assert "Docker Desktop" in message
    assert not any(word in message for word in LINUX_ONLY), message


def test_mac_with_a_stopped_engine_is_told_to_start_the_app_or_the_vm(mac):
    message = cli_postgres.stopped_docker_daemon_remediation()
    assert "podman machine start" in message
    assert "open -a Docker" in message
    assert "systemctl" not in message and "sudo" not in message


def test_mac_port_conflict_names_homebrew_services_not_systemd(mac):
    message = cli_postgres.host_postgres_port_conflict_remediation()
    assert "brew services stop" in message
    assert "systemctl" not in message and "service postgresql" not in message
    assert "verilore init" in message


def test_podman_vm_not_running_is_recognised_end_to_end(mac):
    """Podman's own words on a Mac whose VM is stopped."""
    exc = RuntimeError(
        "Cannot connect to Podman. Please verify your connection to the Linux system "
        "using `podman system connection list`, or try `podman machine init` and "
        "`podman machine start` to manage a new Linux VM"
    )
    advice = cli_errors.explain(exc)
    assert advice.code == "container_runtime_unavailable"
    assert "podman machine start" in advice.do
    assert cli_postgres.remediation_for_exception(exc) == advice.do


def test_docker_desktop_closed_is_recognised_end_to_end(mac):
    exc = RuntimeError("Cannot connect to the Docker daemon at unix:///var/run/docker.sock.")
    advice = cli_errors.explain(exc)
    assert "open -a Docker" in advice.do
    assert "systemctl" not in advice.do


def test_doctor_names_macos_rather_than_unknown(mac):
    assert cli_main._doctor_distro().startswith("macOS")


# -- Linux distributions ----------------------------------------------------


@pytest.mark.parametrize(
    ("distro_id", "family", "command"),
    [
        ("opensuse-tumbleweed", "opensuse suse", "sudo zypper install -y podman"),
        ("opensuse-leap", "suse opensuse", "sudo zypper install -y podman"),
        ("almalinux", "rhel centos fedora", "sudo dnf install -y podman"),
        ("linuxmint", "ubuntu debian", "sudo apt update && sudo apt install -y podman"),
        ("manjaro", "arch", "sudo pacman -S podman"),
        ("endeavouros", "arch", "sudo pacman -S podman"),
    ],
)
def test_each_family_gets_its_own_package_manager(linux, distro_id, family, command):
    assert cli_postgres.runtime_install_command(distro_id, family) == command


def test_an_unknown_linux_is_not_handed_another_distributions_command(linux):
    command = cli_postgres.runtime_install_command("nixos", "")
    assert command.startswith("install Podman as")
    assert cli_postgres.PODMAN_INSTALL_DOCS in command
    assert not any(word in command for word in LINUX_ONLY)


def test_ids_match_whole_words_only(linux):
    """`ol` is Oracle Linux; a substring test matched it inside other names."""
    assert "dnf" not in cli_postgres.runtime_install_command("solus", "")


def test_docker_io_is_offered_only_where_apt_installs_it(linux):
    assert "docker.io" in cli_postgres.missing_container_runtime_remediation("debian", "")
    assert "docker.io" not in cli_postgres.missing_container_runtime_remediation("fedora", "")
    assert "docker.io" not in cli_postgres.missing_container_runtime_remediation("arch", "")


def test_wsl_also_offers_docker_desktop(monkeypatch):
    monkeypatch.setattr(cli_postgres, "is_macos", lambda: False)
    monkeypatch.setattr(cli_postgres, "is_wsl2", lambda: True)
    monkeypatch.setattr(cli_postgres, "linux_distro_id", lambda: "ubuntu")
    monkeypatch.setattr(cli_postgres, "linux_distro_family", lambda: "debian")
    missing = cli_postgres.missing_container_runtime_remediation()
    assert "sudo apt update && sudo apt install -y podman" in missing
    assert "WSL integration" in missing
    stopped = cli_postgres.stopped_docker_daemon_remediation()
    assert "sudo service docker start" in stopped
    assert "WSL integration" in stopped


def test_every_platform_offers_an_existing_database_instead():
    for macos in (True, False):
        for wsl in (True, False):
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(cli_postgres, "is_macos", lambda m=macos: m)
                patch.setattr(cli_postgres, "is_wsl2", lambda w=wsl: w)
                message = cli_postgres.missing_container_runtime_remediation()
            assert "verilore init --database-url" in message, (macos, wsl)


# -- a schema that cannot be applied ----------------------------------------


def test_a_failed_migration_never_points_at_a_source_checkout():
    """pipx and uv installs have no `verilore/migrations/alembic.ini` to run."""
    for detail in (
        'Migration failed: NotSupportedError: extension "pg_trgm" is not available',
        'Migration failed: InsufficientPrivilege: permission denied to create extension "vector"',
        "Migration failed: OperationalError: server closed the connection unexpectedly",
    ):
        advice = cli_main._migration_failure_advice(detail)
        assert "alembic" not in advice.do and "alembic.ini" not in advice.why
        assert "verilore init" in advice.do
        assert advice.code == "memory_unavailable"


def test_a_missing_extension_is_named_with_where_to_get_it():
    advice = cli_main._migration_failure_advice(
        "Migration failed: NotSupportedError: (psycopg2.errors.FeatureNotSupported) "
        'extension "vector" is not available\nDETAIL: Could not open extension control file'
    )
    assert '"vector"' in advice.why
    assert "pgvector/pgvector:pg15" in advice.do


def test_a_role_that_may_not_create_extensions_is_told_so():
    advice = cli_main._migration_failure_advice(
        'Migration failed: ProgrammingError: permission denied to create extension "vector"'
    )
    assert "may not create extensions" in advice.why
    assert 'CREATE EXTENSION "vector"' in advice.do


def test_an_unrecognised_failure_shows_its_first_line_only():
    advice = cli_main._migration_failure_advice(
        "Migration failed: OperationalError: boom\n[SQL: CREATE TABLE corpora (...)]"
    )
    assert advice.why == "Migration failed: OperationalError: boom"
