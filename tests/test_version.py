import os
import tomllib
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

import rif_runtime


@pytest.fixture()
def patch_metadata_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch rif_runtime._version.version to always raise PackageNotFoundError."""

    def _raise(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr("rif_runtime._version.version", _raise)


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    expected = data["project"]["version"]

    # Verify installed package metadata matches pyproject.toml.
    # CI always runs `pip install -e .` before pytest (see ci.yml), so this
    # path is always taken there. Local dev runs without an editable install
    # are skipped rather than hard-failed to avoid confusing new contributors.
    try:
        installed = version("rif-runtime")
    except PackageNotFoundError:
        if os.environ.get("CI"):
            pytest.fail(
                "rif-runtime not installed in CI — ci.yml must run "
                "`pip install -e .` before pytest"
            )
        pytest.skip("rif-runtime not installed — run `pip install -e .` first")

    assert installed == expected, (
        f"installed metadata {installed!r} != pyproject {expected!r}"
    )
    assert rif_runtime.__version__ == expected


def test_read_version_from_pyproject_path_resolution() -> None:
    """_read_version_from_pyproject() resolves pyproject.toml via the 3-parent path."""
    from rif_runtime._version import _read_version_from_pyproject

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        expected = tomllib.load(f)["project"]["version"]

    result = _read_version_from_pyproject()
    assert result == expected, (
        f"_read_version_from_pyproject() returned {result!r}, expected {expected!r}; "
        "check that Path(__file__).parent.parent.parent resolves to the repo root"
    )


def test_version_falls_back_to_pyproject(
    patch_metadata_unavailable: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_read_version() reads pyproject.toml when metadata raises PackageNotFound."""
    monkeypatch.setattr(
        "rif_runtime._version._read_version_from_pyproject", lambda: "9.8.7"
    )

    from rif_runtime._version import _read_version

    assert _read_version() == "9.8.7"


def test_version_unknown_when_all_fallbacks_fail(
    patch_metadata_unavailable: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_read_version() returns 'unknown' and warns when all sources fail."""
    monkeypatch.setattr(
        "rif_runtime._version._read_version_from_pyproject", lambda: None
    )

    from rif_runtime._version import _read_version

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = _read_version()

    assert result == "unknown"
    assert len(w) == 1
    assert issubclass(w[0].category, RuntimeWarning)
    assert "rif-runtime" in str(w[0].message)
