# Architecture Decision Records (ADRs)

This directory contains all architectural decisions governing the RIF Runtime system. Each ADR documents a critical design choice, including the problem context, decision rationale, and implementation constraints.

## Quick Navigation

| ADR | Title | Status | Domain |
|-----|-------|--------|--------|
| [0001](./ADR-0001-governance-as-subsystem.md) | Governance as Subsystem | Active | Core Architecture |
| [0002](./ADR-0002-evidence-as-authoritative-record.md) | Evidence as Authoritative Record | Active | Audit & Forensics |
| [0003](./ADR-0003-audit-as-evidence-sink.md) | Audit as Evidence Sink | Active | Audit & Forensics |
| [0004](./ADR-0004-memory-context-separation.md) | Memory Context Separation | Active | Isolation & Security |
| [0005](./ADR-0005-replay-as-divergence-verification.md) | Replay as Divergence Verification | Active | Verification & Testing |
| [0006](./ADR-0006-capability-gateway-uniform-control.md) | Capability Gateway Uniform Control | Active | Access Control |
| [0007](./ADR-0007-adaptation-future-executions-only.md) | Adaptation - Future Executions Only | Active | Learning & Adaptation |

## Organization by Domain

### Core Architecture
- **ADR-0001**: Governance as Subsystem - Establishes governance as a first-class architectural subsystem

### Audit & Evidence Trail
- **ADR-0002**: Evidence as Authoritative Record - Defines evidence as the single source of truth
- **ADR-0003**: Audit as Evidence Sink - Implements audit logging as an evidence aggregation mechanism

### Security & Isolation
- **ADR-0004**: Memory Context Separation - Isolates execution contexts and memory boundaries
- **ADR-0006**: Capability Gateway Uniform Control - Uniform access control through capability tokens

### Execution & Verification
- **ADR-0005**: Replay as Divergence Verification - Uses replay mechanisms for detecting and verifying divergence
- **ADR-0007**: Adaptation - Future Executions Only - Constrains learning to future execution paths

## Reading Guide

1. **Start here**: ADR-0001 (Governance as Subsystem) - establishes the overall architectural pattern
2. **For audit/compliance**: ADR-0002 → ADR-0003 - evidence chain and audit mechanisms
3. **For security**: ADR-0004, ADR-0006 - context isolation and capability-based access control
4. **For testing/verification**: ADR-0005 - replay and divergence detection
5. **For learning systems**: ADR-0007 - adaptation constraints and patterns

## Decision Status Levels

- **Active**: Currently implemented and in use
- **Superseded**: Replaced by a newer ADR (see reference)
- **Deprecated**: No longer recommended for new implementations
- **Proposed**: Under consideration for implementation

## Contributing

When proposing a new ADR:

1. Use the next sequential number (e.g., ADR-0008)
2. Follow the template provided in any existing ADR
3. Include context, decision, and consequences sections
4. Link to related ADRs and implementation references
5. Submit as a pull request to this directory

## Implementation References

See `CLAUDE.md` in the root directory for detailed implementation mappings to codebase modules:
- Governance layer: `src/governance/`
- Audit subsystem: `src/audit/`
- Execution engine: `src/execution/`
- Resources subsystem: `src/resources/`
- Security utilities: `src/security/`
