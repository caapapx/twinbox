# Integrations

Host-specific bundles that are **not** part of the Python package under `src/twinbox_core/`.

| Path | Role |
|------|------|
| [`openclaw/`](openclaw/README.md) | OpenClaw fragment, npm plugin (`plugin-twinbox-task`), deploy docs, bridge units |

The Go vendor tarball (`scripts/package_vendor_tarball.sh`) includes `integrations/openclaw/` under `vendor/` after `twinbox install --archive`.
