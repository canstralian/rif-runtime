"""Agent package: the template, its worked examples, and the manifest binding.

Every module here sat at 0% coverage. `agents/manifest.py` in particular is the
Python side of a checked-in contract (`.rif/agents/manifest.schema.yaml`) with
nothing asserting the two agree, and `DeputyAgent.review` branches on a
StrEnum by string comparison without a test proving that works.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml

from rif_runtime.agents.deputy import DeputyAgent
from rif_runtime.agents.manifest import AgentManifest
from rif_runtime.agents.orchestrator import OrchestratorAgent
from rif_runtime.schemas import Decision, PolicyDecision, Posture

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / ".rif" / "agents" / "manifest.schema.yaml"
)


def _decision(decision: Decision) -> PolicyDecision:
    return PolicyDecision(
        decision=decision,
        actor="agent:test",
        action="http.request",
        target="https://example.com",
        environment="RIF_Runtime",
        posture=Posture.normal,
        reason="test",
        matched_rule="policy.test",
    )


# --- manifest contract -------------------------------------------------------


def test_agent_manifest_matches_the_declared_schema():
    """AgentManifest is the binding for .rif/agents/manifest.schema.yaml.

    Without this the dataclass and the schema can drift silently, which is
    exactly the "two individually plausible implementations that disagree at
    the seam" that spec/README.md exists to prevent.
    """
    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    fields = {f.name for f in dataclasses.fields(AgentManifest)}

    assert fields == set(schema["properties"]), (
        "AgentManifest fields and manifest.schema.yaml properties have diverged"
    )
    assert set(schema["required"]) <= fields


def test_agent_manifest_is_immutable():
    manifest = AgentManifest(
        name="agent:example",
        kind="claude-skill",
        description="",
        owns=(),
        responsibilities=(),
        inputs=(),
        outputs=(),
        depends_on=(),
        blocks=(),
        quality_gates=(),
        invariants=(),
    )

    try:
        manifest.name = "agent:mutated"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("AgentManifest should be frozen")


# --- deputy ------------------------------------------------------------------


def test_deputy_flags_a_denial():
    """Branches on a StrEnum via string comparison; this pins that it works."""
    review = DeputyAgent().review(_decision(Decision.deny))

    assert review["agent"] == "agent:deputy"
    assert review["finding"] == "policy denial observed"
    assert review["rule"] == "policy.test"


def test_deputy_passes_an_allow_through():
    review = DeputyAgent().review(_decision(Decision.allow))

    assert review["finding"] == "request allowed"


def test_deputy_treats_review_as_not_a_denial():
    """Decision has three members; `review` must not be read as a denial."""
    review = DeputyAgent().review(_decision(Decision.review))

    assert review["finding"] == "request allowed"


# --- orchestrator ------------------------------------------------------------


def test_orchestrator_builds_a_governed_request():
    request = OrchestratorAgent().request_http("https://example.com", reason="why")

    assert request.actor == "agent:orchestrator"
    assert request.action == "http.request"
    assert request.target == "https://example.com"
    assert request.reason == "why"


def test_orchestrator_actor_follows_the_template_convention():
    """template.py points at OrchestratorAgent as the naming example."""
    from rif_runtime.agents.template import TemplateAgent

    assert TemplateAgent(OrchestratorAgent.name).validate() is True


# --- execution lifecycle seam ------------------------------------------------


def test_execution_state_overlaps_run_status_as_the_spec_review_notes():
    """Pins the overlap the identity-spine review is holding open.

    ExecutionState is seeded but unwired. If someone converges it with
    RunStatus without going through that review, this test's premise changes
    and the reconciliation gets noticed rather than landing silently.
    """
    from rif_runtime.execution.state import ExecutionState
    from rif_runtime.runs.schemas import RunStatus

    shared = {member.value for member in ExecutionState} & {
        member.value for member in RunStatus
    }

    assert shared == {"created", "policy_approved", "denied", "failed"}


def test_execution_state_is_not_used_by_the_runtime():
    """Seeded means seeded: nothing should be reading it yet."""
    import ast

    root = Path(__file__).resolve().parent.parent / "src" / "rif_runtime"

    def imports_execution_state(node: ast.AST, module_name: str) -> bool:
        """Every spelling of the import, absolute and relative.

        `ast` puts the leading dots of a relative import in `node.level`, not in
        `node.module` -- so `from .state import X` is module="state", level=1,
        and matching on the literal ".state" never fires. The first version of
        this guard did exactly that and could not detect any relative form.

        Matching on the *spelling* is not enough either: `from .. import state`
        reads like this module but resolves to `rif_runtime.state`, a different
        module that does not exist. Relative imports are therefore resolved
        against the importing module's own package, and only an import that
        resolves to `rif_runtime.execution.state` counts.
        """
        target = "rif_runtime.execution.state"
        if isinstance(node, ast.Import):
            return any(alias.name == target for alias in node.names)
        if not isinstance(node, ast.ImportFrom):
            return False

        if node.level:
            package = module_name.rsplit(".", 1)[0] if "." in module_name else ""
            # One dot means the importer's own package; each extra dot climbs.
            parts = package.split(".") if package else []
            climb = node.level - 1
            if climb > len(parts):
                return False
            base = ".".join(parts[: len(parts) - climb] if climb else parts)
            resolved = f"{base}.{node.module}" if node.module else base
        else:
            resolved = node.module or ""

        # `from ...execution import state` / `from ...execution.state import X`
        return resolved == target or (
            resolved == target.rsplit(".", 1)[0]
            and any(alias.name == "state" for alias in node.names)
        )

    importers = []
    for path in root.rglob("*.py"):
        if path.name == "state.py" and path.parent.name == "execution":
            continue
        relative = path.relative_to(root).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        module_name = ".".join(("rif_runtime", *parts))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if imports_execution_state(node, module_name):
                importers.append(str(path.relative_to(root)))

    assert not importers, (
        f"ExecutionState is now imported by {importers}. Wiring it is Track B "
        "work held by docs/spec-review-identity-spine-migration.md -- update "
        "that review's status before landing this."
    )
