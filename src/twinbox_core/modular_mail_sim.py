"""Deterministic synthetic mailbox fixtures for modular / OpenClaw-oriented testing.

Writes phase1-context.json, intent-classification.json, phase-4 queue YAMLs,
and refreshes activity-pulse.json — no IMAP or LLM required.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .artifacts import generated_at as artifacts_generated_at
from .daytime_slice import write_activity_pulse
from .paths import resolve_state_root

SHANGHAI = ZoneInfo("Asia/Shanghai")

# Thread subject roots (normalize_thread groups Re:/Fwd: under same key)
THREAD_SUBJECTS: tuple[str, ...] = (
    "北辰项目资源申请",
    "客户 Acme 发票对账",
    "发布窗口 3.2 确认",
    "候选人 Zhang 面试安排",
    "SLA 告警：支付回调延迟",
    "内部合规培训通知",
    "产品周报 2026-W13",
    "会议纪要：Q1 复盘",
    "供应商合同续签",
    "支持工单 #4421 日志",
)

INTENTS_CYCLE: tuple[str, ...] = (
    "collaboration",
    "finance",
    "scheduling",
    "recruiting",
    "escalation",
    "internal_update",
    "internal_update",
    "collaboration",
    "finance",
    "support",
)


def _iso(offset_hours: float) -> str:
    return (datetime.now(SHANGHAI) - timedelta(hours=offset_hours)).isoformat(timespec="seconds")


def build_simulation_payload(*, count: int = 30) -> dict[str, Any]:
    """Return envelopes, sampled_bodies, classifications, and phase-4 queue rows."""
    if count < 1:
        raise ValueError("count must be >= 1")

    envelopes: list[dict[str, Any]] = []
    sampled_bodies: dict[str, dict[str, str]] = {}
    classifications: list[dict[str, Any]] = []

    for i in range(count):
        tid = i + 1
        msg_id = f"sim-{tid:04d}"
        base = THREAD_SUBJECTS[i % len(THREAD_SUBJECTS)]
        intent = INTENTS_CYCLE[i % len(INTENTS_CYCLE)]
        # Spread across last 48h so daytime window catches them
        offset = 2.0 + (i * 1.35)
        prefix = "Re: " if i % 4 == 1 else "Fwd: " if i % 4 == 2 else ""
        subject = f"{prefix}{base}" if prefix else base

        envelopes.append(
            {
                "id": msg_id,
                "folder": "INBOX",
                "subject": subject,
                "date": _iso(offset_hours=offset),
                "from": {
                    "name": f"Sender {tid % 5 + 1}",
                    "addr": f"peer{tid % 5 + 1}@partner.example.com",
                },
                "to": {"name": "Owner", "addr": "owner@example.com"},
                "has_attachment": tid % 7 == 0,
                "flags": [] if tid % 3 else ["Seen"],
            }
        )
        sampled_bodies[msg_id] = {
            "subject": subject,
            "body": (
                f"[sim {msg_id}] Thread hint: {base}. Intent hint: {intent}. "
                f"Please review budget line {tid} and confirm by EOD."
            ),
        }
        classifications.append(
            {
                "id": msg_id,
                "intent": intent,
                "confidence": 0.82 + (tid % 7) * 0.02,
                "evidence": [f"synthetic modular seed ({intent})", f"envelope {msg_id}"],
            }
        )

    dist: dict[str, int] = {}
    for c in classifications:
        k = str(c["intent"])
        dist[k] = dist.get(k, 0) + 1

    now = artifacts_generated_at()
    daily_urgent = [
        {
            "thread_key": THREAD_SUBJECTS[0],
            "flow": "delivery",
            "stage": "triage",
            "waiting_on": "customer",
            "urgency_score": 88,
            "evidence_source": "envelope-sim-0001",
            "why": "[sim] 资源申请待确认路径",
            "recipient_role": "to",
        },
        {
            "thread_key": THREAD_SUBJECTS[4],
            "flow": "support",
            "stage": "escalated",
            "waiting_on": "vendor",
            "urgency_score": 92,
            "evidence_source": "envelope-sim-0005",
            "why": "[sim] SLA 相关线程需优先关注",
            "recipient_role": "to",
        },
    ]
    pending_replies = [
        {
            "thread_key": THREAD_SUBJECTS[1],
            "flow": "finance",
            "waiting_on_me": True,
            "why": "[sim] 发票金额待你确认",
            "evidence_source": "envelope-sim-0002",
            "recipient_role": "to",
        },
        {
            "thread_key": THREAD_SUBJECTS[3],
            "flow": "recruiting",
            "waiting_on_me": True,
            "why": "[sim] 面试时段待回复",
            "evidence_source": "envelope-sim-0004",
            "recipient_role": "to",
        },
    ]
    sla_risks = [
        {
            "thread_key": THREAD_SUBJECTS[4],
            "flow": "support",
            "risk_description": "[sim] 回调延迟超过内部阈值",
            "recipient_role": "to",
        },
    ]

    return {
        "envelopes": envelopes,
        "sampled_bodies": sampled_bodies,
        "intent_payload": {
            "generated_at": now,
            "model": "modular-mail-sim",
            "dry_run": False,
            "stats": {
                "total_classified": len(classifications),
                "total_envelopes": len(envelopes),
                "batches": 1,
            },
            "distribution": dist,
            "classifications": classifications,
        },
        "phase4": {
            "daily-urgent.yaml": {"generated_at": now, "daily_urgent": daily_urgent},
            "pending-replies.yaml": {"generated_at": now, "pending_replies": pending_replies},
            "sla-risks.yaml": {"generated_at": now, "sla_risks": sla_risks},
        },
    }


def seed_state_root(state_root: str | Path, *, count: int = 30) -> dict[str, Any]:
    """Write all artifacts under state_root and rebuild activity-pulse.json."""
    root = Path(state_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "runtime").mkdir(parents=True, exist_ok=True)

    data = build_simulation_payload(count=count)
    now = artifacts_generated_at()

    phase1 = {
        "generated_at": now,
        "lookback_days": 14,
        "owner_domain": "example.com",
        "envelopes": data["envelopes"],
        "sampled_bodies": data["sampled_bodies"],
        "stats": {
            "total_envelopes": len(data["envelopes"]),
            "sampled_bodies": len(data["sampled_bodies"]),
            "folders_scanned": ["INBOX"],
        },
    }

    ctx_dir = root / "runtime" / "context"
    p1_dir = root / "runtime" / "validation" / "phase-1"
    p4_dir = root / "runtime" / "validation" / "phase-4"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    p1_dir.mkdir(parents=True, exist_ok=True)
    p4_dir.mkdir(parents=True, exist_ok=True)

    (ctx_dir / "phase1-context.json").write_text(
        json.dumps(phase1, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (p1_dir / "intent-classification.json").write_text(
        json.dumps(data["intent_payload"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for name, payload in data["phase4"].items():
        (p4_dir / name).write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Fresh pulse: drop dedupe so notifiable items appear on first OpenClaw turn
    dedupe = ctx_dir / "activity-pulse-state.json"
    if dedupe.is_file():
        dedupe.unlink()

    _pulse, pulse_path = write_activity_pulse(root, window_hours=72, top_k=5)

    return {
        "state_root": str(root),
        "envelope_count": len(data["envelopes"]),
        "phase1_context": str(ctx_dir / "phase1-context.json"),
        "intent_classification": str(p1_dir / "intent-classification.json"),
        "activity_pulse": str(pulse_path),
        "activity_pulse_summary": _pulse.get("summary", {}),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default="", help="Defaults to TWINBOX_STATE_ROOT or resolved cwd")
    parser.add_argument("--count", type=int, default=30, help="Number of synthetic envelopes")
    parser.add_argument("--json", action="store_true", help="Print result as JSON")
    args = parser.parse_args(argv)

    sr = (args.state_root or os.environ.get("TWINBOX_STATE_ROOT", "")).strip()
    if not sr:
        sr = str(resolve_state_root(Path.cwd()))

    try:
        report = seed_state_root(sr, count=args.count)
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"status": "ok", **report}, ensure_ascii=False, indent=2))
    else:
        print(f"Seeded {report['envelope_count']} envelopes -> {report['state_root']}")
        print(f"  phase1-context: {report['phase1_context']}")
        print(f"  activity-pulse: {report['activity_pulse']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
