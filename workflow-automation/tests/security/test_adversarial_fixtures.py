"""Drive the engine with on-disk adversarial fixtures (spec §8.2, §10)."""

from __future__ import annotations

import json
from pathlib import Path

from wfa.classifier.provenance import Classifier
from wfa.shared.enums import Profile, RunOutcome
from wfa.shared.models import Event, ProvenanceFacts
from wfa.steps.base import StepRegistry

from tests.conftest import FakePlatform
from tests.security.steps_for_tests import ReadCredentialStep

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "adversarial"


def _load_event(name: str) -> Event:
    data = json.loads((FIXTURES / name).read_text())
    return Event(**data)


CRED_PROBE = """
version: "1"
id: cred-probe
on: {pull_request: [opened]}
profile_required: UNTRUSTED
permissions: [contents:read]
credentials: [github_token]
steps:
  - id: steal
    uses: test.read_credential
    taint: NEUTRAL
    permission: contents:read
    output_schema: x.json
    with: {}
"""


def test_fork_pr_fixture_classified_untrusted_despite_owner_claim():
    event = _load_event("fork_pr_injection.json")
    # Platform truth: a fork PR by a non-write actor, regardless of the payload's
    # self-asserted author_association: OWNER.
    facts = ProvenanceFacts(installation_verified=True, is_fork_pr=True, actor_has_write=False)
    profile, basis = Classifier(FakePlatform(facts)).classify(event)
    assert profile is Profile.UNTRUSTED and basis == "fork-pr"


def test_fork_pr_fixture_gets_zero_credentials(make_engine):
    reg = StepRegistry()
    reg.register(ReadCredentialStep())
    engine = make_engine(CRED_PROBE, registry=reg)
    event = _load_event("fork_pr_injection.json")
    rec = engine.run_workflow(event, "cred-probe", Profile.UNTRUSTED, "fork-pr")
    assert rec.outcome is RunOutcome.ABORTED and rec.rule_id == "HB-4"
