# Feature Specification: Enterprise Provider Connectors

**Feature Directory**: `010-enterprise-provider-connectors`

**Created**: 2026-09-15

**Status**: Planned / **deferred** until trigger

**Trigger**: target org cannot use IMAP app passwords, **or** requires shared-mailbox/Webhook that IMAP cannot cover. Until then do **not** add a second fetch stack.

**Related**: `001` ingest envelope shape; vault for tokens.

## Purpose

Microsoft Graph and Gmail OAuth/Webhook connectors that implement the **same** `fetch_incremental` / event shapes as IMAP. No `graph_*` MCP tool family.

## Requirements (when triggered)

- **FR-001**: Connector adapters produce the same envelope/context artifacts as IMAP fetch.
- **FR-002**: Tokens live in vault; refresh under per-account lock.
- **FR-003**: MCP tool names stay `twinbox_*`; no provider-specific tool surface.
- **FR-004**: Existing IMAP regression suite remains green alongside connector contract tests.

## Non-Goals (until trigger)

- Parallel rewrite of sync for Graph/Gmail
- Provider-specific MCP tools

## Success Criteria

- Untriggered: deferred with no code path required
- Triggered: contract tests + IMAP regression green
