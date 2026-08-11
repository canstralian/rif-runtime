"""Runtime configuration contract for RIF.

Loads settings from ``rif.toml`` (project root) with environment-variable
overrides prefixed ``RIF_``.  Env vars take precedence over file values.

Env-var mapping (section flattened with underscore, uppercased):
  [runtime] posture        -> RIF_POSTURE
  [runtime] environment    -> RIF_ENVIRONMENT
  [runtime] cloud_egress   -> RIF_CLOUD_EGRESS
  [server]  host           -> RIF_SERVER_HOST
  [server]  port           -> RIF_SERVER_PORT
  [server]  root_path      -> RIF_SERVER_ROOT_PATH
  [provider] mode          -> RIF_PROVIDER_MODE
  [provider] model         -> RIF_PROVIDER_MODEL
  [provider] endpoint      -> RIF_PROVIDER_ENDPOINT
  [paths]   data_dir       -> RIF_DATA_DIR
  [paths]   config_dir     -> RIF_CONFIG_DIR
"""

from __future__ import annotations

import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .schemas import RuntimeConfig

_SETTINGS_TOML_PATH = Path("rif.toml")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProviderMode(StrEnum):
    """Supported provider execution modes."""

    local = "local"
    remote = "remote"
    hybrid = "hybrid"


class PostureLevel(StrEnum):
    """Runtime governance posture levels."""

    normal = "normal"
    elevated = "elevated"
    restricted = "restricted"
    locked = "locked"


# ---------------------------------------------------------------------------
# Settings sub-models
# ---------------------------------------------------------------------------


class RuntimeSection(BaseModel):
    """Top-level runtime behaviour knobs."""

    model_config = ConfigDict(extra="forbid")

    posture: PostureLevel = PostureLevel.normal
    environment: str = "production"
    cloud_egress: bool = False


class ServerSection(BaseModel):
    """HTTP server configuration."""

    model_config = ConfigDict(extra="forbid")

    # Binding all interfaces is the useful default for the containerised
    # deployment this config contract targets; operators narrow it with
    # [server] host in rif.toml or RIF_SERVER_HOST.  This is the single source
    # of truth for the bind address — `rif serve` reads it rather than carrying
    # its own default (see cli.py).
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8000
    root_path: str = ""

    @field_validator("port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return v


class ProviderSection(BaseModel):
    """LLM / AI provider configuration."""

    model_config = ConfigDict(extra="forbid")

    mode: ProviderMode = ProviderMode.local
    model: str = "default"
    endpoint: str = ""


class PathsSection(BaseModel):
    """Filesystem paths used by the runtime."""

    model_config = ConfigDict(extra="forbid")

    data_dir: str = "data"
    config_dir: str = "config"


# ---------------------------------------------------------------------------
# Top-level settings
# ---------------------------------------------------------------------------


class RifSettings(BaseModel):
    """Canonical runtime settings loaded from rif.toml + RIF_* env vars.

    Unknown keys are rejected (extra='forbid') so typos surface immediately.
    """

    model_config = ConfigDict(extra="forbid")

    runtime: RuntimeSection = RuntimeSection()
    server: ServerSection = ServerSection()
    provider: ProviderSection = ProviderSection()
    paths: PathsSection = PathsSection()

    def safe_summary(self) -> dict[str, Any]:
        """Return a secret-safe dict suitable for logging at startup.

        Redacts provider.endpoint (may contain tokens in query params).
        """
        data = self.model_dump()
        endpoint = data["provider"]["endpoint"]
        if endpoint:
            data["provider"]["endpoint"] = "***"
        return data


# ---------------------------------------------------------------------------
# Env-var override mapping
# ---------------------------------------------------------------------------

# Maps RIF_<NAME> env var to (section, key) path in the settings dict.
_ENV_MAP: dict[str, tuple[str, str]] = {
    "RIF_POSTURE": ("runtime", "posture"),
    "RIF_ENVIRONMENT": ("runtime", "environment"),
    "RIF_CLOUD_EGRESS": ("runtime", "cloud_egress"),
    "RIF_SERVER_HOST": ("server", "host"),
    "RIF_SERVER_PORT": ("server", "port"),
    "RIF_SERVER_ROOT_PATH": ("server", "root_path"),
    "RIF_PROVIDER_MODE": ("provider", "mode"),
    "RIF_PROVIDER_MODEL": ("provider", "model"),
    "RIF_PROVIDER_ENDPOINT": ("provider", "endpoint"),
    "RIF_DATA_DIR": ("paths", "data_dir"),
    "RIF_CONFIG_DIR": ("paths", "config_dir"),
}


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Overlay RIF_* env vars onto a parsed TOML dict (mutates in place)."""
    for env_key, (section, key) in _ENV_MAP.items():
        value = os.environ.get(env_key)
        if value is None:
            continue
        data.setdefault(section, {})[key] = _coerce_env_value(value, section, key)
    return data


def _coerce_env_value(raw: str, section: str, key: str) -> str | int | bool:
    """Best-effort coercion so env vars match expected TOML types."""
    # Boolean fields
    if key == "cloud_egress":
        return raw.lower() in ("1", "true", "yes")
    # Integer fields
    if key == "port":
        return int(raw)
    return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""


def load_settings(
    path: Path | str | None = None,
) -> RifSettings:
    """Load RIF settings from TOML file + env-var overrides.

    Args:
        path: Explicit path to the TOML file.  Defaults to ``rif.toml`` in
              the current working directory.

    Returns:
        Validated ``RifSettings`` instance.

    Raises:
        ConfigError: If the file contains invalid/unknown keys or values
                     fail validation.
    """
    toml_path = Path(path) if path is not None else _SETTINGS_TOML_PATH

    # Load base config from file; fall back to empty dict (all defaults)
    if toml_path.is_file():
        with open(toml_path, "rb") as f:
            data: dict[str, Any] = tomllib.load(f)
    else:
        data = {}

    # Apply env-var overrides
    _apply_env_overrides(data)

    # Validate
    try:
        return RifSettings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


# Module-level singleton (lazy)
_settings: RifSettings | None = None


def get_settings() -> RifSettings:
    """Return the module-level settings singleton, loading on first access."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Reset the cached singleton (useful in tests)."""
    global _settings  # noqa: PLW0603
    _settings = None


# ---------------------------------------------------------------------------
# Legacy loader (backward-compatible)
# ---------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> RuntimeConfig:
    """Load the environments config from YAML (legacy interface).

    Used by ``RIFRuntime.__init__``.  The path now defaults to
    ``<settings.paths.config_dir>/environments.yaml``.
    """
    if path is None:
        settings = get_settings()
        path = Path(settings.paths.config_dir) / "environments.yaml"
    else:
        path = Path(path)

    if not path.is_file():
        # Provide sensible defaults when environments file is absent
        from .schemas import EnvironmentProfile

        return RuntimeConfig(
            default_environment="production",
            environments={"production": EnvironmentProfile()},
        )

    return RuntimeConfig.model_validate(yaml.safe_load(path.read_text()))
