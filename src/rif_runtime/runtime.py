import threading
from pathlib import Path
from typing import Any

from .capabilities.capability import Capability
from .capabilities.models import CapabilityRecord
from .capabilities.registry import CapabilityRegistry
from .config import get_settings, load_config
from .configuration.policies import PolicyStore
from .execution.kernel import ExecutionKernel
from .execution.manifest import ExecutionManifest
from .execution.result import ExecutionResult, ExecutionStatus
from .governance.posture import at_least_posture, escalate_posture
from .governance.reflexive import ReflexiveLoop
from .graph.memory import GovernanceGraph
from .mcp.metasploit import (
    CapabilityToken,
    GovernanceMode,
    GovernanceOutcome,
    MetasploitGovernor,
    MetasploitIntent,
)
from .policy import PolicyEngine
from .replay import ReplayEngine
from .schemas import EnvironmentProfile, PolicyDecision, PolicyRequest, Posture
from .storage.jsonl import HashChainedJsonlStore, JsonlStore


class RIFRuntime:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.config = load_config()
        self.environment_name = self._configured_environment()
        # One configured directory owns every piece of persistent state —
        # policies, decisions, posture history, evidence — so RIF_DATA_DIR
        # (equivalently [paths] data_dir in rif.toml) relocates all of them
        # together. Tests pass an explicit tmp_path instead.
        self.data_dir = Path(
            data_dir if data_dir is not None else get_settings().paths.data_dir
        )
        self.policy = PolicyEngine()
        self.policy_store = PolicyStore(self.data_dir / "policies.json")
        self.reflexive = ReflexiveLoop()
        self.governance_graph = GovernanceGraph()
        self.decisions_path = self.data_dir / "decisions.jsonl"
        # Hash-chained: the decision log is the audit trail, so a silently
        # edited row has to be detectable, not merely unlikely. Rows written
        # before chaining existed are reported as `unchained_leading` rather
        # than being counted as verified.
        self.decisions_store = HashChainedJsonlStore(self.decisions_path)
        self.posture_store = JsonlStore(self.data_dir / "posture_history.jsonl")
        self.metasploit = MetasploitGovernor()
        self.evidence_store = JsonlStore(self.data_dir / "metasploit_evidence.jsonl")
        self.capability_registry = CapabilityRegistry()
        self.execution_kernel = ExecutionKernel(self.capability_registry)
        self.capability_evidence_store = JsonlStore(
            self.data_dir / "capability_evidence.jsonl"
        )
        self._lock = threading.RLock()
        self.posture = self._restore_posture()

    def _restore_posture(self) -> Posture:
        """Derive the posture this process must start in.

        ``posture_history.jsonl`` is authoritative when it has rows: it records
        every transition, including an operator's explicit set or reset, so its
        last entry is the posture the runtime was left in. Falling back to
        replaying ``decisions.jsonl`` covers a first boot after decisions were
        recorded without any transition (no escalation yet, hence ``normal``
        unless the denial thresholds say otherwise).

        Without this a restart silently dropped a ``locked`` runtime back to
        ``normal``, re-opening everything ``PolicyEngine.evaluate()``'s
        ``posture.locked`` check had shut down.

        The configured posture (``RIF_POSTURE`` / ``[runtime] posture``) is
        then applied as a *floor*, not an assignment. It was previously parsed,
        validated, and never read, so ``RIF_POSTURE=locked`` started a runtime
        that allowed everything. A floor is the safe reading of that setting:
        an operator who configures ``locked`` cannot have it quietly lowered by
        a stale ``normal`` in the history, while a runtime that escalated to
        ``restricted`` at runtime does not get relaxed back down to a
        configured ``normal`` either.
        """
        return at_least_posture(self._restored_posture(), self._configured_posture())

    def _restored_posture(self) -> Posture:
        """Last persisted posture, or the one replay derives from decisions."""
        for row in reversed(self.posture_store.read_all()):
            try:
                return Posture(row["new_posture"])
            except (KeyError, ValueError):
                continue
        return ReplayEngine(self.decisions_path).recover_posture()

    def _configured_posture(self) -> Posture:
        """Posture floor declared by configuration."""
        return Posture(get_settings().runtime.posture)

    def _configured_environment(self) -> str:
        """Environment named by configuration, else the profile default.

        ``RIF_ENVIRONMENT`` / ``[runtime] environment`` was parsed and
        validated and then never read -- the runtime always took
        ``default_environment`` from environments.yaml, so selecting an
        environment by configuration silently did nothing.

        An unknown name raises rather than falling back: environments carry the
        egress constraints, so quietly serving a different profile than the one
        configured is the kind of silent downgrade this runtime exists to
        prevent. Only an unset value (``None``) falls back to the profile
        default -- an explicit name that happens to match no profile still
        raises, so it cannot be mistaken for "unconfigured".
        """
        configured = get_settings().runtime.environment
        if configured is None:
            return self.config.default_environment
        if configured in self.config.environments:
            return configured
        raise ValueError(
            f"configured environment {configured!r} is not defined in "
            f"environments.yaml (known: {sorted(self.config.environments)})"
        )

    @property
    def profile(self) -> EnvironmentProfile:
        return self.config.environments[self.environment_name]

    def set_posture(self, posture: Posture) -> Posture:
        """Set the posture explicitly, persisting the transition."""
        with self._lock:
            old_posture = self.posture
            self.posture = posture
            if old_posture != posture:
                self.posture_store.append(
                    {"old_posture": str(old_posture), "new_posture": str(posture)}
                )
            return self.posture

    def set_environment(self, name: str) -> None:
        if name not in self.config.environments:
            raise ValueError(f"unknown environment: {name}")
        self.environment_name = name

    def evaluate(self, req: PolicyRequest, record: bool = True) -> PolicyDecision:
        with self._lock:
            decision = self.policy.evaluate(
                req,
                self.environment_name,
                self.profile,
                self.posture,
                self.policy_store.list(),
            )
            if not record:
                return decision
            return self.record_decision(decision)

    def record_decision(self, decision: PolicyDecision) -> PolicyDecision:
        with self._lock:
            self.governance_graph.record_decision(decision)
            old_posture = self.posture
            self.posture = self.reflexive.observe(decision, self.posture)
            self.decisions_store.append(decision.model_dump())
            if old_posture != self.posture:
                self.posture_store.append(
                    {"old_posture": str(old_posture), "new_posture": str(self.posture)}
                )
            return decision

    def register_capability(
        self,
        capability: Capability,
        record: CapabilityRecord,
    ) -> None:
        """Register executable code together with its governance identity."""
        with self._lock:
            self.capability_registry.register(capability, record)

    def execute_capability(self, manifest: ExecutionManifest) -> ExecutionResult:
        """Execute only after policy authorization and capability admission."""
        with self._lock:
            policy_request = PolicyRequest(
                actor=manifest.actor,
                action=manifest.action,
                target=manifest.target or manifest.capability,
                context={
                    "capability": manifest.capability,
                    "manifest_id": manifest.manifest_id,
                    **manifest.metadata,
                },
            )
            decision = self.evaluate(policy_request)
            if decision.decision.value != "allow":
                self.capability_evidence_store.append(
                    {
                        "event": "execution_denied",
                        "manifest_id": manifest.manifest_id,
                        "capability": manifest.capability,
                        "policy_decision": decision.model_dump(mode="json"),
                    }
                )
                return ExecutionResult(
                    status=ExecutionStatus.DENIED,
                    message=f"policy denied: {decision.reason}",
                    metadata={"manifest_id": manifest.manifest_id},
                )

            record = self.capability_registry.admit(manifest.capability)
            result = self.execution_kernel.execute(manifest)
            self.capability_evidence_store.append(
                {
                    "event": "execution_completed",
                    "manifest_id": manifest.manifest_id,
                    "capability": manifest.capability,
                    "capability_status": record.lifecycle.status.value,
                    "policy_decision": decision.model_dump(mode="json"),
                    "result": {
                        "status": result.status.value,
                        "message": result.message,
                        "output": result.output,
                        "metadata": result.metadata,
                        "completed_at": result.completed_at.isoformat(),
                    },
                }
            )
            return result

    def evaluate_metasploit(
        self,
        intent: MetasploitIntent,
        mode: GovernanceMode = GovernanceMode.read_only_firewall,
        token: CapabilityToken | None = None,
        record: bool = True,
    ) -> GovernanceOutcome:
        with self._lock:
            outcome = self.metasploit.evaluate(
                intent,
                mode=mode,
                env_name=self.environment_name,
                posture=self.posture,
                token=token,
            )
            if not record:
                return outcome
            decision = outcome.decision
            self.governance_graph.record_decision(decision)
            old_posture = self.posture
            self.posture = self.reflexive.observe(decision, self.posture)
            if outcome.severe:
                self.posture = escalate_posture(self.posture)
            self.decisions_store.append(decision.model_dump())
            self.evidence_store.append(outcome.evidence.model_dump())
            if old_posture != self.posture:
                self.posture_store.append(
                    {"old_posture": str(old_posture), "new_posture": str(self.posture)}
                )
            return outcome

    def graph_summary(self) -> dict[str, Any]:
        return self.governance_graph.summary()

    def telemetry_summary(self) -> dict[str, Any]:
        return {
            "recent_denials_60m": self.reflexive.telemetry.denial_count(minutes=60),
            "event_count": len(self.reflexive.telemetry.events),
        }

    def persisted_summary(
        self, decisions: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        # One read feeds all three decision figures. Four separate reads of a
        # log being appended to concurrently can disagree, so the "summary"
        # would describe no single state of the file.
        rows = self.decisions_store.read_all() if decisions is None else decisions
        return {
            "decisions_total": self.decisions_store.count(rows),
            "posture_transitions_total": self.posture_store.count(),
            "decisions_by_result": self.decisions_store.count_by("decision", rows),
            "decisions_by_rule": self.decisions_store.count_by("matched_rule", rows),
        }

    def verify_decision_chain(
        self, decisions: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Recompute the decision log's hash chain.

        Reports integrity of what is on disk. It does not prove that the log
        records every decision the runtime made -- an attacker who can truncate
        the file can rewrite a shorter valid chain.
        """
        return self.decisions_store.verify(decisions).as_dict()

    def audit_summary(self) -> dict[str, Any]:
        # GET /v1/audit previously re-read and re-hashed decisions.jsonl five
        # times per call, on a route that is unauthenticated unless
        # RIF_REQUIRE_READ_AUTH is set. Read once, derive everything from it.
        decisions = self.decisions_store.read_all()
        return {
            "environment": self.environment_name,
            "posture": self.posture.value
            if hasattr(self.posture, "value")
            else self.posture,
            "live": {
                "graph": self.graph_summary(),
                "telemetry": self.telemetry_summary(),
            },
            "persisted": self.persisted_summary(decisions),
            "decision_chain": self.verify_decision_chain(decisions),
        }
