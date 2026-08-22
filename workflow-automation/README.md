# Workflow Automation (WFA-001)

An **event-driven, unattended developer automation engine**: it observes repository
and service events, classifies their provenance, and executes declarative YAML
workflows (PR summarisation, ticket creation, notifications, and user-defined
automations).

This is the reference implementation of spec **WFA-001 v2.2**. It is a
self-contained Python package (`wfa`) with no database and no external services in
the test path — the platform API, message broker, and downstream service clients are
all injected, so the whole engine runs end-to-end in-process.

## Why this engine is treated as dangerous

It is an **unattended, credentialed actor triggered by events it does not control**
(spec §1.1). There is no human in the loop at execution time, and its triggers —
"a pull request was opened" — can be caused by any member of the public on any public
repository. So the security model does not rest on approval prompts. It rests on
**provenance classification and pre-committed policy**: what an event is permitted to
cause is decided *before* the event arrives, based on who could have caused it.

## The core guarantees (and where they live)

| Guarantee | Module |
| --- | --- |
| The whole event payload is untrusted (T4); provenance comes from the platform API, never the body | `classifier/provenance.py` |
| Fork PRs / issues / anonymous webhooks run `UNTRUSTED`: **zero credentials, no SINK steps** | `runner/engine.py`, `security/credentials.py`, `runner/permissions.py` |
| Workflow definitions resolve only from the signed registry / protected branch — never the event head ref | `runner/resolve.py` |
| Templating is value-substitution only — no shell, no expression evaluation | `template/substitute.py` |
| Subprocess steps use argv arrays, never a shell | `steps/exec/safe_argv.py` |
| Webhooks are HMAC-authenticated before parsing; replays rejected | `ingress/` |
| Escalated steps need single-use, action-bound T3 approval; timeout aborts | `runner/escalation.py`, `console/operator.py` |
| Output is redacted + sink-encoded on the write path | `security/redactor.py`, `security/encode.py` |
| Egress is deny-by-default; RFC1918/loopback/link-local blocked (metadata pivot) | `security/egress.py` |
| Every decision is recorded in an append-only hash-chained audit log | `security/audit.py` |

The **runner (`runner/engine.py`) is the single enforcement chokepoint**: every step
dispatch passes through it, in a fixed order (resolve → profile mismatch → permission
intersection → per-step taint/permission/SINK/escalation/credential/substitution/
encode/validate/execute/redact/audit). No step reaches `execute()` without passing
classification, permission intersection, and — where declared — escalation.

## Layout

```
src/wfa/
  ingress/      HMAC verify, replay window, constant-shape responses
  classifier/   provenance derivation (platform API), idempotency keying
  queue/        durable broker, leases, fencing tokens, retry, dead-letter
  runner/       resolve (protected ref), engine (chokepoint), permissions,
                escalation, chain depth, checkpoints
  steps/        github/ jira/ slack/ llm/ docs/ + exec/ (argv-only)
  template/     value substitution, no evaluation
  security/     credentials, redactor, sink encoders, egress, audit, normalize
  console/      T3 operator surface
  observability/ health / readiness
  shared/       enums, models, errors, hard-block rule ids
```

## Develop / test

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

ruff format --check .
ruff check .
mypy src/wfa --ignore-missing-imports
pytest --cov=wfa --cov-report=term-missing
```

The test suite mirrors spec §10: `tests/unit/`, `tests/integration/`,
`tests/security/` (one suite per injection vector A–I plus the six mandatory
scenarios), driven partly by on-disk `tests/fixtures/adversarial/` payloads.

Coverage target (spec §10): 85% overall, **100% on `classifier/`, `runner/`,
`security/`, and `template/`**.

## Status / deferred (spec §12)

- **OD-2**: the general-purpose arbitrary-subprocess step is intentionally not shipped
  in 0.1; only the argv-array safety primitive (`steps/exec/safe_argv.py`) ships.
- **OD-1**: the broker is in-process here for testability; production is Postgres
  (transactional enqueue + fencing tokens). See `deploy/docker-compose.yaml`.
- The step interface is synchronous in this implementation (the spec sketches an
  async `AsyncIterator[StepChunk]` signature in §8.3); the enforcement semantics are
  identical and are what the tests pin.
