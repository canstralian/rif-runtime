from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_version_from_pyproject() -> str | None:
    # Returns None (not raises) so _read_version() can escalate to RuntimeWarning.
    # None is correct both for built wheels (no pyproject.toml on this path) and
    # for source checkouts where the layout changed.
    #
    # Depth assumption: src/rif_runtime/_version.py is exactly 3 dirs below
    # the repo root (root/src/rif_runtime/_version.py). Only valid in source/editable
    # checkouts — built wheels go through importlib.metadata instead.
    try:
        _pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
        with _pyproject.open("rb") as _f:
            resolved: str = tomllib.load(_f)["project"]["version"]
            return resolved
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError):
        return None


def _read_version() -> str:
    """Resolve package version without a hardcoded duplicate of pyproject.toml.

    Resolution order:
    1. importlib.metadata  — installed package, normal case
    2. pyproject.toml      — editable source checkout without pip install
    3. RuntimeWarning + "unknown" — last resort when both paths unavailable
    """
    try:
        return version("rif-runtime")
    except PackageNotFoundError:
        pass

    # Package not installed — read directly from pyproject.toml in the source tree.
    # Real use case: `python -m rif_runtime` in a fresh clone before `pip install -e .`.
    v = _read_version_from_pyproject()
    if v is not None:
        return v

    # Neither metadata nor pyproject.toml is reachable — surface this loudly
    # rather than returning a silently-stale constant.
    import warnings

    warnings.warn(
        "rif-runtime: version could not be determined. "
        "Run `pip install -e .` to fix this.",
        RuntimeWarning,
        stacklevel=2,
    )
    return "unknown"


# Called once when rif_runtime is first imported; Python's module cache means
# this runs at most once per process.
__version__ = _read_version()
