---
name: forge-implementation
description: "Implement scoped features and fixes using the consuming repository's patterns, contracts, and validation requirements."
---

# Forge Implementation

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

This skill module governs how coding agents execute implementation tasks. It enforces the read-before-write discipline, minimal-change principle, and mandatory test requirement defined by the consuming repository.

---

## Activation

Load this skill when asked to:
- Implement a new feature or component
- Fix a bug or regression
- Scaffold a new file, module, or service
- Refactor code (explicit scope only)

---

## Procedure

Follow in strict order. Do not skip steps.

### 1. Understand
- Read all files relevant to the change before writing any code.
- Identify the existing patterns: naming, indentation, imports, error handling.
- Check if a similar pattern already exists — prefer extending over creating.

### 2. Plan
- Define the minimal set of changes required.
- Identify which files will be created vs. modified.
- Note any side effects or dependent systems.

### 3. Implement
- Make the change. Follow existing style exactly.
- Follow the repository’s language and typing rules; never hardcode secrets.
- Validate external data at the boundary.
- Log writes to external systems.

### 4. Test
- Write tests: happy path + key edge cases + regression for this change.
- Run tests. Fix failures before proceeding.
- Do not leave skipped or commented-out tests.

### 5. Commit
- Commit message: `type(scope): description`
- One logical change per commit.
- If the change is breaking: add `BREAKING CHANGE:` footer.

---

## Output Contract

When reporting implementation complete, include:

```
## Implementation Complete — <feature/fix ref>
**Agent**: [persona]
**Stamped**: <ISO 8601>

### Changes
- Created: [file list]
- Modified: [file list]

### Tests
- Written: [test file list]
- Result: PASS | FAIL (with failure details if applicable)

### Commit
<sha> — <message>
```

---

## Anti-Patterns (Prohibited)

- Refactoring code not in scope of the task
- Adding speculative abstractions or "future-proofing"
- Removing error handling that "looks redundant"
- Skipping tests because the change is "small"
- Using `console.log` for production observability
