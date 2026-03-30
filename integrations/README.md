# Integrations

Host-specific bundles that are **not** part of the Python package under `src/twinbox_core/`.

| Path | Role |
|------|------|
| [`openclaw/`](openclaw/README.md) | OpenClaw fragment, **JS 插件**（`plugin-twinbox-task`：运行时只加载已打包的 `dist/index.mjs`，**无需** `npm ci`；见该目录 README），deploy 文档，bridge units |

The Go vendor tarball (`scripts/package_vendor_tarball.sh`) includes `integrations/openclaw/` under `vendor/` after `twinbox install --archive`.
