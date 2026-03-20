# Gastown 操作指南 — twinbox

> 从零复现 twinbox 的 gastown 多 agent 编排环境。

## 前置依赖

| 工具 | 安装方式 | 验证 |
|------|---------|------|
| Go 1.25+ | 系统自带或 [官方安装](https://go.dev/dl/) | `go version` |
| gt (gastown) | `cd ~/fun/gastown && make build && cp gt ~/go/bin/` | `gt --version` |
| bd (beads) | `go install github.com/steveyegge/beads/cmd/bd@latest` | `bd --version` |
| dolt | 见下方手动安装 | `dolt version` |
| tmux | `apt install tmux` | `tmux -V` |

### Dolt 手动安装（无 sudo）

```bash
DOLT_VERSION=$(curl -sI https://github.com/dolthub/dolt/releases/latest | grep -i location | grep -oP 'v[\d.]+')
curl -L "https://github.com/dolthub/dolt/releases/download/${DOLT_VERSION}/dolt-linux-amd64.tar.gz" -o /tmp/dolt.tar.gz
tar xzf /tmp/dolt.tar.gz -C /tmp
cp /tmp/dolt-linux-amd64/bin/dolt ~/go/bin/dolt
```

### 环境变量（写入 `~/.bashrc`）

```bash
# Gastown / Go CLI bootstrap
case ":$PATH:" in
  *":$HOME/go/bin:"*) ;;
  *) export PATH="$HOME/go/bin:$PATH" ;;
esac
case ":$PATH:" in
  *":/usr/local/go/bin:"*) ;;
  *) export PATH="$PATH:/usr/local/go/bin" ;;
esac
export GT_TOWN_ROOT="${GT_TOWN_ROOT:-$HOME/gt}"
```

写入后立刻 reload 并验证：

```bash
source ~/.bashrc
hash -r
command -v gt
command -v bd
echo "$GT_TOWN_ROOT"
```

如果你的登录 shell 走 `~/.bash_profile`，确保它会 source `~/.bashrc`：

```bash
[ -f ~/.bashrc ] && . ~/.bashrc
```

---

## 一、创建 Town

Town 是 gastown 的顶层工作空间，管理所有 rig。

```bash
gt install ~/gt --git --name mytown
cd ~/gt
git config user.email "you@example.com"
git config user.name "yourname"
git add -A && git commit -m "feat: initial Gas Town HQ"
```

验证：
```bash
cat ~/gt/mayor/town.json   # 应有 name、owner
ls ~/gt/.beads/formulas/   # 应有 42 个内置 formula
```

---

## 二、注册 Rig

Rig 是项目容器。twinbox 作为 rig 挂到 town 下。

```bash
cd ~/gt
gt rig add twinbox https://github.com/caapapx/twinbox.git --prefix tw
```

产出结构：
```
~/gt/twinbox/
├── config.json          # rig 配置
├── .repo.git/           # 共享 bare repo
├── .beads/              # rig 级 beads（prefix: tw）
├── mayor/rig/           # mayor 的工作 clone
├── refinery/rig/        # refinery 的工作 worktree
├── witness/             # witness agent
├── polecats/            # polecat 工作目录
└── crew/                # 人工工作空间
```

---

## 三、部署 Formula

twinbox 的 formula 定义在源码 `.beads/formulas/` 下，需要复制到 town 搜索路径：

```bash
cp /path/to/twinbox/.beads/formulas/twinbox-*.formula.toml ~/gt/.beads/formulas/
```

验证：
```bash
gt formula show twinbox-phase1          # workflow 类型，2 个 step
gt formula show twinbox-full-pipeline   # convoy 类型，4 条 leg
```

5 个 formula：

| Formula | 类型 | 说明 |
|---------|------|------|
| twinbox-phase1 | workflow | Intent 分类：loading → thinking |
| twinbox-phase2 | workflow | Persona 推断：loading → thinking |
| twinbox-phase3 | workflow | Lifecycle 建模：loading → thinking |
| twinbox-phase4 | workflow | Value 输出：loading → thinking |
| twinbox-full-pipeline | convoy | 全流程 4 leg + synthesis |

---

## 四、启动 Daemon

Daemon 是后台进程，管理所有 agent 的 tmux session。

```bash
cd ~/gt
gt daemon start
```

daemon 自动创建的 tmux session：

| Session | 角色 | 说明 |
|---------|------|------|
| hq-mayor | Mayor | 全局协调 |
| hq-deacon | Deacon | 巡逻调度 |
| tw-witness | Witness | 监控 polecat 健康 |
| tw-refinery | Refinery | 处理 MR 合并 |

```bash
gt daemon stop    # 停止
gt daemon status  # 查看状态
```

---

## 五、Sling 分发工作

核心命令。将 formula 分发给 polecat 执行。

### Sling 前先同步源码仓库（必须）

polecat worktree 是从 rig 的 `origin/master` 创建的。源码仓库本地 `master` 上如果还有未 push 的 commit，
polecat 即使在 formula 里执行 `git pull/rebase` 也拿不到这些脚本改动。

```bash
cd /path/to/twinbox
git checkout master
git pull --ff-only origin master
git push origin master
```

twinbox 的 formula 现在会在执行开始时再做一次 `git fetch + ff-only/rebase`，
用于修复“worktree 创建后仍停在旧远端 commit”的情况；但它不能替代这一步 `push`。

### 共享状态根目录（新增）

Phase 1-4 的脚本现在都会从统一的 `canonical root` 读取：
- `.env`
- `runtime/context/`
- `runtime/validation/phase-*`
- `docs/validation/`

这样多个 polecat worktree 可以共享同一份上下文和产物，而不是各写各的隔离 worktree。Phase 4 只是最明显的 fan-out 场景。

在源码仓库执行一次注册：

```bash
cd /path/to/twinbox
bash scripts/register_canonical_root.sh
bash scripts/phase4_gastown.sh roots
```

解析顺序：
1. `TWINBOX_CANONICAL_ROOT`
2. `~/.config/twinbox/canonical-root`
3. 当前 checkout（仅普通仓库可回退；linked worktree 未配置时会直接报错）

### 单 Phase 执行

```bash
gt sling twinbox-phase1 twinbox --create    # spawn polecat + 执行 phase1
gt sling twinbox-phase2 twinbox --create    # 同理
```

### Dry-run（只看不跑）

```bash
gt sling twinbox-phase1 twinbox --dry-run
```

### 执行链路

```
gt sling → spawn polecat → cook formula → 创建 wisp → hook 挂载
         → daemon 在 tmux 启动 Claude Code session
         → polecat 读取 hook，按 formula step 执行
         → 完成后提交代码 + 提交 MR
         → refinery 自动合并到 master
         → witness 全程监控健康状态
```

---

## 六、查看状态

```bash
# Agent 列表
gt agents

# Bead/Wisp 状态
bd list

# 查看特定 wisp
bd show tw-wisp-xxxx

# 查看 polecat 实时输出（tmux）
tmux attach -t tw-rust          # 直接进入
tmux capture-pane -t tw-rust -p # 不进入，抓输出

# 查看 witness 监控
tmux capture-pane -t tw-witness -p

# 查看 refinery 合并记录
git -C ~/gt/twinbox/refinery/rig log --oneline -10

# tmux session 列表
tmux ls
```

---

## 七、Fallback 编排（不依赖 gastown）

纯 bash 串行执行，不需要 town/rig/daemon：

```bash
cd /path/to/twinbox

# 全流程
bash scripts/run_pipeline.sh

# 单 Phase
bash scripts/run_pipeline.sh --phase 2

# Phase 4 统一入口
bash scripts/phase4_gastown.sh loading
bash scripts/phase4_gastown.sh think-urgent
bash scripts/phase4_gastown.sh think-sla
bash scripts/phase4_gastown.sh think-brief
bash scripts/phase4_gastown.sh merge

# Dry-run
bash scripts/run_pipeline.sh --dry-run
```

---

## 八、清理与重置

```bash
# 停止 daemon
cd ~/gt && gt daemon stop

# 杀掉所有 gastown tmux session
for s in $(tmux ls -F '#{session_name}' | grep -E '^(hq-|tw-)'); do
  tmux kill-session -t "$s"
done

# 删除 polecat
gt polecat remove twinbox/rust --force

# 完全重置（删除 town）
rm -rf ~/gt
```

---

## 九、常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `gt: command not found` | `~/go/bin` 不在 PATH，或 shell 没 reload | `source ~/.bashrc && hash -r && command -v gt` |
| `not in a Gas Town workspace` | 没设 GT_TOWN_ROOT 或不在 town 目录 | `export GT_TOWN_ROOT=$HOME/gt && cd ~/gt` |
| `cannot determine agent identity` | town 没初始化完整 | `gt doctor --fix` |
| `Dolt server unreachable` | dolt 没启动 | `gt dolt start` 或 `bd dolt start` |
| `formula not found` | formula 不在搜索路径 | 复制到 `~/gt/.beads/formulas/` |
| polecat session 不启动 | daemon 没跑 | `gt daemon start` |
| WARNING: built with go build | 用了 go install 而非 make build | `cd gastown && make build && cp gt ~/go/bin/` |

---

## 十、架构总览

```
~/gt/                          ← Town 根目录
├── mayor/                     ← Mayor（全局协调）
│   ├── town.json
│   ├── rigs.json
│   └── rig/                   ← twinbox 的 mayor clone
├── deacon/                    ← Deacon（巡逻调度）
├── .beads/formulas/           ← Formula 搜索路径（town 级）
│   ├── twinbox-phase1.formula.toml
│   ├── twinbox-phase2.formula.toml
│   ├── twinbox-phase3.formula.toml
│   ├── twinbox-phase4.formula.toml
│   └── twinbox-full-pipeline.formula.toml
└── twinbox/                   ← Rig
    ├── config.json
    ├── .repo.git/             ← 共享 bare repo
    ├── refinery/rig/          ← Refinery worktree（合并目标）
    ├── witness/               ← Witness（健康监控）
    └── polecats/              ← Polecat 工作目录
        └── rust/twinbox/      ← polecat 的 git worktree

~/fun/twinbox/                 ← 源码仓库
├── .beads/formulas/           ← Formula 源文件
├── scripts/
│   ├── phase{1,2,3,4}_loading.sh
│   ├── phase{1,2,3,4}_thinking.sh
│   └── run_pipeline.sh        ← Fallback 编排
└── docs/guides/
    └── gastown-operations.md   ← 本文件
```
