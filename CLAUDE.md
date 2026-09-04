# twinbox 工程指引

> 本文件是进入仓库后的**决策与工作流入口**，不是完整设计或运行手册。实施前先判定变更类型；细节回到其权威来源。

## 权威与证据顺序

冲突时按以下顺序处理；低层文档不得覆盖高层事实或约束：

1. **代码、测试、运行事实**：当前行为、可复现验证与本地状态。易变数值（采样条数、截断长度、TTL）以代码与当前 feature plan 为准，不在本文件硬编码。
2. [**constitution**](.specify/memory/constitution.md)：不可违背的只读邮箱、全文边界、工具契约与凭据不变量。
3. **SpecKit feature contract**：当前功能目录中的 `spec.md`、`plan.md`、`tasks.md`，定义已批准功能的范围与验收。
4. [**变更分类**](docs/governance/change-classification.md)：决定是否建 artifact、以及 artifact 不能冒充运行事实。

## 先分类，再行动

每项工作先按[变更分类](docs/governance/change-classification.md)标为一种：

| 类型 | 适用范围 | 必做后续 |
| --- | --- | --- |
| `none` | 纯核查或不改变产品承诺的局部工作 | 记录验证结论；不建 SpecKit artifact。 |
| `temporary` | 有限期修复、开关或绕行 | 记录 owner / expiry / rollback / exit；到期关闭或升级。 |
| `feature` | 新的持久用户/系统能力 | 建立或更新 SpecKit feature contract，并按任务实施和验证。 |
| `decision` | 改变长期技术/产品取舍 | 修订 constitution（或 ADR），并在受影响 contract 中引用。 |

仅在以下情形升级请人决策：安全边界、架构边界、不可逆迁移，或存在实质上同等的多个方案。其余事项先依据权威来源推进并留下证据。

## 不可绕过的护栏

完整约束以 [constitution](.specify/memory/constitution.md) 为准。尤其不得：对真实邮箱 send / move / delete / archive / flag；把邮件全文写入 Agent OS / 平台侧存储；破坏既有 `twinbox_*` 工具名与 envelope 形状；在输出、日志或追踪文件中暴露凭据。

## 主干

- **`master`**：默认主干（MCP Skill / CLI）。不要用 `feat/*` 当长期主干。
- **`archive/openclaw-monolith`**：冻结的旧大栈，不再当默认分支。
- 不要再把主干叫 `openclaw-skill`、`feat/mcp-server` 或 `main`。

## 任务手册（最小路径）

| 场景 | 先读 | 改哪里 | 验证 |
| --- | --- | --- | --- |
| IMAP 抓取 / MIME / 采样 | constitution I–II；相关 `specs/*/spec.md` | `twinbox_core/imap_fetch.py` | `python3 -m twinbox_core.cli <cmd> --json`；相关 pytest |
| 分析 / 队列标签 / pulse | constitution II–IV | `twinbox_core/analyze.py`、`pulse.py`、`queue.py` | 构造邮件 + mock LLM；不要依赖真实 IMAP |
| MCP 工具层 | constitution IV | `mcp-server.mjs` | `tests/mcp-smoke.mjs` |
| 抽取 / 小时过滤 | constitution II、IV | `twinbox_core/extract.py`、`cli.py` | `tests/test_extract.py` |
| SpecKit 新功能或范围变更 | 本文件分类器 + 对应 `specs/<id>/` | `spec.md` / `plan.md` / `tasks.md` | analyze；实现与验收对齐 tasks |
| 配置 | constitution V | 追踪默认值在 `config/`；真凭据只在 `~/.twinbox/` | `twinbox_status` 输出须脱敏 |

调试：修改 `twinbox_core` 后直接跑 CLI，无需重启 daemon。默认不自动 commit / push。

## 当前交付面 vs Planned

- **已实现**：9 个 `twinbox_*` MCP 工具（`mcp-server.mjs` → `python3 -m twinbox_core.cli`）。
- **Planned / 未收敛**：[`specs/001-everything-mail-adapter`](specs/001-everything-mail-adapter/spec.md)（Agent OS ingest、多账号 vault）。不要把它写成已上线能力。
- **当前 feature**：分析正确性见 [`specs/002-analysis-correctness`](specs/002-analysis-correctness/spec.md)。实现前以该 contract 为准；[`twinbox-evolution-prompt.md`](twinbox-evolution-prompt.md) 只是历史输入。

## 关键路径

| 用途 | 路径 |
|------|------|
| Skill 定义 | `SKILL.md` |
| Python 核心 | `twinbox_core/` |
| CLI 入口 | `twinbox_core/cli.py` |
| MCP 入口 | `mcp-server.mjs` |
| 本地配置 | `~/.twinbox/twinbox.json` |
| 宪法 | `.specify/memory/constitution.md` |
