"""CLI surface: the serve command's defaults are a deployment concern."""

from unittest.mock import patch

from typer.testing import CliRunner

from rif_runtime.cli import app

runner = CliRunner()


def test_serve_does_not_enable_reload_by_default():
    """`rif serve` is the README's start command; it must not auto-reload.

    Reload was previously hardcoded on, so the documented way to start the
    service spawned uvicorn's file-watching supervisor in production.
    """
    with patch("rif_runtime.cli.uvicorn.run") as run:
        result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["reload"] is False


def test_serve_reload_flag_enables_it():
    with patch("rif_runtime.cli.uvicorn.run") as run:
        result = runner.invoke(app, ["serve", "--reload"])

    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["reload"] is True


def test_serve_takes_host_and_port_from_settings(monkeypatch):
    """Asserted against injected settings, not the ambient ones.

    Reading the real singleton would make this depend on whatever a previous
    test cached, and on RIF_SERVER_HOST/RIF_SERVER_PORT in the developer's
    shell. That the *defaults* are loopback:8000 is a configuration contract,
    tested in tests/test_config_contract.py; what belongs here is that the CLI
    forwards whatever configuration says.
    """
    from rif_runtime.config import RifSettings

    settings = RifSettings.model_validate(
        {"server": {"host": "192.0.2.10", "port": 9999}}
    )
    monkeypatch.setattr("rif_runtime.cli.get_settings", lambda: settings)

    with patch("rif_runtime.cli.uvicorn.run") as run:
        runner.invoke(app, ["serve"])

    assert run.call_args.kwargs["host"] == "192.0.2.10"
    assert run.call_args.kwargs["port"] == 9999


def test_serve_flags_override_settings(monkeypatch):
    """Explicit flags win over configuration."""
    from rif_runtime.config import RifSettings

    settings = RifSettings.model_validate(
        {"server": {"host": "192.0.2.10", "port": 9999}}
    )
    monkeypatch.setattr("rif_runtime.cli.get_settings", lambda: settings)

    with patch("rif_runtime.cli.uvicorn.run") as run:
        runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9001"])

    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["port"] == 9001


def test_every_documented_command_is_registered():
    """CLAUDE.md and docs/cli-reference.md list these four."""
    registered = {
        command.name or command.callback.__name__ for command in app.registered_commands
    }

    assert {"serve", "check", "replay", "msf-check"} <= registered
