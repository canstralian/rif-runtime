# RIF Runtime Documentation Index

## Quick Start

- **[README.md](../README.md)** - Project overview and quick start
- **[CLAUDE.md](../CLAUDE.md)** - Comprehensive codebase guide (v0.3.0rc1)
- **[AGENTS.md](../AGENTS.md)** - Agent system documentation

## Architecture & Design

### Architecture Decision Records (ADRs)
See **[docs/adrs/](./adrs/)** for all ADRs.

**Key Decisions:**
1. **Governance as Subsystem** (ADR-0001) - Governance as first-class architecture
2. **Evidence as Authoritative Record** (ADR-0002) - Single source of truth for audit
3. **Audit as Evidence Sink** (ADR-0003) - Centralized audit logging
4. **Memory Context Separation** (ADR-0004) - Execution isolation and context boundaries
5. **Replay as Divergence Verification** (ADR-0005) - Verification through replay
6. **Capability Gateway Uniform Control** (ADR-0006) - Capability-based access control
7. **Adaptation - Future Executions Only** (ADR-0007) - Learning constraints

### System Specifications
See **[docs/specifications/](./specifications/)** for detailed specifications.

**Coverage:**
- REST API contracts and authentication
- Execution pipeline and context management
- Resource allocation and lifecycle
- Security and cryptography
- Audit and compliance

## Module Documentation

Refer to **[CLAUDE.md](../CLAUDE.md)** for detailed module documentation:

### Core Modules
- `config.py` - Configuration management and RIF_* env vars
- `api.py` - REST API surface with [auth] markers
- `auth/` - Control-plane authentication (X-API-Key, ControlPlaneAuth)
- `startup.py` - Application initialization and state setup

### Subsystems
- `execution/` - Kernel → Manifest → Result pipeline
- `resources/` - Resource allocation, tracking, and cleanup
- `audit/` - Hash-linked evidence chain and forensics
- `security/` - Cryptographic utilities and token management
- `governance/` - Governance subsystem and Metasploit integration
- `capabilities/` - Capability token system and validation

### Utilities
- `_version.py` - Version resolution chain (0.3.0rc1)
- `explainability/` - Execution transparency and debugging
- `mcp/` - Model Context Protocol integration

## CI/CD & Operations

See **[CLAUDE.md](../CLAUDE.md)** for CI workflow documentation:

| Workflow | Purpose | Trigger |
|----------|---------|----------|
| `ci` | Full test suite | Every push |
| `quality` | Code formatting (ruff) | Pre-commit |
| `bandit` | Security scanning | Every push |
| `gitleaks` | Secret detection | Every push |
| `codeql` | Static analysis | Every push |
| `dependency-review` | Supply chain check | PRs |
| `bootstrap-guardrails` | Community templates | Manual |
| `release` | Version and publish | Tags |

## Security & Compliance

- **[SECURITY.md](../SECURITY.md)** - Security policy and disclosure
- **Threat Models** (in specs) - Documented threat scenarios
- **Audit Trail** - Hash-linked evidence chain
- **Capability Tokens** - Access control system

## Contributing

- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Contribution guidelines
- **[CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)** - Community standards

## Navigation Map

```
docs/
├── adrs/
│   ├── README.md (ADR index and reading guide)
│   ├── ADR-0001-governance-as-subsystem.md
│   ├── ADR-0002-evidence-as-authoritative-record.md
│   ├── ADR-0003-audit-as-evidence-sink.md
│   ├── ADR-0004-memory-context-separation.md
│   ├── ADR-0005-replay-as-divergence-verification.md
│   ├── ADR-0006-capability-gateway-uniform-control.md
│   └── ADR-0007-adaptation-future-executions-only.md
├── specifications/
│   ├── README.md (Specification overview)
│   ├── API.md (REST API contracts)
│   ├── EXECUTION.md (Execution pipeline)
│   ├── RESOURCES.md (Resource management)
│   ├── SECURITY.md (Security & crypto)
│   └── AUDIT.md (Audit & compliance)
└── DOCUMENTATION_INDEX.md (this file)
```

## Viewing Documents

All documents are in Markdown format and can be:
- Viewed directly on GitHub
- Read locally with any text editor
- Generated into HTML/PDF with documentation tools

## For Specific Roles

### Developers
1. Start: [CLAUDE.md](../CLAUDE.md) - Current codebase state
2. Then: [docs/adrs/](./adrs/) - Architectural context
3. Reference: [docs/specifications/](./specifications/) - Implementation contracts

### Security Auditors
1. Start: [SECURITY.md](../SECURITY.md)
2. Then: [ADR-0004](./adrs/ADR-0004-memory-context-separation.md), [ADR-0006](./adrs/ADR-0006-capability-gateway-uniform-control.md)
3. Reference: Specification security section

### Operations & DevOps
1. Start: [CLAUDE.md](../CLAUDE.md) - Config and deployment
2. Then: [AGENTS.md](../AGENTS.md) - Agent management
3. Reference: CI workflow table in CLAUDE.md

### Product & Architecture
1. Start: [README.md](../README.md) - Project overview
2. Then: [docs/adrs/](./adrs/) - Complete design decisions
3. Reference: [docs/specifications/](./specifications/) - System behavior

## Document Freshness

- **CLAUDE.md**: Updated with v0.3.0rc1 (PR #72)
- **ADRs**: All seven foundational decisions documented
- **Specifications**: Aligned with current implementation

## Last Updated

2026-08-09
