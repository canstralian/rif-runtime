"""Shared test fixtures and fakes.

The fakes stand in for the platform API and downstream service clients so the whole
engine runs end-to-end in-process with no external services — matching the RIF-fleet
"no database, no external services" philosophy.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from wfa.classifier.provenance import Classifier
from wfa.runner.escalation import EscalationBroker
from wfa.runner.engine import RunEngine
from wfa.runner.resolve import SignedRegistry, WorkflowResolver
from wfa.security.audit import AuditLog
from wfa.security.credentials import CredentialBroker
from wfa.shared.models import EngineConfig, Event, ProvenanceFacts
from wfa.steps.registry import default_registry

SIGNING_KEY = b"registry-signing-key"
MASTER_SECRET = b"engine-master-secret"
ESCALATION_KEY = b"escalation-key"


class FakePlatform:
    """A controllable PlatformClient returning authenticated facts, not payload data."""

    def __init__(self, facts: ProvenanceFacts) -> None:
        self.facts = facts
        self.raise_error = False

    def facts_for(self, event: Event) -> ProvenanceFacts:
        if self.raise_error:
            raise RuntimeError("platform unreachable")
        return self.facts


class FakeGithub:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_comment(self, token: str, repo: str, issue_number: int, body: str) -> str:
        self.calls.append(
            {"token": token, "repo": repo, "issue_number": issue_number, "body": body}
        )
        return f"comment-{len(self.calls)}"

    def merge_pr(self, token: str, repo: str, pr_number: int) -> str:
        self.calls.append({"token": token, "repo": repo, "pr_number": pr_number, "merge": True})
        return f"sha-{len(self.calls)}"


class FakeSlack:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post_message(self, token: str, channel: str, text: str) -> str:
        self.calls.append({"token": token, "channel": channel, "text": text})
        return f"ts-{len(self.calls)}"


def sign_registry(raw_yaml: bytes) -> str:
    return hmac.new(SIGNING_KEY, raw_yaml, hashlib.sha256).hexdigest()


@pytest.fixture
def fake_github() -> FakeGithub:
    return FakeGithub()


@pytest.fixture
def fake_slack() -> FakeSlack:
    return FakeSlack()


@pytest.fixture
def registry_steps(fake_github: FakeGithub, fake_slack: FakeSlack):
    return default_registry(github=fake_github, merge=fake_github, slack=fake_slack, llm_model=None)


@pytest.fixture
def engine_config() -> EngineConfig:
    return EngineConfig(
        egress_allow_list=["api.github.com", "slack.com"],
        untrusted_read_permissions=["contents:read"],
        engine_actor="wfa-engine[bot]",
    )


def build_signed_registry(raw_yaml: bytes, step_types: set[str]) -> SignedRegistry:
    reg = SignedRegistry(SIGNING_KEY, declared_step_types=step_types)
    reg.load_signed(raw_yaml, sign_registry(raw_yaml))
    return reg


@pytest.fixture
def make_engine(engine_config, registry_steps, tmp_path: Path):
    """Factory: given workflow YAML text, build a fully wired RunEngine."""

    def _factory(
        workflow_yaml: str,
        *,
        audit_available: bool = True,
        registry=None,
        broker: CredentialBroker | None = None,
        config: EngineConfig | None = None,
    ) -> RunEngine:
        cfg = config if config is not None else engine_config
        steps = registry if registry is not None else registry_steps
        raw = workflow_yaml.encode("utf-8")
        signed = build_signed_registry(raw, steps.types())
        resolver = WorkflowResolver(signed)
        creds = broker if broker is not None else CredentialBroker(MASTER_SECRET)
        for wf in signed.all():
            for cred in wf.credentials:
                creds.register(wf.id, cred, "ghp_" + "b" * 36)
        audit = AuditLog(tmp_path / "audit.jsonl")
        escalation = EscalationBroker(ESCALATION_KEY, ttl_s=cfg.approval_ttl_s)
        return RunEngine(
            cfg,
            resolver,
            steps,
            creds,
            audit,
            escalation,
            audit_available=audit_available,
        )

    return _factory


@pytest.fixture
def trusted_facts() -> ProvenanceFacts:
    return ProvenanceFacts(
        installation_verified=True, actor_has_write=True, is_fork_pr=False, ref_protected=True
    )


@pytest.fixture
def fork_facts() -> ProvenanceFacts:
    return ProvenanceFacts(
        installation_verified=True, actor_has_write=False, is_fork_pr=True, ref_protected=False
    )


def make_event(**overrides) -> Event:
    base = dict(
        delivery_id="d-1",
        source="install-1",
        kind="pull_request",
        action="opened",
        received_at=1000.0,
        delivered_at=1000.0,
        repo="octo/repo",
        actor="octocat",
        head_ref="feature",
        base_ref="main",
        payload={"pr": {"number": 7, "title": "Add feature", "diff": "line one\nline two"}},
    )
    base.update(overrides)
    return Event(**base)


@pytest.fixture
def classifier_trusted(trusted_facts) -> Classifier:
    return Classifier(FakePlatform(trusted_facts))


@pytest.fixture
def classifier_fork(fork_facts) -> Classifier:
    return Classifier(FakePlatform(fork_facts))
