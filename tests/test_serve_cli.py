"""`verilore serve` is the two-step job: init, then serve.

The bind, the startup text and the log format are asserted on the *config* the
command builds, never by opening a socket, so these tests are hermetic.
"""

from __future__ import annotations

from unittest import mock

from typer.testing import CliRunner

from verilore.cli.main import app


def _invoke(args, env=None):
    return CliRunner().invoke(app, args, env=env)


def _built_config(mock_server):
    """The uvicorn config the command handed to the server."""
    (config,), _ = mock_server.call_args
    return config


def test_default_bind_is_localhost_8000():
    """`verilore serve` binds 127.0.0.1:8000 by default."""
    with mock.patch("uvicorn.Server") as server:
        result = _invoke(["serve", "--run"])
    assert result.exit_code == 0, result.output
    server.assert_called_once()
    config = _built_config(server)
    assert config.host == "127.0.0.1"
    assert config.port == 8000


def test_a_nonlocal_host_prints_the_warning():
    """Binding beyond loopback in local mode warns loudly."""
    with mock.patch("uvicorn.Server"):
        result = _invoke(["serve", "--run", "--host", "0.0.0.0"])
    assert result.exit_code == 0, result.output
    assert "0.0.0.0" in result.output
    assert "reachable from the network" in result.output.lower(), result.output


def test_a_local_host_prints_no_warning():
    """Loopback binds silently."""
    with mock.patch("uvicorn.Server"):
        result = _invoke(["serve", "--run", "--host", "127.0.0.1"])
    assert result.exit_code == 0, result.output
    assert "reachable from the network" not in result.output.lower(), result.output


def test_startup_text_contains_the_key_command():
    """The startup text tells the operator how to issue an app key, verbatim."""
    with mock.patch("uvicorn.Server"):
        result = _invoke(["serve", "--run"])
    assert "verilore credential issue" in result.output, result.output
    assert "--corpus" in result.output, result.output


def test_log_format_is_readable_by_default():
    """Default logs are one-line readable text (not JSON)."""
    with mock.patch("uvicorn.Server") as server:
        _invoke(["serve", "--run"])
    formatters = _built_config(server).log_config["formatters"]
    assert "VeriloreJsonFormatter" not in str(formatters)


def test_log_json_selects_the_json_formatter():
    """`--log-json` selects the JSON log formatter."""
    with mock.patch("uvicorn.Server") as server:
        _invoke(["serve", "--run", "--log-json"])
    formatters = _built_config(server).log_config["formatters"]
    assert formatters["default"]["()"] == "verilore.cli.main.VeriloreJsonFormatter"


def test_an_error_response_is_logged_with_its_request_id(caplog):
    """A failed request logs one line naming the request id the caller got."""
    from fastapi.testclient import TestClient

    from verilore.api.main import app as api_app

    route = next(r for r in api_app.routes if getattr(r, "path", "") == "/health")
    original = route.dependant.call

    async def boom(**kwargs):
        raise RuntimeError("the failure under test")

    route.dependant.call = boom
    client = TestClient(api_app)
    try:
        response = client.get("/health")
    finally:
        route.dependant.call = original
        client.close()

    assert response.status_code == 500
    request_id = response.headers["X-Request-Id"]
    assert request_id, response.text
    assert "unhandled_error" in caplog.text
    assert request_id in caplog.text
