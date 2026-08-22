"""Pydantic models crossing engine boundaries or getting persisted.

The single most important modelling decision here is that the **event payload is
T4 in its entirety** (spec §1.2). ``Event.payload`` is an opaque, attacker-writable
blob; provenance is carried separately in ``ProvenanceFacts``, which is populated
*only* from authenticated platform metadata re-fetched by the classifier, never
from the payload body.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from wfa.shared.enums import Profile, RunOutcome, Taint


class Event(BaseModel):
    """A received, authenticated webhook delivery.

    Every attribute other than the transport envelope (``delivery_id``, ``source``,
    ``received_at``) is T4 data. In particular ``repo``, ``actor``, ``head_ref`` and
    the whole ``payload`` are attacker-writable on a fork PR and must never be used
    to derive authority.
    """

    model_config = ConfigDict(frozen=True)

    delivery_id: str
    source: str  # installation / source identifier, bound by HMAC secret
    kind: str  # e.g. "pull_request", "issue_comment", "push"
    action: str = ""  # e.g. "opened", "synchronize"
    received_at: float  # unix seconds, from the engine clock at ingress
    delivered_at: float  # unix seconds claimed in the signed delivery header
    # --- Everything below is T4 (data only) ---
    repo: str = ""
    actor: str = ""
    head_ref: str = ""
    base_ref: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ProvenanceFacts(BaseModel):
    """Authenticated platform facts used to classify an event (spec §2.1).

    These come from the platform API under the engine's own credential, never from
    the payload body. A payload claiming ``author_association: MEMBER`` is ignored;
    the truth is ``actor_has_write`` fetched here.
    """

    model_config = ConfigDict(frozen=True)

    installation_verified: bool = False
    actor_has_write: bool = False
    is_fork_pr: bool = False
    ref_protected: bool = False
    authenticated_internal: bool = False
    scheduled: bool = False


class StepDefinition(BaseModel):
    """One step within a workflow definition (spec §3.1).

    A step missing ``taint``, ``permission``, or ``output_schema`` fails
    registration (enforced in ``wfa.runner.resolve``).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    uses: str  # registered step type, e.g. "llm.summarise"
    taint: Taint
    permission: str
    output_schema: str
    escalates: bool = False
    idempotent: bool = False
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")


class Concurrency(BaseModel):
    model_config = ConfigDict(frozen=True)

    group: str = ""
    cancel_in_progress: bool = False


class WorkflowDefinition(BaseModel):
    """A declarative workflow, resolved only from a signed/protected source (spec §2.2)."""

    model_config = ConfigDict(frozen=True)

    version: str
    id: str
    on: dict[str, list[str]] = Field(default_factory=dict)
    profile_required: Profile
    permissions: list[str] = Field(default_factory=list)
    credentials: list[str] = Field(default_factory=list)
    concurrency: Concurrency = Field(default_factory=Concurrency)
    steps: list[StepDefinition] = Field(default_factory=list)
    # Provenance of the definition itself, set by the resolver. Absent => UNSPECIFIED.
    source_ref: str = "UNSPECIFIED"

    def triggers_on(self, kind: str, action: str) -> bool:
        actions = self.on.get(kind)
        if actions is None:
            return False
        return not action or not actions or action in actions


class EngineConfig(BaseModel):
    """T2 engine configuration (spec §2.5, §6.2). Signed ``engine.yaml``."""

    model_config = ConfigDict(frozen=True)

    max_chain_depth: int = 3
    max_steps_per_run: int = 50
    run_timeout_ms: int = 900_000
    step_timeout_ms: int = 120_000
    max_concurrent_runs: int = 20
    max_concurrent_runs_per_repo: int = 3
    max_payload_bytes: int = 5_242_880
    queue_depth_ceiling: int = 10_000
    replay_window_s: int = 24 * 3600
    timestamp_skew_s: int = 300
    approval_ttl_s: int = 600
    egress_allow_list: list[str] = Field(default_factory=list)
    # Permissions an UNTRUSTED run may hold (read-only APIs, spec §2.1).
    untrusted_read_permissions: list[str] = Field(default_factory=list)
    # Actor identity of the engine itself, for the self-actor loop filter (spec §4.7).
    engine_actor: str = "UNSPECIFIED"


class RunContext(BaseModel):
    """Explicit per-run authority context (spec §6.1).

    No ambient authority: absent context resolves to ``UNSPECIFIED`` and refuses.
    There is no code path from event content to permission assignment.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    delivery_id: str
    root_delivery_id: str
    chain_depth: int
    profile: Profile
    classification_basis: str
    workflow_id: str
    workflow_version: str
    effective_permissions: frozenset[str]
    credential_scope: frozenset[str]
    fencing_token: int = 0


class StepContext(BaseModel):
    """What a single step is handed at dispatch time (spec §8.3).

    A step reads credentials only through ``credentials`` (a resolver injected by the
    runner). Under UNTRUSTED that resolver is absent, so any credential read raises a
    hard-block (HB-4) — zero credentials, verifiable by inspection.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    run_id: str
    step_id: str
    profile: Profile
    chain_depth: int
    permission: str
    taint: Taint
    # Injected by the runner; ``None`` under UNTRUSTED (spec §4.5).
    credentials: Any = None


class RunRecord(BaseModel):
    """Terminal record of a run (spec §3.2)."""

    run_id: str
    delivery_id: str
    root_delivery_id: str
    chain_depth: int
    workflow_id: str
    workflow_version: str
    profile: Profile
    classification_basis: str
    outcome: RunOutcome
    rule_id: str | None = None
    non_deterministic: bool = False
    step_outcomes: dict[str, str] = Field(default_factory=dict)
    step_outputs: dict[str, Any] = Field(default_factory=dict)
