"""Offline snapshot of the value funnel. Reads local state only.

This is a current-disk picture, not a longitudinal score. time_to_surface stays
null until arrival and first-surface timestamps are recorded. No mailbox, no LLM.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from twinbox_core.pulse import normalize_thread_key


def _ids(value: object) -> set[str]:
    return {item.lower() for item in re.findall(r"<[^>]+>", str(value or ""))}


def _load(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot(account_root: Path) -> dict[str, Any]:
    ctx = _load(account_root / "runtime" / "context" / "phase1-context.json", {})
    sent = _load(account_root / "runtime" / "context" / "sent-headers.json", {})
    pulse = _load(account_root / "runtime" / "validation" / "phase-4" / "activity-pulse.json", {})
    envelopes = ctx.get("envelopes") if isinstance(ctx, dict) else []
    headers = sent.get("headers") if isinstance(sent, dict) else []
    attention = pulse.get("needs_attention") if isinstance(pulse, dict) else []
    if not isinstance(envelopes, list):
        envelopes = []
    if not isinstance(headers, list):
        headers = []
    if not isinstance(attention, list):
        attention = []

    replied: set[str] = set()
    for row in headers:
        if isinstance(row, dict):
            replied |= _ids(row.get("in_reply_to")) | _ids(row.get("references"))

    replied_threads: set[str] = set()
    for env in envelopes:
        if not isinstance(env, dict):
            continue
        if _ids(env.get("message_id")) & replied:
            replied_threads.add(normalize_thread_key(env.get("subject")))

    attention_threads = {
        normalize_thread_key(row.get("thread_key"))
        for row in attention
        if isinstance(row, dict)
    }
    cards = json.dumps(attention, ensure_ascii=False).encode("utf-8")
    miss = replied_threads - attention_threads
    unreplied = attention_threads - replied_threads
    return {
        "ok": bool(headers),
        "truth": "sent_headers" if headers else "insufficient",
        "longitudinal": False,
        "replied_thread_count": len(replied_threads),
        "attention_thread_count": len(attention_threads),
        "owner_action_miss": len(miss),
        "push_waste": len(unreplied),
        "attention_cost": {"cards": len(attention), "bytes": len(cards)},
        "time_to_surface": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("account_root")
    args = parser.parse_args()
    print(json.dumps(snapshot(Path(args.account_root)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
