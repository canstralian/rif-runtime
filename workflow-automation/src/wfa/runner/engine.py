"""The enforcement chokepoint (spec §8.1, §8.4 Run phase).

Every step dispatch passes through ``RunEngine._run_step``. Nothing calls a step's
``execute`` without first passing, in order:

    resolve (protected ref, HB-3)
      -> profile mismatch check (§1.5)
      -> permission intersection (profile ∩ definition, §3.4)
      -> per step:
           taint consistency check
        -> permission present in profile (HB-9)
        -> SINK permitted only under TRUSTED (§2.1)
        -> credential availability (HB-4; zero for UNTRUSTED)
        -> escalation approval (§4.9; timeout/absent => abort)
        -> template substitution (value-only, §2.6)
        -> sink encoding of content fields (§4.4)
        -> input schema validation
        -> execute
        -> output schema validation (§3.2)
        -> redact + checkpoint + audit

The profile OUTRANKS the workflow definition (§3.4): a SINK/escalated step in a
workflow running under UNTRUSTED does not execute regardless of the definition.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from wfa.classifier.idempotency import IdempotencyStore, run_id as compute_run_id
from wfa.runner.chain import ChainGuard
from wfa.runner.checkpoint import CheckpointStore
from wfa.runner.escalation import (
    ApprovalError,
    ApprovalToken,
    EscalationBroker,
    resolved_action_hash,
)
from wfa.runner.permissions import credential_scope, intersect_permissions
from wfa.runner.resolve import PROTECTED, WorkflowResolver
from wfa.security.audit import AuditLog
from wfa.security.credentials import CredentialBroker
from wfa.security.encode import encode_for_sink
from wfa.security.normalize import normalize_text, normalize_tree
from wfa.security.redactor import Redactor
from wfa.shared.enums import Profile, RunOutcome, StepOutcome, Taint, profile_satisfies
from wfa.shared.errors import HardBlock
from wfa.shared.models import (
    EngineConfig,
    Event,
    RunContext,
    RunRecord,
    StepContext,
    StepDefinition,
    WorkflowDefinition,
)
from wfa.shared.rules import (
    AUDIT_UNAVAILABLE,
    ESCALATION_REQUIRED,
    PROFILE_MISMATCH,
    SINK_NOT_PERMITTED,
    TAINT_MISMATCH,
    HardBlockRule,
)
from wfa.steps.base import Step, StepRegistry, coerce_output


class _Abort(Exception):
    """Internal control-flow: abort the run with a (rule_id, outcome)."""

    def __init__(self, rule_id: str, outcome: RunOutcome = RunOutcome.ABORTED) -> None:
        # Normalise a HardBlockRule enum to its canonical value ("HB-9"), never the
        # enum's ``ClassName.MEMBER`` repr, so run records serialise cleanly.
        self.rule_id = str(getattr(rule_id, "value", rule_id))
        self.outcome = outcome
        super().__init__(self.rule_id)


@dataclass
class _RunState:
    ctx: RunContext
    record: RunRecord
    context: dict[str, Any]  # template context: {"event": ..., "steps": ...}
    credentials: Any


class RunEngine:
    def __init__(
        self,
        config: EngineConfig,
        resolver: WorkflowResolver,
        registry: StepRegistry,
        credential_broker: CredentialBroker,
        audit: AuditLog,
        escalation: EscalationBroker,
        *,
        idempotency: IdempotencyStore | None = None,
        checkpoints: CheckpointStore | None = None,
        clock: Callable[[], float] = time.time,
        audit_available: bool = True,
    ) -> None:
        self._config = config
        self._resolver = resolver
        self._registry = registry
        self._creds = credential_broker
        self._audit = audit
        self._escalation = escalation
        self._idem = idempotency or IdempotencyStore()
        self._checkpoints = checkpoints or CheckpointStore()
        self._clock = clock
        self.audit_available = audit_available

    @property
    def audit_log(self) -> AuditLog:
        return self._audit

    @property
    def escalation_broker(self) -> EscalationBroker:
        return self._escalation

    @property
    def credential_broker(self) -> CredentialBroker:
        return self._creds

    @property
    def checkpoints(self) -> CheckpointStore:
        return self._checkpoints

    # ------------------------------------------------------------------ dispatch
    def select_workflows(self, event: Event) -> list[str]:
        """Return ids of registered workflows whose triggers match the event."""

        return [
            wf.id
            for wf in self._resolver.registry.all()
            if wf.triggers_on(event.kind, event.action)
        ]

    def dispatch(
        self,
        event: Event,
        profile: Profile,
        classification_basis: str,
        *,
        chain_depth: int = 0,
        root_delivery_id: str | None = None,
        approvals: dict[str, ApprovalToken] | None = None,
    ) -> list[RunRecord]:
        return [
            self.run_workflow(
                event,
                wf_id,
                profile,
                classification_basis,
                chain_depth=chain_depth,
                root_delivery_id=root_delivery_id,
                approvals=approvals,
            )
            for wf_id in self.select_workflows(event)
        ]

    # --------------------------------------------------------------- run a workflow
    def run_workflow(
        self,
        event: Event,
        workflow_id: str,
        profile: Profile,
        classification_basis: str,
        *,
        chain_depth: int = 0,
        root_delivery_id: str | None = None,
        approvals: dict[str, ApprovalToken] | None = None,
    ) -> RunRecord:
        approvals = approvals or {}
        # Resolve definition from the protected ref ONLY (HB-3). The engine never uses
        # the event's head ref — a PR that edits .workflows/ cannot change its own run.
        wf = self._resolver.resolve(workflow_id, PROTECTED)

        rid = compute_run_id(event.delivery_id, wf.id, wf.version)
        existing = self._idem.existing(rid)
        if existing is not None:
            # Redelivery of an identical delivery_id => exactly one run (spec §5.3).
            return existing

        root = root_delivery_id or event.delivery_id
        record = RunRecord(
            run_id=rid,
            delivery_id=event.delivery_id,
            root_delivery_id=root,
            chain_depth=chain_depth,
            workflow_id=wf.id,
            workflow_version=wf.version,
            profile=profile,
            classification_basis=classification_basis,
            outcome=RunOutcome.SUCCEEDED,
        )

        try:
            self._enforce_preconditions(wf, profile, chain_depth)
            state = self._build_state(
                event, wf, profile, classification_basis, chain_depth, root, record
            )
            self._run_steps(wf, state, approvals)
        except _Abort as ab:
            record.outcome = ab.outcome
            record.rule_id = ab.rule_id
        except HardBlock as hb:
            record.outcome = RunOutcome.DEAD_LETTERED
            record.rule_id = hb.rule_id

        self._audit_run_terminal(record)
        self._idem.put(record)
        return record

    # ----------------------------------------------------------------- internals
    def _enforce_preconditions(
        self, wf: WorkflowDefinition, profile: Profile, chain_depth: int
    ) -> None:
        # Chain depth (HB-7).
        guard = ChainGuard(self._config.max_chain_depth, self._config.engine_actor)
        guard.check_depth(chain_depth)
        # Profile mismatch (§1.5): a workflow needing a stronger profile does not run.
        if not profile_satisfies(profile, wf.profile_required):
            raise _Abort(PROFILE_MISMATCH, RunOutcome.FAILED)
        # Step count ceiling (§2.5).
        if len(wf.steps) > self._config.max_steps_per_run:
            raise _Abort("MAX_STEPS", RunOutcome.ABORTED)

    def _build_state(
        self,
        event: Event,
        wf: WorkflowDefinition,
        profile: Profile,
        basis: str,
        chain_depth: int,
        root: str,
        record: RunRecord,
    ) -> _RunState:
        eff_perms = intersect_permissions(
            profile, wf.permissions, self._config.untrusted_read_permissions
        )
        scope = credential_scope(profile, wf.credentials)
        ctx = RunContext(
            run_id=record.run_id,
            delivery_id=event.delivery_id,
            root_delivery_id=root,
            chain_depth=chain_depth,
            profile=profile,
            classification_basis=basis,
            workflow_id=wf.id,
            workflow_version=wf.version,
            effective_permissions=eff_perms,
            credential_scope=scope,
        )
        creds = self._creds.resolver_for(wf.id, profile, scope)
        # Template context. Everything under "event" is T4; "steps" fills as we go.
        # T4 strings are normalised (NFC + control/bidi strip) before any step can
        # interpolate them, closing the instruction-smuggling vector (spec §4.4, E).
        event_ctx: dict[str, Any] = {
            "delivery_id": event.delivery_id,
            "repo": normalize_text(event.repo),
            "actor": normalize_text(event.actor),
            "head_ref": normalize_text(event.head_ref),
            "base_ref": normalize_text(event.base_ref),
            "kind": event.kind,
            "action": event.action,
        }
        event_ctx.update(normalize_tree(event.payload))
        return _RunState(
            ctx=ctx, record=record, context={"event": event_ctx, "steps": {}}, credentials=creds
        )

    def _run_steps(
        self, wf: WorkflowDefinition, state: _RunState, approvals: dict[str, ApprovalToken]
    ) -> None:
        for step_def in wf.steps:
            self._run_step(wf, step_def, state, approvals)

    def _run_step(
        self,
        wf: WorkflowDefinition,
        step_def: StepDefinition,
        state: _RunState,
        approvals: dict[str, ApprovalToken],
    ) -> None:
        step = self._registry.get(step_def.uses)
        if step is None:  # pragma: no cover - registration validates `uses` up front
            raise _Abort("UNKNOWN_STEP", RunOutcome.FAILED)

        # 1. Declared taint must match the step type's intrinsic taint.
        if step_def.taint != step.taint:
            self._record_block(state, step_def, TAINT_MISMATCH)
            raise _Abort(TAINT_MISMATCH)

        # 2. Permission present in the run's profile (HB-9).
        if step_def.permission not in state.ctx.effective_permissions:
            self._record_block(state, step_def, HardBlockRule.HB_9)
            raise _Abort(HardBlockRule.HB_9)

        # 3. Template substitution (value-only) + sink encoding of content fields.
        # Done before the profile/escalation gates so the escalation action hash binds
        # the *resolved* action (spec §4.9). Substitution has no side effects.
        from wfa.template.substitute import TemplateError, resolve_args

        try:
            raw_args = resolve_args(step_def.with_, state.context)
        except TemplateError:
            self._record_block(state, step_def, "TEMPLATE_UNRESOLVED", StepOutcome.FAILED)
            raise _Abort("TEMPLATE_UNRESOLVED", RunOutcome.FAILED) from None

        if step.sink is not None:
            for field in step.content_fields:
                if field in raw_args and isinstance(raw_args[field], str):
                    raw_args[field] = encode_for_sink(step.sink, raw_args[field], state.ctx.profile)

        try:
            args = step.input_model.model_validate(raw_args)
        except Exception:
            self._record_block(state, step_def, "INPUT_SCHEMA", StepOutcome.FAILED)
            raise _Abort("INPUT_SCHEMA", RunOutcome.FAILED) from None

        # 4. Escalation gate (§4.9). Under TRUSTED, escalated steps run per policy.
        # Under any other condition they suspend and require a valid, single-use,
        # action-bound T3 approval token — which authorises *this* escalated step to
        # bypass the profile-based SINK block below. Absent/expired/drifted => abort.
        escalation_authorised = False
        if step_def.escalates:
            if state.ctx.profile is Profile.TRUSTED:
                escalation_authorised = True
            else:
                self._require_approval(state, step, step_def, args, approvals)
                escalation_authorised = True

        # 5. SINK steps run only under TRUSTED (§2.1), unless an escalated step carries
        # a valid T3 approval (an operator explicitly authorising the action).
        if (
            step.taint is Taint.SINK
            and state.ctx.profile is not Profile.TRUSTED
            and not escalation_authorised
        ):
            self._record_block(state, step_def, SINK_NOT_PERMITTED)
            raise _Abort(SINK_NOT_PERMITTED)

        # 6. Audit availability gate for SINK/escalated (spec §5.1). Unauditable
        # action is not permitted; read-only steps continue.
        if (step.taint is Taint.SINK or step_def.escalates) and not self.audit_available:
            self._record_block(state, step_def, AUDIT_UNAVAILABLE)
            raise _Abort(AUDIT_UNAVAILABLE)

        # 7. Credential availability (HB-4). UNTRUSTED => zero credentials, ALWAYS —
        # even a T3-approved escalated step gets no credential under a non-TRUSTED run.
        if step.requires_credentials:
            if state.ctx.profile is not Profile.TRUSTED:
                self._record_block(state, step_def, HardBlockRule.HB_4)
                raise _Abort(HardBlockRule.HB_4)
            if not self._creds.reachable:
                # Credential store degraded: credentialed steps refuse (spec §5.1).
                self._record_block(state, step_def, HardBlockRule.HB_4)
                raise _Abort(HardBlockRule.HB_4)

        # 8. Execute (SINK steps bracketed by intent/completion for INDETERMINATE).
        step_ctx = StepContext(
            run_id=state.ctx.run_id,
            step_id=step_def.id,
            profile=state.ctx.profile,
            chain_depth=state.ctx.chain_depth,
            permission=step_def.permission,
            taint=step.taint,
            credentials=state.credentials,
        )
        if step.taint is Taint.SINK:
            self._checkpoints.write_intent(state.ctx.run_id, step_def.id)
        try:
            result = step.execute(args, step_ctx)
        except HardBlock:
            raise
        except Exception:
            self._record_block(state, step_def, "STEP_ERROR", StepOutcome.FAILED)
            raise _Abort("STEP_ERROR", RunOutcome.FAILED) from None
        if step.taint is Taint.SINK:
            self._checkpoints.write_completion(state.ctx.run_id, step_def.id)

        # 10. Output schema validation (§3.2) — closed model, no partial propagation.
        output = coerce_output(step.output_model, result.output)

        # 11. Redact + checkpoint + record + audit.
        redactor = Redactor()
        scrubbed = redactor.scrub(output.model_dump())
        state.context["steps"][step_def.id] = {"output": scrubbed}
        self._checkpoints.record_output(state.ctx.run_id, step_def.id, scrubbed)
        state.record.step_outcomes[step_def.id] = StepOutcome.SUCCEEDED.value
        state.record.step_outputs[step_def.id] = scrubbed
        if result.non_deterministic:
            state.record.non_deterministic = True
        self._audit_step(state, step_def, step, redactor.redactions_applied, StepOutcome.SUCCEEDED)

    def _require_approval(
        self,
        state: _RunState,
        step: Step,
        step_def: StepDefinition,
        args: Any,
        approvals: dict[str, ApprovalToken],
    ) -> None:
        token = approvals.get(step_def.id)
        action_hash = self._action_hash(step, args)
        if token is None:
            # No approval => suspended; with no human at execution time this resolves
            # to abort (timeout defaults to deny, never proceed — spec §4.9).
            self._record_block(state, step_def, ESCALATION_REQUIRED)
            raise _Abort(ESCALATION_REQUIRED)
        try:
            self._escalation.verify_and_consume(
                token, state.ctx.run_id, step_def.id, action_hash, self._clock()
            )
        except ApprovalError:
            self._record_block(state, step_def, ESCALATION_REQUIRED)
            raise _Abort(ESCALATION_REQUIRED) from None

    @staticmethod
    def _action_hash(step: Step, args: Any) -> str:
        describe = getattr(step, "describe_action", None)
        if callable(describe):
            return resolved_action_hash(describe(args))
        return resolved_action_hash(json.dumps(args.model_dump(), sort_keys=True, default=str))

    # ------------------------------------------------------------------- auditing
    def _base_audit(self, state: _RunState) -> dict[str, Any]:
        return {
            "timestamp": self._clock(),
            "run_id": state.ctx.run_id,
            "root_delivery_id": state.ctx.root_delivery_id,
            "chain_depth": state.ctx.chain_depth,
            "workflow_id": state.ctx.workflow_id,
            "workflow_version": state.ctx.workflow_version,
            "provenance_profile": state.ctx.profile.value,
            "classification_basis": state.ctx.classification_basis,
        }

    def _audit_step(
        self,
        state: _RunState,
        step_def: StepDefinition,
        step: Step,
        redactions: int,
        outcome: StepOutcome,
    ) -> None:
        entry = self._base_audit(state)
        entry.update(
            {
                "step_id": step_def.id,
                "taint": step.taint.value,
                "permission_used": step_def.permission,
                "credential_ref": list(step.requires_credentials),
                "egress_host": None,
                "outcome": outcome.value,
                "rule_id_if_blocked": None,
                "redactions_applied": redactions,
            }
        )
        self._safe_audit(entry)

    def _record_block(
        self,
        state: _RunState,
        step_def: StepDefinition,
        rule_id: Any,
        outcome: StepOutcome = StepOutcome.BLOCKED,
    ) -> None:
        rid = rule_id.value if hasattr(rule_id, "value") else str(rule_id)
        state.record.step_outcomes[step_def.id] = outcome.value
        entry = self._base_audit(state)
        entry.update(
            {
                "step_id": step_def.id,
                "taint": step_def.taint.value,
                "permission_used": step_def.permission,
                "credential_ref": [],
                "egress_host": None,
                "outcome": outcome.value,
                "rule_id_if_blocked": rid,
                "redactions_applied": 0,
            }
        )
        self._safe_audit(entry)

    def _audit_run_terminal(self, record: RunRecord) -> None:
        entry = {
            "timestamp": self._clock(),
            "run_id": record.run_id,
            "root_delivery_id": record.root_delivery_id,
            "chain_depth": record.chain_depth,
            "workflow_id": record.workflow_id,
            "workflow_version": record.workflow_version,
            "provenance_profile": record.profile.value,
            "classification_basis": record.classification_basis,
            "step_id": None,
            "outcome": record.outcome.value,
            "rule_id_if_blocked": record.rule_id,
            "redactions_applied": 0,
        }
        self._safe_audit(entry)

    def _safe_audit(self, entry: dict[str, Any]) -> None:
        # Even if audit is "unavailable" for SINK gating purposes, we still attempt to
        # persist governance records; failure to persist is swallowed so it cannot
        # crash a run, but SINK/escalated steps were already refused upstream.
        try:
            self._audit.append(entry)
        except Exception:  # pragma: no cover - defensive
            pass
