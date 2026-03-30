# Twinbox × OpenClaw 排障与回滚

> 操作主路径见 [DEPLOY.md](./DEPLOY.md)；附录见 [DEPLOY-APPENDIX.md](./DEPLOY-APPENDIX.md)。

---

## 1. env 与会话快照

### 1.1 两层 env 不可互换

- **`state root/twinbox.json`**：Twinbox CLI 的**主**配置（邮箱/LLM 等）；无 JSON 时才会回读历史 **`state root/.env`**。
- **`skills.entries.twinbox.env`**：OpenClaw 在 **agent run** 中注入给 skill 的环境；缺省时 skill 可能被过滤，即使磁盘上已安装 `SKILL.md`。

### 1.2 本机曾观测（2026-03-25）

- 写入 `skills.entries.twinbox.env` **之前**：`twinbox` 虽 `Ready`，`agent:main:main` 与新建 `agent:twinbox:main` 可能都**未**在 prompt 中出现 `twinbox`。
- 写入 env、重启 Gateway、清理旧 `agent:twinbox:main` 快照后：新会话的 `systemPromptReport.skills.entries` 可出现 `twinbox`。

**操作建议**：改 env 后 **重启 Gateway → 新会话 → 再查快照**。

### 1.3 `skills info` vs 会话注入

`openclaw skills info twinbox` 显示 `Ready` ≠ 当前会话 prompt 已包含 `twinbox`。
以 `openclaw agent … --json` 中 `systemPromptReport.skills.entries` 是否含 `twinbox` 为准。

### 1.4 `preflightCommand` 与对话层

`openclaw skills info twinbox` 与「agent 在自然语言里真的执行了 `twinbox mailbox preflight`」**不是**同一回事；不要将模型口头结论当作 preflight 结果。

### 1.5 飞书 / 第三方会话里只看到「先同步邮件 / 让我执行」复读

**成因**：该通道若未绑定与 **Twinbox 插件 + `twinbox` agent** 相同的 Gateway 配置，模型往往拿不到 `twinbox_*` 工具，只能按 skill 的短 `description` 口头编流程；在 `astron-code-latest` 等模型上还容易把同一段话重复两遍。

**处理**：在 OpenClaw 里让飞书侧会话使用已加载 `plugin-twinbox-task` 的 **twinbox** agent（或等价路由），确认 `twinboxBin`、`code-root`、`skills.entries.twinbox.env` 与 [DEPLOY.md](./DEPLOY.md) 一致；改完后 **重启 Gateway** 并 **新开会话**。用 `openclaw agent --agent twinbox --message '…' --json` 对比：若 CLI 有工具调用而飞书没有，问题在通道/agent 绑定而非 Twinbox CLI。

Gateway 若提示 `plugins.allow is empty`，应在 OpenClaw 配置里 **显式 allow** `twinbox-task-tools`（或你的插件 id），避免非确定性加载。

### 1.6 探针：与 `twinbox_latest_mail` / 插件一致的真实命令（优先跑）

以下顺序与插件行为一致，用于区分「模型复读」与「邮件链路真失败」。

1. **最新邮件（与插件 `twinbox task latest-mail --json` 相同）**

   ```bash
   ~/.local/bin/twinbox task latest-mail --json
   ```

   - 若返回 `"ok": false` 且带 `"recovery_tool": "twinbox_daytime_sync"`：属预期首跑；**插件会在一次 `twinbox_latest_mail` 调用内**自动跑 `daytime-sync` 再重试，模型**不应**口头说「先同步邮件数据，然后…」。
   - 自动同步仍失败后，`latest-mail` 会继续报缺 `activity-pulse`——此时应查 **第 2 步**（同步是否成功），而不是让模型用文字「再同步一遍」。

2. **单独跑 daytime-sync（与插件内 `runOrchestrate(schedule --job daytime-sync)` 一致）**

   ```bash
   export TWINBOX_CODE_ROOT="$HOME/.twinbox/vendor"
   cd "$TWINBOX_CODE_ROOT"
   PYTHONPATH="$TWINBOX_CODE_ROOT" python3 -m twinbox_core.orchestration schedule --job daytime-sync --format json
   ```

   - 看 `status` 与 `attempts[].steps[].returncode`。失败时 **同一条 JSON** 内步骤可含 **`stderr`**（截断）、以及 **`diagnostic_hint`** / **`state_root`**。不要在 OpenClaw agent 里用 **workspace `read`** 去打开 `~/.twinbox/runtime/archive/...`（路径不在 workspace 内会失败）；以 JSON 里的 **stderr** 为准向用户说明。若助手在工具后以冒号结尾并停住（半轮停），多为托管模型行为，见 [DEPLOY.md](./DEPLOY.md) 已知限制。
   - 若 **Phase 1 Incremental** 为 `1`，在宿主上直接跑同一条 argv（日志里可见）看 stderr；常见为 **IMAP 连接/文件夹**错误（例如 `imaplib.IMAP4.error`）。含 **非英文邮箱文件夹名**（中文等）时，历史上若出现 `BAD` / `Request not ending with`，请升级到已包含 **IMAP modified UTF-7** 编码的 `twinbox_core`（`imap_incremental` 在 `select` 前编码邮箱名）。**邮件同步未成功时，任何渠道都不会有真实「最新邮件摘要」。**

3. **对照：Gateway + twinbox agent 是否真能走到工具**

   ```bash
   openclaw agent --agent twinbox --message '只调用 twinbox_latest_mail（无参数），不要输出解释性中文。' --json --timeout 120
   ```

   - 若此处 `result.payloads` 里已有「automatic daytime-sync」与 `latest-mail` 拼接输出，而 **飞书里仍只有复读、无工具结果**：问题在 **飞书会话 / 路由 / 模型**，不在 `twinbox` 二进制。

---

## 2. 「缺少 env」类回复

### 2.1 成因 A：未真实执行 preflight

模型可能仅根据 `requires.env` **描述**「缺字段」，而非执行 `twinbox mailbox preflight --json`。以 CLI 在宿主上直接跑的结果为准。

### 2.2 成因 B：state root 漂移到 workspace

未配置 `~/.config/twinbox/state-root` 等时，在 workspace cwd 下可能把 workspace 当成 state root，继而错误地去找 `~/.openclaw/workspace/.env` 或缺少 **`twinbox.json`**。执行 [DEPLOY.md §3.4](./DEPLOY.md) 并核对 §1.1。

### 2.3 `openclaw skills info` 前缀告警

若出现 `[skills] Skipping skill path that resolves outside its configured root.`，多为**其他** skill 的路径越出 OpenClaw 配置的 skill 根目录，**未必**与 twinbox 有关。以 `openclaw skills info twinbox` 是否 `Ready`、以及 `systemPromptReport.skills.entries` 是否含 `twinbox` 为准。

---

## 3. Gateway 相关

### 3.1 Gateway 未运行或 RPC 失败

`openclaw gateway status` 中 **RPC probe** 非 ok 时，`openclaw agent` 无法完成 turn。先按输出中的 systemd / 端口 / `openclaw doctor` 建议处理。

### 3.2 `openclaw agent --json` 看不到助手正文

`result.payloads` 可能为空，非 JSON 模式终端可能只打印 `completed`；这**不表示** turn 失败。若要阅读助手正文，用 `openclaw tui` 或渠道侧历史；验收 Twinbox 逻辑请使用宿主 shell 的 `twinbox … --json`。

---

## 4. 为何有时只看到「Read SKILL.md」

用户问「最新邮件」时，模型可能只读 `SKILL.md` 而不执行 CLI。**更稳**的映射是显式 `twinbox task latest-mail --json` 等（或插件工具）。详见 [SKILL.md](../SKILL.md) 中的 task 入口说明。

---

## 5. 回滚与恢复

1. **配置**：保留备份的 `openclaw.json`、skills 目录与 Twinbox `state root`；回滚时恢复**已知良好**版本。
2. **会话状态**：避免把含陈旧 `skillsSnapshot` 的 `sessions/` 直接当作「恢复即上线」；必要时删特定 agent session 或新建会话验证。
3. **技能文件**：回滚 [SKILL.md](../SKILL.md) 后重复 [DEPLOY.md §4](./DEPLOY.md) 的复制与 Gateway 重启。

---

## 6. 成熟度与当前判断

### 6.1 已有基础

- 根 [SKILL.md](../SKILL.md) 含 `metadata.openclaw`。
- `twinbox mailbox preflight --json`、`twinbox-orchestrate`、调度契约文档已形成。

### 6.2 仍未闭环或未验证（摘录）

- 平台是否自动消费 skill schedule metadata。
- OpenClaw cron / heartbeat 与 Twinbox phase 刷新的完整责任边界。
- listener / action / review 在托管环境中的运行方式。
- 部署后日志、通知、失败重试、stale fallback 的归属。

### 6.3 当前建议

- 不把方案写成「完整托管已结束」；以 **manifest + CLI + bridge** 为实，托管调度与平台预检消费为待验项。
- 优先：稳定部署面（宿主接线 + poller + bridge 闭环）；再验证 `preflightCommand` 与 skill schedule metadata 的真实消费。

---

**文档版本**：本文为排障与回滚；操作主路径见 [DEPLOY.md](./DEPLOY.md)，设计模型见 [docs/ref/openclaw-deploy-model.md](../docs/ref/openclaw-deploy-model.md)，附录见 [DEPLOY-APPENDIX.md](./DEPLOY-APPENDIX.md)。
