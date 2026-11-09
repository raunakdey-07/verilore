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


def test_default_bind_is_localhost_8000():
    """`verilore serve` binds 127.0.0.1:8000 by default."""
    with mock.patch("uvicorn.run") as run:
        result = _invoke(["serve", "--run"])
    assert result.exit_code == 0, result.output
    run.assert_called_once()
    (_, kwargs), = [call for call in run.call_args_list]
    config = kwargs.get("config") or kwargs.get("app")
    assert config is not None
    # If the command built a uvicorn.Config, assert on it; else on kwargs.
    if hasattr(config, "host"):
        assert config.host == "127.0.0.1"
        assert config.port == 8000
    else:
        assert kwargs.get("host") == "127.0.0.1"
        assert kwargs.get("port") == 8000


def test_a_nonlocal_host_prints_the_warning():
    """Binding beyond loopback in local mode warns loudly."""
    with mock.patch("uvicorn.run") as run:
        result = _invoke(["serve", "--run", "--host", "0.0.0.0"])
    assert result.exit_code == 0, result.output
    assert "0.0.0.0" in result.output
    assert "reachable from the network" in result.output.lower(), result.output


def test_a_local_host_prints_no_warning():
    """Loopback binds silently."""
    with mock.patch("uvicorn.run") as run:
        result = _invoke(["serve", "--run", "--host", "127.0.0.1"])
    assert result.exit_code == 0, result.output
    assert "reachable from the network" not in result.output.lower(), result.output


def test_startup_text_contains_the_key_command():
    """The startup text tells the operator how to issue an app key, verbatim."""
    with mock.patch("uvicorn.run"):
        result = _invoke(["serve", "--run"])
    assert "verilore credential issue" in result.output, result.output
    assert "--corpus" in result.output, result.output


def test_log_format_is_readable_by_default():
    """Default logs are one-line readable text (not JSON)."""
    with mock.patch("uvicorn.run") as run:
        _invoke(["serve", "--run"])
    (_, kwargs), = [c for c in run.call_args_list]
    config = kwargs.get("config")
    if config is not None and hasattr(config, "log_config"):
        log_config = config.log_config
        # JSON default case: the formatter class must not be JSONLogger.
        fmt = str(log_config) if not isinstance(log_config, dict) else str(log_config)
        assert "json" not in fmt.lower() or "JsonFormatter" not in fmt
    else:
        log_format = kwargs.get("log_format") or ""
        assert "json" not in str(log_format).lower()


def test_log_json_selects_the_json_formatter():
    """`--log-json` selects the JSON log formatter."""
    with mock.patch("uvicorn.run") as run:
        _invoke(["serve", "--run", "--log-json"])
    (_, kwargs), = [c for c in run.call_args_list]
    config = kwargs.get("config")
    assert config is not None
    haystack = str(getattr(config, "log_config", ""))
    assert "json" in haystack.lower()
