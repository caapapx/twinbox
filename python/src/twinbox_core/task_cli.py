"""Task-facing CLI: project Phase 4 artifacts to user-facing views."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

@dataclass(frozen=True)
class ThreadCard:
    """Thread card for queue display."""
    thread_id: str
    state: str
    waiting_on: str
    last_activity_at: str | None
    confidence: float
    evidence_refs: list[str]
    context_refs: list[str]
    why: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "state": self.state,
            "waiting_on": self.waiting_on,
            "last_activity_at": self.last_activity_at,
            "confidence": self.confidence,
            "evidence_refs": self.evidence_refs,
            "context_refs": self.context_refs,
            "why": self.why,
        }


@dataclass(frozen=True)
class QueueView:
    """Queue view projected from Phase 4 artifacts."""
    queue_type: str
    items: list[ThreadCard]
    rank_reason: str
    review_required: bool
    generated_at: str
    stale: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_type": self.queue_type,
            "items": [item.to_dict() for item in self.items],
            "rank_reason": self.rank_reason,
            "review_required": self.review_required,
            "generated_at": self.generated_at,
            "stale": self.stale,
        }


def _load_yaml_artifact(path: Path) -> dict[str, Any]:
    """Load YAML artifact from Phase 4 output."""
    if not path.exists():
        return {}
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        return {}
    return content


def _is_stale(generated_at_str: str, max_age_hours: int = 24) -> bool:
    """Check if artifact is stale based on generated_at timestamp."""
    try:
        generated = datetime.fromisoformat(generated_at_str)
        now = datetime.now(generated.tzinfo)
        age_hours = (now - generated).total_seconds() / 3600
        return age_hours > max_age_hours
    except (ValueError, TypeError):
        return True


def _get_phase4_dir() -> Path:
    """Get Phase 4 output directory."""
    # Use TWINBOX_CANONICAL_ROOT if set, otherwise use current directory
    canonical_root = Path.cwd()
    if "TWINBOX_CANONICAL_ROOT" in os.environ:
        canonical_root = Path(os.environ["TWINBOX_CANONICAL_ROOT"]).expanduser()
    return canonical_root / "runtime" / "validation" / "phase-4"


def _project_urgent_queue() -> QueueView:
    """Project daily-urgent.yaml to QueueView."""
    phase4_dir = _get_phase4_dir()
    artifact = _load_yaml_artifact(phase4_dir / "daily-urgent.yaml")

    generated_at = artifact.get("generated_at", "")
    items_data = artifact.get("daily_urgent", [])

    items = []
    for item in items_data:
        if not isinstance(item, dict):
            continue
        items.append(ThreadCard(
            thread_id=item.get("thread_key", ""),
            state=f"{item.get('flow', 'UNKNOWN')}/{item.get('stage', 'UNKNOWN')}",
            waiting_on=item.get("waiting_on", ""),
            last_activity_at=None,  # Not in Phase 4 artifact
            confidence=item.get("urgency_score", 0) / 100.0,
            evidence_refs=[item.get("evidence_source", "")],
            context_refs=[],
            why=item.get("why", ""),
        ))

    return QueueView(
        queue_type="urgent",
        items=items,
        rank_reason="urgency_score降序排列",
        review_required=False,
        generated_at=generated_at,
        stale=_is_stale(generated_at),
    )


def _project_pending_queue() -> QueueView:
    """Project pending-replies.yaml to QueueView."""
    phase4_dir = _get_phase4_dir()
    artifact = _load_yaml_artifact(phase4_dir / "pending-replies.yaml")

    generated_at = artifact.get("generated_at", "")
    items_data = artifact.get("pending_replies", [])

    items = []
    for item in items_data:
        if not isinstance(item, dict):
            continue
        items.append(ThreadCard(
            thread_id=item.get("thread_key", ""),
            state=f"{item.get('flow', 'UNKNOWN')}/pending_reply",
            waiting_on="me" if item.get("waiting_on_me") else "unknown",
            last_activity_at=None,
            confidence=0.8,  # Default confidence for pending replies
            evidence_refs=[item.get("evidence_source", "")],
            context_refs=[],
            why=item.get("why", ""),
        ))

    return QueueView(
        queue_type="pending",
        items=items,
        rank_reason="等待我回复的线程",
        review_required=True,
        generated_at=generated_at,
        stale=_is_stale(generated_at),
    )


def _project_sla_risk_queue() -> QueueView:
    """Project sla-risks.yaml to QueueView."""
    phase4_dir = _get_phase4_dir()
    artifact = _load_yaml_artifact(phase4_dir / "sla-risks.yaml")

    generated_at = artifact.get("generated_at", "")
    items_data = artifact.get("sla_risks", [])

    items = []
    for item in items_data:
        if not isinstance(item, dict):
            continue
        items.append(ThreadCard(
            thread_id=item.get("thread_key", ""),
            state=f"{item.get('flow', 'UNKNOWN')}/sla_risk",
            waiting_on="",
            last_activity_at=None,
            confidence=0.9,  # High confidence for SLA risks
            evidence_refs=["sla_monitor"],
            context_refs=[],
            why=item.get("risk_description", ""),
        ))

    return QueueView(
        queue_type="sla_risk",
        items=items,
        rank_reason="SLA风险线程",
        review_required=True,
        generated_at=generated_at,
        stale=_is_stale(generated_at),
    )


def _format_queue_list(queues: list[QueueView]) -> str:
    """Format queue list for human-readable output."""
    lines = []
    for queue in queues:
        stale_marker = " [STALE]" if queue.stale else ""
        review_marker = " [需审阅]" if queue.review_required else ""
        lines.append(f"{queue.queue_type}: {len(queue.items)} 项{stale_marker}{review_marker}")
    return "\n".join(lines)


def _format_queue_show(queue: QueueView) -> str:
    """Format queue details for human-readable output."""
    lines = [
        f"队列类型: {queue.queue_type}",
        f"生成时间: {queue.generated_at}",
        f"排序规则: {queue.rank_reason}",
        f"需要审阅: {'是' if queue.review_required else '否'}",
        f"状态: {'过期' if queue.stale else '最新'}",
        f"线程数: {len(queue.items)}",
        "",
    ]

    for idx, item in enumerate(queue.items, 1):
        lines.extend([
            f"[{idx}] {item.thread_id}",
            f"    状态: {item.state}",
            f"    等待: {item.waiting_on}",
            f"    置信度: {item.confidence:.2f}",
            f"    原因: {item.why}",
            "",
        ])

    return "\n".join(lines)


def cmd_queue_list(args: argparse.Namespace) -> int:
    """List all queues."""
    queues = [
        _project_urgent_queue(),
        _project_pending_queue(),
        _project_sla_risk_queue(),
    ]

    if args.json:
        output = [q.to_dict() for q in queues]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(_format_queue_list(queues))

    return 0


def cmd_queue_show(args: argparse.Namespace) -> int:
    """Show details of a specific queue."""
    queue_map = {
        "urgent": _project_urgent_queue,
        "pending": _project_pending_queue,
        "sla_risk": _project_sla_risk_queue,
    }

    if args.queue_type not in queue_map:
        print(f"错误: 未知队列类型 '{args.queue_type}'", file=sys.stderr)
        print(f"可用类型: {', '.join(queue_map.keys())}", file=sys.stderr)
        return 1

    queue = queue_map[args.queue_type]()

    if args.json:
        print(json.dumps(queue.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(_format_queue_show(queue))

    return 0


def cmd_queue_explain(args: argparse.Namespace) -> int:
    """Explain queue ranking and projection logic."""
    explanation = """
队列投影说明
============

twinbox 的队列视图从 Phase 4 artifacts 投影而来，不是独立的数据管道。

数据源映射：
- urgent 队列 <- runtime/validation/phase-4/daily-urgent.yaml
- pending 队列 <- runtime/validation/phase-4/pending-replies.yaml
- sla_risk 队列 <- runtime/validation/phase-4/sla-risks.yaml

投影规则：
1. urgent: 按 urgency_score 降序排列，confidence = urgency_score / 100
2. pending: 等待我回复的线程，默认 confidence = 0.8
3. sla_risk: SLA 风险线程，默认 confidence = 0.9

过期检测：
- 如果 generated_at 超过 24 小时，标记为 STALE
- 过期队列建议重新运行 Phase 4: twinbox orchestrate run phase4

审阅标记：
- pending 和 sla_risk 队列默认需要人工审阅
- urgent 队列不需要审阅，可直接执行
"""
    print(explanation.strip())
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twinbox",
        description="Task-facing CLI for twinbox email copilot",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # queue commands
    queue_parser = subparsers.add_parser("queue", help="Queue management")
    queue_sub = queue_parser.add_subparsers(dest="queue_command", required=True)

    queue_list = queue_sub.add_parser("list", help="List all queues")
    queue_list.add_argument("--json", action="store_true", help="Output as JSON")

    queue_show = queue_sub.add_parser("show", help="Show queue details")
    queue_show.add_argument("queue_type", help="Queue type (urgent/pending/sla_risk)")
    queue_show.add_argument("--json", action="store_true", help="Output as JSON")

    queue_explain = queue_sub.add_parser("explain", help="Explain queue projection")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for task-facing CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "queue":
            if args.queue_command == "list":
                return cmd_queue_list(args)
            elif args.queue_command == "show":
                return cmd_queue_show(args)
            elif args.queue_command == "explain":
                return cmd_queue_explain(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

