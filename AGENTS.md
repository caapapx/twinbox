# Agent Instructions（入口，勿在此维护正文）

本仓库怎么干活只维护一份：[AGENTS.md](./AGENTS.md)。

@AGENTS.md

产品 MCP 用法：仓内 `twinbox` skill（`.cursor/skills/twinbox`、`.codex/skills/twinbox`）。热更本机 `twinbox-release-remote`；239 现场 `twinbox-release-local`（尚未建则仍走 remote 文档，勿把 local 拷到 Mac）。

---

<!-- Migrated from AGENTS.md -->

# twinbox 工程指引

> 本文件是进入仓库后的**决策与工作流入口**，不是完整设计或运行手册。实施前先判定变更类型；细节回到其权威来源。
>
> **入口约定**：根目录 [AGENTS.md](AGENTS.md) 只作指针。产品 MCP 用法在仓内 `twinbox` skill；热更/主机在 `twinbox-release-remote`。不要另建 `AGENT.md`，不要在 `.claude` / `.agents` / `.cursor` 堆 skill 正文副本。

## 权威与证据顺序

**冲突才比权重**（两处写反时用来裁决，不是检索顺序）：

1. **代码、测试、运行事实**：当前行为、可复现验证与本地/239 状态。易变数值（采样条数、截断长度、TTL）以代码与当前 feature plan 为准，不在本文件硬编码。
2. [**constitution**](.specify/memory/constitution.md)：邮箱变更边界、全文边界、工具契约与凭据不变量。
3. **SpecKit feature contract**：当前功能目录中的 `spec.md`、`plan.md`、`tasks.md`，定义已批准功能的范围与验收。
4. [**ADR**](docs/decisions/README.md)：长期取舍；修宪须引用。
5. [**变更分类**](docs/governance/change-classification.md)：决定是否建 artifact、以及 artifact 不能冒充运行事实。
6. [**As-built baseline**](specs/000-as-built-mcp-baseline/spec.md)：SpecKit 插入前的已验证事实回填（非历史 provenance）。

计划、待办、进化 prompt、评审草稿不能单独当「已上线」。宣称交付须能点名三层：**源码、测试（或制品）、运行态**；缺一层标未验证。

### 按问题选入口

先判断问题类型，只打开对应入口；没点名的层不要预读。

| 在问什么 | 先打开 | 不要先做 |
| --- | --- | --- |
| 范围 / 验收 / 做到哪了 | SpecKit `spec` / `plan` / `tasks`；活跃目录 [`.specify/feature.json`](.specify/feature.json) | 通读实现或扫全仓 |
| 接口现在什么样 / bug 在哪 | 代码、测试、当时那条 CLI / MCP 运行态 | 用本文件「交付面」表或历史 prompt 猜 |
| 热更 / 哪台机器 / 哪个口 | skill `twinbox-release-remote` | 把主机表抄进本文件 |
| WeKnora HTTP | skill `weknora-ops`（凭据 gitignore） | 用记忆里的 URL 另起平行栈 |
| 当时为什么选 A 不选 B | ADR / constitution | 当场重推一遍 |
| 代码在哪 / 怎么串起来 | 下一节「代码搜索」 | 通读全仓；同概念双轨对扫 |

## 先分类，再行动

每项工作先按[变更分类](docs/governance/change-classification.md)标为一种：

| 类型 | 适用范围 | 必做后续 |
| --- | --- | --- |
| `none` | 纯核查或不改变产品承诺的局部工作 | 记录验证结论；不建 SpecKit artifact。 |
| `temporary` | 有限期修复、开关或绕行 | 记录 owner / expiry / rollback / exit；到期关闭或升级。 |
| `feature` | 新的持久用户/系统能力 | 建立或更新 SpecKit feature contract，并按任务实施和验证。 |
| `decision` | 改变长期技术/产品取舍 | 修订 constitution（或 ADR），并在受影响 contract 中引用。 |

热更、探活、对一下现场默认 `none`（验证写在 release skill / 对话结论里）。改变现场默认拓扑或检索后端才升级为 `feature` / `decision`。

仅在以下情形升级请人决策：安全边界、架构边界、不可逆迁移，或存在实质上同等的多个方案。其余事项先依据权威来源推进并留下证据。

## 写哪里

| 这类工作 | 写这里 | 不要写这里 |
| --- | --- | --- |
| 仓库怎么协作、选哪扇门 | 本文件 | skill 全文、主机/端口表 |
| 功能范围、验收、任务状态 | `specs/<id>/` | 本文件堆需求；历史 `twinbox-evolution-prompt.md` |
| 发版、热更、239/251、停启 | `twinbox-release-remote` | 本文件复述 SOP |
| WeKnora HTTP 对接 | `weknora-ops` | Twinbox 核心 recipes；把邮件规则写进 WeKnora skill 正文 |
| 产品 MCP 用法 | 仓内 `twinbox` skill | 发明未注册工具 |
| 真凭据 | `~/.twinbox/`、skill `scripts/.credentials`（gitignore） | git、日志、本文件 |

项目 skill 正文只在 `~/fun/skill-manager/private/`；本仓 hop 目录只软链。本机 `*-release-remote`；`*-local` 只留现场，勿拷到 Mac。

## 不可绕过的护栏

完整约束以 [constitution](.specify/memory/constitution.md) 为准。尤其：默认读路径不对真实邮箱 send / move / delete / archive / flag；任何副作用须匹配 Automation Policy（见 ADR-002 / `006`）；不得把邮件全文写入 Agent OS / 平台侧存储；不得破坏既有 `twinbox_*` 工具名与 envelope 形状；不得在输出、日志或追踪文件中暴露凭据；Semantic Pack 禁止可执行代码。

环境与凭证以**当前磁盘配置**（`~/.twinbox/`、现场 state、skill `.credentials`）为准，禁止用对话记忆另起一套主机/密钥。

## 误判（换现场仍成立再追加；不改已有 ID）

| ID | 误判 | 先拆 |
| --- | --- | --- |
| T01 | 源码已合 / pytest 绿 = 239 已是该版本 | 点名 commit、是否跑过 `twinbox-release-remote`、现场 probe |
| T02 | SpecKit / ADR / 本文件交付表写了 = 已在跑 | 看代码与运行态；计划不是证据 |
| T03 | 本机 MCP 工具可用 = 239 QwenPaw 同一套 | 注册表 vs 现场 bind 目录 |
| T04 | WeKnora / embedding 失败 = pulse 整条挂 | 检索降级不得挡 `run_analysis`；IMAP 权威仍在 |
| T05 | 记忆里的 URL/端口 = 当前栈 | 读 env / `.credentials` / `twinbox.json`，不要平行发明 |

## 主干

- **`master`**：默认主干（MCP Skill / CLI）。不要用 `feat/*` 当长期主干。
- **`archive/openclaw-monolith`**：冻结的旧大栈，不再当默认分支。
- 不要再把主干叫 `openclaw-skill`、`feat/mcp-server` 或 `main`。
- 在 **git 跟踪范围内**干活；不要把归档分支或本机未跟踪残留当产品代码。

提交/推送仅在用户明确要求时做。密钥不进受追踪文件。

## 任务手册（最小路径）

| 场景 | 先读 | 改哪里 | 验证 |
| --- | --- | --- | --- |
| IMAP 抓取 / MIME / 采样 | constitution I–II；相关 `specs/*/spec.md` | `twinbox_core/imap_fetch.py` | `python3 -m twinbox_core.cli <cmd> --json`；相关 pytest |
| 分析 / 队列标签 / pulse | constitution II–IV | `twinbox_core/analyze.py`、`pulse.py`、`queue.py` | 构造邮件 + mock LLM；不要依赖真实 IMAP |
| MCP 工具层 | constitution IV | `mcp-server.mjs` | `tests/mcp-smoke.mjs` |
| 抽取 / 小时过滤 | constitution II、IV | `twinbox_core/extract.py`、`cli.py` | `tests/test_extract.py` |
| SpecKit 新功能或范围变更 | 本文件分类器 + 对应 `specs/<id>/` | `spec.md` / `plan.md` / `tasks.md` | analyze；实现与验收对齐 tasks |
| 热更到 239 QwenPaw | skill `twinbox-release-remote` | 只同步源码，不改凭据 | `./scripts/hot-reload-239.sh`；`probe-239.sh` |
| WeKnora 探活 / 灌库 / 检索 | skill `weknora-ops`；Twinbox 约束 `overlays/twinbox.md` | 现场 KB 与映射表（产品代码走独立 SpecKit） | `wk.sh probe`；禁止把全文当 file 上传 |
| 配置 | constitution V | 追踪默认值在 `config/`；真凭据只在 `~/.twinbox/` | `twinbox_status` 输出须脱敏 |

调试：修改 `twinbox_core` 后直接跑 CLI，无需重启 daemon。pytest 全绿 ≠ 239 运行态已更新。

## 代码搜索（zg 与 claude-context 双轨）

两条轨职责不同，**不要合并成一条默认路径**。权威以活进程 / HTTP 探活为准（当前 251 `:18010` 是 `Qwen3-Embedding-4B` / **2560** 维；旧 8B/4096 已下线）。换维须清库重嵌。Cursor 启动器：`~/.cursor/claude-context-mcp.sh`（勿用 `npx -y @latest`）。

| 轨 | 工具 | embedding | 何时用 |
| --- | --- | --- | --- |
| 快轨 | **zg**（zvec-grep） | 本地 `potion-code-16m-v2`（256 维） | 日常语义、离线、<0.3s |
| 重轨 | MCP `claude-context` → `search_code` | OpenAI 兼容 → 251 `:18010` | 难语义、跨文件 |

| 场景 | 工具与操作 |
| --- | --- |
| 精确符号 / 路径已知 | `Read` / `Grep`，或 `zg query --rg "<symbol>"` |
| 本地快速语义 | `zg query "自然语言"` / MCP `zvec_grep_search` |
| 集群语义发现 | `search_code`（仅当该绝对 path 已索引） |
| 重轨不可用 | **明示降级**到 zg / Grep；禁止假装还能向量搜 |

| 宿主 | 核心 path | 测试/契约 path |
| --- | --- | --- |
| Mac | `/Users/caapap/fun/twinbox/twinbox_core` | `/Users/caapap/fun/twinbox/tests` |
| 239 | `/iflytek/server/twinbox-server/twinbox_core` | `/iflytek/server/twinbox-server/tests` |

禁止工作区根、空 path、`archive/openclaw-monolith`、未跟踪残留、`~/.twinbox/` 当第三种代码根。核心与测试 **各搜一次**。禁止同概念同轮 Grep + `search_code` / `zg` 对扫。两轮仍找不到则停并问。`query` 用自然语言；以 `Read` 源码为准绳。不要把 CodeGraph 当前置。邮件正文、凭据、pulse JSON 不当索引语料。**勿**把 zg 默认改成远程 Embedding（会拖垮快轨并抢 GPU）。

## 当前交付面 vs Planned

本表**易过期**，冲突时以 `mcp-server.mjs` 注册表、代码和 `.specify/feature.json` 为准。

- **已实现（as-built）**：[`specs/000-as-built-mcp-baseline`](specs/000-as-built-mcp-baseline/spec.md) 是插入 SpecKit 前的回填；其后合并进主干的工具以 MCP 入口为准（含 onboard / action 提案等，不必在本文件逐条同步）。
- **活跃功能**：[`.specify/feature.json`](.specify/feature.json)。
- **Planned 合同**：`specs/001`–`007` 等目录；未在代码落地前不要写成当前交付面。
- **决策**：[`docs/decisions/`](docs/decisions/README.md)。
- [`twinbox-evolution-prompt.md`](twinbox-evolution-prompt.md) 只是历史输入。

## 关键路径

| 用途 | 路径 |
|------|------|
| Skill 定义 | `SKILL.md` |
| Python 核心 | `twinbox_core/` |
| CLI 入口 | `twinbox_core/cli.py` |
| MCP 入口 | `mcp-server.mjs` |
| 本地配置 | `~/.twinbox/twinbox.json` |
| 宪法 | `.specify/memory/constitution.md` |
| ADR | `docs/decisions/` |
