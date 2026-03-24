# OpenClaw Docker Compose 部署指南

状态：运维参考  
验证基准：[openclaw/openclaw](https://github.com/openclaw/openclaw) 分支 `main`，提交 `17c1ee7716e3`（2026-03-24）。以下步骤与文件内容与上游该提交中的 `docker-compose.yml`、`docs/install/docker.md`、`scripts/docker/setup.sh`、`.env.example` 对照一致。升级 OpenClaw 时请以 [上游仓库](https://github.com/openclaw/openclaw) 最新文档与 Compose 为准。

---

## 1. 适用场景与前置条件

- **适用**：需要容器化 Gateway、在干净主机上跑 OpenClaw、或按官方流程做 Docker 验证。
- **不适用**：本机开发追求最短迭代循环时，上游文档建议优先使用常规本地安装（非 Docker）。
- **前置**：
  - Docker Engine / Docker Desktop + **Docker Compose v2**
  - 构建镜像时建议 **≥ 2 GB RAM**（上游说明 `pnpm install` 在 1 GB 上可能被 OOM kill，退出码 137）
  - 公网/VPS 暴露端口前阅读上游 [Gateway security](https://github.com/openclaw/openclaw/blob/main/docs/gateway/security/index.md)（含网络暴露加固说明）

---

## 2. 推荐路径：官方 `setup.sh`（构建/拉镜像 + onboarding + 启动）

在**已克隆**的 OpenClaw 仓库根目录执行：

```bash
git clone https://github.com/openclaw/openclaw.git
cd openclaw
./scripts/docker/setup.sh
```

脚本会：本地构建镜像（或使用预构建镜像，见下）、引导 onboarding（含提供商 API Key）、生成 Gateway token 并写入 `.env`、通过 Docker Compose 启动 Gateway。

**使用预构建镜像（跳过本地 build）**：

```bash
export OPENCLAW_IMAGE="ghcr.io/openclaw/openclaw:latest"
./scripts/docker/setup.sh
```

镜像发布于 [GitHub Container Registry](https://github.com/openclaw/openclaw/pkgs/container/openclaw)。上游文档列举的常见 tag：`main`、`latest`、以及版本号 tag（例如 `2026.2.26`）。

**可选环境变量（setup 脚本识别，与 Compose 协同）**：

| 变量 | 作用 |
|------|------|
| `OPENCLAW_IMAGE` | 使用远程镜像替代本地 `openclaw:local` 构建 |
| `OPENCLAW_DOCKER_APT_PACKAGES` | 构建时额外安装的 apt 包（空格分隔） |
| `OPENCLAW_EXTENSIONS` | 构建时预装扩展依赖（空格分隔名称） |
| `OPENCLAW_EXTRA_MOUNTS` | 额外 bind mount，`source:target[:opts]` 逗号分隔 |
| `OPENCLAW_HOME_VOLUME` | 将 `/home/node` 持久化到命名卷 |
| `OPENCLAW_SANDBOX` | 为 `1`/`true`/`yes`/`on` 时参与 sandbox 引导 |
| `OPENCLAW_DOCKER_SOCKET` | 覆盖 Docker socket 路径（如 rootless） |

若启用了 `OPENCLAW_EXTRA_MOUNTS` 或 `OPENCLAW_HOME_VOLUME`，脚本会生成 `docker-compose.extra.yml`，启动时需：

```bash
docker compose -f docker-compose.yml -f docker-compose.extra.yml up -d
```

（日常若只用 setup 脚本，其内部会按同样方式组合文件。）

---

## 3. 手动路径（逐步执行，便于 CI/自动化）

仍在仓库根目录：

```bash
docker build -t openclaw:local -f Dockerfile .
docker compose run --rm openclaw-cli onboard
docker compose up -d openclaw-gateway
```

使用 GHCR 镜像时，在运行 Compose 前导出：

```bash
export OPENCLAW_IMAGE="ghcr.io/openclaw/openclaw:latest"
```

并确保 `.env` 或环境中已定义下文 **Compose 必需变量**。

---

## 4. Compose 拓扑与端口（已验证快照）

**服务**（`docker-compose.yml`）：

| 服务名 | 角色 |
|--------|------|
| `openclaw-gateway` | Gateway：监听容器内 `18789`，健康检查请求 `http://127.0.0.1:18789/healthz` |
| `openclaw-cli` | CLI：`network_mode: service:openclaw-gateway`，与 Gateway 共享网络命名空间，便于通过 `127.0.0.1` 访问 Gateway |

**宿主机端口映射**（可通过环境变量覆盖）：

- `OPENCLAW_GATEWAY_PORT`（默认 **18789**）→ 容器 `18789`
- `OPENCLAW_BRIDGE_PORT`（默认 **18790**）→ 容器 `18790`

**数据持久化**（bind mount，路径由宿主机变量指定）：

- `OPENCLAW_CONFIG_DIR` → 容器内 `/home/node/.openclaw`
- `OPENCLAW_WORKSPACE_DIR` → 容器内 `/home/node/.openclaw/workspace`

`setup.sh` 中的默认值（未导出时）：

- `OPENCLAW_CONFIG_DIR` = `$HOME/.openclaw`
- `OPENCLAW_WORKSPACE_DIR` = `$HOME/.openclaw/workspace`

镜像内进程用户为 **`node`（uid 1000）**。若 bind mount 报权限错误，上游建议：

```bash
sudo chown -R 1000:1000 /path/to/openclaw-config /path/to/openclaw-workspace
```

**`openclaw-gateway` 启动命令要点**：`gateway --bind ${OPENCLAW_GATEWAY_BIND:-lan} --port 18789`。`lan` 为默认，便于宿主机浏览器访问已发布的端口；`bind` 合法值见上游文档（勿用 `0.0.0.0` 等主机别名替代 `gateway.bind` 语义）。

---

## 5. 最小 `.env` 示例（Compose 层）

除上游 `.env.example` 中的模型 Key、Channel 等外，Docker Compose 会读取例如：

```bash
# 镜像（本地构建可省略，默认为 openclaw:local）
# OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest

# 宿主机目录（必须存在且建议 uid 1000 可写）
OPENCLAW_CONFIG_DIR=/home/you/.openclaw
OPENCLAW_WORKSPACE_DIR=/home/you/.openclaw/workspace

# 网关鉴权（公网暴露时务必使用强随机值）
OPENCLAW_GATEWAY_TOKEN=$(openssl rand -hex 32)

# 可选：时区
OPENCLAW_TZ=UTC

# 可选：端口
# OPENCLAW_GATEWAY_PORT=18789
# OPENCLAW_BRIDGE_PORT=18790

# 可选：与 Claude Web/Ai 会话相关（仅在使用对应认证方式时）
# CLAUDE_AI_SESSION_KEY=
# CLAUDE_WEB_SESSION_KEY=
# CLAUDE_WEB_COOKIE=
```

完整说明与优先级见上游 [.env.example](https://github.com/openclaw/openclaw/blob/main/.env.example) 文件头注释。

---

## 6. 验证与日常操作

### 6.1 Twinbox 邮箱登录快速路径（3 分钟）

如果你要在 OpenClaw 中挂载 twinbox skill，优先走这条最短路径：

```bash
export MAIL_ADDRESS="you@example.com"
export IMAP_HOST="imap.example.com"
export IMAP_PORT="993"
export IMAP_LOGIN="you@example.com"
export IMAP_PASS="<app-password>"
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="465"
export SMTP_LOGIN="you@example.com"
export SMTP_PASS="<app-password>"

twinbox mailbox preflight --json
```

命令会自动补默认值：

- `MAIL_ACCOUNT_NAME=myTwinbox`
- `MAIL_DISPLAY_NAME={MAIL_ACCOUNT_NAME}`
- `IMAP_ENCRYPTION=tls`
- `SMTP_ENCRYPTION=tls`

返回结果重点看这些字段：

- `login_stage`: `unconfigured | validated | mailbox-connected`
- `status`: `success | warn | fail`
- `missing_env`: 缺失环境变量列表
- `actionable_hint`: 面向用户的修复提示
- `next_action`: 下一步建议

邮箱登录原理可以简化成下面这条链路：

```text
+------------------+
| OpenClaw / 用户   |
| 填 env 表单       |
+---------+--------+
          |
          | IMAP_*, SMTP_*, MAIL_ADDRESS
          v
+-------------------------------+
| twinbox mailbox preflight     |
| task-facing CLI               |
| 统一入口                      |
+---------------+---------------+
                |
                v
+-------------------------------+
| mailbox.py                    |
| 1. 读 .env + 进程环境变量      |
| 2. 补默认值                   |
|    - MAIL_ACCOUNT_NAME        |
|    - MAIL_DISPLAY_NAME        |
|    - IMAP/SMTP_ENCRYPTION     |
| 3. 检查缺项                   |
+---------------+---------------+
                |
      missing?  | yes
                v
      +-------------------------+
      | status=fail             |
      | login_stage=unconfigured|
      | missing_env + 修复建议   |
      +-------------------------+

                no
                |
                v
+-------------------------------+
| 渲染 himalaya config.toml     |
| 把 env 转成邮件客户端配置      |
+---------------+---------------+
                |
                v
+-------------------------------+
| 调用 himalaya                 |
| envelope list --output json   |
| 对 IMAP 做只读连通性验证       |
+---------------+---------------+
                |
      fail?     | yes
                v
      +-------------------------+
      | status=fail             |
      | login_stage=validated   |
      | 分类: auth/tls/network  |
      | actionable_hint         |
      +-------------------------+

                no
                |
                v
+-------------------------------+
| IMAP 通过                     |
| SMTP 在只读模式不阻塞         |
| 记为 warn/skip                |
+---------------+---------------+
                |
                v
+-------------------------------+
| 返回给 OpenClaw               |
| login_stage=mailbox-connected |
| status=success 或 warn        |
| next_action                   |
+-------------------------------+
```

也就是说，这里的“登录”不是网页会话登录，而是 twinbox 用环境变量生成一份临时的 Himalaya 邮件配置，再执行一次只读 IMAP 拉取测试。能读到 envelope，就认为邮箱已经接通；如果失败，则按 `missing_env`、认证、TLS/端口、网络这几类返回可修复反馈。

只读模式下，SMTP 只作为提示项，不阻塞 `mailbox-connected`。预检通过后，下一步通常是：

```bash
twinbox-orchestrate run --phase 1
```

**健康检查（无需鉴权）**：

```bash
curl -fsS http://127.0.0.1:18789/healthz   # liveness
curl -fsS http://127.0.0.1:18789/readyz   # readiness
```

**控制界面**：浏览器打开 `http://127.0.0.1:18789/`，在 Settings 中粘贴 Gateway token。

**再次打印 Dashboard URL（不自动打开浏览器）**：

```bash
docker compose run --rm openclaw-cli dashboard --no-open
```

**带鉴权的深度健康检查**：

```bash
docker compose exec openclaw-gateway node dist/index.js health --token "$OPENCLAW_GATEWAY_TOKEN"
```

**非交互自动化（如 CI）**：对 `docker compose run` 使用 `-T` 禁用 TTY，例如：

```bash
docker compose run -T --rm openclaw-cli gateway probe
docker compose run -T --rm openclaw-cli devices list --json
```

**Channel 配置示例**（在仓库根、Compose 上下文正确时）：

```bash
docker compose run --rm openclaw-cli channels login
docker compose run --rm openclaw-cli channels add --channel telegram --token "<token>"
docker compose run --rm openclaw-cli channels add --channel discord --token "<token>"
```

---

## 7. 附录：`docker-compose.yml` 验证快照（`17c1ee7716e3`）

以下全文与上游该提交的 `docker-compose.yml` 一致，便于离线对照；**生产请以克隆仓库内的当前文件为准**。

```yaml
services:
  openclaw-gateway:
    image: ${OPENCLAW_IMAGE:-openclaw:local}
    environment:
      HOME: /home/node
      TERM: xterm-256color
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:-}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: ${OPENCLAW_ALLOW_INSECURE_PRIVATE_WS:-}
      CLAUDE_AI_SESSION_KEY: ${CLAUDE_AI_SESSION_KEY:-}
      CLAUDE_WEB_SESSION_KEY: ${CLAUDE_WEB_SESSION_KEY:-}
      CLAUDE_WEB_COOKIE: ${CLAUDE_WEB_COOKIE:-}
      TZ: ${OPENCLAW_TZ:-UTC}
    volumes:
      - ${OPENCLAW_CONFIG_DIR}:/home/node/.openclaw
      - ${OPENCLAW_WORKSPACE_DIR}:/home/node/.openclaw/workspace
      ## Uncomment the lines below to enable sandbox isolation
      ## (agents.defaults.sandbox). Requires Docker CLI in the image
      ## (build with --build-arg OPENCLAW_INSTALL_DOCKER_CLI=1) or use
      ## scripts/docker/setup.sh with OPENCLAW_SANDBOX=1 for automated setup.
      ## Set DOCKER_GID to the host's docker group GID (run: stat -c '%g' /var/run/docker.sock).
      # - /var/run/docker.sock:/var/run/docker.sock
    # group_add:
    #   - "${DOCKER_GID:-999}"
    ports:
      - "${OPENCLAW_GATEWAY_PORT:-18789}:18789"
      - "${OPENCLAW_BRIDGE_PORT:-18790}:18790"
    init: true
    restart: unless-stopped
    command:
      [
        "node",
        "dist/index.js",
        "gateway",
        "--bind",
        "${OPENCLAW_GATEWAY_BIND:-lan}",
        "--port",
        "18789",
      ]
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:18789/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
        ]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 20s

  openclaw-cli:
    image: ${OPENCLAW_IMAGE:-openclaw:local}
    network_mode: "service:openclaw-gateway"
    cap_drop:
      - NET_RAW
      - NET_ADMIN
    security_opt:
      - no-new-privileges:true
    environment:
      HOME: /home/node
      TERM: xterm-256color
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:-}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: ${OPENCLAW_ALLOW_INSECURE_PRIVATE_WS:-}
      BROWSER: echo
      CLAUDE_AI_SESSION_KEY: ${CLAUDE_AI_SESSION_KEY:-}
      CLAUDE_WEB_SESSION_KEY: ${CLAUDE_WEB_SESSION_KEY:-}
      CLAUDE_WEB_COOKIE: ${CLAUDE_WEB_COOKIE:-}
      TZ: ${OPENCLAW_TZ:-UTC}
    volumes:
      - ${OPENCLAW_CONFIG_DIR}:/home/node/.openclaw
      - ${OPENCLAW_WORKSPACE_DIR}:/home/node/.openclaw/workspace
    stdin_open: true
    tty: true
    init: true
    entrypoint: ["node", "dist/index.js"]
    depends_on:
      - openclaw-gateway
```

---

## 8. 延伸阅读（上游）

- [docs/install/docker.md](https://github.com/openclaw/openclaw/blob/main/docs/install/docker.md) — Docker 安装主文档  
- [docs/install/docker-vm-runtime.md](https://github.com/openclaw/openclaw/blob/main/docs/install/docker-vm-runtime.md) — VM 上持久化与磁盘增长说明  
- [Gateway sandboxing](https://github.com/openclaw/openclaw/blob/main/docs/gateway/sandboxing.md) — Agent Sandbox 与 Gateway 容器化的关系  
- VPS 场景：上游文档中的 *Hetzner (Docker VPS)*、*Docker VM Runtime* 章节（见 `docker.md` 底部链接）
