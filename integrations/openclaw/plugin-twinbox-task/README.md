# Twinbox OpenClaw plugin (`twinbox-task-tools`)

## 宿主要不要跑 `npm ci`？

**不用。** 网关加载的是 **已打包的** [`dist/index.mjs`](./dist/index.mjs)（`package.json` 里 `openclaw.extensions` 指向该文件）。  
依赖已打进 `dist/`，`node_modules/` 不在 tarball 里是故意的——**Go + Python vendor 安装路径与 `twinbox install --archive` 已足够**，无需在机器上再执行 `npm ci`。

## 什么时候才需要 npm？

仅在你 **修改** 本目录下的 `*.mjs` 源码并要更新 `dist/` 时（仓库维护者）：

```bash
cd integrations/openclaw/plugin-twinbox-task
npm ci
npm run build
```

然后把新的 `dist/index.mjs` 一并提交。

## 与「合并」进 Go/Python 的关系

OpenClaw Gateway 只按 **JS 插件契约**加载工具；**不能**把这段逻辑塞进 `twinbox` 二进制或 `twinbox_core` 里替代 Gateway 插件。  
能合并的是 **交付物**：同一套 vendor 归档里已带上 `dist/` + `package.json`，**部署步骤**上仍是「装 Go + 解压 vendor + `twinbox onboard/deploy`」，**不增加** npm 安装步骤。
