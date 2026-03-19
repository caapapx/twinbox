# CLAUDE.md

## 项目概述

twinbox 是一个以线程为中心的邮件 Copilot 基础设施。
核心路径：read-only → draft → controlled send。

## 关键路径

- 架构：docs/architecture.md
- 方案：docs/plans/
- 规范：docs/specs/
- 脚本：scripts/*.sh
- 类型合约：agent/custom_scripts/types.ts
- 策略配置：config/policy.default.yaml
- 角色配置：config/profiles/

## 文档索引规则

见 AGENTS.md 的"文档索引规则"章节。

## 开发约束

1. 只使用 master 分支
2. 提交信息格式：`type: short description`
3. Phase 1-4 只读，禁止 send/move/delete/archive/flag
4. 新增方案文档放 docs/plans/
5. gastown 是符号链接，不要修改其内容

## Dolt Server — Operational Awareness (All Agents)

Dolt is the data plane for beads (issues, mail, identity, work history). It runs
as a single server on port 3307 serving all databases. **It is fragile.**

### If you detect Dolt trouble

Symptoms: `bd` commands hang/timeout, "connection refused", "database not found",
query latency > 5s, unexpected empty results.

**BEFORE restarting Dolt, collect diagnostics.** Dolt hangs are hard to
reproduce. A blind restart destroys the evidence. Always:

```bash
# 1. Capture goroutine dump (safe — does not kill the process)
kill -QUIT $(cat ~/gt/.dolt-data/dolt.pid)  # Dumps stacks to Dolt's stderr log

# 2. Capture server status while it's still (mis)behaving
gt dolt status 2>&1 | tee /tmp/dolt-hang-$(date +%s).log

# 3. THEN escalate with the evidence
gt escalate -s HIGH "Dolt: <describe symptom>"
```

**Do NOT just `gt dolt stop && gt dolt start` without steps 1-2.**

**Escalation path** (any agent can do this):
```bash
gt escalate -s HIGH "Dolt: <describe symptom>"     # Most failures
gt escalate -s CRITICAL "Dolt: server unreachable"  # Total outage
```

The Mayor receives all escalations. Critical ones also notify the Overseer.

### If you see test pollution

Orphan databases (testdb_*, beads_t*, beads_pt*, doctest_*) accumulate on the
production server and degrade performance. This is a recurring problem.

```bash
gt dolt status              # Check server health + orphan count
gt dolt cleanup             # Remove orphan databases (safe — protects production DBs)
```

**NEVER use `rm -rf` on `~/.dolt-data/` directories.** Use `gt dolt cleanup` instead.

### Key commands
```bash
gt dolt status              # Server health, latency, orphan count
gt dolt start / stop        # Manage server lifecycle
gt dolt cleanup             # Remove orphan test databases
```

### Communication hygiene

Every `gt mail send` creates a permanent bead + Dolt commit. Every `gt nudge`
creates nothing. **Default to nudge for routine agent-to-agent communication.**

Only use mail when the message MUST survive the recipient's session death
(handoffs, structured protocol messages, escalations). See `mail-protocol.md`.

### War room
Active incidents tracked in `mayor/DOLT-WAR-ROOM.md`. Full escalation protocol
in `gastown/mayor/rig/docs/design/escalation.md`.


## Dolt Server — Operational Awareness (All Agents)

Dolt is the data plane for beads (issues, mail, identity, work history). It runs
as a single server on port 3307 serving all databases. **It is fragile.**

### If you detect Dolt trouble

Symptoms: `bd` commands hang/timeout, "connection refused", "database not found",
query latency > 5s, unexpected empty results.

**BEFORE restarting Dolt, collect diagnostics.** Dolt hangs are hard to
reproduce. A blind restart destroys the evidence. Always:

```bash
# 1. Capture goroutine dump (safe — does not kill the process)
kill -QUIT $(cat ~/gt/.dolt-data/dolt.pid)  # Dumps stacks to Dolt's stderr log

# 2. Capture server status while it's still (mis)behaving
gt dolt status 2>&1 | tee /tmp/dolt-hang-$(date +%s).log

# 3. THEN escalate with the evidence
gt escalate -s HIGH "Dolt: <describe symptom>"
```

**Do NOT just `gt dolt stop && gt dolt start` without steps 1-2.**

**Escalation path** (any agent can do this):
```bash
gt escalate -s HIGH "Dolt: <describe symptom>"     # Most failures
gt escalate -s CRITICAL "Dolt: server unreachable"  # Total outage
```

The Mayor receives all escalations. Critical ones also notify the Overseer.

### If you see test pollution

Orphan databases (testdb_*, beads_t*, beads_pt*, doctest_*) accumulate on the
production server and degrade performance. This is a recurring problem.

```bash
gt dolt status              # Check server health + orphan count
gt dolt cleanup             # Remove orphan databases (safe — protects production DBs)
```

**NEVER use `rm -rf` on `~/.dolt-data/` directories.** Use `gt dolt cleanup` instead.

### Key commands
```bash
gt dolt status              # Server health, latency, orphan count
gt dolt start / stop        # Manage server lifecycle
gt dolt cleanup             # Remove orphan test databases
```

### Communication hygiene

Every `gt mail send` creates a permanent bead + Dolt commit. Every `gt nudge`
creates nothing. **Default to nudge for routine agent-to-agent communication.**

Only use mail when the message MUST survive the recipient's session death
(handoffs, structured protocol messages, escalations). See `mail-protocol.md`.

### War room
Active incidents tracked in `mayor/DOLT-WAR-ROOM.md`. Full escalation protocol
in `gastown/mayor/rig/docs/design/escalation.md`.

