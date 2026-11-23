# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""How `onnxruntime` is imported, and the one note of a host's it drops (ORT-1).

On a Hyper-V machine (GitHub's and Azure's Linux runners, other Hyper-V
guests), `import onnxruntime` writes this to the process's stderr, from C++,
before Python gets control back:

    [W:onnxruntime:Default, device_discovery.cc:95 GetPciBusId] Skipping
    pci_bus_id for PCI path at "/sys/devices/LNXSYSTM:00/.../VMBUS:00/<guid>"
    because filename "<guid>" did not match expected pattern of ...

It is the runtime looking for GPUs and finding the hypervisor's display
adapter, which has no PCI address; nothing is wrong, and every `verilore`
command printed it. Reproduced in a mount namespace that shows a `hyperv_drm`
card: it is written during the import, so
`onnxruntime.set_default_logger_severity` (which needs the module) comes too
late, and onnxruntime reads no environment variable for it.

So the command line, and only the command line, imports onnxruntime with
file descriptor 2 pointed at a temporary file for the length of the import,
then writes back every byte except that line. A library never redirects
stderr: the descriptor is the whole process's, and a server or an SDK caller
would lose its own lines. `load()` is a plain import unless the command line
asked for `load_dropping_device_notes`.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Callable
from types import ModuleType

__all__ = ["DEVICE_NOTE", "HOST_NOTE", "load", "load_dropping_device_notes", "use"]

_ANSI = re.compile(rb"\x1b\[[0-9;]*m")
#: The device-discovery warning, as the command line drops it: nothing else.
DEVICE_NOTE = re.compile(
    rb"^\S+ \S+ \[W:onnxruntime:[^\]]*device_discovery\.cc:\d+ GetPciBusId\] Skipping pci_bus_id "
)
#: Any warning, note or detail line onnxruntime writes ([W:], [I:], [V:]).
#: Not its errors ([E:], [F:]). Text, for readers of a log.
HOST_NOTE = re.compile(r"^(?:\x1b\[[0-9;]*m)?\S+ \S+ \[[WIV]:onnxruntime:")


def _plain() -> ModuleType:
    # An import statement, not `importlib.import_module`: it goes through
    # `builtins.__import__`, as the code this replaced did, so whatever a caller
    # or a test put there still decides.
    import onnxruntime

    return onnxruntime


_loader: Callable[[], ModuleType] = _plain


def use(loader: Callable[[], ModuleType]) -> None:
    """Import onnxruntime with `loader` from now on, in this process."""
    global _loader
    _loader = loader


def load() -> ModuleType:
    """`onnxruntime`, imported the way this process asked for (a plain import by default)."""
    return _loader()


def _without_device_notes(captured: bytes) -> bytes:
    kept = [
        line
        for line in captured.splitlines(keepends=True)
        if not DEVICE_NOTE.match(_ANSI.sub(b"", line))
    ]
    return b"".join(kept)


def load_dropping_device_notes() -> ModuleType:
    """Import onnxruntime and drop the GetPciBusId warning from what it writes.

    For the command line only (see the module docstring). Everything written to
    stderr during the import, by onnxruntime or anything else, is written back
    in order once the import returns or fails, except that one line.
    """
    if "onnxruntime" in sys.modules:
        return _plain()  # nothing left to write; the import statement still decides
    try:
        sys.stderr.flush()
        saved = os.dup(2)
    except (OSError, ValueError, AttributeError):
        return _plain()
    with tempfile.TemporaryFile() as capture:
        os.dup2(capture.fileno(), 2)
        try:
            return _plain()
        finally:
            try:
                sys.stderr.flush()
            except (OSError, ValueError):
                pass
            os.dup2(saved, 2)
            os.close(saved)
            capture.seek(0)
            rest = memoryview(_without_device_notes(capture.read()))
            while rest:
                rest = rest[os.write(2, rest) :]
