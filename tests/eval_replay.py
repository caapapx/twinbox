"""Replay eval metrics (no live IMAP)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def evaluate(replay_root: Path) -> dict[str, Any]:
    pulse = _load(replay_root / "runtime" / "validation" / "phase-4" / "activity-pulse.json", {})
    pending_path = replay_root / "runtime" / "validation" / "phase-4" / "pending-replies.yaml"
    pending_text = pending_path.read_text(encoding="utf-8") if pending_path.is_file() else ""
    attention = pulse.get("needs_attention") if isinstance(pulse, dict) else []
    if not isinstance(attention, list):
        attention = []
    join_misses = []
    if isinstance(pulse, dict):
        join_misses = (pulse.get("diagnostics") or {}).get("queue_join_misses") or []
    waiting = [t for t in attention if isinstance(t, dict) and "pending" in (t.get("queue_tags") or [])]
    false_waiting = [t for t in waiting if "同意" in str(t.get("why", "")) or "已审批" in str(t.get("why", ""))]
    return {
        "ok": True,
        "replay_root": str(replay_root),
        "waiting_on_me_count": len(waiting),
        "waiting_on_me_false_positives": len(false_waiting),
        "queue_join_misses": join_misses,
        "needs_attention_count": len(attention),
        "pending_artifact_present": bool(pending_text),
        "projections_present": bool(isinstance(pulse, dict) and pulse.get("projections")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(evaluate(Path(args.root)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
