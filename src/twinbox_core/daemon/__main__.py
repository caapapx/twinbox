"""Entry: python -m twinbox_core.daemon"""

from __future__ import annotations

from twinbox_core.daemon.server import run_daemon_forever

if __name__ == "__main__":
    raise SystemExit(run_daemon_forever())
