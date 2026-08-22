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

import textwrap
from collections.abc import Generator
from pathlib import Path

import pytest

from rif_runtime.config import (
    ConfigError,
    RifSettings,
    get_settings,
    load_settings,
    reset_settings,
)


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Clear the settings singleton and ambient RIF_* overrides per test.

    These are loader contract tests, so they must see declared defaults. The
    suite-wide RIF_DATA_DIR set in conftest.py (state isolation for RIFRuntime)
    would otherwise leak in as an override; tests that exercise overrides set
    their own env vars in the test body, after this fixture has run.
    """
    for env_key in ("RIF_DATA_DIR", "RIF_CONFIG_DIR"):
        monkeypatch.delenv(env_key, raising=False)
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


# --- .env.example fidelity ---------------------------------------------------
#
# .env.example once documented 58 variables of which the runtime read 3. The
# 55 dead names included RIF_SECURITY_SANDBOX_ENABLED, RIF_AUTH_ENABLED and
# RIF_SECURITY_NETWORK_ISOLATION -- inert strings that read as security
# controls. Documented-but-inert configuration is worse than undocumented
# configuration, so this is enforced rather than left to review.

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _documented_env_vars() -> set[str]:
    names = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        names.add(line.split("=", 1)[0].strip())
    return names


def _source_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / "src").rglob("*.py")
    )


# Settings that are parsed and surfaced but deliberately not acted on. Each
# needs a reason, and .env.example must say the same thing to the operator.
RECORDED_ONLY_SETTINGS = {
    "RIF_CLOUD_EGRESS": "advisory flag; egress is decided by profile + rules",
    "RIF_PROVIDER_MODE": "provider config is not authorization",
    "RIF_PROVIDER_MODEL": "provider config is not authorization",
    "RIF_PROVIDER_ENDPOINT": "provider config is not authorization",
}


def test_env_example_documents_only_variables_the_code_reads():
    source = _source_text()
    inert = sorted(name for name in _documented_env_vars() if name not in source)

    assert not inert, (
        f".env.example documents {len(inert)} variable(s) that nothing in src/ "
        f"reads: {inert}. Remove them, or implement them. A setting that looks "
        "like a control but does nothing is a false assurance."
    )


# --- every mapped setting must change something ------------------------------
#
# Two earlier versions of this guard were vacuous. The first grepped src/ for
# the variable name, which config.py's own _ENV_MAP satisfies for every name.
# The second matched the `settings.<section>.<key>` attribute path, which the
# ordinary `server = get_settings().server` / `server.host` idiom never spells
# out. Static analysis kept measuring the wrong thing, so these assert observed
# behaviour instead: set the variable, then look at what the runtime does. A
# setting that stops being honoured fails here regardless of how it is written.


def test_data_dir_setting_relocates_persistent_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIF_DATA_DIR", str(tmp_path))
    reset_settings()
    from rif_runtime.runtime import RIFRuntime

    assert RIFRuntime().decisions_path == tmp_path / "decisions.jsonl"


def test_config_dir_setting_selects_the_environments_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "environments.yaml").write_text(
        textwrap.dedent(
            """\
            default_environment: OnlyHere
            environments:
              OnlyHere:
                networking_type: open
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RIF_CONFIG_DIR", str(tmp_path))
    reset_settings()
    from rif_runtime.config import load_config

    assert load_config().default_environment == "OnlyHere"


def test_environment_setting_selects_the_active_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RIF_ENVIRONMENT", "RIF_CI")
    reset_settings()
    from rif_runtime.runtime import RIFRuntime

    assert RIFRuntime().environment_name == "RIF_CI"


def test_unknown_environment_setting_raises_rather_than_falling_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silent fallback would serve a different egress profile than configured."""
    monkeypatch.setenv("RIF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RIF_ENVIRONMENT", "no_such_environment")
    reset_settings()
    from rif_runtime.runtime import RIFRuntime

    with pytest.raises(ValueError, match="no_such_environment"):
        RIFRuntime()


def test_posture_setting_reaches_the_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RIF_POSTURE", "restricted")
    reset_settings()
    from rif_runtime.runtime import RIFRuntime

    assert RIFRuntime().posture == "restricted"


def test_server_host_and_port_settings_reach_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`rif serve` hardcoded these, so both were documented, parsed and ignored."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from rif_runtime.cli import app as cli_app

    monkeypatch.setenv("RIF_SERVER_HOST", "10.1.2.3")
    monkeypatch.setenv("RIF_SERVER_PORT", "9123")
    reset_settings()

    with patch("rif_runtime.cli.uvicorn.run") as run:
        CliRunner().invoke(cli_app, ["serve"])

    assert run.call_args.kwargs["host"] == "10.1.2.3"
    assert run.call_args.kwargs["port"] == 9123


def test_server_root_path_setting_reaches_the_asgi_app(tmp_path: Path) -> None:
    """Mount prefix for reverse-proxy sub-path deployments.

    Runs in a subprocess because api.py reads the setting while building the
    module-level app: once this process has imported it, the object is fixed
    and an in-process override would prove nothing.
    """
    import json
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "RIF_SERVER_ROOT_PATH": "/api/v1",
        "RIF_DATA_DIR": str(tmp_path),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from rif_runtime.api import app; "
            "print(json.dumps(app.root_path))",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip()) == "/api/v1"


def test_recorded_only_settings_are_declared_in_env_example() -> None:
    """An operator reading the file must see which settings do not act."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    for name in RECORDED_ONLY_SETTINGS:
        preamble = text[: text.index(f"{name}=")]
        section = preamble.rsplit("# ---", 1)[-1].lower()
        assert (
            "not acted on" in section
            or "does not itself" in section
            or "not authorization" in section
        ), f"{name} is recorded-only but .env.example does not say so"


def test_every_mapped_setting_is_covered_here_or_declared_recorded_only() -> None:
    """No mapped setting may escape both the behavioural tests and the exemptions.

    This is the part that keeps the section above complete: adding a key to
    _ENV_MAP without either proving it does something or declaring that it does
    not fails here.
    """
    from rif_runtime.config import _ENV_MAP

    covered = {
        "RIF_DATA_DIR",
        "RIF_CONFIG_DIR",
        "RIF_ENVIRONMENT",
        "RIF_POSTURE",
        "RIF_SERVER_HOST",
        "RIF_SERVER_PORT",
        "RIF_SERVER_ROOT_PATH",
    }
    unaccounted = sorted(set(_ENV_MAP) - covered - set(RECORDED_ONLY_SETTINGS))

    assert not unaccounted, (
        f"{unaccounted} are mapped but neither behaviourally tested above nor "
        "declared in RECORDED_ONLY_SETTINGS."
    )


def test_env_example_documents_every_mapped_setting():
    """Every RIF_* name in config._ENV_MAP is discoverable in .env.example."""
    from rif_runtime.config import _ENV_MAP

    documented = _documented_env_vars()
    missing = sorted(name for name in _ENV_MAP if name not in documented)

    assert not missing, f".env.example is missing mapped setting(s): {missing}"


def test_env_example_documents_the_auth_and_supabase_variables():
    """Names read directly via os.environ rather than through _ENV_MAP."""
    documented = _documented_env_vars()

    for name in (
        "RIF_CONTROL_PLANE_API_KEYS",
        "RIF_REQUIRE_READ_AUTH",
        "RIF_CORS_ORIGINS",
        "RIF_PBKDF2_ITERATIONS",
        "RIF_MSF_BROKER_KEY",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        assert name in documented, f".env.example does not document {name}"


# --- serverless / missing-config cold start ----------------------------------
#
# The Vercel entrypoint (api/index.py) imports rif_runtime.api from a CWD that
# may not contain config/environments.yaml, with RIF_ENVIRONMENT set. Raising on
# an unknown environment name is right when the file exists and omits it; it is
# wrong when there is no file at all, because the fallback config invents its
# own name and the mismatch is an artefact rather than a misconfiguration.


def test_missing_environments_file_adopts_the_configured_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIF_CONFIG_DIR", str(tmp_path))  # no environments.yaml
    monkeypatch.setenv("RIF_ENVIRONMENT", "RIF_Runtime")
    reset_settings()
    from rif_runtime.config import load_config

    config = load_config()

    assert config.default_environment == "RIF_Runtime"
    assert "RIF_Runtime" in config.environments
    assert config.environments["RIF_Runtime"].networking_type == "limited", (
        "the fallback profile must stay restrictive"
    )


def test_runtime_starts_with_no_environments_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cold-start path: RIF_ENVIRONMENT set, config/ absent."""
    monkeypatch.setenv("RIF_CONFIG_DIR", str(tmp_path / "absent"))
    monkeypatch.setenv("RIF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RIF_ENVIRONMENT", "RIF_Runtime")
    reset_settings()
    from rif_runtime.runtime import RIFRuntime

    runtime = RIFRuntime()

    assert runtime.environment_name == "RIF_Runtime"
    assert runtime.profile.networking_type == "limited"


def test_unknown_environment_still_raises_when_the_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The safety property is unchanged where it actually applies."""
    (tmp_path / "environments.yaml").write_text(
        textwrap.dedent(
            """\
            default_environment: OnlyHere
            environments:
              OnlyHere:
                networking_type: open
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RIF_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("RIF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RIF_ENVIRONMENT", "NotInThatFile")
    reset_settings()
    from rif_runtime.runtime import RIFRuntime

    with pytest.raises(ValueError, match="NotInThatFile"):
        RIFRuntime()


def test_vercel_config_ships_the_environments_file() -> None:
    """includeFiles must carry config/, or the deployment runs on the fallback."""
    import json

    vercel = json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8"))
    included = vercel["builds"][0].get("config", {}).get("includeFiles", [])

    assert any(entry.startswith("config/") for entry in included), (
        "vercel.json does not include config/, so environments.yaml is absent "
        "at runtime and the deployment silently uses the fallback profile"
    )
    # And the name it sets must be one that environments.yaml actually defines.
    import yaml

    environments = yaml.safe_load(
        (REPO_ROOT / "config" / "environments.yaml").read_text(encoding="utf-8")
    )["environments"]
    assert vercel["env"]["RIF_ENVIRONMENT"] in environments


def test_a_blank_environment_is_treated_as_unset(monkeypatch):
    """RIF_ENVIRONMENT= must not be read as an environment named "".

    load_config's fallback took a blank value as unset (`or "production"`)
    while RIFRuntime._configured_environment tested `is None` and so treated it
    as a configured name. With no environments.yaml on disk the fallback
    invented "production" and the runtime then refused to start against the
    empty string, so a container spec with a blank RIF_ENVIRONMENT crashed on
    cold start.
    """
    for blank in ("", "   "):
        monkeypatch.setenv("RIF_ENVIRONMENT", blank)
        reset_settings()
        assert get_settings().runtime.environment is None

    monkeypatch.setenv("RIF_ENVIRONMENT", "  RIF_Runtime  ")
    reset_settings()
    assert get_settings().runtime.environment == "RIF_Runtime"


def test_a_blank_environment_still_starts_the_runtime(tmp_path, monkeypatch):
    """The end-to-end shape of the same defect: cold start with no config dir."""
    from rif_runtime.runtime import RIFRuntime

    monkeypatch.setenv("RIF_ENVIRONMENT", "")
    monkeypatch.setenv("RIF_CONFIG_DIR", str(tmp_path / "absent"))
    reset_settings()

    runtime = RIFRuntime(data_dir=tmp_path / "data")
    assert runtime.environment_name in runtime.config.environments
