# OpenClaw 部署体验优化计划

## 背景

参考 steipete/gog 和 steipete/summarize 的优秀设计，优化 twinbox 在 OpenClaw 中的部署和使用体验。

## 对比分析

### steipete skills 的优势
- ✅ 一键安装（`openclaw skills install <slug>`）
- ✅ 清晰的依赖声明
- ✅ 轻量级（主要是 Markdown + 脚本）
- ✅ 全局可用
- ✅ 简单的故障排查

### twinbox 当前状态
- ⚠️ 多步安装流程
- ⚠️ 重运行时依赖（Python + daemon）
- ⚠️ Agent 专属
- ⚠️ 插件 + Skill 双层架构
- ✅ 强大的缓存和连接池
- ✅ 完整的 Phase 流水线

## 优化方案

### Phase 1: 简化安装（高优先级）

**目标：** 从多步手动流程变为一键安装

**任务：**
1. 创建 `install.sh` 脚本
   ```bash
   curl -sSL https://twinbox.dev/install.sh | bash
   ```
   - 检测系统环境（Python 版本、依赖）
   - 安装 twinbox CLI 到 `~/.local/bin/`
   - 安装 vendor runtime
   - 配置 OpenClaw plugin
   - 创建 SKILL.md 软链接
   - 启动 daemon
   - 输出验证结果

2. 发布到 ClawHub
   - 注册 `twinbox` skill slug
   - 提供 `openclaw skills install twinbox` 支持

3. 改进 `twinbox onboard openclaw`
   - 添加 `--check-only` 模式（仅检查不安装）
   - 添加 `--repair` 模式（修复损坏的安装）
   - 输出更友好的进度提示

**验收标准：**
- 新用户从零到可用 < 5 分钟
- 单条命令完成安装
- 失败时有清晰的错误提示和修复建议

### Phase 2: 健康检查命令（中优先级）

**目标：** 提供一键诊断工具

**任务：**
1. 实现 `twinbox doctor` 命令
   ```bash
   twinbox doctor [--json]
   ```
   检查项：
   - Python 版本 (>= 3.11)
   - twinbox CLI 版本
   - Daemon 状态（运行中/停止/错误）
   - IMAP 连接性
   - OpenClaw plugin 加载状态
   - Skill 注册状态
   - Phase 4 产物新鲜度
   - 磁盘空间

2. 集成到 SKILL.md
   ```markdown
   ## Troubleshooting

   Run health check:
   ```bash
   twinbox doctor
   ```

   Common issues:
   - [Session pollution](...)
   - [Daemon not starting](...)
   ```

**验收标准：**
- 一条命令诊断所有常见问题
- 输出包含修复建议
- 支持 `--json` 用于自动化

### Phase 3: 文档重构（高优先级）

**目标：** 降低学习曲线，提高可发现性

**任务：**
1. 重写 README.md 开头部分
   - 30 秒电梯演讲
   - Quick Start（3 条命令以内）
   - 核心场景演示（GIF/视频）
   - 常见问题（FAQ 前置）

2. 创建 `docs/openclaw/` 目录
   - `installation.md` - 详细安装指南
   - `first-use.md` - 首次使用教程
   - `troubleshooting.md` - 故障排查索引
   - `architecture.md` - 架构说明（给高级用户）

3. 改进 SKILL.md 可读性
   - 精简 frontmatter description（< 200 字）
   - 核心约束前置
   - 示例对话模板
   - 故障排查快速链接

**验收标准：**
- 新用户 5 分钟内理解核心价值
- 安装文档 < 1 页
- 每个错误信息都有对应的文档链接

### Phase 4: 降低运行时复杂度（低优先级，探索性）

**目标：** 提供轻量级模式

**任务：**
1. 实现 `--no-daemon` 模式
   ```bash
   twinbox task latest-mail --no-daemon --json
   ```
   - 直接执行，不经过 daemon
   - 适合低频调用场景
   - 牺牲缓存换取简单性

2. 探索 Go 重写核心路径
   - Phase 4 产物读取和投影
   - 基础 CLI 命令
   - 保持 Python 用于 Phase 1-3 流水线

3. 提供 Docker 一键部署
   ```bash
   docker run -v ~/.twinbox:/root/.twinbox twinbox/openclaw
   ```

**验收标准：**
- `--no-daemon` 模式可用且稳定
- Docker 镜像 < 500MB
- 性能不低于当前 daemon 模式

### Phase 5: 依赖声明标准化（中优先级）

**目标：** 让 OpenClaw 自动检查依赖

**任务：**
1. 扩展 SKILL.md metadata
   ```yaml
   metadata:
     openclaw:
       requires:
         system:
           - python: ">=3.11"
           - binary: twinbox
           - binary: twinbox-orchestrate
         env: [IMAP_HOST, ...]
       setup:
         command: "twinbox onboard openclaw --json"
         verify: "twinbox doctor --json"
       health:
         check: "twinbox daemon status --json"
         interval: 300  # 5 分钟
   ```

2. 提供依赖检查 API
   ```bash
   twinbox check-deps --json
   ```
   返回：
   ```json
   {
     "python": {"required": ">=3.11", "found": "3.11.5", "ok": true},
     "twinbox": {"required": true, "found": "/usr/local/bin/twinbox", "ok": true},
     "daemon": {"required": true, "running": true, "ok": true}
   }
   ```

**验收标准：**
- OpenClaw 能自动检测依赖缺失
- 用户看到清晰的"缺少 X"提示
- 提供一键修复链接

## 实施优先级

### 立即执行（本周）
1. ✅ 会话污染与工具断链长文归档至仓库根 `BUGFIX.md`（`docs/troubleshooting/session-pollution.md` 为入口跳转）
2. 重写 README.md Quick Start 部分
3. 实现 `twinbox doctor` 基础版本

### 短期（2 周内）
1. 创建 `install.sh` 脚本
2. 改进 `twinbox onboard openclaw` 输出
3. 重构文档结构

### 中期（1 个月内）
1. 发布到 ClawHub
2. 实现完整的 `twinbox doctor`
3. 扩展 SKILL.md metadata

### 长期（探索性）
1. `--no-daemon` 模式
2. Docker 一键部署
3. Go 重写核心路径

## 成功指标

- 安装成功率 > 95%
- 首次使用时间 < 10 分钟
- 故障自助解决率 > 80%
- GitHub issues 中安装问题 < 20%

## 参考资源

- [steipete/gog deployment](https://clawhub.ai/steipete/gog)
- [steipete/summarize setup](https://clawhub.ai/steipete/summarize)
- [OpenClaw skills documentation](https://openclaw.ai)
- [ClawHub marketplace](https://clawhub.ai)
