# Feature Specification: Enterprise API & RBAC

**Feature Directory**: `008-enterprise-api-rbac`

**Created**: 2026-09-15

**Status**: Planned / **deferred** until trigger

**Trigger (must all be false today)**: a second tenant appears, **or** Agent OS must call Twinbox over HTTP instead of local MCP. Until then this feature MUST NOT be implemented.

**Related**: [企业邮件智能体路线](../../.cursor/plans/) Phase 2; constitution IV–V; `001` MailboxAccount.

## Purpose

Optional FastAPI control plane wrapping the **same** Python functions used by CLI/MCP. Tenants, members, MailboxGrant, ActionApproval, AuditEvent. No second sync/pulse implementation.

## Non-Goals (until trigger)

- Do not ship FastAPI/uvicorn in the default local MCP path.
- Do not duplicate `cmd_sync` / pulse logic in an API layer.
- Do not allow gateway-style “any mailboxId” scanning across tenants.

## Requirements (when triggered)

- **FR-001**: API calls existing `twinbox_core` entrypoints only.
- **FR-002**: OIDC JWT + JWKS; MCP and API share one `RequestContext` ACL model.
- **FR-003**: Cross-tenant access denied 100% in contract tests.
- **FR-004**: MCP hot-path latency must not regress when API is present but unused.
- **FR-005**: First control-plane store is SQLite WAL; PostgreSQL only after multi-replica threshold.

## Success Criteria

- Untriggered: this directory remains Planned/deferred with zero runtime dependency.
- Triggered: cross-tenant rejection tests green; MCP smoke still green without requiring API.
