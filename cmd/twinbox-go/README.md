# twinbox (Go thin CLI)

Optional Go entry that prefers the Twinbox Unix-socket daemon (`cli_invoke` JSON-RPC) and falls back to `python3 -m twinbox_core.task_cli` when the socket is unavailable.
When delivered as the only binary on `PATH`, build it as `twinbox`; the fallback path seeds `PYTHONPATH` from `TWINBOX_CODE_ROOT/src`, `TWINBOX_HOME/vendor`, `TWINBOX_STATE_ROOT/vendor`, and the default `~/.twinbox/vendor`, so it can replace `scripts/twinbox` on vendor-based hosts. The source directory remains `cmd/twinbox-go/`, but the user-facing command should now be `twinbox`.

## Build

**Repo convention**（见根目录 `AGENTS.md`）：从仓库根执行

```bash
bash scripts/build_go_twinbox.sh              # → dist/twinbox
bash scripts/build_go_twinbox.sh --install    # 另复制到 ~/.local/bin/twinbox
bash scripts/build_go_twinbox.sh --install --ensure-path   # 按需幂等写 ~/.bashrc PATH
```

手动等价：

```bash
cd cmd/twinbox-go
go build -o ../../dist/twinbox .
```

## Usage

```bash
export TWINBOX_STATE_ROOT=/path/to/state   # or rely on ~/.config/twinbox/state-root
./twinbox task todo --json
./twinbox --profile work task todo --json
```

### Vendor install (local tarball or HTTP URL)

Build a tarball from the repo (`scripts/package_vendor_tarball.sh`). The archive includes `twinbox_core/`, `integrations/openclaw/` (OpenClaw fragment + plugin sources; `node_modules` excluded), repo-root `SKILL.md`, and `scripts/install_openclaw_twinbox_init.sh`. Then:

```bash
./twinbox install --archive /path/to/twinbox_core-0.1.0.tar.gz
./twinbox install --archive https://example.com/twinbox_core-0.1.0.tar.gz
# optional: --state-root /path/to/state  (default: $TWINBOX_STATE_ROOT or ~/.twinbox)
```

Then run `twinbox …` directly, or `PYTHONPATH="$TWINBOX_STATE_ROOT/vendor" python3 -m twinbox_core.task_cli …` if you want to bypass Go.
`install --archive` writes `vendor/MANIFEST.json` with `twinbox_version` and **`~/.config/twinbox/code-root`** pointing at the vendor directory so `resolve_code_root()` uses the installed bundle (OpenClaw deploy finds `vendor/integrations/openclaw/openclaw.fragment.json` without a git checkout). Override with **`TWINBOX_CODE_ROOT`** for development.

On success, the command prints a few lines: paths, file count / `twinbox_version`, fallback `PYTHONPATH` hint, and suggested next command (`onboard openclaw`, which runs deploy and starts the Twinbox daemon after wiring unless `--no-start-daemon`). Use `mailbox preflight` anytime to verify IMAP read-only.

Override socket path:

```bash
./twinbox --socket /path/to/daemon.sock task todo --json
```

## Coexistence with Python

- Same argv as `twinbox` after optional `--socket`.
- Python remains the source of truth for behavior; this binary only saves cold-start cost when the daemon is running (`twinbox daemon start`).
- **Interactive** commands (`onboard`, `onboarding`) always run the Python process in the **foreground** with your real TTY, even if the daemon is up — the daemon’s `cli_invoke` has no interactive stdin, so those would otherwise fail with EOF on `input()`.
- **`daemon stop`** and **`daemon restart`** also bypass RPC: asking the live daemon to stop/restart itself via `cli_invoke` tears down the socket before the JSON-RPC reply, which surfaces as `EOF` and a noisy fallback. Foreground Python performs lifecycle directly.
- `--profile NAME` is honored on the fallback path before Python import, so shared-vendor profile installs work without a repo checkout.
- When running from vendor instead of repo `src/`, fallback requires `vendor/MANIFEST.json` and rejects a mismatched `twinbox_version`.
- A manually named legacy build like `twinbox-go` still works; diagnostics reuse the actual executable basename.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `TWINBOX_DAEMON_SOCKET` | Unix socket path (overrides default derived from state root) |
| `TWINBOX_STATE_ROOT` | State root; default socket is `$TWINBOX_STATE_ROOT/run/daemon.sock` |
| `TWINBOX_PYTHON` | Python executable for fallback (default `python3`) |
| `TWINBOX_CODE_ROOT` | Working directory for the fallback Python process (optional) |
| `TWINBOX_RPC_CACHE_POLICY` | Passed to daemon `cli_invoke` as `cache_policy` (e.g. `prefer_cache`, `cache_only`) |
| `TWINBOX_RPC_TIMEOUT_MS` | Subprocess timeout for `cli_invoke` (daemon); also extends socket read deadline if larger than the default |

## Timeouts

- Connect to socket: 3s
- Full RPC round-trip: 30s minimum; grows with `TWINBOX_RPC_TIMEOUT_MS` when set
