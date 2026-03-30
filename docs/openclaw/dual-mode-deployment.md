# Twinbox 双模式部署指南

Twinbox 现在支持两种使用模式：

## 模式 1：Agent-Specific（深度集成）

**适用场景：** 需要完整的邮箱管理功能，包括 onboarding、上下文管理、路由规则等。

**部署位置：** `~/.openclaw/skills/twinbox/`

**使用方式：**
1. 在 OpenClaw 中创建/切换到 `twinbox` agent 会话
2. 直接对话："帮我看下最新的邮件"
3. Agent 自动调用 twinbox 工具

**特点：**
- ✅ 完整功能（onboarding、队列管理、线程检视等）
- ✅ 会话上下文保持
- ✅ 自动工具调用
- ⚠️ 仅在 twinbox agent 中可用

## 模式 2：Global AgentSkill（快速查询）

**适用场景：** 在任何会话中快速查看邮箱状态。

**部署位置：** `~/.openclaw/skills/twinbox-global/`

**使用方式：**
在任何 OpenClaw 会话中：
```
/twinbox          # 查看最新邮件
/twinbox todo     # 查看待办
/twinbox weekly   # 查看周报
/twinbox status   # 检查状态
```

**特点：**
- ✅ 全局可用（任何会话）
- ✅ 快速查询
- ✅ 显示在 `/skill` 列表中
- ⚠️ 功能简化（仅查询，无 onboarding）

## 部署步骤

### 1. 部署 Agent-Specific 模式（已有）

```bash
twinbox onboard openclaw
```

### 2. 部署 Global AgentSkill 模式（新增）

```bash
# 复制 skill 文件到 OpenClaw
cp -r .agents/skills/twinbox-global ~/.openclaw/skills/

# 重启 Gateway 加载新 skill
openclaw gateway restart
```

### 3. 验证部署

```bash
# 检查两个 skill 都存在
ls -la ~/.openclaw/skills/twinbox/
ls -la ~/.openclaw/skills/twinbox-global/

# 在 OpenClaw 中运行
/skill  # 应该看到 twinbox 在列表中
```

## 使用建议

- **日常快速查询** → 使用 `/twinbox` 命令（模式 2）
- **深度邮箱管理** → 切换到 `twinbox` agent（模式 1）
- **首次配置** → 必须在 `twinbox` agent 中完成 onboarding

## 技术细节

两种模式共享：
- 同一个 twinbox CLI
- 同一个 daemon
- 同一套 Phase 4 产物

区别仅在调用方式和功能范围。
