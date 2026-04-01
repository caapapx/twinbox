# Twinbox × OpenClaw 部署操作主路径

> **本文面向运维**：前置条件 → 宿主接线 → 验证 → 对话引导 → 维护与卸载。
> 设计模型（三层分工、数据流）见 [docs/ref/openclaw-deploy-model.md](../docs/ref/openclaw-deploy-model.md)。
> 排障与问题记录见仓库根 [BUGFIX.md](../../BUGFIX.md)；附录见 [DEPLOY-APPENDIX.md](./DEPLOY-APPENDIX.md)。
> Agent 行为与命令契约见仓库根 [SKILL.md](../SKILL.md)。

---

## 1. 适用范围与路径约定

**覆盖**：Twinbox 作为 OpenClaw 托管 Markdown skill（及可选插件工具）的安装路径、`openclaw.json` 配置、roots 初始化、验证与常见误判。
**不覆盖**：OpenClaw 本体安装与升级（以 [docs.openclaw.ai](https://docs.openclaw.ai) 为准）；Claude Code / Opencode 本地 `.claude/` skill。

**路径约定**：文中 `bash scripts/...` 默认在 **Twinbox 仓库根目录** 执行。若在 `integrations/openclaw/` 子目录下，请用 `bash ../../scripts/...`。

---

## 2. 推荐整体顺序

```
§3.1–§3.5（宿主接线，含默认 bridge/timer 安装与健康检查）
  → §3.6–§3.7（验证与专用 agent）
    → §3.8（在 OpenClaw 里跑 onboarding）
      → §3.9（可选：首次全量 phase 4 验证）
      → §3.10（调度与 cron 同步；bridge 已在 §3.1–§3.5 默认安装）
```

任一步失败先查仓库根 [BUGFIX.md](../../BUGFIX.md)「OpenClaw 集成排障」；未完成宿主接线时，**不要**假设 skill 已注入或 onboarding 能代替 env。

---

## 3. 从零部署

### 3.1 前置：OpenClaw 可用

- 已安装并可执行 `openclaw`（示例：`npm install -g openclaw@latest`）。
- 至少能完成：`openclaw config validate`、按需启动 Gateway。

### 3.2 安装 Twinbox CLI

需要 Python ≥ 3.11。在仓库根创建 venv 并安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

验证两个命令可执行：

```bash
twinbox --help
twinbox-orchestrate --help
```

后续所有 `twinbox` / `twinbox-orchestrate` 命令均在此 venv 激活后执行。

### 3.3 初始化数据目录（state root）

> **两个目录概念**：
> - **code root**：twinbox 仓库本身（代码、脚本）所在路径，通常是你 `git clone` 的位置。
> - **state root**：运行时数据目录，存放 `twinbox.json`（邮箱/LLM/集成配置）、phase 产物、日志等。默认为 `~/.twinbox`，与代码仓库分离，不会进 git。

在仓库根执行初始化脚本，将两个路径写入 `~/.config/twinbox/`：

```bash
bash scripts/install_openclaw_twinbox_init.sh
```

成功输出示例：

```
Wrote Twinbox roots:
  ~/.config/twinbox/code-root  -> /path/to/twinbox
  ~/.config/twinbox/state-root -> /home/yourname/.twinbox
```

> **注意**：首次运行时 OpenClaw workspace 可能还不存在，脚本不会报错，继续即可。如果报错，查看 `~/.twinbox/logs/init.log`。

验证路径已写入：

```bash
cat ~/.config/twinbox/code-root
cat ~/.config/twinbox/state-root
```

### 3.4 配置邮箱与 LLM（门槛）

此时 state root 已初始化为 `~/.twinbox`，Twinbox 的唯一配置真源为 `~/.twinbox/twinbox.json`（历史 `.env` 仅作迁移期兼容读取）。

**配置邮箱**（密码通过环境变量注入，不会出现在命令行历史）：

```bash
TWINBOX_SETUP_IMAP_PASS=<app_password> twinbox mailbox setup --email you@example.com --json
```

命令自动探测 IMAP/SMTP 服务器配置，写入 `~/.twinbox/twinbox.json`，并运行连通预检。`"status": "ok"` 表示成功。失败时日志见 `~/.twinbox/runtime/validation/preflight/mailbox-smoke.stderr.log`。

**配置 LLM API**（Phase 1-4 流水线必需）：

```bash
TWINBOX_SETUP_API_KEY=<your_key> twinbox config set-llm --provider openai --json
# 或 --provider anthropic
```

写入 `~/.twinbox/twinbox.json` 并验证后端可连通。`"backend_validated": true` 表示成功。

**可选：手动验证邮箱连通**：

```bash
twinbox mailbox preflight --json
```

`"status": "warn"` 或 `"ok"` 均表示 IMAP 连通成功（SMTP 在只读模式下跳过）。

### 3.5 安装托管 skill 文件（含插件）

#### Markdown skill

**推荐**：优先使用 `twinbox onboard openclaw`。它会检查邮箱/LLM 门槛、执行宿主接线，并在最后交接到对话 onboarding。`twinbox deploy openclaw` 保留为高级/脚本化入口。旧版曾使用 `state_root/skills/twinbox/SKILL.md`，升级后若存在该路径可手动删除以免混淆。

仅手工时：

```bash
cp /path/to/twinbox/SKILL.md ~/.openclaw/skills/twinbox/SKILL.md
```

#### 安装总向导（推荐）

在仓库根、已激活 venv 的前提下，先走总向导：

```bash
cd /path/to/twinbox
source .venv/bin/activate
twinbox onboard openclaw --json
```

向导默认会：

- 检查 `openclaw`、`code-root`、`state-root`、`state root/twinbox.json`、当前 onboarding stage
- 在缺少邮箱或 LLM 配置时补做最小门槛配置
- 调用宿主接线（见下方高级入口）
- 把 onboarding 进度同步到下一个应进入的对话阶段，并给出后续动作

#### 一键宿主接线（高级入口）

在仓库根、已激活 venv 的前提下，可用 CLI 串行完成：**roots 初始化**、`~/.openclaw/openclaw.json` 中 `skills.entries.twinbox` 合并（默认从 **state root** 的 `twinbox.json` 同步邮箱相关键）、**按宿主 OS/CPU 检查或释放 `himalaya`**（`--json` 中 `ensure_himalaya` 步；Linux x86_64/aarch64 可自动从 twinbox 内置包解压到 `runtime/bin`，其它平台为 `skipped` 时需自行安装）、**同步 `SKILL.md`**（先写入 `$TWINBOX_STATE_ROOT/SKILL.md`，再对 `~/.openclaw/skills/twinbox/SKILL.md` **创建指向该文件的符号链接**；若宿主不支持软链则回退为复制）、**`openclaw gateway restart`**：

```bash
cd /path/to/twinbox
source .venv/bin/activate
twinbox deploy openclaw --json
```

##### 可选：并入 `openclaw.fragment.json`（插件路径等）

需要把 **插件**、`twinboxBin` 绝对路径等一并写入宿主 `~/.openclaw/openclaw.json` 时，在仓库内维护片段文件（**先于** `skills.entries.twinbox` 做深度合并）：

1. 复制示例：`cp integrations/openclaw/openclaw.fragment.example.json integrations/openclaw/openclaw.fragment.json`
2. 将示例中的 `REPLACE_ME` 换成本机 **Twinbox 仓库绝对路径**（勿把含本机路径的 `openclaw.fragment.json` 提交到 git，见仓库根 `.gitignore`）。
3. 照常执行 `twinbox deploy openclaw`；若该文件不存在则跳过此步。

CLI：`--fragment PATH` 指定其它 JSON 片段；`--no-fragment` 不读默认路径 `integrations/openclaw/openclaw.fragment.json`。

常用选项：`--dry-run`（只输出计划、不写盘）；`--no-restart`；`--no-env-sync`（仅 `enabled: true`，不覆盖已有 `env`）；`--strict`（在默认从 `state root/twinbox.json` 同步邮箱键时，若缺任一 OpenClaw 必填键则**失败退出**、不写 `openclaw.json`、不复制 SKILL）。若未使用 `--strict` 且单配置文件尚未含完整邮箱字段，合并后 OpenClaw 仍可能缺键，需先完成 §3.4 或手改 JSON。

##### 撤销本次宿主接线（与 deploy 对称，非全量卸载）

误执行 deploy 或想先拆掉 OpenClaw 侧的 Markdown skill 时，用 **rollback**（**不删** `~/.twinbox` 邮件数据；**会移除** Twinbox vendor-safe bridge user units；**不删** OpenClaw 插件与其它 cron —— 全量 teardown 见本文 **§5** `uninstall_openclaw_twinbox.sh`）：

```bash
twinbox deploy openclaw --rollback --json
```

可选：`--remove-config` 同时删除 `~/.config/twinbox/`（`code-root` / `state-root` 指针）；`--dry-run`；`--no-restart`。

实现见 `src/twinbox_core/openclaw_deploy.py`（`run_openclaw_rollback`）。

与 **`scripts/reset_twinbox_state.sh`** 的区别：reset 只清 **`runtime/`** 与 twinbox **会话**，**保留** `openclaw.json`、skill 文件与 `~/.config/twinbox`。rollback 只做 **OpenClaw 宿主接线** 的逆操作。

在 `~/.openclaw/openclaw.json` 中启用并写入 **完整** 邮箱 env（手改或与上面命令等价）：

```json
{
  "skills": {
    "entries": {
      "twinbox": {
        "enabled": true,
        "env": {
          "IMAP_HOST": "...", "IMAP_PORT": "...",
          "IMAP_LOGIN": "...", "IMAP_PASS": "...",
          "SMTP_HOST": "...", "SMTP_PORT": "...",
          "SMTP_LOGIN": "...", "SMTP_PASS": "...",
          "MAIL_ADDRESS": "..."
        }
      }
    }
  }
}
```

**安全**：`skills.entries.*.env`、Gateway `token` 等为敏感信息，**勿提交到 git**；泄露后应轮换凭据。

#### 插件工具（推荐同步安装）

当模型频繁停在「Read SKILL.md」而不执行 CLI 时，插件提供**确定性工具**直接调用 `twinbox task … --json`：

| 项 | 说明 |
|----|------|
| 位置 | [plugin-twinbox-task/](./plugin-twinbox-task/) |
| 网关实际加载 | **[`dist/index.mjs`](./plugin-twinbox-task/dist/index.mjs)**（esbuild 打包，依赖已内联）。**宿主不需要 `npm ci`**；与 `twinbox install --archive` / vendor 解压同一份文件即可。 |
| 源码（仅维护者） | [index.mjs](./plugin-twinbox-task/index.mjs)、[register-twinbox-tools.mjs](./plugin-twinbox-task/register-twinbox-tools.mjs) — 改源码后在本目录执行 `npm ci && npm run build` 并提交新的 `dist/`。 |
| 配置 | `twinboxBin`：可选，建议写 Gateway 宿主机上的绝对路径；`cwd`：Twinbox code root。若未显式配置 `twinboxBin`，插件会先尝试 `<cwd>/scripts/twinbox`，再退回 PATH 中的 `twinbox` |
| 测试 | `node --test integrations/openclaw/plugin-twinbox-task/register-twinbox-tools.test.mjs` |

详见 [plugin-twinbox-task/README.md](./plugin-twinbox-task/README.md)。

安装方式以 OpenClaw 当前插件文档为准（见 [DEPLOY-APPENDIX.md §A.1](./DEPLOY-APPENDIX.md)）。插件与 Markdown skill 可并存。

**推荐配置**：如果 Gateway 不是从 Twinbox 仓库根目录启动，或宿主进程的 PATH 不保证包含 `.venv/bin`，请在 `~/.openclaw/openclaw.json` 里把插件配置写成绝对路径：

```json
{
  "plugins": {
    "load": {
      "paths": [
        "/abs/path/to/twinbox/integrations/openclaw/plugin-twinbox-task"
      ]
    },
    "entries": {
      "twinbox-task-tools": {
        "enabled": true,
        "config": {
          "cwd": "/abs/path/to/twinbox",
          "twinboxBin": "/abs/path/to/twinbox/scripts/twinbox"
        }
      }
    }
  }
}
```

原因是插件工具调用的是 `spawn(twinboxBin, ...)`，不会额外经过仓库里的 `scripts/twinbox` 包装脚本；只有把 `twinboxBin` 指到 `scripts/twinbox`，或让插件通过 `cwd` 自动探测到它，才能稳定激活 `.venv` 并补齐 `PYTHONPATH`。不要假设 Gateway 进程的 PATH 自带 Twinbox `.venv/bin`。

然后 **重启 Gateway**，用 **新会话** 起 agent turn 检查 `systemPromptReport.skills.entries`。

### 3.6 最小验证（宿主）

```bash
openclaw config validate
openclaw skills info twinbox
```

`skills info` 显示 `Ready` **不等于** 当前会话 prompt 已注入 twinbox（见 [BUGFIX.md §env 与会话快照](../../BUGFIX.md)）。

#### 3.6.1 Gateway 与会话级 smoke

Gateway 运行中（`openclaw gateway status` RPC probe 为 ok）时，用单次 agent turn 验证：

```bash
openclaw agent --agent twinbox --message "Acknowledge if twinbox skill is available." --json --timeout 120
```

在输出 JSON 的 `result.meta.systemPromptReport` 中核对：

- `skills.entries` 中应出现 **`twinbox`**。
- `workspaceDir` 对应 agent 配置的专用 workspace。

**注意**：部分版本 `result.payloads` 可能为空；要机器可读验收时，以宿主 shell 的 `twinbox … --json` 为准。

### 3.7 推荐使用方式

- 为 Twinbox 使用**专用 `twinbox` agent**；通用聊天用 `main`。
- 常见只读任务优先**显式** `twinbox task ...`（或插件工具），减少依赖「模型自己选命令」。
- **skill / env 变更后**：开**新 session** 验证，勿复用旧快照会话。

### 3.8 在 OpenClaw 里完成对话引导（推荐）

在 **`twinbox` agent** 且已确认 skill 进入当前会话后：

> **已知限制（2026-03-27）**：在 `xfyun-mass` / `astron-code-latest` 上，OpenClaw 目前只把 skill `description` 注入 system prompt；`SKILL.md` body 要靠 agent 主动读取。`twinbox onboarding start|status|next --json` 又没有原生 `twinbox_onboarding_*` 工具，只能走 generic `exec`，因此该模型可能在工具调用后立刻 stop，表现为 `payloads=[]`、`assistant.content=[]` 或只剩「让我执行命令：」。这不是 Twinbox CLI 本身执行失败的充分证据。

**可观测性（推荐）**：需要可靠 JSON 验收时，在宿主终端执行：

```bash
cd "$(tr -d '\n' < ~/.config/twinbox/code-root)"
twinbox onboarding status --json
```

**引导流程**：

1. 先开**新 session**，优先发一条 **bootstrap**（`twinbox onboard openclaw` 成功后在 TTY outro 会给出可复制引文，含两段：会话引导 + 可选推送绑定）：

   ```text
   请先读取 ~/.openclaw/skills/twinbox/SKILL.md，然后在本轮内立即调用 twinbox_onboarding_status
   （或运行 twinbox onboarding status --json）。不要只说“让我执行命令：”。
   若 current_stage 不是 completed，再调用 twinbox_onboarding_start / twinbox onboarding start --json。
   可选：用 twinbox_latest_mail 做邮件链路自检（较重，会触发 daytime-sync）。
   执行后只基于真实工具输出返回 current_stage、prompt；若失败，贴 stderr。
   ```

2. 若 `current_stage` 仍需对话阶段，按返回 `prompt` 多轮收集信息；若 TTY 已完成 onboarding，可转入日常 `latest-mail` / queue 等。
   需探测服务器时配合 `twinbox mailbox detect EMAIL --json`。
3. 阶段推进：在 OpenClaw 内优先使用原生插件工具 `twinbox_onboarding_start` / `twinbox_onboarding_status` / `twinbox_onboarding_advance`；**push_subscription** 使用 `twinbox_onboarding_confirm_push`（事务性写订阅 + schedule ownership）。Shell 验收仍可用 `twinbox onboarding next --json` 等。
4. 若 bootstrap 后仍出现空 `payloads`，直接在宿主 shell 执行 `twinbox openclaw onboarding-start` 等做验收，并把问题记录为 **OpenClaw model/tool-turn 限制**。
5. 阶段顺序：`mailbox_login` → `llm_setup` → `profile_setup` → `material_import` → `routing_rules` → `push_subscription`。
   - `mailbox_login`：调用 `twinbox_mailbox_setup`（或宿主机 `twinbox mailbox setup`），密码通过 env var 传递
   - `llm_setup`：调用 `twinbox_config_set_llm`（或宿主机 `twinbox config set-llm`），API key 通过 env var 传递

**调度开关（对话中可设置）**：
onboarding 完成后，可在对话里启用或禁用定时任务：

```bash
twinbox schedule enable --job daytime-sync --json
twinbox schedule disable --job daytime-sync --json
```

或通过插件工具 `twinbox_schedule_enable` / `twinbox_schedule_disable` 调用（模型可直接触发）。
详见 [docs/ref/scheduling.md](../docs/ref/scheduling.md) 与 [SKILL.md](../SKILL.md) schedule 工具说明。

### 3.9 首次完整运行（可选验证）

邮箱和 LLM 均配置完成后，可手动运行完整 Phase 1-4 流水线验证端到端数据链路：

```bash
twinbox-orchestrate run --phase 4
```

**期望输出**：每个 phase 打印进度，最后产出 `~/.twinbox/runtime/validation/phase-4/` 下的 YAML 文件。

**如果失败**：日志位置取决于失败阶段：
- Phase 1（邮件拉取）：`~/.twinbox/runtime/validation/preflight/mailbox-smoke.stderr.log`
- Phase 2-4（LLM 处理）：stderr 直接输出；若 LLM 调用失败，检查 `~/.twinbox/twinbox.json` 中 LLM 配置是否有效

首次运行需要真实邮件数据，若 INBOX 为空会产出空 YAML，属正常现象。

### 3.10 调度与宿主桥接

默认路径：`twinbox onboard openclaw` / `twinbox deploy openclaw` 已安装 **vendor-safe** user systemd 单元（`ExecStart` 为已安装 `twinbox host bridge poll`，不依赖仓库 `scripts/`）。手动重装或排障：

```bash
twinbox host bridge install --json
twinbox host bridge status --json
twinbox host bridge poll --dry-run --format json
```

开发机 / 仓库 checkout 仍可沿用：

- `scripts/twinbox_openclaw_bridge.sh` / `scripts/twinbox_openclaw_bridge_poll.sh`
- `scripts/install_openclaw_bridge_user_units.sh`（软链到仓库内样例 [twinbox-openclaw-bridge.service](./twinbox-openclaw-bridge.service)）

---

## 4. 维护与升级

**常规升级**（代码更新）：

```bash
git pull
source .venv/bin/activate
pip install -e .
twinbox deploy openclaw --json
```

（等价于手动 `cp SKILL.md ~/.openclaw/skills/twinbox/SKILL.md` 后 `openclaw gateway restart`；若只需更新 skill 文件、不改 `openclaw.json`，仍可只执行 `cp` + 重启。）

变更后用新会话做一次 smoke：`skills info`、一条 `twinbox task --json`。

**从旧版本迁移**（state root 从仓库根迁到 `~/.twinbox`）：

旧版本的 `.env` 和 `runtime/` 数据存放在仓库根目录。升级后需要手动迁移一次到 `~/.twinbox/twinbox.json` + `runtime/`：

```bash
# 1. 运行初始化脚本（创建 ~/.twinbox，写入新路径）
bash scripts/install_openclaw_twinbox_init.sh

# 2. 迁移现有数据
python3 - <<'PY'
from pathlib import Path
from twinbox_core.env_writer import load_env_file, write_env_file
root = Path("/path/to/twinbox")
state = Path.home() / ".twinbox"
legacy_env = load_env_file(root / ".env")
if legacy_env:
    # 写入 state root 的 twinbox.json（与 write_env_file(state / ".env", …) 等价，后者会合并到 JSON）
    write_env_file(state / "twinbox.json", legacy_env)
PY
mv /path/to/twinbox/runtime ~/.twinbox/runtime

# 3. 验证路径生效
twinbox mailbox preflight --json
```

迁移后仓库根目录下不再保留旧 `.env` 和 `runtime/`，git 状态更干净。

---

## 5. 卸载

### 5.1 完整卸载

移除 systemd 单元、OpenClaw cron、sessions、skill 文件、`openclaw.json` 中 twinbox 条目、`~/.config/twinbox/` 与 runtime：

```bash
bash scripts/uninstall_openclaw_twinbox.sh
```

加 `--dry-run` 预览；加 `--with-pip` 同时卸载 Python 包。

### 5.2 仅重置运行时状态

保留 CLI、roots、openclaw.json、systemd 单元，只清空 `runtime/` 与 sessions：

```bash
bash scripts/reset_twinbox_state.sh
```

加 `--dry-run` 预览。

---

**文档版本**：本文为操作主路径；设计模型见 [docs/ref/openclaw-deploy-model.md](../docs/ref/openclaw-deploy-model.md)，排障见仓库根 [BUGFIX.md](../../BUGFIX.md)，附录见 [DEPLOY-APPENDIX.md](./DEPLOY-APPENDIX.md)。
