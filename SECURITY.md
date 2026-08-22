# Security

## Scope

RIF Runtime is a security-sensitive governance runtime. Its core security property is that policy evaluation remains authoritative over proposed agent actions.

This document describes controls that are present in the repository today, plus limitations that matter when deploying the software. It is not a certification, penetration-test report, or claim of compliance with a particular regulatory framework.

## Security principles

1. **Deny-oriented governance:** policy constraints can reject requests before a governed action path proceeds.
2. **Explicit control-plane authentication:** mutable control-plane endpoints require `X-API-Key` credentials configured through `RIF_CONTROL_PLANE_API_KEYS` and fail closed when no key is configured.
3. **Evidence-aware operation:** decisions and posture transitions are persisted locally and can be replayed into runtime state.
4. **Secret minimization:** the runtime contains recursive redaction helpers for common credential-bearing field names.
5. **Defence in depth:** container, dependency, source-analysis, secret-scanning, and dependency-review controls complement application-level checks.
6. **No model authority:** model output is not itself a policy grant, execution lease, or provider-access authorization.

## Current controls

### Policy and posture

The runtime evaluates `PolicyRequest` objects through `PolicyEngine` and maintains a runtime posture that can become more restrictive as denial conditions accumulate. Posture is persisted and restored at startup.

The exact policy semantics are implementation-defined and tested in `tests/`. Policy-store wildcard precedence remains an explicit design limitation; do not assume that arbitrary wildcard policy rules behave as a general-purpose rule engine.

### Control-plane authentication

Mutable operations such as environment mutation, posture mutation, policy CRUD, and Metasploit capability-token minting are guarded by the `X-API-Key` dependency in `src/rif_runtime/auth.py`.

The configured key set is supplied through:

```text
RIF_CONTROL_PLANE_API_KEYS=key-one,key-two
```

The application hashes supplied and configured keys before constant-time comparison. This is application-level API-key authentication; it is not a substitute for enterprise identity federation, authorization administration, rotation infrastructure, or network controls.

### Cryptographic utilities

`src/rif_runtime/security.py` provides:

- SHA-256 canonical digests;
- HMAC-SHA256 signatures and verification;
- PBKDF2-HMAC-SHA256 secret hashing;
- Fernet encryption using a PBKDF2-derived key;
- recursive redaction of common secret-bearing keys.

`src/rif_runtime/audit.py` provides hash-chain record primitives with a genesis hash and chain verification.

The decision log (`decisions.jsonl`) is hash-chained by `HashChainedJsonlStore`. Each row carries a `_chain` envelope with its `previous_hash` and `current_hash`. Verification detects modification of a retained record, a broken predecessor link, and reordering — including a row removed from the middle, which orphans everything after it. It does **not** detect a deleted trailing suffix: every record that remains is still internally consistent, which is the same limitation as truncation below. `GET /v1/audit` reports the result under `decision_chain`, and `RIFRuntime.verify_decision_chain()` returns it directly.

**Scope of that property.** Chain verification detects integrity failures among the records that are still present. It is not proof of completeness and not an externally anchored ledger:

- an attacker with write access can truncate the log and rewrite a shorter, internally valid chain — nothing in the file commits to its own length;
- the chain is unwitnessed, so it establishes internal consistency, not third-party attestation;
- rows written before chaining was introduced carry no envelope. They are reported as `unchained_leading` and are explicitly **not** counted as verified;
- other stores (`posture_history.jsonl`, `metasploit_evidence.jsonl`) remain plain append-only JSONL and are not chained;
- concurrent appends are serialised by an advisory `flock`, and each writer re-reads the tail inside that lock, so two processes appending to one log (a `rif check` alongside a running `rif serve`) produce one chain rather than a fork. `fcntl` is POSIX-only; on a platform without it the lock degrades to a no-op and the single-writer assumption returns.

Tamper-*evidence* is therefore what this provides. Tamper-*proofing* would require external anchoring or an append-only medium the runtime does not control.

### Persistence and replay

The runtime persists decision and posture history under the configured data directory and can reconstruct graph/posture state with `ReplayEngine`.

Replay is a reconstruction mechanism. It should not be described as proof that an external action occurred exactly as represented, nor as protection against an attacker who can rewrite the underlying files.

### Container baseline

The supplied `Dockerfile` runs the application as a non-root user (`UID 10001`) on a Python slim base image.

Deployment-level controls such as read-only filesystems, capability dropping, seccomp, network policy, resource limits, TLS termination, secret management, and runtime isolation depend on the deployment configuration. They must not be inferred merely from the existence of the Dockerfile.

### Dependency and CI controls

The repository contains:

- hash-pinned runtime and development locks;
- a lock-sync merge-gate job;
- `pip install --require-hashes` in locked CI jobs;
- `pip-audit` against both locks;
- an unconstrained clean-clone resolution test;
- Bandit;
- CodeQL;
- Gitleaks;
- Dependency Review.

The workflows themselves are the authoritative evidence that these controls are configured. A workflow file is not evidence that a particular run passed; run status must be checked separately.

### Release limitations

The current release workflow builds Python distributions and publishes GitHub Releases. The repository does **not** currently claim:

- signed release artefacts;
- SBOM generation as a release control;
- reproducible builds;
- cryptographically verified container provenance.

These are future hardening items, not active controls.

## Threats and current posture

| Threat | Current mitigation | Limitation |
|---|---|---|
| Unauthorized policy operation | Control-plane API-key guard | API keys are not enterprise IAM |
| Policy bypass through malformed input | Pydantic validation and policy checks | Policy semantics are still evolving |
| Secret leakage in structured data | Redaction helper and secret-scanning workflow | Redaction is field-name based, not a DLP system |
| Local state tampering | Hash-chained decision log with verification, plus replay | Detects edits to the log; a writer who truncates it can rewrite a shorter valid chain, and other JSONL stores are unchained |
| Replay of stale local state | Persisted posture/replay semantics | Replay is not an authorization protocol or nonce service |
| Dependency compromise | Hash locks, audits, dependency review | No signed/SBOM/reproducible release chain yet |
| Container privilege escalation | Non-root image baseline | Full runtime isolation is deployment-dependent |
| Remote model authority | Provider egress remains governed/advisory | General decision-to-provider authorization seam is still specification work |

## Enterprise deployment expectations

Before treating RIF as a production control plane, deployment owners should independently establish:

- TLS and trusted ingress;
- enterprise identity and authorization around administrative operations;
- managed secret storage and key rotation;
- restricted network egress;
- immutable or independently protected evidence retention;
- backup and restore procedures;
- centralized logs and alerting;
- dependency and image provenance appropriate to the threat model;
- vulnerability management and incident response procedures;
- explicit data-retention and privacy policies;
- tested disaster recovery.

The repository does not currently provide all of those controls as a turnkey platform.

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

[Click here to report a security vulnerability](mailto:distortedprojection@gmail.com)

Please include the affected component/version, a concise description, reproduction steps or proof of concept where appropriate, and the potential impact.

Please allow 7 days for an initial response. Coordinated disclosure is preferred.

## Security changes

Security-sensitive changes should include:

- the threat or failure mode being addressed;
- the authoritative decision boundary;
- regression tests for the security property;
- evidence of the relevant CI/security checks;
- documentation of any remaining limitation.

Avoid describing a proposed control as implemented until the repository contains the executable control and a test or workflow demonstrates it.
