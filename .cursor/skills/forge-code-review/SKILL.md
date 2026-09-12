---
name: forge-code-review
description: "Review pull requests and code changes for evidence-backed correctness, security, and repository contract compliance."
---

# Forge Code Review

## Repository authority

Read the consuming repository's applicable AGENTS.md, CLAUDE.md, architecture,
contribution and security guidance first. Shared procedures do not replace local
contracts, identity decisions, validation commands, or task scope. Flag conflicts;
do not import Forge's language choices or daily ship state.

Determine required checks from local configuration and workflows, distinguishing
configured checks from executed results. Mark missing evidence [UNVERIFIED].
Do not infer permission to commit, publish, deploy, merge, or contact others from
loading this skill. Use the authorization already supplied for the task.

## Purpose

This skill module defines the operating procedure for LLM-assisted code review. When loaded, the agent switches into structured review mode: sequential checks, explicit output format, no speculative suggestions beyond scope.

---

## Activation

Load this skill when asked to:
- Review a pull request diff
- Audit a file or function for correctness, security, or style
- Compare two implementations

---

## Review Checklist

Run in order. Flag each item as `PASS`, `WARN`, or `FAIL`.

| # | Check | Notes |
|---|-------|-------|
| 1 | **Typing** | Apply the consuming repository’s language and typing rules |
| 2 | **Secrets** | No hardcoded credentials or tokens |
| 3 | **Input validation** | External data validated at boundary |
| 4 | **Error handling** | Exceptions caught, logged, not swallowed |
| 5 | **Tests present** | Change covered by tests; tests pass |
| 6 | **No dead code** | No commented-out blocks, unused imports |
| 7 | **Conventional commit** | Commit message follows `type(scope): msg` |
| 8 | **SAST clean** | No injection surfaces, no `eval` |
| 9 | **Audit logging** | Writes to external systems are logged |
| 10 | **Scope discipline** | Change is minimal; no unrelated refactors |

---

## Output Format

```
## Code Review — <file or PR ref>
**Reviewer**: [agent persona]
**Stamped**: <ISO 8601>

### Summary
<1–3 sentence verdict>

### Findings
| Severity | Location | Issue | Recommendation |
|----------|----------|-------|----------------|
| FAIL     | ...      | ...   | ...            |
| WARN     | ...      | ...   | ...            |

### Verdict
Recommendation: APPROVE | REQUEST CHANGES | BLOCK (not a submitted review)
```

---

## Severity Levels

| Level | Meaning |
|-------|---------|
| `FAIL` | Must fix before merge. Correctness, security, or test coverage issue. |
| `WARN` | Should fix. Style, maintainability, or minor risk. |
| `NOTE` | Informational. No action required. |
