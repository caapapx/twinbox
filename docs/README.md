# Docs

唯一入口。少目录、短命名、能合并就合并。

## Read first

1. [architecture.md](./ref/architecture.md)
2. [ROADMAP.md](../ROADMAP.md)（路线与待办索引）
3. [runtime.md](./ref/runtime.md)
4. [routing-rules.md](./ref/routing-rules.md) (语义分拣规则)
5. [cli.md](./ref/cli.md)
6. [rpc-protocol.md](./ref/rpc-protocol.md)（daemon JSON-RPC）/ [artifact-contract.md](./ref/artifact-contract.md)（Phase 1–4 产物路径约定）/ [code-root-developer.md](./ref/code-root-developer.md)（code root 与宿主）

## Layout

- **文档与代码不一致时**：以大范围重构分支上的 **实现与单测** 为准；先看 [daemon-and-runtime-slice.md](./ref/daemon-and-runtime-slice.md)（daemon / Go 薄壳 / 模组化模拟邮箱等**当前事实**），再读归档计划类文档。
- **本地开发 vs OpenClaw 宿主**：前者默认仓库根 `twinbox.json` + `runtime/`；后者默认 `~/.twinbox` + `~/.config/twinbox` + OpenClaw 配置 — 对照见仓库根 [README.md](../README.md)（**Choose your setup path**）/ [README.zh.md](../README.zh.md)（**选择安装路径**）。宿主操作主路径：[`integrations/openclaw/DEPLOY.md`](../integrations/openclaw/DEPLOY.md)。
- [`ref/`](./ref/architecture.md): 架构、契约、CLI、运行时参考
- [`../integrations/openclaw/`](../integrations/openclaw/README.md): OpenClaw 托管 skill、部署与宿主桥接（仓库根目录）；正式部署步骤见 [`../integrations/openclaw/DEPLOY.md`](../integrations/openclaw/DEPLOY.md)；排障见仓库根 [`BUGFIX.md`](../BUGFIX.md)；附录见 [`../integrations/openclaw/DEPLOY-APPENDIX.md`](../integrations/openclaw/DEPLOY-APPENDIX.md)
- [`ref/openclaw-deploy-model.md`](./ref/openclaw-deploy-model.md): OpenClaw 三层分工设计模型与数据流（配合 DEPLOY.md 操作路径阅读）
- **验证报告**：仅存本地 / `runtime/validation/`，勿向仓库提交实例数据（见 `docs/ref/validation.md`）
- **会话污染说明**：见仓库根 [`BUGFIX.md`](../BUGFIX.md) 小节 “OpenClaw 集成排障”。

## Rules

- **License**：Apache-2.0，见仓库根目录 [LICENSE](../LICENSE) / [NOTICE](../NOTICE)；第三方组件（如 bundled 工具）以各自许可证为准。
- 根入口保持简短，不维护大段重复索引
- 新文档优先并入现有文件；确实放不下再新建
- 优先放 `ref/` 或 `integrations/` 下与主题配套的 README
- 本地或 state root 下验证输出中的实例数据不能当成通用事实
- 新增**读者常打开的**文档时，在本页 **Read first** / **Layout** 或 `AGENTS.md`「核心文档入口」补一条链向（`validation/` 实例可只链到子索引）；详见 `AGENTS.md` 协作约束第 5 条
