# twinbox 工程指引

> 本文件是进入仓库后的**决策与工作流入口**，不是完整设计或运行手册。实施前先判定变更类型；细节回到其权威来源。
>
> **入口约定**：根目录 [AGENTS.md](AGENTS.md) 只作指针。产品 MCP 用法在仓内 `twinbox` skill。不要另建 `AGENT.md`。产品 skill 正文只在根目录 [SKILL.md](SKILL.md)；仓内 hop 只保留 [`.agents/skills/twinbox`](.agents/skills/twinbox)（软链到根 `SKILL.md`）。不要在 `.claude` / `.cursor` / `.codex` 再堆副本。单数 `.agent/` 已废弃，不要创建。

## 权威与证据顺序

**冲突才比权重**（两处写反时用来裁决，不是检索顺序）：

1. **代码、测试、运行事实**：当前行为、可复现验证与部署运行态。易变数值（采样条数、截断长度、TTL）以代码与当前 feature plan 为准，不在本文件硬编码。
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
| 人话验收 / 该粘哪句台词 | 本文件「场景验收与对照实验」；全文在根目录 `PROMPTS.md`（gitignore） | 把台词当 SpecKit 合同；把括号里的验收点一起粘贴 |
| 架构优化有没有变快/变小 | 本文件对照协议 + 本地台账 `docs/benchmarks/2026-09-15-qwenpaw-twinbox-perf.md`（gitignore）；先认 [预算层](docs/budgets.md)（读 / 注意 / 时序） | 每轮重抽 prompt 当 delta；增量窗 `analysis_ms` 对全窗基线；闸低却串第二箱；把 `RHYTHM_EOD`≈17:00 当测量错峰 |
| 查询快不快 / 过期会不会重分析 | 本文件「读路径 vs 刷新」；代码 `pulse.py` / `cli._staleness` / FR-006 | 把 pulse 当成 Redis TTL；过期查询会偷偷 IMAP/LLM |
| 热更 / 哪台机器 / 哪个口 | 仓外 release skill | 把主机表抄进本文件 |
| 对照实验怎么在 239 跑（L1/L2 脚本、闸 vLLM） | 仓外 `twinbox-release-remote` → `references/bench.md` | 把 Run 数字 / 主机口抄进 skill；协议权威仍是本文件 |
| 检索 HTTP 对接 | 现场配置与 overlays（凭据 gitignore） | 用记忆里的 URL 另起平行栈 |
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
| 场景台词何时用、对照实验怎么记 | 本文件「场景验收与对照实验」 | 把 Run 数字、主机、随机覆盖题抄进本文件 |
| 台词全文 / 工作日剧本 | 根目录 `PROMPTS.md`（gitignore；维护说明在该文件末尾） | SpecKit；本文件堆 15 节原文 |
| 对照台账（金标冻结原文、记分板、Run 日志） | `docs/benchmarks/2026-09-15-qwenpaw-twinbox-perf.md`（gitignore） | git；把 invalid Run 写进 §5 记分板 |
| 人性化预算宏（读/注意/时序/打扰；人历 vs 测量错峰） | [`docs/budgets.md`](docs/budgets.md) | 把易变数字抄死成本文件；把 17:00 当 L2 analysis 对照窗 |
| 功能范围、验收、任务状态 | `specs/<id>/` | 本文件堆需求；本地评审 HTML |
| 发版、热更、停启 | 现场 release skill（仓外） | 本文件复述 SOP |
| 检索 HTTP 对接 | 仓外 ops skill | Twinbox 核心 recipes；不要把邮件规则写进检索 skill 正文 |
| 产品 MCP 用法 | 仓内 `twinbox` skill | 发明未注册工具 |
| 真凭据 | `~/.twinbox/`（gitignore） | git、日志、本文件 |

产品 `twinbox` skill 在仓内（根 `SKILL.md`；hop 仅 `.agents/skills/twinbox`）。现场专属 ops skill 不要拷进公开树。

## 场景验收与对照实验

台词全文与 Run 数字不进 git。本文件只钉：**何时用哪把尺子、金标原文、什么叫有效对照**。细节与追加日志回本地文件。宣称优化前先认 [预算层](docs/budgets.md)（读 vs 注意 vs 时序），避免混层归因；人历含 EOD≈17:00，**测量错峰**仍仅午间+夜间。

### 何时用哪份

| 目的 | 打开 | 用法 |
| --- | --- | --- |
| 10 分钟体感 / 给宿主 Agent 可粘贴台词 | `PROMPTS.md` §1 最小试玩，或 §2 / §9 对应场景 | 只粘台词围栏；**不要**把括号里的验收点一起粘贴（除非要 Agent 自检） |
| 对照实验、宣称「优化有效」 | 本小节协议 + 台账 §2–§5 | 一轮一个自变量；金标原文永不改字 |
| 覆盖面 / 会不会走错工具 | `PROMPTS.md` 随机抽一节，台账只记「覆盖」 | **不算**性能提升 |
| 能力边界 / 反幻觉 | `PROMPTS.md` §8 / §11 / §13 记分卡 | 用路线图冒充运行态 |
| 失败注入 | `PROMPTS.md` §10 | 测完恢复密码/网络；不要在生产 vault 上做 |

`PROMPTS.md` 按节：§2 日常读邮（应不堵 IMAP）；§3 同步与 freshness；§4 账号与 vault；§5 ingest/events；§6 extract（不刷新 daily pulse）；§7 onboard；§8 action dry-run；§9 工作日剧本；§12 单工具冒烟；§15 深度总包。工具增删先改 §12，再改组合剧本。该文件是测试台词本，不是合同。

### 测评标准（自身对照）

要的是**同一金标、处理前=对照、处理后=实验**，不是每轮重抽题的普查。

| 原则 | 落点 |
| --- | --- |
| 对照 | 每个金标用例都有基线数字；没有基线的题不谈提升 |
| 单一变量 | 一轮只宣称一个处理。vLLM 负载、job、lookback、是否超时、**分析路径**（skip / 增量 / 全窗）、是否串第二箱都是无关变量 |
| 等量 | 同一 host / **同一 account_id** / `daytime-sync` lookback=7 / 同一 prompt 原文 / 冷 session；CLI 同一 argv；L2 **同路径**才对比 `analysis_ms`；L2 只在**错峰日历窗**内开跑（见下） |
| 重复 | 金标固定重测；单次超时标 **invalid**，不拿来减基线 |
| 随机 | 随机的是「将来要不要把新题升格进金标」，不是每次改测量尺子 |

**无效对照（勿再犯）**：换 prompt、换 job、超时当成功、E2E 墙钟在集群排队变化时归因 Twinbox、**增量窗 `analysis_ms` 对全窗基线**、**闸时 running 低却把超时后的下一箱当成错峰**、一次热更多刀却宣称某一刀让 analysis 变快。

### 分层（禁止混层归因）

| 层 | 怎么测 | 可归因于 |
| --- | --- | --- |
| L1 CLI | 宿主 venv `python -m twinbox_core.cli … --json`；先确认 `twinbox_core.__file__` 不是过期 `site-packages` 影子 | Twinbox 输出形状 / 本地 I/O |
| L2 sync | **只许** `daytime-sync`（lookback=7）+ **显式 `--account-id`** → 该账号 `last-run.json` | fetch / select / analysis（还要拆路径，见下表） |
| L3 E2E | 宿主 Agent 冷 session 金标原文 | 编排+模型+tool_result；墙钟默认**观察项**，除非 vLLM `num_requests_running` 与基线差 ≤2 |

L2 **测量错峰**（`MEASURE_OFFPEAK`；job 仍是 `daytime-sync` lookback=7，**不要**改成 `nightly-full`）：

| 窗 | 何时（Asia/Shanghai） | 用途 |
| --- | --- | --- |
| 午间 | **12:00–14:00**（吃饭午休） | 与夜间同等合法；不必干等夜里 |
| 夜间 | 下班后至次日上班前，**避开** `nightly-full` 那一跳（锁互斥 + lookback 30） | 同一套金标，不是另一种 job |

**`RHYTHM_EOD`≈17:00（建议 16:30–17:30）只进人历**（走前扫 todo），默认**不**进本表；除非当次 vLLM 闸过，否则 sync 不上 §5 `analysis_ms`。人历全表见 [docs/budgets.md](docs/budgets.md) §0。

日历在窗内 **不等于** 集群空：开跑前仍读 `num_requests_running`；超时后不串箱（T08）。

L2 分析路径（job 同为 `daytime-sync` 也不自动等量）：

| 路径 | 怎么认 | 可填的记分板格 |
| --- | --- | --- |
| skip | `analysis_path=skip`（或 `reason=no-new-mail`） | 只证「无新信不跑 LLM」；**禁止**填 `analysis_ms` 对全窗基线 |
| incremental | `analysis_path=incremental` | select 可记；`analysis_ms` 只能对**增量基线**，不能对 R0 全窗 |
| full | `analysis_path=full` | 才与全窗基线比 `analysis_ms`；select 的 `envelope_in` 才是整窗 |

标 **invalid**（数字可记日志，不覆盖记分板）：LLM timed out / analysis degraded；SSH 或入口不可达；金标被改写或漏跑；用了 `nightly-full` 填 analysis 格；E2E 墙钟未记录 vLLM running；**L2 未写 account_id / 分析路径 / 开跑时 running**；为凑全窗而删 YAML 却不把「删 YAML」写成自变量。

金标 vs 覆盖：金标原文冻结；改题 = 新 ID，从下一 Run 才有基线。覆盖只验走错工具 / 越权。

### 金标用例（冻结；出处 `PROMPTS.md`）

G5 在 `proposals=0` 时 **skip**，不是失败。

| ID | 来源 | 原文（复制即跑） | 期望工具 |
| --- | --- | --- | --- |
| G1 | §8 | 给我看当前的动作提案（action_proposals）。说明这些是 dry-run，不会 SMTP 发送，也不会改 IMAP 邮件状态。 | `action_proposals` |
| G2 | §5 | 列出 twinbox_events（limit 20）。确认是结构化事件/引用，不是全文；若为空，说明需要先 sync/分析还是当前就是空。 | `events` |
| G3 | §2.1 | 有没有新未读？只看未读线程。 | `latest_mail` unread |
| G4 | §2.2 | 今天有什么待办和待回复？按紧急程度排一下，每条给主题 + 为什么紧急。 | `todo` |
| G5 | §8 | 把某条提案 reject，原因写「策略过宽」。然后再拉提案列表看状态变化。 | `action_review`；无提案则 skip |
| G6 | §2.1 | 我刚打开电脑，先别同步。立刻告诉我最新邮件是谁发的——这是在测查询延迟，请报一下你调用了哪个工具、大概多久返回。 | `latest_mail`；禁止 sync |

CLI 金标 argv：C1 `status`；C2 `accounts list`；C3 `todo`；C4 `weekly`；C5 `events --limit 20`；C6 `ingest --limit 10`；C7 `actions proposals`；C8 `latest-mail`；C9 `latest-mail --unread-only`；C10 `thread --query 部署`。

### 记分板只认这些指标

| 指标 | 层 | 可比条件 | 目标（相对基线） |
| --- | --- | --- | --- |
| `cli_ms` / `cli_bytes` | L1 | 同 argv | 查询类保持亚秒；C8 卡片保持小 |
| `e2e_tool_bytes` | L3 | 同 Gx；冷 session | 与 L1 同向才谈压缩机 |
| `e2e_wall_s` | L3 | 仅当 vLLM running 接近基线 | 默认观察 |
| `fetch_ms` / `analysis_ms` | L2 | 同账号 + daytime-sync + analysis ok + **同路径**（全窗对全窗）；开跑时 vLLM 接近该基线 | fetch ≪ analysis |
| `select.envelope_in/llm` | L2 | `last-run.select`；超时也可有计数；路径不限 | `llm < in` 才算 select 生效；**不等于** analysis 变快 |
| 能力面 | L3 | 金标每次勾 | MCP 对、无正文、不发信 |

禁止把 `e2e_wall_s` 单独写成「压缩机有效」，除非 L1 `cli_bytes` 与 L3 `e2e_tool_bytes` 同向，且声明了相近 vLLM 负载。

活记分板与 Run 日志只追加在 gitignore 台账；宣称有效必须点名 **valid** 配对。一轮填：Run-id、唯一自变量、代码/热更、**account_id**、分析路径、`new_envelope_count`、vLLM（闸 / **该账号开跑** / 结束）、job、金标是否跑全、判定 valid/invalid。L2 **一次只跑一箱**；超时或 running 升上去之后，必须再闸，禁止立刻开下一箱。

### 能力面勾选（测完才算验收，不是性能）

查询未要求时不乱 sync；stale 不阻塞 IMAP；sync 有 `run_id` 且 `recent_runs` 能对上；freshness 区分 attempt/success；accounts 仅 `password_set`；ingest/events 无正文；多账号不串箱；一箱失败不拖死另一箱；`queue_action` 只动本地队列；action_* 不发信；extract 不刷新 daily pulse；IDLE/Graph/企业 HTTP/真发送不说成已上线。

## 不可绕过的护栏

完整约束以 [constitution](.specify/memory/constitution.md) 为准。尤其：默认读路径不对真实邮箱 send / move / delete / archive / flag；任何副作用须匹配 Automation Policy（见 ADR-002 / `006`）；不得把邮件全文写入 Agent OS / 平台侧存储；不得破坏既有 `twinbox_*` 工具名与 envelope 形状；不得在输出、日志或追踪文件中暴露凭据；Semantic Pack 禁止可执行代码。

环境与凭证以**当前磁盘配置**（`~/.twinbox/`、现场 state、skill `.credentials`）为准，禁止用对话记忆另起一套主机/密钥。

## 误判（换现场仍成立再追加；不改已有 ID）

| ID | 误判 | 先拆 |
| --- | --- | --- |
| T01 | 源码已合 / pytest 绿 = 部署主机已是该版本 | 点名 commit、是否跑过现场热更、运行态 probe |
| T02 | SpecKit / ADR / 本文件交付表写了 = 已在跑 | 看代码与运行态；计划不是证据 |
| T03 | 本机 MCP 工具可用 = 宿主 Agent 同一套 | 注册表 vs 现场 bind 目录 |
| T04 | 检索 / embedding 失败 = pulse 整条挂 | 检索降级不得挡 `run_analysis`；IMAP 权威仍在 |
| T05 | 记忆里的 URL/端口 = 当前栈 | 读 env / `.credentials` / `twinbox.json`，不要平行发明 |
| T06 | pulse 过期 = 下次查询会自动重分析 | 过期只标 `staleness.stale`；重分析只走 cron 或显式 `twinbox_sync` |
| T07 | `daytime-sync` 且 analysis ok = 可与全窗基线比 `analysis_ms` | 先认路径：skip / 增量 / 全窗；增量窗只对增量基线 |
| T08 | 等闸时 running 低 = 本轮错峰 | 每个 `account_id` 开跑前再读 metrics；超时后客户端已返回，服务端仍可能占槽，禁止立刻串下一箱 |
| T09 | checkout 热更了 = 测到的是新代码 | 看宿主 venv `twinbox_core.__file__` 与源码 md5；cron 常走 `site-packages` |
| T10 | 只有夜里才算错峰 / 时钟在午休 = 集群一定空 | 午间 12:00–14:00 与夜间都是合法窗；窗内仍要读 running，job 仍是 daytime-sync |
| T11 | 下班前 ≈17:00 = 可填 analysis 记分板的错峰 | `RHYTHM_EOD` 是人历读节点；`MEASURE_OFFPEAK` 仅午+夜（见 [docs/budgets.md](docs/budgets.md)） |

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
| SpecKit · 薄契约（`temporary` / 局部 `feature`，一次 PR 收口） | 本文件分类器 + `specs/<id>/` | `spec.md` + `tasks.md`（`plan.md` 可省） | 实现对齐 `tasks.md`；不跑 clarify / analyze 仪式 |
| SpecKit · 完整档（持久能力 / 跨模块 / 含 `decision`） | 分类器 + constitution + `specs/<id>/` | `specify →（歧义则 clarify）→ plan → tasks`；checklist 按风险；spec 不写技术栈，进 plan | 过 `analyze` 才实现；`converge` 后才标 `implemented`；对话改范围先回写 spec / tasks |
| 热更到宿主 Agent | 仓外 release skill | 只同步源码，不改凭据 | 现场 probe；pytest 全绿 ≠ 运行态已更新 |
| 检索探活 / 灌库 | 仓外 ops skill；Twinbox 约束 overlays | 现场 KB 与映射表（产品代码走独立 SpecKit） | 禁止把全文当 file 上传 |
| 配置 | constitution V | 追踪默认值在 `config/`；真凭据只在 `~/.twinbox/` | `twinbox_status` 输出须脱敏 |
| 对照实验 / 宣称优化有效 | 本文件「场景验收与对照实验」；现场脚本仓外 `twinbox-release-remote` `references/bench.md` | 只改一个自变量；L2 一箱一闸；数字追加 gitignore 台账 | 金标 G1–G6 + C1–C10；路径不同或超时不进 `analysis_ms` 格 |

调试：修改 `twinbox_core` 后直接跑 CLI，无需重启 daemon。pytest 全绿 ≠ 宿主运行态已更新。

## 代码搜索（zg 与 claude-context 双轨）

两条轨职责不同，**不要合并成一条默认路径**。权威以活进程 / HTTP 探活为准。embedding 模型与维数以当前部署配置为准，换维须清库重嵌。Cursor 启动器若用本地脚本，勿用 `npx -y @latest`。

| 轨 | 工具 | embedding | 何时用 |
| --- | --- | --- | --- |
| 快轨 | **zg**（zvec-grep） | 本地代码 embedding | 日常语义、离线、<0.3s |
| 重轨 | MCP `claude-context` → `search_code` | 自托管 OpenAI 兼容 embedding | 难语义、跨文件 |

| 场景 | 工具与操作 |
| --- | --- |
| 精确符号 / 路径已知 | `Read` / `Grep`，或 `zg query --rg "<symbol>"` |
| 本地快速语义 | `zg query "自然语言"` / MCP `zvec_grep_search` |
| 集群语义发现 | `search_code`（仅当该绝对 path 已索引） |
| 重轨不可用 | **明示降级**到 zg / Grep；禁止假装还能向量搜 |

核心与测试 **各搜一次**。禁止工作区根、空 path、`archive/openclaw-monolith`、未跟踪残留、`~/.twinbox/` 当第三种代码根。禁止同概念同轮 Grep + `search_code` / `zg` 对扫。两轮仍找不到则停并问。`query` 用自然语言；以 `Read` 源码为准绳。邮件正文、凭据、pulse JSON 不当索引语料。**勿**把 zg 默认改成远程 Embedding（会拖垮快轨）。

## 当前交付面 vs Planned

本表**易过期**，冲突时以 `mcp-server.mjs` 注册表、代码和 `.specify/feature.json` 为准。

- **已实现（as-built）**：[`specs/000-as-built-mcp-baseline`](specs/000-as-built-mcp-baseline/spec.md) 是插入 SpecKit 前的回填；其后合并进主干的工具以 MCP 入口为准（含 onboard / action 提案等，不必在本文件逐条同步）。
- **活跃功能**：[`.specify/feature.json`](.specify/feature.json)。
- **Planned 合同**：`specs/001`（部分落地）、`003`–`007`、`008`/`010`（触发后）、`009`（IDLE）；未在代码落地前不要写成当前交付面。
- **企业路线已确认实施**：Phase 0 合同 + Phase 1 多账号只读 + 最小可观测性；Phase 2/6 触发后做；Phase 3+ 按路线顺序。
- **决策**：[`docs/decisions/`](docs/decisions/README.md)。

## 读路径 vs 刷新（物化快照，不是 TTL 缓存）

查询延迟靠 **磁盘上的 pulse JSON**；新鲜度靠 **调度或显式 sync**。没有 Redis、没有「过期自动重算」的读旁路。易变阈值以代码为准（`STALE_HOURS_DEFAULT`、lookback、`MAX_RUN_HISTORY`），不要把数字抄死成本节法律。

| 层 | 落点 | 读/写行为 | 过期 / 背压 |
| --- | --- | --- | --- |
| 查询投影 | `activity-pulse.json` | `latest_mail` / `todo` / `weekly` 只读快照 | **缺失** → MCP 自动完整 sync；**仅过期** → 原样返回 + `staleness.stale`，不 IMAP、不 LLM |
| 分析产物 | `daily-urgent.yaml` 等 | daytime：无新信 **skip LLM**；有新信封按 thread_key **合并**；`nightly-full` 才整窗重写 | `quick-refresh` **跳过 LLM**，pulse 仍重建；查询 staleness 看的是 pulse `generated_at`，不是分析时刻 |
| IMAP 增量 | `uid-watermarks.json` + `envelopes-merged.json` | 只拉 `last_uid+1:*`，再按 lookback 裁窗口 | 窗口外信封/正文会 trim；**不是**分析缓存 |
| embedding sidecar | `runtime/context/embeddings/*.json` | 有文件则跳过（write-once）；`embed_new_messages` 会 prune 窗口外 sidecar | 无独立 TTL；GC 挂在 fetch/embed 写路径 |
| 调度互斥 | `schedule/run-due.lock` | cron 并发时 `skipped: locked` | 写路径背压，防双跑 LLM |
| 运行日志 | `runtime/runs/history.jsonl` | 追加 | 滚动保留 `MAX_RUN_HISTORY` |
| 查询载荷 | CLI `_compact_*` | latest ≤5 / todo ≤20 卡片 | 减的是 **Agent 上下文**，不是磁盘 pulse 全文 |

**没有的**：读路径 TTL 触发重分析；通用 HTTP/LLM prompt cache。vLLM `cache_input_tokens` 是宿主侧，不是 Twinbox 引擎。daytime 增量合并 **有**，所以 L2 对照必须先认路径（T07）。

## 关键路径

| 用途 | 路径 |
|------|------|
| Skill 定义 | `SKILL.md` |
| 场景台词本 | `PROMPTS.md`（gitignore） |
| 对照台账 | `docs/benchmarks/2026-09-15-qwenpaw-twinbox-perf.md`（gitignore） |
| 人性化预算宏 | [`docs/budgets.md`](docs/budgets.md) |
| Python 核心 | `twinbox_core/` |
| Vault / runs / ingest | `twinbox_core/vault.py` · `runs.py` · `adapter.py` |
| CLI 入口 | `twinbox_core/cli.py` |
| MCP 入口 | `mcp-server.mjs` |
| 本地配置 | `~/.twinbox/twinbox.json` |
| 宪法 | `.specify/memory/constitution.md` |
| ADR | `docs/decisions/` |
