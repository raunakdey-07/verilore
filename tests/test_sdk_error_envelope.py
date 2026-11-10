"""A remote failure reaches the app as a `VeriloreError` with every field set.

The guide's error snippet logs code, message, retryable and request_id. Each of
them has to be right for the failures an app actually meets: a refusal from the
server, a server that is down, and a response with no error envelope.
"""

from __future__ import annotations

from verilore.errors import VeriloreError
from verilore.sdk import MemoryClientError, _remote_error


class _Response:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


def test_it_is_a_verilore_error():
    assert issubclass(MemoryClientError, VeriloreError)


def test_a_request_that_got_no_answer_is_retryable():
    """Timeouts and an unreachable server are what a retry can fix."""
    assert MemoryClientError("timeout", "slow", 504).retryable is True
    assert MemoryClientError("transport_error", "down", 503).retryable is True
    assert MemoryClientError("http_error", "bad gateway", 502).retryable is True


def test_a_refusal_is_not_retryable():
    assert MemoryClientError("vl_forbidden", "no", 403).retryable is False
    assert MemoryClientError("vl_invalid_request", "bad", 422).retryable is False


def test_what_the_server_says_wins():
    """The server's envelope decides when it says something."""
    assert MemoryClientError("transport_error", "x", 503, retryable=False).retryable is False
    error = _remote_error(
        _Response(429, {"detail": {"code": "vl_rate_limited", "retryable": True}}), "x"
    )
    assert error.retryable is True
    assert error.code == "vl_rate_limited"


def test_the_request_id_is_the_one_the_server_logged():
    """From the envelope when it has one, else from the X-Request-Id header."""
    from_envelope = _remote_error(
        _Response(403, {"detail": {"code": "vl_forbidden", "request_id": "rid-body"}}), "x"
    )
    assert from_envelope.request_id == "rid-body"

    from_header = _remote_error(
        _Response(503, None, headers={"X-Request-Id": "rid-header"}), "unavailable"
    )
    assert from_header.request_id == "rid-header"
    assert from_header.retryable is True
