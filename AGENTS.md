# AGENTS.md

本文件为仓库**协作与文档约定的完整版**。根目录 **`CLAUDE.md`** 为其摘要，供助手快速加载；二者不一致时以 **本文** 为准。

## 文档索引规则

| 目录 | 用途 | 命名规则 |
|------|------|----------|
| src/twinbox_core/ | Python 核心库（Phase 1-4、CLI、LLM、daemon、测试种子）| 按模块命名 |
| tests/ | Python 单元测试 | `test_<module>.py` |
| scripts/ | Shell 流水线脚本（phase 加载/思考/合并）、宿主辅助脚本 | `phase<N>_<step>.sh`、`seed_modular_mail_sim.sh` 等 |
| config/ | 运行时配置（用户画像、策略、行动模板） | `<name>.yaml` / `<name>.toml` |
| agent/ | TypeScript 扩展契约骨架（spec-first，尚未完整实现） | `*.ts` |
| docs/ref/ | 架构、契约、CLI、运行时参考 | 短名优先，如 `cli.md` |
| docs/validation/ | 实例级验证报告（本地数据，不入公开发布） | `phase-N-report.md` |
| docs/assets/ | 图片、静态资源 | 按需 |

## 核心文档入口

- 文档入口：`docs/README.md`
- 架构：`docs/ref/architecture.md`
- OpenClaw 部署操作主路径：`integrations/openclaw/DEPLOY.md`
- OpenClaw 部署设计模型：`docs/ref/openclaw-deploy-model.md`
- OpenClaw 排障与回滚：`integrations/openclaw/TROUBLESHOOT.md`
- OpenClaw 部署附录：`integrations/openclaw/DEPLOY-APPENDIX.md`
- 路线与待办索引：`ROADMAP.md`
- Daemon / Go 薄壳 / 模组化测试（**当前事实，优先于旧「暂缓 Go」表述**）：`docs/ref/daemon-and-runtime-slice.md`
- Daemon JSON-RPC：`docs/ref/rpc-protocol.md`；Phase 产物路径约定：`docs/ref/artifact-contract.md`
- Code root 开发者说明：`docs/ref/code-root-developer.md`
- 验证工件契约：`docs/ref/validation.md`
- 编排契约：`docs/ref/orchestration.md`
- 运行时规范：`docs/ref/runtime.md`
- 语义规则引擎：`docs/ref/routing-rules.md`

（原 `docs/archive/`、`docs/guide/` 目录已移除；旧版 Phase 报告与归档文如需可查 git 历史。）

## 协作约束

1. 所有文档先看 `docs/README.md`，优先并入现有文件，不轻易新增目录或文件
2. 新增文档前先检查是否有可合并的已有文档
3. validation/ 下的内容是实例数据，不应被方案文档引用为"事实"
4. 文档内交叉引用使用相对路径
5. **新增或移动**文档路径时，同步更新**可发现性**（至少一处，避免零索引）：
   - 常用契约/指南：在 `docs/README.md` 的 **Read first** 或 **Layout** 增删一条链接，和/或在本文 **核心文档入口** 增删一条；或
   - 落在已有子包/子目录时：更新该目录的 **README.md**（例如 `integrations/openclaw/README.md`）
   - **可不上抬到 Read first 的情况**：`docs/validation/` 实例报告，只需在主题文档或子索引中链入即可
6. **Git 提交与推送（默认不自动）**：代理**不要**在任务结束时自动执行 `git commit` 或 `git push`。完成改动后给出变更摘要即可；**仅当用户在本轮对话中明确要求**提交、推送、或「提交并推送」时，再执行相应 Git 操作。用户未提及时，假定由用户在本地自行 `commit` / `push`。
   - **高置信度门槛**（用户要求提交时仍适用）：已对变更范围跑过约定检查（例如相关 `pytest`、或任务指定的 smoke/脚本），失败已处理或已说明为何不跑
   - **变更粒度**：优先按**可独立验收的一整块任务**（一个逻辑完整的修复或功能）组织提交；避免把互不相关的改动塞进同一 commit，也避免仅为「小步」而把同一任务拆成大量无意义碎提交。与「评测/任务是否以单个 commit 为粒度」无关——仓库关心的是**语义完整 + 可验证**，而非 commit 个数本身
   - **提交**：`git add` 仅包含本次任务相关改动；提交信息遵守 `type: short description`；推送前用 `git status` 确认无意外未提交文件
   - **推送**：具备 `git` 写权限与网络、且用户**明确要求推送**、且**未**要求「勿推送 / 仅本地 / draft」时，执行 `git push` 到**当前分支已设置的上游**（如 `origin/dev-go`）；合并入仓库主线后，主分支通常为 `master`
   - **环境受限**：沙箱禁用网络、无凭据、或推送被拒时，说明原因并保留本地改动，由用户手动 `git commit` / `git push`
   - **禁止**：对共享分支 `git push --force`；非用户明确要求不擅自 `git commit --no-verify` / 绕过 hook
7. **Skill 与 OpenClaw 同步约束**：当新增或修改 CLI 命令、核心功能（如新增参数、修改规则逻辑）或 OpenClaw Tool (`register-twinbox-tools.mjs`) 时，**必须**执行以下同步操作：
   - 更新 `SKILL.md`（以及 `.agents/skills/twinbox/SKILL.md` 等相关副本）中对应的说明、参数和示例。
   - 重新加载 OpenClaw 网关以使 Tool 变更生效：`openclaw gateway restart`
8. **Go 交付与运行时打包约束**（发布形态）：
   - 用户侧命令名固定为 **`twinbox`**。Go 源码目录可保留 `cmd/twinbox-go/`，但交付产物必须构建为 `dist/twinbox`（而非 `twinbox-go`）。
   - `twinbox` 二进制默认按用户级安装到 `PATH`（推荐 `~/.local/bin`），**不要**放在 `~/.twinbox` 这类 state root 下，也不要在日常流程里用 `sudo twinbox ...`。
   - 用户级安装后，需把 `~/.local/bin` 持久化到 shell 启动文件（当前约定：`~/.bashrc`，例如 `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc`），避免重开终端后命令丢失。
   - Python 运行时与 OpenClaw 宿主资源通过归档交付：执行 `scripts/package_vendor_tarball.sh` 产出 `dist/twinbox_core-<version>.tar.gz`（内含 `twinbox_core/`、`integrations/openclaw/`、根 `SKILL.md`、`scripts/install_openclaw_twinbox_init.sh`；排除 `__pycache__` 与插件 `node_modules`），供 `twinbox install --archive ...` 解压到 `vendor/` 并写入 `~/.twinbox/code-root` 指向该目录（旧版 `~/.config/twinbox/code-root` 仍可读）；开发时仍可用 `TWINBOX_CODE_ROOT` 指向 git 仓库。**OpenClaw 插件**在网关侧只加载已提交的 `plugin-twinbox-task/dist/index.mjs`（esbuild 打包），**用户侧不需要 `npm ci`**；仅维护者改插件源码时需在本目录 `npm ci && npm run build` 并提交新的 `dist/`。
9. **Go CLI 变更后的默认构建与安装**（自动化助手与本地开发者）：凡修改 **`cmd/twinbox-go/`** 下代码，或修复 **仅能通过 Go 薄壳复现/验证** 的 CLI 行为（含 `main.go` 的 RPC 绕行、`install` 子命令等），在提交前**默认**应完成：
   - **构建并覆盖仓库内交付路径**：在仓库根执行 **`bash scripts/build_go_twinbox.sh`**（或等价：`cd cmd/twinbox-go && go build -o ../../dist/twinbox .`），产物为 **`dist/twinbox`**。
   - **同步用户可执行文件**（开发机常用）：同一脚本加 **`--install`**（或环境变量 **`TWINBOX_GO_INSTALL=1`**），将二进制复制到 **`TWINBOX_GO_BIN_DEST`**（默认 **`$HOME/.local/bin/twinbox`**），避免 PATH 上仍是旧构建。
   - **PATH 持久化**（按需一次）：加 **`--ensure-path`**（或 **`TWINBOX_GO_ENSURE_PATH=1`**），在 **`~/.bashrc`** 中按标记行幂等追加 `export PATH="$HOME/.local/bin:$PATH"`（与第 8 条约定一致；非 bash 用户请自行配置）。
   - 一键组合示例：`bash scripts/build_go_twinbox.sh --install --ensure-path`
   - **验证**：`go test ./cmd/twinbox-go/...` 通过后再提交；若沙箱无法写 `~/.local/bin`，至少完成 **`dist/`** 构建并在说明中注明。
