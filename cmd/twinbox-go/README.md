# twinbox-go (thin CLI)

Optional Go entry that prefers the Twinbox Unix-socket daemon (`cli_invoke` JSON-RPC) and falls back to `python3 -m twinbox_core.task_cli` when the socket is unavailable.

## Build

```bash
cd cmd/twinbox-go
go build -o twinbox-go .
```

## Usage

```bash
export TWINBOX_STATE_ROOT=/path/to/state   # or rely on ~/.config/twinbox/state-root
./twinbox-go task todo --json
```

### Offline vendor install (tarball)

Build a tarball from the repo (`scripts/package_vendor_tarball.sh`), then:

```bash
./twinbox-go install --archive /path/to/twinbox_core-0.1.0.tar.gz
# optional: --state-root /path/to/state  (default: $TWINBOX_STATE_ROOT or ~/.twinbox)
```

Then run with `PYTHONPATH="$TWINBOX_STATE_ROOT/vendor" python3 -m twinbox_core.task_cli …` (or set `TWINBOX_HOME` when using profiles).

Override socket path:

```bash
./twinbox-go --socket /path/to/daemon.sock task todo --json
```

## Coexistence with Python

- Same argv as `twinbox` after optional `--socket`.
- Python remains the source of truth for behavior; this binary only saves cold-start cost when the daemon is running (`twinbox daemon start`).

## Environment variables

| Variable | Purpose |
|----------|---------|
| `TWINBOX_DAEMON_SOCKET` | Unix socket path (overrides default derived from state root) |
| `TWINBOX_STATE_ROOT` | State root; default socket is `$TWINBOX_STATE_ROOT/run/daemon.sock` |
| `TWINBOX_PYTHON` | Python executable for fallback (default `python3`) |
| `TWINBOX_CODE_ROOT` | Working directory for the fallback Python process (optional) |

## Timeouts

- Connect to socket: 3s
- Full RPC round-trip: 30s
