"""FastAPI startup hook for configuration validation.

Import and call ``register_config_startup(app)`` from the main API module
to wire in configuration loading and validation at startup.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from .config import ConfigError, get_settings

logger = logging.getLogger(__name__)


def register_config_startup(app: FastAPI) -> None:
    """Register a startup event that validates and caches configuration."""

    @app.on_event("startup")
    def _validate_config() -> None:
        try:
            settings = get_settings()
        except ConfigError as exc:
            logger.critical("Configuration validation failed: %s", exc)
            raise SystemExit(1) from exc

        # Store on app.state so route handlers can access if needed
        app.state.settings = settings

        logger.info(
            "RIF runtime configuration loaded: %s",
            settings.safe_summary(),
        )
