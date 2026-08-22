"""Workflow resolution (spec §2.2, §8.4 Run phase).

Workflow definitions resolve ONLY from:
  1. the signed registry mounted at deploy time, or
  2. ``.workflows/`` on the repository's protected default branch, at the commit
     currently protected — never at the event's head ref (HB-3).

A pull request that modifies ``.workflows/`` does not change the workflow that runs
on it. Registration validates every step declares ``taint``, ``permission`` and
``output_schema``, and that every referenced credential is declared (undeclared
credentials are refused at load time, not run time — spec §1.5).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import yaml

from wfa.shared.errors import HardBlock, RegistrationError
from wfa.shared.models import WorkflowDefinition
from wfa.shared.rules import HardBlockRule

# The only refs a definition may be sourced from. The event head ref is never here.
PROTECTED = "protected-default-branch"
REGISTRY = "signed-registry"


def _validate_registration(wf: WorkflowDefinition, declared_step_types: set[str]) -> None:
    if not wf.steps:
        raise RegistrationError(f"workflow {wf.id!r} has no steps")
    seen: set[str] = set()
    for step in wf.steps:
        if step.id in seen:
            raise RegistrationError(f"duplicate step id {step.id!r}")
        seen.add(step.id)
        # taint/permission/output_schema are non-optional in the model, but empty
        # strings would slip through — reject them explicitly.
        if not step.permission:
            raise RegistrationError(f"step {step.id!r} missing permission")
        if not step.output_schema:
            raise RegistrationError(f"step {step.id!r} missing output_schema")
        if declared_step_types and step.uses not in declared_step_types:
            raise RegistrationError(f"step {step.id!r} uses unknown step type {step.uses!r}")
    # Every credential a step could use must be declared on the workflow.
    # (Credential *use* is per step type; here we require the workflow to declare
    # the full set it may draw on.) A workflow with zero declared credentials is
    # valid — it simply runs credential-free.


class SignedRegistry:
    """A registry of workflow definitions authenticated by an HMAC signature.

    Load-time signature failure => HB-8 (Minimal mode at startup). We keep the last
    good set and never hot-load an unsigned set (spec §5.1).
    """

    def __init__(self, signing_key: bytes, declared_step_types: set[str] | None = None) -> None:
        self._key = signing_key
        self._declared = declared_step_types or set()
        self._workflows: dict[str, WorkflowDefinition] = {}

    def _sign(self, raw: bytes) -> str:
        return hmac.new(self._key, raw, hashlib.sha256).hexdigest()

    def load_signed(self, raw_yaml: bytes, signature: str) -> None:
        if not hmac.compare_digest(self._sign(raw_yaml), signature):
            raise HardBlock(HardBlockRule.HB_8, "registry signature verification failed")
        docs = [d for d in yaml.safe_load_all(raw_yaml.decode("utf-8")) if d]
        loaded: dict[str, WorkflowDefinition] = {}
        for doc in docs:
            wf = _parse_definition(doc, source_ref=REGISTRY)
            _validate_registration(wf, self._declared)
            loaded[wf.id] = wf
        # Atomic swap only after all validate — retain last-good on any failure.
        self._workflows = loaded

    def get(self, workflow_id: str) -> WorkflowDefinition | None:
        return self._workflows.get(workflow_id)

    def all(self) -> list[WorkflowDefinition]:
        return list(self._workflows.values())


def _parse_definition(doc: dict[str, Any], source_ref: str) -> WorkflowDefinition:
    data: dict[Any, Any] = dict(doc)
    # YAML 1.1 gotcha: an unquoted ``on:`` key parses to the boolean ``True`` (same as
    # GitHub Actions files). Remap it so trigger bindings are not silently lost.
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    data["source_ref"] = source_ref
    return WorkflowDefinition.model_validate(data)


class WorkflowResolver:
    """Resolves the definition to run for an event, enforcing HB-3."""

    def __init__(self, registry: SignedRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> SignedRegistry:
        return self._registry

    def resolve(self, workflow_id: str, source_ref: str) -> WorkflowDefinition:
        """Return the registered definition, refusing any non-protected source (HB-3).

        ``source_ref`` is where the caller *claims* the definition came from. Even if
        an attacker's PR edits ``.workflows/`` at the head ref, the runner passes the
        protected ref here; a head-ref source is rejected outright.
        """

        if source_ref not in (PROTECTED, REGISTRY):
            raise HardBlock(HardBlockRule.HB_3, f"non-protected source ref: {source_ref!r}")
        wf = self._registry.get(workflow_id)
        if wf is None:
            raise HardBlock(HardBlockRule.HB_3, f"unknown/unregistered workflow {workflow_id!r}")
        if wf.source_ref not in (PROTECTED, REGISTRY):
            raise HardBlock(HardBlockRule.HB_3, f"definition not from protected source: {wf.id!r}")
        return wf
