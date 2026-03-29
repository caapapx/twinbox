# twinbox-go (thin CLI)

Optional Go entry that prefers the Twinbox Unix-socket daemon (`cli_invoke` JSON-RPC) and falls back to `python3 -m twinbox_core.task_cli` when the socket is unavailable.
When used as the only binary on `PATH`, the fallback path now seeds `PYTHONPATH` from `TWINBOX_CODE_ROOT/src`, `TWINBOX_HOME/vendor`, `TWINBOX_STATE_ROOT/vendor`, and the default `~/.twinbox/vendor`, so it can replace `scripts/twinbox` on vendor-based hosts.

## Build

```bash
cd cmd/twinbox-go
go build -o twinbox-go .
```

## Usage

```bash
export TWINBOX_STATE_ROOT=/path/to/state   # or rely on ~/.config/twinbox/state-root
./twinbox-go task todo --json
./twinbox-go --profile work task todo --json
```

### Vendor install (local tarball or HTTP URL)

Build a tarball from the repo (`scripts/package_vendor_tarball.sh`), then:

```bash
./twinbox-go install --archive /path/to/twinbox_core-0.1.0.tar.gz
./twinbox-go install --archive https://example.com/twinbox_core-0.1.0.tar.gz
# optional: --state-root /path/to/state  (default: $TWINBOX_STATE_ROOT or ~/.twinbox)
```

Then run `twinbox-go …` directly, or `PYTHONPATH="$TWINBOX_STATE_ROOT/vendor" python3 -m twinbox_core.task_cli …` if you want to bypass Go.

Override socket path:

```bash
./twinbox-go --socket /path/to/daemon.sock task todo --json
```

## Coexistence with Python

- Same argv as `twinbox` after optional `--socket`.
- Python remains the source of truth for behavior; this binary only saves cold-start cost when the daemon is running (`twinbox daemon start`).
- `--profile NAME` is honored on the fallback path before Python import, so shared-vendor profile installs work without a repo checkout.

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
