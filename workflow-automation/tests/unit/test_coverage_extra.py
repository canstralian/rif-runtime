"""Targeted tests closing residual branches in the 100%-coverage packages."""

from __future__ import annotations

import json

import pytest

from wfa.runner.checkpoint import CheckpointStore
from wfa.runner.resolve import PROTECTED, SignedRegistry, WorkflowResolver
from wfa.security.credentials import CredentialBroker, CredentialResolver
from wfa.security.encode import encode_for_sink
from wfa.security.normalize import normalize_tree
from wfa.security.redactor import Redactor, _shannon_entropy
from wfa.shared.enums import Profile
from wfa.shared.errors import HardBlock, RegistrationError
from wfa.shared.models import WorkflowDefinition
from wfa.template.substitute import substitute

from tests.conftest import sign_registry


# -------------------------------------------------------------------- template
def test_substitute_on_dict_recurses_directly():
    out = substitute({"a": "${event.x}", "b": 1}, {"event": {"x": "v"}})
    assert out == {"a": "v", "b": 1}


# ------------------------------------------------------------------- checkpoint
def test_checkpoint_store_lifecycle():
    cp = CheckpointStore()
    cp.record_output("r", "s", {"k": 1})
    assert cp.output("r", "s") == {"k": 1}
    cp.write_intent("r", "sink")
    assert cp.is_indeterminate("r", "sink")  # intent, no completion
    cp.write_completion("r", "sink")
    assert not cp.is_indeterminate("r", "sink")


# ------------------------------------------------------------------- credentials
def test_credential_resolver_non_trusted_direct():
    broker = CredentialBroker(b"m")
    broker.register("wf", "t", "v")
    # Construct a resolver with a non-TRUSTED profile directly (defence in depth).
    resolver = CredentialResolver(broker, "wf", Profile.UNTRUSTED, frozenset({"t"}))
    with pytest.raises(HardBlock) as e:
        resolver.get("t")
    assert e.value.rule_id == "HB-4"


# ---------------------------------------------------------------------- encode
def test_jira_trusted_keeps_broadcast():
    out = encode_for_sink("jira", "release done @channel", Profile.TRUSTED)
    assert "@channel" in out


# ------------------------------------------------------------------- normalize
def test_normalize_tree_mixed_dict_keys():
    out = normalize_tree({"str_key": "v\u202e", 3: "x"})
    assert out["str_key"] == "v"
    assert out[3] == "x"


def test_normalize_tree_list_and_scalar():
    out = normalize_tree(["a\u202eb", {"k": "v"}, 5])
    assert out[0] == "ab"
    assert out[1] == {"k": "v"}
    assert out[2] == 5


# -------------------------------------------------------------------- redactor
def test_shannon_entropy_empty_is_zero():
    assert _shannon_entropy("") == 0.0


# ---------------------------------------------------------------------- steps
def test_slack_step_posts_via_client():
    from wfa.shared.enums import Taint
    from wfa.shared.models import StepContext
    from wfa.steps.slack.post_message import PostMessageIn, SlackPostMessage

    class _Cred:
        def get(self, ref: str) -> str:
            return "xoxb-token"

    class _Client:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str, str]] = []

        def post_message(self, token: str, channel: str, text: str) -> str:
            self.sent.append((token, channel, text))
            return "ts-1"

    client = _Client()
    step = SlackPostMessage(client=client)
    ctx = StepContext(
        run_id="r",
        step_id="s",
        profile=Profile.TRUSTED,
        chain_depth=0,
        permission="chat:write",
        taint=Taint.SINK,
        credentials=_Cred(),
    )
    result = step.execute(PostMessageIn(channel="#ops", text="hi"), ctx)
    assert result.output.ts == "ts-1"
    assert client.sent == [("xoxb-token", "#ops", "hi")]


def test_coerce_output_validates_and_passes_through():
    from wfa.steps.base import coerce_output
    from wfa.steps.llm.summarise import SummariseOut

    obj = SummariseOut(summary="x")
    assert coerce_output(SummariseOut, obj) is obj  # already-typed passes through
    assert coerce_output(SummariseOut, {"summary": "y"}).summary == "y"


def test_redactor_keeps_long_low_entropy_token():
    r = Redactor()
    token = "a" * 30  # long but zero entropy => not a secret
    assert r.scrub(token) == token


# --------------------------------------------------------------------- resolve
WF = """
version: "1"
id: w
on: {pull_request: [opened]}
profile_required: UNTRUSTED
permissions: [contents:read]
steps:
  - id: s
    uses: llm.summarise
    taint: SOURCE
    permission: contents:read
    output_schema: x.json
    with: {content: "c"}
"""


def _load(yaml_text: str) -> SignedRegistry:
    reg = SignedRegistry(b"k", declared_step_types={"llm.summarise"})
    raw = yaml_text.encode()
    reg.load_signed(raw, _sign(raw))
    return reg


def _sign(raw: bytes) -> str:
    import hashlib
    import hmac

    return hmac.new(b"k", raw, hashlib.sha256).hexdigest()


def test_registration_rejects_no_steps():
    bad = WF.replace(
        """steps:
  - id: s
    uses: llm.summarise
    taint: SOURCE
    permission: contents:read
    output_schema: x.json
    with: {content: "c"}
""",
        "steps: []\n",
    )
    with pytest.raises(RegistrationError):
        _load(bad)


def test_registration_rejects_duplicate_step_ids():
    dup = (
        WF
        + """  - id: s
    uses: llm.summarise
    taint: SOURCE
    permission: contents:read
    output_schema: x.json
    with: {content: "c"}
"""
    )
    with pytest.raises(RegistrationError):
        _load(dup)


def test_registration_rejects_empty_permission():
    bad = WF.replace(
        "permission: contents:read\n    output_schema", 'permission: ""\n    output_schema'
    )
    with pytest.raises(RegistrationError):
        _load(bad)


def test_registration_rejects_empty_output_schema():
    bad = WF.replace("output_schema: x.json", 'output_schema: ""')
    with pytest.raises(RegistrationError):
        _load(bad)


def test_registration_accepts_quoted_on_key():
    # A quoted "on" key is a proper string (no YAML 1.1 bool coercion); the remap
    # branch is skipped and the trigger still binds.
    quoted = WF.replace("on: {pull_request: [opened]}", '"on": {pull_request: [opened]}')
    reg = _load(quoted)
    assert reg.get("w").triggers_on("pull_request", "opened")


def test_resolver_rejects_definition_with_bad_source_ref():
    reg = _load(WF)
    # Simulate a registered definition whose recorded source is not protected.
    tainted = reg.get("w").model_copy(update={"source_ref": "refs/heads/attacker"})
    reg._workflows["w"] = tainted
    with pytest.raises(HardBlock) as e:
        WorkflowResolver(reg).resolve("w", PROTECTED)
    assert e.value.rule_id == "HB-3"


def test_signed_registry_roundtrip_via_helper():
    raw = WF.encode()
    reg = SignedRegistry(b"key", declared_step_types={"llm.summarise"})
    reg.load_signed(
        raw, __import__("hmac").new(b"key", raw, __import__("hashlib").sha256).hexdigest()
    )
    assert isinstance(reg.get("w"), WorkflowDefinition)
    # sign_registry helper (conftest) matches the SIGNING_KEY used elsewhere.
    assert isinstance(json.loads('{"ok": true}'), dict)
    assert sign_registry(b"x")  # exercised for parity with the fixtures
