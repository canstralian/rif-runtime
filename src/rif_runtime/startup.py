"""Configuration validation at application start.

Two entry points, because configuration is reached at two different moments:

``validate_config`` runs at *import* of ``rif_runtime.api``, which is the one
that actually fires in production. ``api.py`` builds a module-level
``RIFRuntime()``, and that constructor loads configuration -- so an invalid
``rif.toml`` raises during import, before any lifespan handler could run. Left
alone, the operator sees a bare ``ConfigError`` traceback from deep inside
``config.py`` with no indication that the problem is their configuration file.

``config_lifespan`` runs when the application starts serving, and caches the
validated settings on ``app.state`` for route handlers.

Both funnel through ``validate_config`` so the diagnostic is identical wherever
the failure surfaces. ``get_settings`` memoises, so the second call is free.

The lifespan replaced an ``@app.on_event("startup")`` handler. Beyond the
deprecation, ``on_event`` gave the failure path no clear semantics: a
``SystemExit`` raised inside it was swallowed by anyio's task group and
surfaced to callers as ``CancelledError``, so "configuration is invalid" and
"startup was cancelled" were indistinguishable. Under lifespan the exception
propagates.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI

from .config import ConfigError, RifSettings, get_settings

logger = logging.getLogger(__name__)


def validate_config() -> RifSettings:
    """Load and validate settings, logging a clear diagnostic on failure.

    Fails fast: invalid configuration must stop the process rather than boot a
    half-configured runtime that would decide policy against defaults nobody
    chose. ``ConfigError`` is re-raised unchanged so the caller -- import
    machinery or lifespan -- surfaces it in its own idiom.
    """
    try:
        return get_settings()
    except ConfigError:
        logger.critical(
            "Configuration validation failed; refusing to start. "
            "Check rif.toml and RIF_* environment variables.",
            exc_info=True,
        )
        raise


@contextmanager
def configuration_diagnostics() -> Iterator[None]:
    """Label configuration errors raised while building the runtime.

    ``validate_config`` only covers settings *parsing*. ``RIFRuntime`` then
    validates the parsed values against the environments file and raises
    ``ValueError`` for a name that matches no profile -- outside the diagnostic
    path, so ``RIF_ENVIRONMENT=typo`` produced an unlabelled traceback while
    ``RIF_POSTURE=typo`` produced a clear message. Same class of failure, so
    the same treatment.
    """
    try:
        yield
    except ValueError:
        logger.critical(
            "Runtime configuration is invalid; refusing to start. "
            "Check rif.toml, config/environments.yaml, and RIF_* "
            "environment variables.",
            exc_info=True,
        )
        raise


@asynccontextmanager
async def config_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration, cache it on ``app.state``, then serve."""
    settings = validate_config()

    # Stored on app.state so route handlers can reach it without re-loading.
    app.state.settings = settings

    logger.info(
        "RIF runtime configuration loaded: %s",
        settings.safe_summary(),
    )

    yield
