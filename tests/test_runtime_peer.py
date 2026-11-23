"""The runtime client checks its peer, and says why a socket folder was refused (RUNTIME-2).

RUNTIME-1 put the fallback socket in `/tmp/verilore-<uid>/`, used only when it
is this user's and 0700. Two things were left:

* Between that check and `connect()` the platform can say who is listening.
  On Linux the client now reads the peer's user id (`SO_PEERCRED`) after
  connecting and before the first byte of the token, and talks to nobody else.
  Elsewhere the folder check is the boundary, as before.
* When the folder belonged to another user, the runtime fell back to the long
  path and its log said only "AF_UNIX path too long". It now says which folder
  was refused and why, and what to set.
"""

from __future__ import annotations

import asyncio
import errno
import os
import socket
import struct
import sys

import pytest

from verilore.api import runtime


class _Socket:
    def __init__(self, uid):
        self.uid = uid

    def getsockopt(self, level, option, size):
        assert (level, option) == (socket.SOL_SOCKET, socket.SO_PEERCRED)
        return struct.pack("3i", 4242, self.uid, 100)


class _Writer:
    def __init__(self, sock):
        self.sock = sock

    def get_extra_info(self, name):
        return self.sock if name == "socket" else None


linux = pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="SO_PEERCRED is Linux's")


@linux
def test_a_peer_running_as_another_user_is_refused():
    assert runtime._peer_is_this_user(_Writer(_Socket(os.getuid())))
    assert not runtime._peer_is_this_user(_Writer(_Socket(os.getuid() + 1)))


@linux
def test_the_check_runs_after_connect_and_before_the_token(tmp_path, monkeypatch):
    path = tmp_path / "r.sock"
    received = bytearray()

    async def scenario():
        async def handle(reader, writer):
            received.extend(await reader.read(1024))
            writer.close()

        server = await asyncio.start_unix_server(handle, path=str(path))
        seen = {}

        def refuse(writer):
            # Connected, and nothing written yet.
            seen["connected"] = writer.get_extra_info("socket") is not None
            return False

        monkeypatch.setattr(runtime, "_peer_is_this_user", refuse)
        try:
            with pytest.raises(runtime.RuntimeError_, match="another user"):
                await runtime._call_async(path, "s3cret-token", {"op": "ping"}, 2.0, 2.0)
            await asyncio.sleep(0.05)
        finally:
            server.close()
            await server.wait_closed()
        return seen

    seen = asyncio.run(scenario())
    assert seen == {"connected": True}
    assert b"s3cret-token" not in received and len(received) == 0


@linux
def test_this_users_own_runtime_is_accepted(tmp_path):
    path = tmp_path / "r.sock"

    async def scenario():
        server = await asyncio.start_unix_server(lambda r, w: w.close(), path=str(path))
        try:
            _reader, writer = await asyncio.open_unix_connection(str(path))
            ok = runtime._peer_is_this_user(writer)
            writer.close()
            return ok
        finally:
            server.close()
            await server.wait_closed()

    assert asyncio.run(scenario()) is True


@pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets and modes")
def test_a_refused_socket_folder_is_named(tmp_path, monkeypatch):
    long_home = tmp_path / ("x" * 120)
    long_home.mkdir()
    shared = tmp_path / "tmp"
    shared.mkdir()
    folder = shared / f"verilore-{os.getuid()}"
    folder.mkdir(mode=0o777)
    os.chmod(folder, 0o777)
    monkeypatch.setenv("VERILORE_STATE_DIR", str(long_home))
    monkeypatch.setenv("TMPDIR", str(shared))
    # `/tmp/verilore-<uid>` is tried after TMPDIR; this machine's may be fine.
    real = runtime._private_folder
    monkeypatch.setattr(runtime, "_private_folder", lambda f: f == folder and real(f))

    assert runtime.socket_path() == long_home / "runtime.sock"
    assert runtime._REFUSED == f"{folder} can be opened by other users (mode 777)"

    async def too_long(*_args, **_kwargs):
        raise OSError(errno.ENAMETOOLONG, "AF_UNIX path too long")

    monkeypatch.setattr(asyncio, "start_unix_server", too_long)
    runtime._ensure_token()
    with pytest.raises(runtime.RuntimeError_) as raised:
        asyncio.run(runtime.serve())
    message = str(raised.value)
    assert "AF_UNIX path too long" in message
    assert "can be opened by other users" in message and "VERILORE_STATE_DIR" in message
