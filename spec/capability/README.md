# spec/capability

Contract for declaring what a capability (agent, device, or skill) is authorized to
do: its authority set, resource pinning, and budgets.

`capability_manifest.schema.json` is migrated unchanged from
`contracts/rif_familiar/capability_manifest.schema.json` — the first concrete
instance of this contract, originally scoped to the RIF Familiar / Field Observer
device. It seeds this directory rather than being rewritten, per ADR-0008's
instruction to migrate existing contracts rather than duplicate them.

Runtime implementation: none yet. The schema's only consumer today is
`tests/test_rif_familiar_contracts.py`, which validates it against the fixtures in
`fixtures/rif_familiar/`.

Note that `src/rif_runtime/mcp/capabilities.py` — despite the name — does **not**
implement this contract. It is the Metasploit MCP tool taxonomy
(`CONTRACT_VERSION = "msf-governance/v1"`), classifying tool capabilities by
authority; this schema describes a device's declared authority set, budgets, and
relay policy. The two are unrelated. A general capability-manifest contract for
the runtime (as opposed to the RIF Familiar device) is still to be written.
