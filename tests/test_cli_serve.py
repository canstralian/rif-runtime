"""Tests for `rif serve` bind-address resolution.

`serve` used to hardcode 127.0.0.1 while the configuration contract defaulted
to 0.0.0.0, so the two entry points disagreed about where the API binds.  The
contract is now the single source of truth and the CLI flags are overrides.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import typer

from rif_runtime import cli
from rif_runtime.config import reset_settings


@pytest.fixture(autouse=True)
def _reset_singleton() -> Generator[None, None, None]:
    reset_settings()
    yield
    reset_settings()


@pytest.fixture()
def captured_uvicorn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Stub uvicorn.run and pin cwd to an empty dir so no rif.toml is found."""
    calls: dict[str, Any] = {}

    def _fake_run(_app: str, **kwargs: Any) -> None:
        calls.update(kwargs)

    # Targeted by dotted path rather than `cli.uvicorn`: uvicorn is imported by
    # cli, not re-exported from it, so the attribute access trips mypy strict's
    # no_implicit_reexport under the `mypy src/ tests/` run in lint.yml.
    monkeypatch.setattr("rif_runtime.cli.uvicorn.run", _fake_run)
    monkeypatch.chdir(tmp_path)
    return calls


def test_serve_takes_host_from_config_contract(
    captured_uvicorn: dict[str, Any],
) -> None:
    """With no flags and no rif.toml, serve binds the contract's default."""
    cli.serve()
    assert captured_uvicorn["host"] == "0.0.0.0"  # nosec B104
    assert captured_uvicorn["port"] == 8000


def test_serve_reads_host_from_rif_toml(
    captured_uvicorn: dict[str, Any], tmp_path: Path
) -> None:
    """A rif.toml [server] section drives the bind address."""
    (tmp_path / "rif.toml").write_text('[server]\nhost = "127.0.0.1"\nport = 9001\n')
    cli.serve()
    assert captured_uvicorn["host"] == "127.0.0.1"
    assert captured_uvicorn["port"] == 9001


def test_serve_reads_host_and_port_from_env(
    captured_uvicorn: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """RIF_SERVER_HOST / RIF_SERVER_PORT override the contract defaults.

    Port is asserted as an int: env vars arrive as strings and go through
    _coerce_env_value, so a regression there would hand uvicorn "9002".
    """
    monkeypatch.setenv("RIF_SERVER_HOST", "10.0.0.7")
    monkeypatch.setenv("RIF_SERVER_PORT", "9002")
    cli.serve()
    assert captured_uvicorn["host"] == "10.0.0.7"
    assert captured_uvicorn["port"] == 9002
    assert isinstance(captured_uvicorn["port"], int)


@pytest.mark.parametrize("bad_port", [0, -1, 70000])
def test_explicit_port_is_validated(
    captured_uvicorn: dict[str, Any], bad_port: int
) -> None:
    """An out-of-range --port is rejected, not forwarded to uvicorn.

    Overrides bypassed ServerSection._port_range before, so `--port 70000`
    reached uvicorn and failed there with a far less useful message.
    """
    with pytest.raises(typer.BadParameter):
        cli.serve(port=bad_port)
    assert captured_uvicorn == {}


def test_explicit_flags_beat_config(
    captured_uvicorn: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--host/--port win over both rif.toml and RIF_* env vars."""
    monkeypatch.setenv("RIF_SERVER_HOST", "10.0.0.7")
    monkeypatch.setenv("RIF_SERVER_PORT", "9002")
    cli.serve(host="127.0.0.1", port=8123)
    assert captured_uvicorn["host"] == "127.0.0.1"
    assert captured_uvicorn["port"] == 8123
