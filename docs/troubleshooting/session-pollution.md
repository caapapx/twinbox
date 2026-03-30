# 会话污染问题诊断与解决

## 问题表现

在 OpenClaw `twinbox` agent 会话中：
- ✅ 第一个问题（如"帮我看下最新的邮件"）正常返回结果
- ❌ 第二个问题（如"今天中午前我必须处理什么？"）失败
- ❌ 第三个问题继续失败
- ✅ 新开会话后，第一个问题又能正常工作

**失败模式：**
- Agent 回复"让我执行命令："但不调用工具
- 返回空内容（`payloads=[]` 或 `assistant.content=[]`）
- 工具调用后立即停止，无文字摘要

## 根本原因

### OpenClaw 系统提示限制

OpenClaw 仅将 SKILL.md 的 **`description` 字段**注入系统提示，文件其余内容需要 agent **主动读取**才可见。

**会话污染链：**
1. 第一轮：agent 可能读取了完整 SKILL.md，了解工具调用约束
2. 第二轮：agent 依赖会话历史，但核心约束不在系统提示中
3. 第三轮：agent 退化为"承诺执行但不调用"模式
4. 新会话：强制重新读取 SKILL.md，恢复正常

### 弱工具模型的断链行为

部分托管模型在工具调用后容易"断链"：
- 说"现在我去执行..."然后停止
- 调用工具后返回空内容
- 需要用户再次提醒才继续

## 解决方案

### 1. 强化 description 字段（已实施）

将核心约束写入 `SKILL.md` 的 `description`（会注入系统提示）：

```yaml
description: >-
  Twinbox 邮箱技能：必须先调用对应 OpenClaw 插件工具，工具返回后再写文字摘要。
  禁止反复只说不调工具（如「让我执行」「需要先同步邮件」）——
  同一回合必须发出 twinbox_* 工具调用，否则视为失败。
```

### 2. Bootstrap 消息模式（推荐）

每个新会话开始时，发送 bootstrap 消息：

```
请先读取 ~/.openclaw/skills/twinbox/SKILL.md，
然后在本轮内立即直接运行：
twinbox task latest-mail --json
不要只说「让我执行命令：」。执行后只基于真实 stdout 汇报结果。
```

**作用：**
- 强制 agent 读取完整 SKILL.md
- 在同一回合内完成读取 + 工具调用 + 摘要
- 建立正确的工具调用模式

### 3. 使用原生插件工具

确保 `plugin-twinbox-task` 已加载：

```bash
# 检查插件状态
cat ~/.openclaw/openclaw.json | jq '.plugins.entries["twinbox-task-tools"]'

# 重启 Gateway 加载插件
openclaw gateway restart
```

原生工具（`twinbox_latest_mail`、`twinbox_task_todo` 等）比通用 `exec` 更稳定。

### 4. 会话卫生习惯

**何时新建会话：**
- 连续 2 次工具调用失败
- Agent 重复说"让我执行"但不执行
- 返回空内容或 `payloads=[]`

**不要：**
- 在失败会话中反复重试相同问题
- 期望 agent 自己"恢复"工具调用能力

## 验证步骤

### 测试场景 1：连续多问题

1. 新建 `twinbox` agent 会话
2. 发送 bootstrap 消息（见上文）
3. 依次提问：
   - "帮我看下最新的邮件"
   - "今天中午前我必须处理什么？"
   - "本周邮箱简报"
4. 每个问题都应返回完整结果

### 测试场景 2：无 bootstrap

1. 新建会话，直接提问"帮我看下最新的邮件"
2. 第二个问题"今天待办"
3. 观察是否出现断链

**预期：**
- 有 bootstrap：连续成功
- 无 bootstrap：第二问可能失败

### 测试场景 3：插件 vs CLI

对比两种调用方式的稳定性：
- 原生工具：`twinbox_latest_mail`
- 通用 exec：`twinbox task latest-mail --json`

## 监控指标

在 `~/.openclaw/logs/` 中检查：
- 工具调用成功率
- 空响应频率
- 会话长度 vs 失败率的关系

## 相关提交

- `b1de21c` - 移除 session 参数避免卡住
- `0fa7196` - 添加反断链规则到 SKILL.md
- `25a7891` - Turn contract 嵌入 frontmatter description

## 参考文档

- `integrations/openclaw/prompt-test.md` - 提示测试流程
- `scripts/run_openclaw_prompt_tests.py` - 自动化测试
- `.agents/skills/twinbox/SKILL.md` - 完整技能定义
