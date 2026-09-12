# Shared Forge components

This repository opts into two Forge skills (`forge-code-review` and
`forge-implementation`) and the read-only `forge-code-reviewer` Cursor agent.
`forge.lock.json` records the exact source commit, selected components and hashes.
The generated files are in `.cursor/skills/` and `.cursor/agents/`.

Mandare's AGENTS.md, CLAUDE.md, architecture, identity decisions, specification
reviews and actual CI requirements remain local and authoritative. These shared
procedures do not ratify proposals, authorize execution or change runtime policy.
The marketing personas and Forge's daily ship state are not installed.

## Use

After checking out this change, reload Cursor and confirm the components appear.
Invoke `/forge-code-review` or `/forge-implementation`, or ask for the
`forge-code-reviewer` agent to inspect a scoped diff. The read-only agent inspects
existing evidence; it must not claim unexecuted tests passed. Run required validation
through an appropriately authorized execution context.

## Verify or update

Clone private `canstralian/forge` beside this checkout with normal Git credentials.
Use its reviewed `scripts/forge_sync.py`; do not execute an unreviewed upstream script.

```bash
python ../forge/scripts/forge_sync.py --target . --check
git -C ../forge fetch origin
python ../forge/scripts/forge_sync.py --target . --ref NEW_FULL_FORGE_SHA
python ../forge/scripts/forge_sync.py --target . --ref NEW_FULL_FORGE_SHA --pr
```

The preview is read-only. `--pr` explicitly creates a branch, writes the update,
commits, pushes and opens a draft PR using authenticated Git and `gh`. Start from
a clean, updated base branch. Review and satisfy Mandare's gates before merging.
No update runs automatically. Locally changed managed files stop synchronization;
keep Mandare-specific additions in local instructions or separately named files.

Initial source dependency: [Forge PR #4](https://github.com/canstralian/forge/pull/4).
Land Forge first. If its merge changes the source SHA, refresh this lock from the
landed commit before merging this consumer change. This change is independent of
Mandare #179/#180 and does not replace their state document or development lead.
