# 变更分类与证据治理

本规则把运行事实、长期约束和功能交付分层，避免把计划、临时操作或历史 prompt 误当作当前系统状态。

## 来源与权威顺序

冲突时依次采用：

1. 代码、测试与可复现运行事实；
2. [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md) 的不变量；
3. 当前功能的 SpecKit feature contract（`specs/<id>/spec.md`、`plan.md`、`tasks.md`）；
4. 已审阅的长期决策（[`docs/decisions/`](../decisions/README.md) ADR）；
5. [As-built baseline](../../specs/000-as-built-mcp-baseline/spec.md)（retroactive 事实回填，不是历史 SpecKit provenance）；
6. 研究假设 / 会议纪要 / 进化 prompt：只作输入，不得冒充已实现。

低优先级文档应链接并解释差异，不得静默覆盖高优先级来源。计划、待办和历史 prompt 不是已实现或已部署的证据。

按问题选入口（检索）与冲突权重不同：见仓库 [CLAUDE.md](../../CLAUDE.md)。

## 分类器与必做动作

| 类型 | 判定 | 必做动作 |
| --- | --- | --- |
| `none` | 仅调查、答复，或不改变产品、架构、运行态承诺的局部工作 | 留下命令、测试或结论证据；不创建交付 artifact。 |
| `temporary` | 有到期时间的修复、开关、绕行或运行缓解 | 记录 owner、expiry、rollback、exit 与 validation。到期前关闭、回滚或升级为 feature/decision。 |
| `feature` | 新增或持久改变用户/系统能力 | 创建或更新该功能的 SpecKit feature contract，并完成实现、验证与任务收敛。 |
| `decision` | 改变长期边界、技术选型或取舍 | 更新 constitution 或 ADR，并在受影响的 feature contract 中引用。 |

复合变更必须完成每一项附带动作。只有安全、架构边界、不可逆迁移，或多个实质等价方案时才升级请求决策。

## Artifact 状态（补充）

| 状态 | 用途 |
| --- | --- |
| **as-built baseline** | 事后回填已验证行为；标明 Known Gap；不声称历史上遵循 SpecKit。 |
| **ADR Accepted / Superseded** | 长期决策；Superseded 保留理由与替代，不删历史。 |
| **research hypothesis** | 未验证产品/文化假设；可进 `research.md`，不得写入 Success Criteria 当作事实。 |
| **Planned / Draft feature** | 已冻结意图与验收方向，实现未收敛；禁止写成当前交付面。 |

## 何时需要 SpecKit contract

- **需要**：`feature`，以及改变既有功能验收、范围或实现路径的工作。
- **不需要**：纯核查（`none`）、有明确退出条件的临时缓解（`temporary`）。
- **decision**：ADR ± constitution；再在受影响 feature 中引用，而不是只改 README。

## 场景

1. **本地文案或注释修复**：不改能力范围，通常为 `none`。
2. **分析正确性 / MCP 行为修复**：持久改变工具输出语义，为 `feature`（见 `specs/002-analysis-correctness`）。
3. **Agent OS ingest / 多账号 adapter**：平台数据平面，为 `feature`（见 `specs/001-everything-mail-adapter`，当前 Planned）。
4. **语义包 / 周报运营 / 注意力投影 / 策略自动化**：独立 `feature`（`003`–`006`），不得整包塞进 `001`/`002`。
5. **主干改名 / 默认只读边界与策略执行**：长期取舍，为 `decision`，须 ADR + constitution。
6. **SpecKit 后插入的能力盘点**：`as-built baseline`（`000`），不是新功能交付。
