# spec/skill

Contract for the skill package format — the self-contained, versioned, testable
unit that packages a single capability (`SKILL.md` + `skill.yaml` + `scripts/` +
`references/` + `tests/`), per ADR-0008.

**Placeholder** — no schema yet. This runtime does not currently have a formal
skill package format; `.claude/skills/run-rif-runtime/` is the closest existing
example and should inform the first schema.

## Next slice
Define `skill_manifest.schema.json`, based on the shape already used in
`.claude/skills/run-rif-runtime/`. Note that the manifest file there is named
`manifest.yaml`, not `skill.yaml`; the first schema should either adopt that name
or record the rename explicitly. That directory also carries both `SKILL.md` and a
lowercase `skill.md`, which the contract should resolve.
