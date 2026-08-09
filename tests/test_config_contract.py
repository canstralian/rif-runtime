"""Tests for the runtime configuration contract (issue #17).

Covers:
- Loading from rif.toml
- Environment variable overrides
- Missing file fallback to defaults
- Rejection of unknown keys
- Provider mode validation
- Port range validation
- Secret-safe summary
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from rif_runtime.config import (
    ConfigError,
    RifSettings,
    load_settings,
    reset_settings,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Generator[None, None, None]:
    """Ensure the module-level singleton is cleared between tests."""
    reset_settings()
    yield
    reset_settings()


# ---------------------------------------------------------------------------
# Load from TOML
# ---------------------------------------------------------------------------


class TestLoadFromToml:
    """Settings are correctly parsed from a rif.toml file."""

    def test_load_defaults(self, tmp_path: Path) -> None:
        """A minimal TOML with no sections yields all defaults."""
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("")
        settings = load_settings(toml_file)
        assert settings.runtime.posture == "normal"
        assert settings.runtime.cloud_egress is False
        assert settings.server.port == 8000
        assert settings.provider.mode == "local"
        assert settings.paths.data_dir == "data"

    def test_load_custom_values(self, tmp_path: Path) -> None:
        """Custom values in TOML are correctly loaded."""
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text(
            "[runtime]\n"
            'posture = "elevated"\n'
            'environment = "staging"\n'
            "cloud_egress = true\n"
            "\n"
            "[server]\n"
            'host = "127.0.0.1"\n'
            "port = 9000\n"
            "\n"
            "[provider]\n"
            'mode = "remote"\n'
            'model = "gpt-4"\n'
            'endpoint = "https://api.example.com/v1"\n'
        )
        settings = load_settings(toml_file)
        assert settings.runtime.posture == "elevated"
        assert settings.runtime.environment == "staging"
        assert settings.runtime.cloud_egress is True
        assert settings.server.host == "127.0.0.1"
        assert settings.server.port == 9000
        assert settings.provider.mode == "remote"
        assert settings.provider.model == "gpt-4"
        assert settings.provider.endpoint == "https://api.example.com/v1"


# ---------------------------------------------------------------------------
# Env-var overrides
# ---------------------------------------------------------------------------


class TestEnvVarOverrides:
    """RIF_* environment variables override TOML values."""

    def test_override_posture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text('[runtime]\nposture = "normal"\n')
        monkeypatch.setenv("RIF_POSTURE", "elevated")
        settings = load_settings(toml_file)
        assert settings.runtime.posture == "elevated"

    def test_override_port(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("[server]\nport = 8000\n")
        monkeypatch.setenv("RIF_SERVER_PORT", "3000")
        settings = load_settings(toml_file)
        assert settings.server.port == 3000

    def test_override_cloud_egress_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("[runtime]\ncloud_egress = false\n")
        monkeypatch.setenv("RIF_CLOUD_EGRESS", "true")
        settings = load_settings(toml_file)
        assert settings.runtime.cloud_egress is True

    def test_override_cloud_egress_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("[runtime]\ncloud_egress = true\n")
        monkeypatch.setenv("RIF_CLOUD_EGRESS", "0")
        settings = load_settings(toml_file)
        assert settings.runtime.cloud_egress is False

    def test_override_provider_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text('[provider]\nmode = "local"\n')
        monkeypatch.setenv("RIF_PROVIDER_MODE", "hybrid")
        settings = load_settings(toml_file)
        assert settings.provider.mode == "hybrid"

    def test_env_override_without_toml_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env vars work even when no TOML file exists."""
        missing = tmp_path / "nonexistent.toml"
        monkeypatch.setenv("RIF_POSTURE", "restricted")
        monkeypatch.setenv("RIF_SERVER_PORT", "4000")
        settings = load_settings(missing)
        assert settings.runtime.posture == "restricted"
        assert settings.server.port == 4000


# ---------------------------------------------------------------------------
# Missing file fallback
# ---------------------------------------------------------------------------


class TestMissingFileFallback:
    """When rif.toml does not exist, all defaults apply."""

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.toml"
        settings = load_settings(missing)
        assert settings == RifSettings()

    def test_defaults_cloud_egress_off(self, tmp_path: Path) -> None:
        """Cloud egress defaults to off (acceptance criterion)."""
        missing = tmp_path / "nope.toml"
        settings = load_settings(missing)
        assert settings.runtime.cloud_egress is False


# ---------------------------------------------------------------------------
# Validation: unknown keys rejected
# ---------------------------------------------------------------------------


class TestUnknownKeysRejected:
    """Unknown configuration keys cause a validation error."""

    def test_unknown_top_level_key(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("[bogus]\nfoo = 1\n")
        with pytest.raises(ConfigError):
            load_settings(toml_file)

    def test_unknown_nested_key(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("[runtime]\nunknown_key = true\n")
        with pytest.raises(ConfigError):
            load_settings(toml_file)


# ---------------------------------------------------------------------------
# Validation: provider mode
# ---------------------------------------------------------------------------


class TestProviderModeValidation:
    """Provider mode must be one of the allowed values."""

    def test_invalid_provider_mode(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text('[provider]\nmode = "cloud"\n')
        with pytest.raises(ConfigError):
            load_settings(toml_file)

    @pytest.mark.parametrize("mode", ["local", "remote", "hybrid"])
    def test_valid_provider_modes(self, tmp_path: Path, mode: str) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text(f'[provider]\nmode = "{mode}"\n')
        settings = load_settings(toml_file)
        assert settings.provider.mode == mode


# ---------------------------------------------------------------------------
# Validation: port range
# ---------------------------------------------------------------------------


class TestPortValidation:
    """Server port must be in valid TCP range."""

    def test_port_zero_invalid(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("[server]\nport = 0\n")
        with pytest.raises(ConfigError):
            load_settings(toml_file)

    def test_port_too_high(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("[server]\nport = 70000\n")
        with pytest.raises(ConfigError):
            load_settings(toml_file)


# ---------------------------------------------------------------------------
# Secret-safe summary
# ---------------------------------------------------------------------------


class TestSafeSummary:
    """The safe_summary method redacts sensitive fields."""

    def test_endpoint_redacted(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text(
            '[provider]\nendpoint = "https://key:secret@api.example.com"\n'
        )
        settings = load_settings(toml_file)
        summary = settings.safe_summary()
        assert summary["provider"]["endpoint"] == "***"

    def test_empty_endpoint_not_redacted(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "rif.toml"
        toml_file.write_text("")
        settings = load_settings(toml_file)
        summary = settings.safe_summary()
        assert summary["provider"]["endpoint"] == ""
