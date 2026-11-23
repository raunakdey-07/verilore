"""A Hyper-V host's device note is not a command's output, or a runtime's error (ORT-1).

`import onnxruntime` writes "[W:onnxruntime:Default, device_discovery.cc:95
GetPciBusId] Skipping pci_bus_id ..." to stderr on Hyper-V machines (GitHub's
Linux runners among them), from C++, during the import. Every `verilore`
command printed it, and `verilore runtime status` showed it as the "last
error" of a runtime that had stopped because it was idle.

The command line imports onnxruntime with descriptor 2 pointed at a file and
writes back everything but that line. A library never does: the descriptor is
the whole process's. These tests use a stand-in `onnxruntime` that writes to
descriptor 2 at import, as the real one does, in a subprocess, so that what
reaches the real descriptor is what is checked.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

NOTE = (
    "\x1b[0;93m2026-11-22 06:17:54.252608127 [W:onnxruntime:Default, device_discovery.cc:95 "
    'GetPciBusId] Skipping pci_bus_id for PCI path at "/sys/devices/LNXSYSTM:00/LNXSYBUS:00/'
    'ACPI0004:00/VMBUS:00/5620e0c7-8062-4dce-aeb7-520c7ef76171" because filename '
    '"5620e0c7-8062-4dce-aeb7-520c7ef76171" did not match expected pattern of '
    "[0-9a-f]+:[0-9a-f]+:[0-9a-f]+[.][0-9a-f]+\x1b[m"
)
OTHER_WARNING = "2026-11-22 06:17:54.3 [W:onnxruntime:Default, env.cc:1 Init] something else"
ERROR = "2026-11-22 06:17:54.4 [E:onnxruntime:Default, inference_session.cc:1 Load] failed"


@pytest.fixture
def fake_onnxruntime(tmp_path):
    """An `onnxruntime` that writes to descriptor 2 while it is imported."""

    def make(*, fail: bool = False) -> Path:
        package = tmp_path / "onnxruntime"
        package.mkdir()
        lines = ["before", NOTE, OTHER_WARNING, ERROR, "after"]
        body = "import os\n" + "".join(
            f"os.write(2, {(line + chr(10)).encode()!r})\n" for line in lines
        )
        if fail:
            body += "raise ImportError('libonnxruntime.so: cannot open shared object file')\n"
        (package / "__init__.py").write_text(body)
        return tmp_path

    return make


def _run(code: str, path: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(path), str(ROOT)])}
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=ROOT,
        check=False,
    )


def test_the_command_line_drops_the_device_note_and_nothing_else(fake_onnxruntime):
    done = _run(
        """
        import sys
        from verilore import ort_import
        sys.stderr.write("written before\\n")
        ort_import.load_dropping_device_notes()
        sys.stderr.write("written after\\n")
        print("imported")
        """,
        fake_onnxruntime(),
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == "imported\n"
    assert done.stderr.splitlines() == [
        "written before",
        "before",
        OTHER_WARNING,
        ERROR,
        "after",
        "written after",
    ]


def test_an_import_that_fails_still_says_why(fake_onnxruntime):
    done = _run(
        """
        from verilore import ort_import
        try:
            ort_import.load_dropping_device_notes()
        except ImportError as error:
            print("raised", error)
        import sys
        sys.stderr.write("stderr restored\\n")
        """,
        fake_onnxruntime(fail=True),
    )
    assert "raised libonnxruntime.so" in done.stdout
    assert done.stderr.splitlines() == ["before", OTHER_WARNING, ERROR, "after", "stderr restored"]


def test_a_library_leaves_stderr_alone(fake_onnxruntime):
    """The SDK, the server and the MCP server import onnxruntime plainly."""
    done = _run(
        """
        from verilore import ort_import
        import verilore.sdk  # noqa: F401
        assert ort_import._loader is ort_import._plain
        ort_import.load()
        """,
        fake_onnxruntime(),
    )
    assert done.returncode == 0, done.stderr
    assert NOTE in done.stderr.splitlines()


def test_only_the_command_line_asks_for_it(fake_onnxruntime):
    done = _run(
        """
        from typer.testing import CliRunner
        from verilore import ort_import
        from verilore.cli.main import app
        CliRunner().invoke(app, ["runtime", "status"])
        print(ort_import._loader is ort_import.load_dropping_device_notes)
        """,
        fake_onnxruntime(),
    )
    assert done.stdout.strip().splitlines()[-1] == "True", done.stderr


def test_the_command_line_builds_no_database_engine_before_its_command(fake_onnxruntime):
    """`verilore init --database-url` sets the URL inside the command.

    The database module reads `DATABASE_URL` once, as it is imported, so the
    callback that runs before every command must not import it. When it did,
    through the `verilore.api.services` package, `init` checked the default
    `localhost:5432` instead of the URL it was given, and every install job
    failed.
    """
    done = _run(
        """
        import sys
        from typer.testing import CliRunner
        from verilore.cli.main import app

        seen = []

        @app.command("probe")
        def probe():
            seen.append("verilore.api.services.db" in sys.modules)

        CliRunner().invoke(app, ["probe"])
        print(seen)
        """,
        fake_onnxruntime(),
    )
    assert done.stdout.strip().splitlines()[-1] == "[False]", done.stdout + done.stderr


def test_the_model_is_loaded_through_it():
    """A plain `import onnxruntime` elsewhere would bring the note back."""
    found = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in (ROOT / "verilore").rglob("*.py")
        if path.name != "ort_import.py"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if re.match(r"\s*(import onnxruntime|from onnxruntime)", line)
    ]
    assert not found, "use ort_import.load(): " + ", ".join(found)


def test_a_runtime_that_stopped_cleanly_has_no_last_error(tmp_path, monkeypatch):
    from verilore.api import runtime as runtime_module

    monkeypatch.setenv("VERILORE_STATE_DIR", str(tmp_path / "s"))
    (tmp_path / "s").mkdir()
    runtime_module.log_path().write_text(f"--- start 2026-11-22 06:00:00\n{NOTE}\n")
    assert runtime_module.last_error() is None
    with runtime_module.log_path().open("a") as log:
        log.write(f"{ERROR}\n{OTHER_WARNING}\n")
    assert runtime_module.last_error() == ERROR


def test_a_loud_import_cannot_block_on_its_own_stderr(tmp_path):
    """Captured to a file, not a pipe: a pipe nobody reads until the import
    returns fills at 64 KiB, and the import would wait on it for ever."""
    package = tmp_path / "onnxruntime"
    package.mkdir()
    (package / "__init__.py").write_text(
        "import os\n"
        f"os.write(2, {(NOTE + chr(10)).encode()!r})\n"
        "for _ in range(1024):\n"
        "    os.write(2, b'x' * 1023 + b'\\n')\n"
    )
    done = _run(
        """
        from verilore import ort_import
        ort_import.load_dropping_device_notes()
        print("imported")
        """,
        tmp_path,
    )
    assert done.stdout == "imported\n"
    lines = done.stderr.splitlines()
    assert len(lines) == 1024 and NOTE not in lines
