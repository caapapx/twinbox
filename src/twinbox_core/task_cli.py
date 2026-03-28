"""Task-facing CLI: project Phase 4 artifacts to user-facing views."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .paths import resolve_state_root

from .task_cli_daemon import dispatch_daemon, register_daemon_parser
from .task_cli_loading import dispatch_loading, register_loading_parser
from .task_cli_vendor import dispatch_vendor, register_vendor_parser

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


@dataclass(frozen=True)
class DigestView:
    """Digest view projected from Phase 4 artifacts."""
    digest_type: str
    sections: dict[str, Any]
    generated_at: str
    stale: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest_type": self.digest_type,
            "sections": self.sections,
            "generated_at": self.generated_at,
            "stale": self.stale,
        }


@dataclass(frozen=True)
class ActionCard:
    """Action suggestion projected from Phase 4 artifacts."""
    action_id: str
    thread_id: str
    action_type: str  # reply | forward | archive | flag
    why_now: str
    risk_level: str  # low | medium | high
    required_review_fields: list[str]
    suggested_draft_mode: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "thread_id": self.thread_id,
            "action_type": self.action_type,
            "why_now": self.why_now,
            "risk_level": self.risk_level,
            "required_review_fields": self.required_review_fields,
            "suggested_draft_mode": self.suggested_draft_mode,
        }


@dataclass(frozen=True)
class ReviewItem:
    """Review item for human review surface."""
    review_id: str
    thread_id: str
    review_type: str  # state_override | action_approval | confidence_check
    current_state: str
    proposed_change: str
    reason: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "thread_id": self.thread_id,
            "review_type": self.review_type,
            "current_state": self.current_state,
            "proposed_change": self.proposed_change,
            "reason": self.reason,
            "created_at": self.created_at,
        }


def _load_yaml_artifact(path: Path) -> dict[str, Any]:
    """Load YAML artifact from Phase 4 output. Returns {} on any failure."""
    if not path.exists():
        return {}
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(content, dict):
        return {}
    return content


def _load_json_artifact(path: Path) -> dict[str, Any]:
    """Load a JSON artifact and return {} on any failure."""
    if not path.exists():
        return {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return content if isinstance(content, dict) else {}


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
    return resolve_state_root(Path.cwd()) / "runtime" / "validation" / "phase-4"


def _state_root() -> Path:
    return resolve_state_root(Path.cwd())


def _strip_thread_display_prefix(thread_id: str) -> str:
    return re.sub(r"^\[(?:CC|GRP)\]\s*", "", str(thread_id or "").strip(), flags=re.IGNORECASE)


def _thread_lookup_key(thread_id: str) -> str:
    from .daytime_slice import _normalize_thread as _normalize_activity_thread

    return _normalize_activity_thread(_strip_thread_display_prefix(thread_id))


def _thread_matches(candidate: object, target: str) -> bool:
    candidate_text = str(candidate or "").strip()
    target_text = _strip_thread_display_prefix(target)
    return (
        candidate_text == target_text
        or _thread_lookup_key(candidate_text) == _thread_lookup_key(target_text)
    )


def _message_id_from_ref(message_ref: object) -> str:
    text = str(message_ref or "")
    if "#" not in text:
        return ""
    return text.rsplit("#", 1)[-1].strip()


def _find_thread_in_phase3_context(thread_id: str) -> dict[str, Any] | None:
    payload = _load_json_artifact(_state_root() / "runtime" / "validation" / "phase-3" / "context-pack.json")
    top_threads = payload.get("top_threads", [])
    if not isinstance(top_threads, list):
        return None
    for item in top_threads:
        if isinstance(item, dict) and _thread_matches(item.get("thread_key"), thread_id):
            return item
    return None


def _find_thread_in_activity_pulse(thread_id: str) -> dict[str, Any] | None:
    from .daytime_slice import DaytimeSliceError, load_activity_pulse

    try:
        payload = load_activity_pulse(_state_root())
    except DaytimeSliceError:
        return None
    thread_index = payload.get("thread_index", [])
    if not isinstance(thread_index, list):
        return None
    for item in thread_index:
        if isinstance(item, dict) and _thread_matches(item.get("thread_key"), thread_id):
            return item
    return None


def _pulse_snapshot_for_thread(thread_id: str) -> dict[str, Any] | None:
    item = _find_thread_in_activity_pulse(thread_id)
    if not isinstance(item, dict):
        return None
    return {
        "thread_key": str(item.get("thread_key", "") or ""),
        "latest_message_ref": str(item.get("latest_message_ref", "") or ""),
        "message_count": int(item.get("message_count", 0) or 0),
        "fingerprint": str(item.get("fingerprint", "") or ""),
        "last_activity_at": str(item.get("last_activity_at", "") or ""),
        "queue_tags": item.get("queue_tags", []) if isinstance(item.get("queue_tags"), list) else [],
    }


def _find_thread_sampled_body(thread_id: str, latest_message_ref: str = "") -> dict[str, Any] | None:
    payload = _load_json_artifact(_state_root() / "runtime" / "context" / "phase1-context.json")
    sampled_bodies = payload.get("sampled_bodies", {})
    envelopes = payload.get("envelopes", [])
    if not isinstance(sampled_bodies, dict):
        sampled_bodies = {}
    if not isinstance(envelopes, list):
        envelopes = []

    preferred_id = _message_id_from_ref(latest_message_ref)
    if preferred_id:
        row = sampled_bodies.get(preferred_id)
        if isinstance(row, dict):
            return {
                "message_id": preferred_id,
                "subject": str(row.get("subject", "") or ""),
                "body": str(row.get("body", "") or ""),
                "date": "",
            }

    for envelope in reversed(envelopes):
        if not isinstance(envelope, dict) or not _thread_matches(envelope.get("subject"), thread_id):
            continue
        message_id = str(envelope.get("id", "") or "")
        row = sampled_bodies.get(message_id)
        if not isinstance(row, dict):
            continue
        return {
            "message_id": message_id,
            "subject": str(row.get("subject", envelope.get("subject", "")) or ""),
            "body": str(row.get("body", "") or ""),
            "date": str(envelope.get("date", "") or ""),
        }
    return None


def _thread_confidence(queue_data: dict[str, Any], pulse_data: dict[str, Any], context_data: dict[str, Any]) -> float:
    for raw in (
        queue_data.get("urgency_score"),
        context_data.get("intent_confidence"),
        pulse_data.get("score"),
    ):
        if raw is None or raw == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        return value if value <= 1 else value / 100.0
    return 0.0


def _recipient_role_map() -> dict[str, str]:
    phase3_context = _state_root() / "runtime" / "validation" / "phase-3" / "context-pack.json"
    try:
        payload = json.loads(phase3_context.read_text(encoding="utf-8"))
    except Exception:
        return {}
    top_threads = payload.get("top_threads", []) if isinstance(payload, dict) else []
    role_map: dict[str, str] = {}
    if not isinstance(top_threads, list):
        return role_map
    for item in top_threads:
        if not isinstance(item, dict):
            continue
        key = str(item.get("thread_key", "") or "")
        role = str(item.get("recipient_role", "") or "")
        if key and role:
            role_map[key] = role
    return role_map


def _display_thread_key(thread_key: str, recipient_role: str | None) -> str:
    if recipient_role in ("cc_only", "indirect"):
        return f"[CC] {thread_key}"
    if recipient_role == "group_only":
        return f"[GRP] {thread_key}"
    return thread_key


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
        thread_id = item.get("thread_key", "")
        role = item.get("recipient_role")
        if role in ("cc_only", "indirect"):
            thread_id = f"[CC] {thread_id}"
        elif role == "group_only":
            thread_id = f"[GRP] {thread_id}"
        items.append(ThreadCard(
            thread_id=thread_id,
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
        thread_id = item.get("thread_key", "")
        role = item.get("recipient_role")
        if role in ("cc_only", "indirect"):
            thread_id = f"[CC] {thread_id}"
        elif role == "group_only":
            thread_id = f"[GRP] {thread_id}"
        items.append(ThreadCard(
            thread_id=thread_id,
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
- 过期队列建议重新运行 Phase 4: twinbox-orchestrate run --phase 4

审阅标记：
- pending 和 sla_risk 队列默认需要人工审阅
- urgent 队列不需要审阅，可直接执行
"""
    print(explanation.strip())
    return 0


def cmd_queue_dismiss(args: argparse.Namespace) -> int:
    """Dismiss a thread from queue-facing pulse views."""
    from .user_queue_state import dismiss_thread

    snapshot = _pulse_snapshot_for_thread(args.thread_id)
    if not snapshot:
        print(f"错误: 未找到线程 '{args.thread_id}'", file=sys.stderr)
        return 1
    queue_tags = snapshot.get("queue_tags", [])
    dismissed_from_queue = queue_tags[0] if isinstance(queue_tags, list) and queue_tags else ""
    dismiss_thread(
        state_root=_state_root(),
        thread_key=str(snapshot["thread_key"]),
        snapshot=snapshot,
        reason=args.reason,
        dismissed_from_queue=dismissed_from_queue,
    )
    output = {
        "thread_key": snapshot["thread_key"],
        "status": "dismissed",
        "reason": args.reason,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"已忽略线程: {snapshot['thread_key']}")
    return 0


def cmd_queue_complete(args: argparse.Namespace) -> int:
    """Mark a thread as completed so it stays hidden until restored."""
    from .user_queue_state import complete_thread

    snapshot = _pulse_snapshot_for_thread(args.thread_id)
    if not snapshot:
        print(f"错误: 未找到线程 '{args.thread_id}'", file=sys.stderr)
        return 1
    complete_thread(
        state_root=_state_root(),
        thread_key=str(snapshot["thread_key"]),
        snapshot=snapshot,
        action_taken=args.action_taken,
    )
    output = {
        "thread_key": snapshot["thread_key"],
        "status": "completed",
        "action_taken": args.action_taken,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"已完成线程: {snapshot['thread_key']}")
    return 0


def cmd_queue_restore(args: argparse.Namespace) -> int:
    """Restore a thread back to visible queue state."""
    from .user_queue_state import restore_thread

    restore_thread(state_root=_state_root(), thread_key=args.thread_id)
    output = {
        "thread_key": args.thread_id,
        "status": "restored",
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"已恢复线程: {args.thread_id}")
    return 0


def cmd_schedule_list(args: argparse.Namespace) -> int:
    """List effective schedule config merged from defaults and runtime overrides."""
    from .schedule_override import load_schedule_config

    payload = load_schedule_config(_state_root())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    lines = [f"时区: {payload.get('timezone', '')}", "", "当前调度:", ""]
    for row in payload.get("schedules", []):
        if not isinstance(row, dict):
            continue
        lines.extend(
            [
                f"- {row.get('name', 'unknown')}: {row.get('effective_cron', '')} ({row.get('source', 'default')})",
                f"  默认: {row.get('default_cron', '')}",
                f"  命令: {row.get('command', '')}",
            ]
        )
    print("\n".join(lines))
    return 0


def cmd_schedule_update(args: argparse.Namespace) -> int:
    """Update one runtime schedule override."""
    from .schedule_override import update_schedule_override

    try:
        payload = update_schedule_override(
            state_root=_state_root(),
            job_name=args.job_name,
            cron=args.cron,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"已更新 {payload['job_name']} -> {payload['effective_cron']}")
    print(payload["next_action"])
    return 0


def cmd_schedule_reset(args: argparse.Namespace) -> int:
    """Reset one runtime schedule override back to default."""
    from .schedule_override import reset_schedule_override

    try:
        payload = reset_schedule_override(
            state_root=_state_root(),
            job_name=args.job_name,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"已恢复 {payload['job_name']} 默认 cron: {payload['effective_cron']}")
    print(payload["next_action"])
    return 0


def cmd_schedule_enable(args: argparse.Namespace) -> int:
    """Enable a schedule and create the OpenClaw cron job."""
    from .schedule_override import enable_schedule

    try:
        payload = enable_schedule(
            state_root=_state_root(),
            job_name=args.job_name,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"已启用 {payload['job_name']}: {payload['effective_cron']}")
    print(payload["next_action"])
    return 0


def cmd_schedule_disable(args: argparse.Namespace) -> int:
    """Disable a schedule and delete the OpenClaw cron job."""
    from .schedule_override import disable_schedule

    try:
        payload = disable_schedule(
            state_root=_state_root(),
            job_name=args.job_name,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"已禁用 {payload['job_name']}")
    print(payload["next_action"])
    return 0


def cmd_context_import_material(args: argparse.Namespace) -> int:
    """Import user material to runtime/context/material-extracts/ and optional Markdown extract."""
    canonical_root = _state_root()

    materials_dir = canonical_root / "runtime" / "context" / "material-extracts"
    materials_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(args.source).expanduser()
    if not source_path.exists():
        print(f"错误: 源文件不存在: {args.source}", file=sys.stderr)
        return 1

    # Copy material to materials directory
    import shutil
    dest_path = materials_dir / source_path.name
    shutil.copy2(source_path, dest_path)

    # Update material-manifest.json
    manifest_path = canonical_root / "runtime" / "context" / "material-manifest.json"
    manifest = {"generated_at": "", "materials": []}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    from datetime import datetime
    manifest["generated_at"] = datetime.now().isoformat()

    # Update or append material entry
    materials = manifest.setdefault("materials", [])
    existing = next((m for m in materials if m.get("filename") == source_path.name), None)
    if existing:
        existing["imported_at"] = datetime.now().isoformat()
        existing["source"] = str(source_path)
        existing["intent"] = args.intent
    else:
        materials.append({
            "filename": source_path.name,
            "imported_at": datetime.now().isoformat(),
            "source": str(source_path),
            "intent": args.intent,
        })

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已导入材料: {source_path.name} -> {dest_path}")
    print(f"更新清单: {manifest_path}")

    try:
        from .material_extract import MaterialExtractError, write_extract_for_import

        extract_path = write_extract_for_import(source_path, materials_dir)
    except MaterialExtractError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    if extract_path is not None:
        print(f"已生成抽取 Markdown（供 Phase 4 引用）: {extract_path}")
    return 0


def cmd_material_list(args: argparse.Namespace) -> int:
    """List all imported materials."""
    canonical_root = _state_root()
    manifest_path = canonical_root / "runtime" / "context" / "material-manifest.json"
    if not manifest_path.exists():
        print("无材料")
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    materials = manifest.get("materials", [])
    if not materials:
        print("无材料")
        return 0
    for m in materials:
        intent = m.get("intent", "reference")
        print(f"{m['filename']:<40} intent={intent:<15} imported={m.get('imported_at', 'unknown')}")
    return 0


def cmd_material_set_intent(args: argparse.Namespace) -> int:
    """Set material intent."""
    canonical_root = _state_root()
    manifest_path = canonical_root / "runtime" / "context" / "material-manifest.json"
    if not manifest_path.exists():
        print(f"错误: manifest 不存在", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    materials = manifest.get("materials", [])
    target = next((m for m in materials if m.get("filename") == args.filename), None)
    if not target:
        print(f"错误: 材料不存在: {args.filename}", file=sys.stderr)
        return 1
    target["intent"] = args.intent
    manifest["generated_at"] = datetime.now().isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已更新 {args.filename} intent -> {args.intent}")
    return 0


def cmd_material_remove(args: argparse.Namespace) -> int:
    """Remove material."""
    canonical_root = _state_root()
    materials_dir = canonical_root / "runtime" / "context" / "material-extracts"
    manifest_path = canonical_root / "runtime" / "context" / "material-manifest.json"

    if not manifest_path.exists():
        print(f"错误: manifest 不存在", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    materials = manifest.get("materials", [])
    target = next((m for m in materials if m.get("filename") == args.filename), None)
    if not target:
        print(f"错误: 材料不存在: {args.filename}", file=sys.stderr)
        return 1

    # Remove files
    import shutil
    material_path = materials_dir / args.filename
    if material_path.exists():
        material_path.unlink()

    # Remove extract
    from twinbox_core.material_extract import extract_output_path
    extract_path = extract_output_path(material_path, materials_dir)
    if extract_path.exists():
        extract_path.unlink()

    # Update manifest
    manifest["materials"] = [m for m in materials if m.get("filename") != args.filename]
    manifest["generated_at"] = datetime.now().isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已删除材料: {args.filename}")
    return 0


def cmd_material_preview(args: argparse.Namespace) -> int:
    """Preview material impact on Phase 4."""
    canonical_root = _state_root()
    manifest_path = canonical_root / "runtime" / "context" / "material-manifest.json"

    if not manifest_path.exists():
        print(f"错误: manifest 不存在", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    materials = manifest.get("materials", [])
    target = next((m for m in materials if m.get("filename") == args.filename), None)
    if not target:
        print(f"错误: 材料不存在: {args.filename}", file=sys.stderr)
        return 1

    intent = target.get("intent", "reference")
    print(f"材料: {args.filename}")
    print(f"Intent: {intent}")
    print(f"导入时间: {target.get('imported_at', 'unknown')}")
    print()

    # Read material extract to analyze structure
    materials_dir = canonical_root / "runtime" / "context" / "material-extracts"
    from twinbox_core.material_extract import extract_output_path
    extract_path = extract_output_path(Path(args.filename), materials_dir)

    if extract_path.exists():
        content = extract_path.read_text(encoding="utf-8")
        # Parse table structure
        lines = content.split("\n")
        table_headers = [l for l in lines if l.startswith("|") and "---" not in l]
        if table_headers:
            print(f"表格结构: {table_headers[0].count('|') - 1} 列")
            print(f"表头: {table_headers[0].strip()}")
        print()

    # Analyze context for relevant threads (prefer Phase 4 which has lifecycle_flow)
    phase4_context = canonical_root / "runtime" / "validation" / "phase-4" / "context-pack.json"
    phase3_context = canonical_root / "runtime" / "validation" / "phase-3" / "context-pack.json"

    context_path = phase4_context if phase4_context.exists() else phase3_context
    if context_path.exists():
        ctx = json.loads(context_path.read_text(encoding="utf-8"))
        # Phase 4 uses 'threads', Phase 3 uses 'top_threads'
        threads = ctx.get("threads") or ctx.get("top_threads", [])

        # Count threads by lifecycle_flow
        flow_counts = {}
        for t in threads:
            flow = t.get("lifecycle_flow") or "UNMODELED"
            flow_counts[flow] = flow_counts.get(flow, 0) + 1

        print("本周线程分布:")
        for flow, count in sorted(flow_counts.items(), key=lambda x: -x[1]):
            print(f"  {flow}: {count}")
        print()

        if intent == "template_hint":
            print("预期影响:")
            print("- 将作为输出格式参考注入 Phase 4")
            print("- LLM 会尝试按类似结构组织相关数据")
            print("- 不会被 synthetic 规则隔离")
        else:
            print("预期影响:")
            print("- 作为参考数据注入 Phase 4")
            print("- 用于排序和判断提示")
            print("- 如标记为 synthetic 会隔离到 material_summary")
    else:
        print("Phase 3 context 不存在，无法预览线程相关性")

    return 0


def cmd_context_upsert_fact(args: argparse.Namespace) -> int:
    """Add or update manual fact to runtime/context/manual-facts.yaml."""
    canonical_root = _state_root()

    facts_path = canonical_root / "runtime" / "context" / "manual-facts.yaml"
    facts_data = {"facts": []}
    if facts_path.exists():
        facts_data = yaml.safe_load(facts_path.read_text(encoding="utf-8")) or {"facts": []}

    from datetime import datetime
    new_fact = {
        "id": args.id,
        "type": args.type,
        "source": args.source,
        "updated_at": datetime.now().strftime("%Y-%m-%d"),
        "content": args.content,
    }

    # Update existing fact or append new one
    facts = facts_data.setdefault("facts", [])
    existing_idx = next((i for i, f in enumerate(facts) if f.get("id") == args.id), None)
    if existing_idx is not None:
        facts[existing_idx] = new_fact
        print(f"已更新事实: {args.id}")
    else:
        facts.append(new_fact)
        print(f"已添加事实: {args.id}")

    facts_path.write_text(yaml.dump(facts_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"保存到: {facts_path}")
    return 0


def cmd_context_profile_set(args: argparse.Namespace) -> int:
    """Set user profile configuration."""
    canonical_root = _state_root()

    profiles_dir = canonical_root / "config" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    profile_path = profiles_dir / f"{args.profile}.yaml"

    if args.key and args.value:
        # Update specific key
        profile_data = {}
        if profile_path.exists():
            profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}

        # Support nested keys like "style.language"
        keys = args.key.split(".")
        current = profile_data
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = args.value

        profile_path.write_text(yaml.dump(profile_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"已更新配置: {args.profile}.{args.key} = {args.value}")
    else:
        # Show current profile
        if profile_path.exists():
            print(profile_path.read_text(encoding="utf-8"))
        else:
            print(f"配置文件不存在: {profile_path}", file=sys.stderr)
            return 1

    return 0


def cmd_context_refresh(args: argparse.Namespace) -> int:
    """Refresh Phase 1 context-pack."""
    print("刷新 Phase 1 context-pack...")
    print("提示: 使用 'twinbox-orchestrate run --phase 1' 重新生成 Phase 1 artifacts")
    return 0


def cmd_mailbox_preflight(args: argparse.Namespace) -> int:
    """Run read-only mailbox preflight for password-env mode."""
    from .mailbox import format_preflight_text, run_preflight

    exit_code, result = run_preflight(
        state_root=args.state_root,
        account_override=args.account,
        folder=args.folder,
        page_size=args.page_size,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_preflight_text(result))

    return exit_code


def cmd_mailbox_detect(args: argparse.Namespace) -> int:
    """Auto-detect mailbox server configuration from email address."""
    from .mailbox_detect import detect_to_env

    email = args.email
    result = detect_to_env(email, verbose=not args.json)

    if result is None:
        if args.json:
            print(json.dumps({"error": "No valid IMAP/SMTP servers detected"}, ensure_ascii=False))
        else:
            print(f"❌ No valid servers detected for {email}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"✅ Detected config for {email}:")
        print(f"  IMAP: {result['IMAP_HOST']}:{result['IMAP_PORT']} ({result['IMAP_ENCRYPTION']})")
        print(f"  SMTP: {result['SMTP_HOST']}:{result['SMTP_PORT']} ({result['SMTP_ENCRYPTION']})")
        print(f"  Confidence: {result['_confidence']}")
        print(f"  Note: {result['_note']}")

    return 0


def cmd_mailbox_setup(args: argparse.Namespace) -> int:
    """Configure mailbox credentials via env var injection and write twinbox.json."""
    return cmd_config_mailbox_set(args)


def cmd_config_show(args: argparse.Namespace) -> int:
    """Show the single-source Twinbox configuration."""
    from .twinbox_config import config_path_for_state_root, load_config_or_legacy, load_masked_twinbox_config, save_twinbox_config

    state_root = _state_root()
    config_path = config_path_for_state_root(state_root)
    if config_path.exists():
        payload = load_masked_twinbox_config(config_path)
    else:
        payload = load_config_or_legacy(state_root / ".env")
        save_twinbox_config(config_path, payload)
        payload = load_masked_twinbox_config(config_path)
    payload["config_file_path"] = str(config_path)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Twinbox config: {config_path}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_config_mailbox_set(args: argparse.Namespace) -> int:
    """Configure mailbox settings into the single-source Twinbox config."""
    from .env_writer import mask_secret, merge_env_file, write_env_file
    from .mailbox import resolve_mailbox_paths, run_preflight
    from .mailbox_detect import detect_to_env
    from .twinbox_config import config_path_for_state_root

    imap_pass = os.environ.get("TWINBOX_SETUP_IMAP_PASS", "").strip()
    if not imap_pass:
        if args.json:
            print(json.dumps({
                "status": "fail",
                "error_code": "missing_imap_pass",
                "actionable_hint": "Set TWINBOX_SETUP_IMAP_PASS env var before calling this command.",
            }, ensure_ascii=False, indent=2))
        else:
            print("错误: 必须设置 TWINBOX_SETUP_IMAP_PASS 环境变量", file=sys.stderr)
        return 2

    smtp_pass = os.environ.get("TWINBOX_SETUP_SMTP_PASS", "").strip() or imap_pass
    imap_host = getattr(args, "imap_host", "")
    imap_port = getattr(args, "imap_port", "")
    imap_encryption = getattr(args, "imap_encryption", "")
    smtp_host = getattr(args, "smtp_host", "")
    smtp_port = getattr(args, "smtp_port", "")
    smtp_encryption = getattr(args, "smtp_encryption", "")
    detected = None
    if not imap_host or not smtp_host:
        detected = detect_to_env(args.email, verbose=False)
        if detected is None:
            if args.json:
                print(json.dumps({
                    "status": "fail",
                    "error_code": "detect_failed",
                    "actionable_hint": f"Could not auto-detect mailbox servers for {args.email}.",
                }, ensure_ascii=False, indent=2))
            else:
                print(f"错误: 无法自动探测邮箱服务器: {args.email}", file=sys.stderr)
            return 1

    imap_login = args.imap_login or args.email
    smtp_login = args.smtp_login or args.email
    updates: dict[str, str] = {
        "MAIL_ADDRESS": args.email,
        "IMAP_HOST": imap_host or detected["IMAP_HOST"],
        "IMAP_PORT": imap_port or detected["IMAP_PORT"],
        "IMAP_ENCRYPTION": imap_encryption or detected["IMAP_ENCRYPTION"],
        "IMAP_LOGIN": imap_login,
        "IMAP_PASS": imap_pass,
        "SMTP_HOST": smtp_host or detected["SMTP_HOST"],
        "SMTP_PORT": smtp_port or detected["SMTP_PORT"],
        "SMTP_ENCRYPTION": smtp_encryption or detected["SMTP_ENCRYPTION"],
        "SMTP_LOGIN": smtp_login,
        "SMTP_PASS": smtp_pass,
    }

    paths = resolve_mailbox_paths(state_root=args.state_root)
    merged = merge_env_file(paths.env_file, updates)
    write_env_file(paths.env_file, merged)
    exit_code, preflight = run_preflight(state_root=args.state_root)

    output = {
        "status": "ok" if exit_code == 0 else "warn",
        "config_file_path": str(config_path_for_state_root(paths.state_root)),
        "mailbox_config": {
            "MAIL_ADDRESS": args.email,
            "IMAP_HOST": updates["IMAP_HOST"],
            "IMAP_PORT": updates["IMAP_PORT"],
            "IMAP_ENCRYPTION": updates["IMAP_ENCRYPTION"],
            "IMAP_LOGIN": imap_login,
            "IMAP_PASS": mask_secret(imap_pass),
            "SMTP_HOST": updates["SMTP_HOST"],
            "SMTP_PORT": updates["SMTP_PORT"],
            "SMTP_ENCRYPTION": updates["SMTP_ENCRYPTION"],
            "SMTP_LOGIN": smtp_login,
            "SMTP_PASS": mask_secret(smtp_pass),
        },
        "preflight_result": preflight,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"✅ Mailbox config written: {config_path_for_state_root(paths.state_root)}")
        print(f"  IMAP: {updates['IMAP_HOST']}:{updates['IMAP_PORT']} ({updates['IMAP_ENCRYPTION']})")
        print(f"  SMTP: {updates['SMTP_HOST']}:{updates['SMTP_PORT']} ({updates['SMTP_ENCRYPTION']})")
    return exit_code


def cmd_config_set_llm(args: argparse.Namespace) -> int:
    """Configure LLM API key and write twinbox.json."""
    from .env_writer import mask_secret, merge_env_file, write_env_file
    from .llm import resolve_backend, LLMError
    from .twinbox_config import config_path_for_state_root

    api_key = os.environ.get("TWINBOX_SETUP_API_KEY", "").strip()
    if not api_key:
        if args.json:
            print(json.dumps({
                "status": "fail",
                "error_code": "missing_api_key",
                "actionable_hint": "Set TWINBOX_SETUP_API_KEY env var before calling this command.",
            }, ensure_ascii=False, indent=2))
        else:
            print("错误: 必须设置 TWINBOX_SETUP_API_KEY 环境变量", file=sys.stderr)
        return 2

    state_root = _state_root()
    env_file = state_root / ".env"

    if not args.model.strip():
        if args.json:
            print(json.dumps({
                "status": "fail",
                "error_code": "missing_model",
                "actionable_hint": "Pass --model explicitly. Twinbox no longer uses a built-in default model.",
            }, ensure_ascii=False, indent=2))
        else:
            print("错误: 必须显式传入 --model；Twinbox 不再内置默认模型", file=sys.stderr)
        return 2

    if not args.api_url.strip():
        if args.json:
            print(json.dumps({
                "status": "fail",
                "error_code": "missing_api_url",
                "actionable_hint": "Pass --api-url explicitly. Twinbox no longer uses a built-in default API URL.",
            }, ensure_ascii=False, indent=2))
        else:
            print("错误: 必须显式传入 --api-url；Twinbox 不再内置默认 API URL", file=sys.stderr)
        return 2

    updates: dict[str, str] = {}
    if args.provider == "anthropic":
        updates["ANTHROPIC_API_KEY"] = api_key
        updates["ANTHROPIC_MODEL"] = args.model
        updates["ANTHROPIC_BASE_URL"] = args.api_url
    else:  # openai (default)
        updates["LLM_API_KEY"] = api_key
        updates["LLM_MODEL"] = args.model
        updates["LLM_API_URL"] = args.api_url

    merged = merge_env_file(env_file, updates)
    write_env_file(env_file, merged)

    # Validate by resolving backend from the merged env (not process env)
    from .llm import load_env_file as llm_load_env_file, merged_env
    try:
        from .llm import resolve_backend
        cfg = resolve_backend(env_file=env_file, env={})
        backend_ok = True
        resolved_model = cfg.model
        resolved_url = cfg.url
    except LLMError as exc:
        backend_ok = False
        resolved_model = args.model or ""
        resolved_url = args.api_url or ""

    api_url_display = resolved_url or args.api_url or ""
    output = {
        "status": "ok" if backend_ok else "warn",
        "provider": args.provider,
        "model": resolved_model,
        "api_url": api_url_display,
        "api_key_masked": mask_secret(api_key),
        "config_file_path": str(config_path_for_state_root(state_root)),
        "backend_validated": backend_ok,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        status_icon = "✅" if backend_ok else "⚠️"
        print(f"{status_icon} LLM 配置已写入: {config_path_for_state_root(state_root)}")
        print(f"  Provider: {args.provider}")
        print(f"  Model: {resolved_model}")
        print(f"  API Key: {mask_secret(api_key)}")
    return 0 if backend_ok else 1


def cmd_config_set_integration(args: argparse.Namespace) -> int:
    """Persist Twinbox integration preferences into twinbox.json."""
    from .twinbox_config import config_path_for_state_root, load_twinbox_config, save_twinbox_config

    state_root = _state_root()
    config_path = config_path_for_state_root(state_root)
    payload = load_twinbox_config(config_path)
    integration = payload.get("integration", {}) if isinstance(payload.get("integration"), dict) else {}
    if args.fragment_path:
        integration["fragment_path"] = str(Path(args.fragment_path).expanduser())
    if args.use_fragment:
        integration["use_fragment"] = args.use_fragment == "yes"
    payload["integration"] = integration
    save_twinbox_config(config_path, payload)
    result = {"status": "ok", "config_file_path": str(config_path), "integration": integration}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"✅ Integration config written: {config_path}")
    return 0


def cmd_config_set_openclaw(args: argparse.Namespace) -> int:
    """Persist OpenClaw defaults into twinbox.json."""
    from .twinbox_config import config_path_for_state_root, load_twinbox_config, save_twinbox_config

    state_root = _state_root()
    config_path = config_path_for_state_root(state_root)
    payload = load_twinbox_config(config_path)
    openclaw_cfg = payload.get("openclaw", {}) if isinstance(payload.get("openclaw"), dict) else {}
    if args.home:
        openclaw_cfg["home"] = str(Path(args.home).expanduser())
    if args.bin:
        openclaw_cfg["bin"] = args.bin
    if args.strict:
        openclaw_cfg["strict"] = True
    if args.no_strict:
        openclaw_cfg["strict"] = False
    if args.sync_env:
        openclaw_cfg["sync_env_from_dotenv"] = True
    if args.no_sync_env:
        openclaw_cfg["sync_env_from_dotenv"] = False
    if args.restart_gateway:
        openclaw_cfg["restart_gateway"] = True
    if args.no_restart_gateway:
        openclaw_cfg["restart_gateway"] = False
    payload["openclaw"] = openclaw_cfg
    save_twinbox_config(config_path, payload)
    result = {"status": "ok", "config_file_path": str(config_path), "openclaw": openclaw_cfg}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"✅ OpenClaw defaults written: {config_path}")
    return 0


def cmd_deploy_openclaw(args: argparse.Namespace) -> int:
    """Host-side OpenClaw wiring (SKILL sync, openclaw.json, roots, gateway)."""
    from twinbox_core.openclaw_deploy import run_openclaw_deploy, run_openclaw_rollback
    from twinbox_core.twinbox_config import config_path_for_state_root, load_twinbox_config

    state_root = _state_root()
    config = load_twinbox_config(config_path_for_state_root(state_root))
    openclaw_defaults = config.get("openclaw", {}) if isinstance(config.get("openclaw"), dict) else {}
    integration_defaults = config.get("integration", {}) if isinstance(config.get("integration"), dict) else {}

    code_root = Path(args.repo_root).expanduser() if args.repo_root else None
    configured_home = str(openclaw_defaults.get("home", "") or "").strip()
    openclaw_home = Path(args.openclaw_home).expanduser() if args.openclaw_home else (Path(configured_home).expanduser() if configured_home else None)
    openclaw_bin = args.openclaw_bin or str(openclaw_defaults.get("bin", "") or "openclaw")
    if args.rollback:
        report = run_openclaw_rollback(
            code_root=code_root,
            openclaw_home=openclaw_home,
            dry_run=args.dry_run,
            restart_gateway=(not args.no_restart) if args.no_restart else bool(openclaw_defaults.get("restart_gateway", True)),
            remove_config=args.remove_config,
            openclaw_bin=openclaw_bin,
        )
        label = "Rollback"
    else:
        fragment_value = args.fragment.strip() or str(integration_defaults.get("fragment_path", "") or "").strip()
        frag = Path(fragment_value).expanduser() if fragment_value else None
        report = run_openclaw_deploy(
            code_root=code_root,
            openclaw_home=openclaw_home,
            dry_run=args.dry_run,
            restart_gateway=(not args.no_restart) if args.no_restart else bool(openclaw_defaults.get("restart_gateway", True)),
            sync_env_from_dotenv=(not args.no_env_sync) if args.no_env_sync else bool(openclaw_defaults.get("sync_env_from_dotenv", True)),
            strict=args.strict or bool(openclaw_defaults.get("strict", False)),
            fragment_path=frag,
            no_fragment=args.no_fragment or integration_defaults.get("use_fragment") is False,
            openclaw_bin=openclaw_bin,
        )
        label = "Deploy"
    if args.json:
        print(json.dumps(report.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        for step in report.steps:
            print(f"[{step.status}] {step.id}: {step.message}")
        if not report.ok:
            print(f"{label} finished with errors.", file=sys.stderr)
    return 0 if report.ok else 1


def cmd_onboard_openclaw(args: argparse.Namespace) -> int:
    """Guided OpenClaw host onboarding with handoff to conversational onboarding."""
    return _cmd_onboard_openclaw_journey(args)


def cmd_onboard_openclaw_v2(args: argparse.Namespace) -> int:
    """Compatibility alias for the journey-style OpenClaw host onboarding shell."""
    return _cmd_onboard_openclaw_journey(args)


def _cmd_onboard_openclaw_journey(args: argparse.Namespace) -> int:
    """Journey-style OpenClaw host onboarding shell with stronger handoff."""
    from twinbox_core.openclaw_onboard import run_openclaw_onboard_v2

    code_root = Path(args.repo_root).expanduser() if args.repo_root else None
    openclaw_home = Path(args.openclaw_home).expanduser() if args.openclaw_home else None
    report = run_openclaw_onboard_v2(
        code_root=code_root,
        openclaw_home=openclaw_home,
        dry_run=args.dry_run,
        openclaw_bin=args.openclaw_bin,
    )
    if args.json:
        print(json.dumps(report.to_json_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def cmd_onboarding_status(args: argparse.Namespace) -> int:
    """Show onboarding progress."""
    from .onboarding import load_state, get_stage_prompt

    state = load_state(_state_root())

    if args.json:
        print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("Twinbox Onboarding Journey")
        print("Phase 2 of 2: Continue inside the twinbox agent")
        print(f"  Current Stage: {state.current_stage}")
        print(f"  Completed: {', '.join(state.completed_stages) if state.completed_stages else 'None'}")
        if state.current_stage not in ["not_started", "completed"]:
            print(f"\n{get_stage_prompt(state.current_stage)}")

    return 0


def cmd_onboarding_start(args: argparse.Namespace) -> int:
    """Start onboarding flow."""
    from .onboarding import load_state, save_state, get_stage_prompt, get_next_stage

    state_root = _state_root()
    state = load_state(state_root)

    if state.current_stage == "not_started":
        next_stage = get_next_stage("not_started")
        if next_stage:
            state.current_stage = next_stage
            save_state(state_root, state)

    if args.json:
        print(json.dumps({"stage": state.current_stage, "prompt": get_stage_prompt(state.current_stage)}, ensure_ascii=False))
    else:
        print("Twinbox Onboarding Journey")
        print("Phase 2 of 2: Continue inside the twinbox agent\n")
        print(get_stage_prompt(state.current_stage))

    return 0


def cmd_onboarding_next(args: argparse.Namespace) -> int:
    """Complete current onboarding stage and move to next stage."""
    from .onboarding import complete_stage, get_next_stage, get_stage_prompt, load_state, save_state

    state_root = _state_root()
    state = load_state(state_root)

    if state.current_stage == "not_started":
        next_stage = get_next_stage("not_started")
        if next_stage:
            state.current_stage = next_stage

    if state.current_stage == "completed":
        output = {
            "completed_stage": None,
            "current_stage": "completed",
            "completed_stages": state.completed_stages,
            "prompt": "Onboarding already completed.",
        }
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print("✅ Onboarding 已完成")
        return 0

    completed_stage = state.current_stage
    complete_stage(state, state.current_stage)
    save_state(state_root, state)

    output = {
        "completed_stage": completed_stage,
        "current_stage": state.current_stage,
        "completed_stages": state.completed_stages,
        "prompt": get_stage_prompt(state.current_stage),
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("Twinbox Onboarding Journey")
        print("Phase 2 of 2: Continue inside the twinbox agent")
        print(f"✅ 已完成阶段: {completed_stage}")
        print(f"➡️ 当前阶段: {state.current_stage}")
        if state.current_stage != "completed":
            print(get_stage_prompt(state.current_stage))

    return 0


def cmd_push_subscribe(args: argparse.Namespace) -> int:
    """Subscribe to push notifications."""
    from .push_subscription import subscribe

    filters = {}
    if args.min_urgency:
        filters["min_urgency"] = args.min_urgency
    sub = subscribe(_state_root(), args.session_id, filters)

    if args.json:
        print(json.dumps(sub.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"✅ Subscribed {args.session_id}")

    return 0


def cmd_push_unsubscribe(args: argparse.Namespace) -> int:
    """Unsubscribe from push notifications."""
    from .push_subscription import unsubscribe

    ok = unsubscribe(_state_root(), args.session_id)
    if args.json:
        print(json.dumps({"success": ok}, ensure_ascii=False))
    else:
        print(f"{'✅' if ok else '❌'} {args.session_id}")
    return 0 if ok else 1


def cmd_push_list(args: argparse.Namespace) -> int:
    """List push subscriptions."""
    from .push_subscription import load_subscriptions

    subs = load_subscriptions(_state_root())
    if args.json:
        print(json.dumps({"subscriptions": [s.to_dict() for s in subs]}, ensure_ascii=False, indent=2))
    else:
        for s in subs:
            print(f"{'✅' if s.enabled else '❌'} {s.session_id} ({s.push_count} pushes)")
    return 0


def cmd_push_dispatch(args: argparse.Namespace) -> int:
    """Manually trigger push dispatch (for testing)."""
    from .daytime_slice import load_activity_pulse
    from .push_dispatcher import dispatch_push

    state_root = _state_root()
    payload = load_activity_pulse(state_root)
    result = dispatch_push(state_root, payload, openclaw_bin=args.openclaw_bin)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"📤 Push dispatch: {result['sent']} sent, {result['failed']} failed, {result['skipped']} skipped")

    return 0


def _find_thread_in_artifacts(thread_id: str) -> dict | None:
    """Find thread information from Phase 3/4 artifacts."""
    canonical_root = _state_root()

    validation_root = canonical_root / "runtime" / "validation"
    queue_hit: dict[str, Any] | None = None

    # Search in Phase 4 artifacts
    phase4_files = [
        validation_root / "phase-4" / "daily-urgent.yaml",
        validation_root / "phase-4" / "pending-replies.yaml",
        validation_root / "phase-4" / "sla-risks.yaml",
    ]

    for artifact_path in phase4_files:
        if not artifact_path.exists():
            continue

        data = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))
        queue_key = artifact_path.stem.replace("-", "_")

        if queue_key in data and isinstance(data[queue_key], list):
            for item in data[queue_key]:
                if _thread_matches(item.get("thread_key"), thread_id):
                    queue_hit = {
                        "thread_id": str(item.get("thread_key", "") or _strip_thread_display_prefix(thread_id)),
                        "queue_type": queue_key,
                        "data": item,
                        "source": str(artifact_path),
                    }
                    break
        if queue_hit:
            break
    pulse_item = _find_thread_in_activity_pulse(thread_id)
    context_item = _find_thread_in_phase3_context(thread_id)
    sampled_body = _find_thread_sampled_body(
        thread_id,
        latest_message_ref=str((pulse_item or {}).get("latest_message_ref", "") or ""),
    )

    if not queue_hit and not pulse_item and not context_item and not sampled_body:
        return None

    resolved_thread_id = (
        str((queue_hit or {}).get("thread_id", "") or "")
        or str(((queue_hit or {}).get("data", {}) or {}).get("thread_key", "") or "")
        or str((pulse_item or {}).get("thread_key", "") or "")
        or str((context_item or {}).get("thread_key", "") or "")
        or _strip_thread_display_prefix(thread_id)
    )
    return {
        "thread_id": resolved_thread_id,
        "queue_type": str((queue_hit or {}).get("queue_type", "") or ""),
        "data": ((queue_hit or {}).get("data", {}) or {}),
        "source": str((queue_hit or {}).get("source", "") or ""),
        "pulse": pulse_item or {},
        "context": context_item or {},
        "sampled_body": sampled_body or {},
    }


def cmd_thread_inspect(args: argparse.Namespace) -> int:
    """Inspect thread current state."""
    thread_info = _find_thread_in_artifacts(args.thread_id)

    if not thread_info:
        print(f"错误: 未找到线程 '{args.thread_id}'", file=sys.stderr)
        return 1

    data = thread_info.get("data", {})
    pulse_data = thread_info.get("pulse", {})
    context_data = thread_info.get("context", {})
    sampled_body = thread_info.get("sampled_body", {})
    latest_subject = (
        str(pulse_data.get("latest_subject", "") or "")
        or str(context_data.get("latest_subject", "") or "")
        or str(sampled_body.get("subject", "") or "")
    )
    last_activity_at = (
        str(data.get("last_activity_at", "") or "")
        or str(pulse_data.get("last_activity_at", "") or "")
        or str(context_data.get("latest_date", "") or "")
        or str(sampled_body.get("date", "") or "")
        or "unknown"
    )
    waiting_on = (
        str(data.get("waiting_on", "") or "")
        or str(pulse_data.get("waiting_on", "") or "")
        or "unknown"
    )
    why = (
        str(data.get("why", "") or "")
        or str(pulse_data.get("why", "") or "")
        or str(context_data.get("body_excerpt", "") or "")
    )
    evidence_refs = [
        ref for ref in [
            str(data.get("evidence_source", "") or ""),
            str(pulse_data.get("latest_message_ref", "") or ""),
        ] if ref
    ] or ["unknown"]
    context_refs = [
        ref for ref in [
            str(data.get("flow", "") or ""),
            str(context_data.get("intent", "") or ""),
        ] if ref
    ] or ["unknown"]
    confidence = _thread_confidence(data, pulse_data, context_data)
    content_excerpt = (
        str(sampled_body.get("body", "") or "")
        or str(context_data.get("body_excerpt", "") or "")
    )
    participants = context_data.get("participants", [])
    if not isinstance(participants, list):
        participants = []

    if args.json:
        output = {
            "thread_id": thread_info["thread_id"],
            "state": data.get("stage", "unknown"),
            "waiting_on": waiting_on,
            "last_activity_at": last_activity_at,
            "confidence": confidence,
            "evidence_refs": evidence_refs,
            "context_refs": context_refs,
            "why": why,
            "latest_subject": latest_subject,
            "latest_message_ref": str(pulse_data.get("latest_message_ref", "") or ""),
            "message_count": int(pulse_data.get("message_count", 0) or 0),
            "unread_count": int(pulse_data.get("unread_count", 0) or 0),
            "new_message_count": int(pulse_data.get("new_message_count", 0) or 0),
            "queue_tags": pulse_data.get("queue_tags", []) if isinstance(pulse_data.get("queue_tags"), list) else [],
            "participants": participants,
            "content_excerpt": content_excerpt,
            "explainability": {
                "state_reasoning": why,
                "confidence_factors": [
                    f"Urgency score: {data.get('urgency_score', pulse_data.get('score', 0))}",
                    f"Owner: {data.get('owner', context_data.get('latest_from', 'unknown'))}",
                    f"Action hint: {data.get('action_hint', pulse_data.get('why', 'none'))}",
                ],
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"线程: {thread_info['thread_id']}",
            f"状态: {data.get('stage', 'unknown')}",
            f"等待: {waiting_on}",
            f"最近主题: {latest_subject or 'unknown'}",
            f"最近活动: {last_activity_at}",
            f"置信度: {confidence:.2f}",
            "",
            "证据:",
            *[f"- {ref}" for ref in evidence_refs],
            "",
            "上下文:",
            *[f"- {ref}" for ref in context_refs],
            "",
            f"原因: {why}",
        ]
        if content_excerpt:
            lines.extend([
                "",
                "内容摘要:",
                content_excerpt[:600],
            ])
        print("\n".join(lines))

    return 0


def cmd_thread_explain(args: argparse.Namespace) -> int:
    """Explain thread state reasoning."""
    thread_info = _find_thread_in_artifacts(args.thread_id)

    if not thread_info:
        print(f"错误: 未找到线程 '{args.thread_id}'", file=sys.stderr)
        return 1

    data = thread_info["data"]
    urgency_score = data.get("urgency_score", 0)

    if args.json:
        output = {
            "thread_id": thread_info["thread_id"],
            "state": data.get("stage", "unknown"),
            "explainability": {
                "reasoning_steps": [
                    f"线程位于 {data.get('flow', 'unknown')} 流程的 {data.get('stage', 'unknown')} 阶段",
                    f"当前等待: {data.get('waiting_on', 'unknown')}",
                    f"负责人: {data.get('owner', 'unknown')}",
                    f"紧急度评分: {urgency_score}",
                ],
                "confidence": urgency_score / 100.0,
                "confidence_breakdown": {
                    "urgency_score": urgency_score / 100.0,
                },
                "alternative_states": [],
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"线程: {thread_info['thread_id']}",
            f"当前状态: {data.get('stage', 'unknown')}",
            "",
            "状态推断依据:",
            f"1. 线程位于 {data.get('flow', 'unknown')} 流程的 {data.get('stage', 'unknown')} 阶段",
            f"2. 当前等待: {data.get('waiting_on', 'unknown')}",
            f"3. 负责人: {data.get('owner', 'unknown')}",
            f"4. 紧急度评分: {urgency_score}",
            "",
            f"置信度: {urgency_score / 100.0:.2f}",
            f"- 紧急度评分: +{urgency_score / 100.0:.2f}",
            "",
            f"原因: {data.get('why', '')}",
            f"建议行动: {data.get('action_hint', 'none')}",
        ]
        print("\n".join(lines))

    return 0


def cmd_thread_progress(args: argparse.Namespace) -> int:
    """Search current thread progress by thread key, subject, or business keyword."""
    from .daytime_slice import search_activity_pulse

    matches = search_activity_pulse(args.query, limit=args.limit)

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    if not matches:
        print("未找到匹配线程")
        return 0

    lines = ["线程进展查询", "=" * 40, ""]
    for idx, item in enumerate(matches, 1):
        queue_tags = ",".join(item.get("queue_tags", [])) or "none"
        lines.extend([
            f"[{idx}] {item.get('thread_key', 'unknown')}",
            f"    主题: {item.get('latest_subject', '')}",
            f"    最近活动: {item.get('last_activity_at', '')}",
            f"    队列标签: {queue_tags}",
            f"    新增邮件: {item.get('new_message_count', 0)}",
            f"    原因: {item.get('why', '')}",
            "",
        ])
    print("\n".join(lines))
    return 0


def cmd_digest_daily(args: argparse.Namespace) -> int:
    """Show daily digest."""
    canonical_root = _state_root()

    validation_root = canonical_root / "runtime" / "validation" / "phase-4"

    # Load queue artifacts
    urgent_path = validation_root / "daily-urgent.yaml"
    pending_path = validation_root / "pending-replies.yaml"
    sla_path = validation_root / "sla-risks.yaml"

    if args.json:
        output = {
            "digest_type": "daily",
            "sections": {},
            "generated_at": "",
            "stale": False,
        }

        if urgent_path.exists():
            urgent_data = yaml.safe_load(urgent_path.read_text(encoding="utf-8"))
            output["sections"]["urgent"] = {"items": urgent_data.get("daily_urgent", [])}
            output["generated_at"] = urgent_data.get("generated_at", "")

        if pending_path.exists():
            pending_data = yaml.safe_load(pending_path.read_text(encoding="utf-8"))
            output["sections"]["pending"] = {"items": pending_data.get("pending_replies", [])}

        if sla_path.exists():
            sla_data = yaml.safe_load(sla_path.read_text(encoding="utf-8"))
            output["sections"]["sla_risks"] = {"items": sla_data.get("sla_risks", [])}

        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = ["每日摘要", "=" * 40, ""]

        if urgent_path.exists():
            urgent_data = yaml.safe_load(urgent_path.read_text(encoding="utf-8"))
            urgent_items = urgent_data.get("daily_urgent", [])
            lines.extend([
                f"紧急事项 ({len(urgent_items)} 项):",
                "",
            ])
            for item in urgent_items[:5]:  # Show top 5
                lines.append(f"- {item.get('thread_key', 'unknown')}: {item.get('why', '')}")
            lines.append("")

        if pending_path.exists():
            pending_data = yaml.safe_load(pending_path.read_text(encoding="utf-8"))
            pending_items = pending_data.get("pending_replies", [])
            lines.extend([
                f"待回复 ({len(pending_items)} 项):",
                "",
            ])
            for item in pending_items[:5]:  # Show top 5
                lines.append(f"- {item.get('thread_key', 'unknown')}")
            lines.append("")

        if sla_path.exists():
            sla_data = yaml.safe_load(sla_path.read_text(encoding="utf-8"))
            sla_items = sla_data.get("sla_risks", [])
            lines.extend([
                f"SLA 风险 ({len(sla_items)} 项):",
                "",
            ])
            for item in sla_items[:5]:  # Show top 5
                lines.append(f"- {item.get('thread_key', 'unknown')}")
            lines.append("")

        print("\n".join(lines))

    return 0


def cmd_digest_pulse(args: argparse.Namespace) -> int:
    """Show the latest daytime activity pulse."""
    from .daytime_slice import DaytimeSliceError, load_activity_pulse

    try:
        pulse = load_activity_pulse()
    except DaytimeSliceError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    stale = _is_stale(pulse.get("generated_at", ""))

    if args.json:
        print(json.dumps({
            "digest_type": "pulse",
            "sections": {
                "notifiable": pulse.get("notifiable_items", []),
                "recent_activity": pulse.get("recent_activity", []),
                "needs_attention": pulse.get("needs_attention", []),
            },
            "generated_at": pulse.get("generated_at", ""),
            "stale": stale,
            "notify_payload": pulse.get("notify_payload", {}),
        }, ensure_ascii=False, indent=2))
        return 0

    notify = pulse.get("notify_payload", {})
    notifiable = pulse.get("notifiable_items", [])
    lines = [
        "日内脉冲",
        "=" * 40,
        "",
        f"生成时间: {pulse.get('generated_at', '')}",
        f"状态: {'过期' if stale else '最新'}",
        f"推送摘要: {notify.get('summary', '')}",
        f"待推送线程: {len(notifiable)}",
        "",
    ]
    for item in notifiable:
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('thread_key', 'unknown')}: {item.get('why', '')}")
    print("\n".join(lines))
    return 0


def cmd_digest_weekly(args: argparse.Namespace) -> int:
    """Show weekly digest."""
    canonical_root = _state_root()

    validation_root = canonical_root / "runtime" / "validation" / "phase-4"
    weekly_path = validation_root / "weekly-brief-raw.json"

    if not weekly_path.exists():
        print("错误: 未找到 weekly-brief-raw.json", file=sys.stderr)
        return 1

    weekly_data = json.loads(weekly_path.read_text(encoding="utf-8"))
    brief = weekly_data.get("weekly_brief", {})

    if args.json:
        output = {
            "digest_type": "weekly",
            "sections": {
                "action_now": brief.get("top_actions", []),
                "backlog": [],
                "important_changes": brief.get("rhythm_observation", ""),
            },
            "generated_at": "",
            "stale": False,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = [
            "每周简报",
            "=" * 40,
            "",
            f"周期: {brief.get('period', 'unknown')}",
            f"线程总数: {brief.get('total_threads_in_window', 0)}",
            "",
            "必须处理的行动:",
            "",
        ]

        for action in brief.get("top_actions", []):
            lines.append(f"- {action}")

        lines.extend([
            "",
            "本周重要变化:",
            "",
            brief.get("rhythm_observation", ""),
        ])

        print("\n".join(lines))

    return 0


def _build_latest_mail_task_view() -> dict[str, Any]:
    from .daytime_slice import load_activity_pulse

    pulse = load_activity_pulse()
    stale = _is_stale(pulse.get("generated_at", ""))
    notify = pulse.get("notify_payload", {})
    return {
        "task": "latest-mail",
        "generated_at": pulse.get("generated_at", ""),
        "stale": stale,
        "summary": notify.get("summary", ""),
        "urgent_top_k": notify.get("urgent_top_k", []),
        "recent_activity": pulse.get("recent_activity", []),
        "needs_attention": pulse.get("needs_attention", []),
        "pending_count": notify.get("pending_count", 0),
        "notify_payload": notify,
    }


def _build_todo_task_view() -> dict[str, Any]:
    urgent = _project_urgent_queue().to_dict()
    pending = _project_pending_queue().to_dict()
    actions = [item.to_dict() for item in _project_action_suggestions()]
    reviews = [item.to_dict() for item in _project_review_items()]
    stale = bool(urgent.get("stale")) and bool(pending.get("stale"))
    return {
        "task": "todo",
        "generated_at": urgent.get("generated_at") or pending.get("generated_at", ""),
        "stale": stale,
        "urgent": urgent,
        "pending": pending,
        "suggested_actions": actions,
        "review_items": reviews,
    }


def _build_weekly_task_view() -> dict[str, Any]:
    canonical_root = _state_root()
    validation_root = canonical_root / "runtime" / "validation" / "phase-4"
    weekly_path = validation_root / "weekly-brief-raw.json"
    if not weekly_path.exists():
        raise FileNotFoundError("weekly-brief-raw.json")
    weekly_data = json.loads(weekly_path.read_text(encoding="utf-8"))
    brief = weekly_data.get("weekly_brief", {})
    return {
        "task": "weekly",
        "digest_type": "weekly",
        "sections": {
            "action_now": brief.get("top_actions", []),
            "backlog": [],
            "important_changes": brief.get("rhythm_observation", ""),
        },
        "generated_at": weekly_data.get("generated_at", ""),
        "stale": _is_stale(weekly_data.get("generated_at", "")) if weekly_data.get("generated_at") else False,
    }


def cmd_task_latest_mail(args: argparse.Namespace) -> int:
    """Deterministic task entrypoint for latest-mail / today summary questions."""
    from .daytime_slice import DaytimeSliceError

    try:
        payload = _build_latest_mail_task_view()
    except DaytimeSliceError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "unread_only", False):
        payload["recent_activity"] = [i for i in payload.get("recent_activity", []) if i.get("unread_count", 0) > 0]
        payload["needs_attention"] = [i for i in payload.get("needs_attention", []) if i.get("unread_count", 0) > 0]
        payload["urgent_top_k"] = [i for i in payload.get("urgent_top_k", []) if i.get("unread_count", 0) > 0]
        payload["unread_only"] = True
        # Also filter notify_payload if it exists
        if "notify_payload" in payload and isinstance(payload["notify_payload"], dict):
            notify = payload["notify_payload"]
            if "urgent_top_k" in notify:
                notify["urgent_top_k"] = [i for i in notify.get("urgent_top_k", []) if i.get("unread_count", 0) > 0]
            notify["unread_only"] = True
        # Avoid stale push summary (still said "3 threads" while unread filter left 1)
        n_urgent = len(payload.get("urgent_top_k") or [])
        n_recent = len(payload.get("recent_activity") or [])
        payload["summary"] = (
            f"未读视图：推送区 {n_urgent} 条；近期活跃未读线程 {n_recent} 条"
            f"（原始摘要：{payload.get('summary') or '无'}）"
        )
        if isinstance(payload.get("notify_payload"), dict):
            payload["notify_payload"]["summary"] = payload["summary"]

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    lines = [
        "最新邮件情况",
        "=" * 40,
        "",
        f"生成时间: {payload.get('generated_at', '')}",
        f"状态: {'过期' if payload.get('stale') else '最新'}",
        f"摘要: {payload.get('summary', '')}",
        f"待回复/待跟进计数: {payload.get('pending_count', 0)}",
        "",
        "最值得关注:",
    ]
    for item in payload.get("urgent_top_k", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('thread_key', 'unknown')}: {item.get('why', '')}")
    if not payload.get("urgent_top_k"):
        lines.append("- 当前无新的高优先级线程")
    print("\n".join(lines))
    return 0


def cmd_task_todo(args: argparse.Namespace) -> int:
    """Deterministic task entrypoint for todo/pending/urgent questions."""
    payload = _build_todo_task_view()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    urgent_items = payload["urgent"].get("items", [])
    pending_items = payload["pending"].get("items", [])
    lines = [
        "当前待办",
        "=" * 40,
        "",
        f"紧急事项: {len(urgent_items)}",
        f"待回复: {len(pending_items)}",
        f"建议行动: {len(payload.get('suggested_actions', []))}",
        f"待审核: {len(payload.get('review_items', []))}",
        "",
        "紧急事项:",
    ]
    for item in urgent_items[:5]:
        lines.append(f"- {item.get('thread_id', 'unknown')}: {item.get('why', '')}")
    if not urgent_items:
        lines.append("- 当前无紧急事项")
    lines.extend(["", "待回复:"])
    for item in pending_items[:5]:
        lines.append(f"- {item.get('thread_id', 'unknown')}: {item.get('why', '')}")
    if not pending_items:
        lines.append("- 当前无待回复线程")
    print("\n".join(lines))
    return 0


def cmd_task_progress(args: argparse.Namespace) -> int:
    """Deterministic task entrypoint for progress lookup."""
    from .daytime_slice import search_activity_pulse

    matches = search_activity_pulse(args.query, limit=args.limit)
    role_map = _recipient_role_map()
    enriched_matches = []
    for item in matches:
        if not isinstance(item, dict):
            enriched_matches.append(item)
            continue
        enriched = dict(item)
        thread_key = str(enriched.get("thread_key", "") or "")
        recipient_role = role_map.get(thread_key)
        if recipient_role:
            enriched["recipient_role"] = recipient_role
            enriched["thread_key_display"] = _display_thread_key(thread_key, recipient_role)
        else:
            enriched["thread_key_display"] = thread_key
        enriched_matches.append(enriched)
    payload = {
        "task": "progress",
        "query": args.query,
        "matches": enriched_matches,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not enriched_matches:
        print(f"未找到与 '{args.query}' 匹配的线程进展")
        return 0

    lines = [f"进展查询: {args.query}", "=" * 40, ""]
    for idx, item in enumerate(enriched_matches, 1):
        lines.extend([
            f"[{idx}] {item.get('thread_key_display', item.get('thread_key', 'unknown'))}",
            f"    主题: {item.get('latest_subject', '')}",
            f"    最近活动: {item.get('last_activity_at', '')}",
            f"    原因: {item.get('why', '')}",
            "",
        ])
    print("\n".join(lines))
    return 0


def cmd_task_weekly(args: argparse.Namespace) -> int:
    """Deterministic task entrypoint for weekly brief lookup."""
    try:
        payload = _build_weekly_task_view()
    except FileNotFoundError:
        print("错误: 未找到 weekly-brief-raw.json", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    lines = [
        "每周摘要",
        "=" * 40,
        "",
        "必须处理的行动:",
    ]
    for action in payload["sections"].get("action_now", []):
        lines.append(f"- {action}")
    if not payload["sections"].get("action_now", []):
        lines.append("- 当前无 action_now")
    print("\n".join(lines))
    return 0


def cmd_task_mailbox_status(args: argparse.Namespace) -> int:
    """Deterministic task entrypoint for mailbox status diagnosis."""
    from .mailbox import format_preflight_text, run_preflight

    exit_code, payload = run_preflight(
        state_root=args.state_root,
        account_override=args.account,
        folder=args.folder,
        page_size=args.page_size,
    )

    if args.json:
        output = {"task": "mailbox-status", **payload}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return exit_code

    print(format_preflight_text(payload))
    return exit_code


def _infer_action_type(item: dict) -> str:
    """Infer action type from thread data."""
    action_hint = item.get("action_hint", "")
    if "reply" in action_hint.lower() or "respond" in action_hint.lower():
        return "reply"
    if "forward" in action_hint.lower():
        return "forward"
    if "archive" in action_hint.lower() or "close" in action_hint.lower():
        return "archive"
    return "reply"  # default


def _infer_risk_level(item: dict) -> str:
    """Infer risk level from urgency score."""
    score = item.get("urgency_score", 0)
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _project_action_suggestions() -> list[ActionCard]:
    """Project action suggestions from Phase 4 urgent and pending artifacts."""
    phase4_dir = _get_phase4_dir()
    actions: list[ActionCard] = []

    # Urgent items -> action suggestions
    urgent_artifact = _load_yaml_artifact(phase4_dir / "daily-urgent.yaml")
    for idx, item in enumerate(urgent_artifact.get("daily_urgent", [])):
        if not isinstance(item, dict):
            continue
        thread_key = item.get("thread_key", "")
        actions.append(ActionCard(
            action_id=f"action-urgent-{idx + 1}",
            thread_id=thread_key,
            action_type=_infer_action_type(item),
            why_now=item.get("why", "Urgent thread requiring attention"),
            risk_level=_infer_risk_level(item),
            required_review_fields=["action_type", "why_now"],
            suggested_draft_mode="quick_reply" if _infer_action_type(item) == "reply" else None,
        ))

    # Pending items -> action suggestions
    pending_artifact = _load_yaml_artifact(phase4_dir / "pending-replies.yaml")
    for idx, item in enumerate(pending_artifact.get("pending_replies", [])):
        if not isinstance(item, dict):
            continue
        thread_key = item.get("thread_key", "")
        actions.append(ActionCard(
            action_id=f"action-pending-{idx + 1}",
            thread_id=thread_key,
            action_type="reply",
            why_now=item.get("why", "Pending reply needed"),
            risk_level="medium",
            required_review_fields=["action_type"],
            suggested_draft_mode="quick_reply",
        ))

    return actions


def cmd_action_suggest(args: argparse.Namespace) -> int:
    """Suggest actions based on current queue state."""
    actions = _project_action_suggestions()

    if not actions:
        if args.json:
            print(json.dumps([], ensure_ascii=False, indent=2))
        else:
            print("当前没有建议的行动。")
        return 0

    if args.json:
        output = [a.to_dict() for a in actions]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"建议行动 ({len(actions)} 项)",
            "=" * 40,
            "",
        ]
        for action in actions:
            risk_marker = {"high": "!!!", "medium": "!!", "low": "!"}.get(action.risk_level, "")
            lines.extend([
                f"[{action.action_id}] {action.thread_id} {risk_marker}",
                f"    类型: {action.action_type}",
                f"    原因: {action.why_now}",
                f"    风险: {action.risk_level}",
                f"    草稿模式: {action.suggested_draft_mode or 'N/A'}",
                "",
            ])
        print("\n".join(lines))

    return 0


def cmd_action_materialize(args: argparse.Namespace) -> int:
    """Materialize a specific action for execution."""
    actions = _project_action_suggestions()
    target = next((a for a in actions if a.action_id == args.action_id), None)

    if not target:
        print(f"错误: 未找到行动 '{args.action_id}'", file=sys.stderr)
        print(f"可用行动: {', '.join(a.action_id for a in actions)}", file=sys.stderr)
        return 1

    if args.json:
        output = {
            **target.to_dict(),
            "materialized": True,
            "review_checklist": [
                {"field": f, "reviewed": False} for f in target.required_review_fields
            ],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"行动详情: {target.action_id}",
            "=" * 40,
            f"线程: {target.thread_id}",
            f"类型: {target.action_type}",
            f"原因: {target.why_now}",
            f"风险: {target.risk_level}",
            f"草稿模式: {target.suggested_draft_mode or 'N/A'}",
            "",
            "审核清单:",
        ]
        for field in target.required_review_fields:
            lines.append(f"  [ ] {field}")
        lines.append("")
        lines.append("提示: 确认审核清单后，使用 'twinbox action apply' 执行此行动")
        print("\n".join(lines))

    return 0


def _project_review_items() -> list[ReviewItem]:
    """Project review items from low-confidence threads."""
    phase4_dir = _get_phase4_dir()
    reviews: list[ReviewItem] = []

    now_iso = datetime.now().isoformat()

    # Find threads with low confidence or needing state override
    for artifact_name, queue_key in [
        ("daily-urgent.yaml", "daily_urgent"),
        ("pending-replies.yaml", "pending_replies"),
    ]:
        artifact = _load_yaml_artifact(phase4_dir / artifact_name)
        for idx, item in enumerate(artifact.get(queue_key, [])):
            if not isinstance(item, dict):
                continue
            urgency_score = item.get("urgency_score", 0)
            confidence = urgency_score / 100.0 if urgency_score else 0.8

            # Low confidence items need review
            if confidence < 0.7:
                thread_key = item.get("thread_key", "")
                reviews.append(ReviewItem(
                    review_id=f"review-{queue_key}-{idx + 1}",
                    thread_id=thread_key,
                    review_type="confidence_check",
                    current_state=item.get("stage", "unknown"),
                    proposed_change="confirm_or_override",
                    reason=f"Low confidence ({confidence:.2f}): {item.get('why', '')}",
                    created_at=now_iso,
                ))

            # Items without why/reason_code need explainability review
            why = item.get("why", "")
            reason_code = item.get("reason_code", "")
            if not why or not reason_code:
                thread_key = item.get("thread_key", "")
                reviews.append(ReviewItem(
                    review_id=f"review-explain-{queue_key}-{idx + 1}",
                    thread_id=thread_key,
                    review_type="confidence_check",
                    current_state=item.get("stage", "unknown"),
                    proposed_change="add_explanation",
                    reason="Missing why or reason_code fields",
                    created_at=now_iso,
                ))

    return reviews


def cmd_review_list(args: argparse.Namespace) -> int:
    """List items needing human review."""
    reviews = _project_review_items()

    if not reviews:
        if args.json:
            print(json.dumps([], ensure_ascii=False, indent=2))
        else:
            print("当前没有需要审核的项目。")
        return 0

    if args.json:
        output = [r.to_dict() for r in reviews]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"待审核项目 ({len(reviews)} 项)",
            "=" * 40,
            "",
        ]
        for review in reviews:
            lines.extend([
                f"[{review.review_id}] {review.thread_id}",
                f"    类型: {review.review_type}",
                f"    当前状态: {review.current_state}",
                f"    建议变更: {review.proposed_change}",
                f"    原因: {review.reason}",
                "",
            ])
        print("\n".join(lines))

    return 0


def cmd_review_show(args: argparse.Namespace) -> int:
    """Show details of a specific review item."""
    reviews = _project_review_items()
    target = next((r for r in reviews if r.review_id == args.review_id), None)

    if not target:
        print(f"错误: 未找到审核项 '{args.review_id}'", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(target.to_dict(), ensure_ascii=False, indent=2))
    else:
        lines = [
            f"审核项: {target.review_id}",
            "=" * 40,
            f"线程: {target.thread_id}",
            f"类型: {target.review_type}",
            f"当前状态: {target.current_state}",
            f"建议变更: {target.proposed_change}",
            f"原因: {target.reason}",
            f"创建时间: {target.created_at}",
        ]
        print("\n".join(lines))

    return 0


def _get_rules_path() -> Path:
    return _state_root() / "config" / "routing-rules.yaml"


def cmd_rule_list(args: argparse.Namespace) -> int:
    """List all semantic routing rules."""
    from .routing_rules import load_rules_raw

    rules_path = _get_rules_path()
    raw_data = load_rules_raw(rules_path)
    rules = raw_data.get("rules", [])

    if args.json:
        print(json.dumps(rules, ensure_ascii=False, indent=2))
        return 0

    if not rules:
        print("当前没有配置任何路由规则。")
        return 0

    lines = [
        f"路由规则 ({len(rules)} 项)",
        "=" * 40,
        "",
    ]
    for r in rules:
        status = "启用" if r.get("active", True) else "禁用"
        lines.extend([
            f"[{r.get('id', 'unknown')}] {r.get('name', '未命名')} ({status})",
            f"    描述: {r.get('description', '无')}",
            f"    条件: {json.dumps(r.get('conditions', {}), ensure_ascii=False)}",
            f"    动作: {json.dumps(r.get('actions', {}), ensure_ascii=False)}",
            "",
        ])
    print("\n".join(lines))
    return 0


def cmd_rule_add(args: argparse.Namespace) -> int:
    """Add a new semantic routing rule."""
    from .routing_rules import load_rules_raw, save_rules_raw

    rules_path = _get_rules_path()
    raw_data = load_rules_raw(rules_path)
    rules = raw_data.setdefault("rules", [])

    try:
        new_rule = json.loads(args.rule_json)
    except json.JSONDecodeError as e:
        print(f"错误: 无效的 JSON 格式 - {e}", file=sys.stderr)
        return 1

    if "id" not in new_rule:
        import uuid
        new_rule["id"] = f"rule_{uuid.uuid4().hex[:8]}"

    # Check if rule exists
    existing_idx = next((i for i, r in enumerate(rules) if r.get("id") == new_rule["id"]), None)
    if existing_idx is not None:
        rules[existing_idx] = new_rule
        print(f"已更新规则: {new_rule['id']}")
    else:
        rules.append(new_rule)
        print(f"已添加规则: {new_rule['id']}")

    save_rules_raw(rules_path, raw_data)
    
    if args.json:
        print(json.dumps({"status": "success", "rule": new_rule}, ensure_ascii=False, indent=2))
    return 0


def cmd_rule_remove(args: argparse.Namespace) -> int:
    """Remove a semantic routing rule."""
    from .routing_rules import load_rules_raw, save_rules_raw

    rules_path = _get_rules_path()
    raw_data = load_rules_raw(rules_path)
    rules = raw_data.get("rules", [])

    existing_idx = next((i for i, r in enumerate(rules) if r.get("id") == args.rule_id), None)
    if existing_idx is None:
        print(f"错误: 未找到规则 '{args.rule_id}'", file=sys.stderr)
        return 1

    removed = rules.pop(existing_idx)
    save_rules_raw(rules_path, raw_data)

    if args.json:
        print(json.dumps({"status": "success", "removed": removed}, ensure_ascii=False, indent=2))
    else:
        print(f"已删除规则: {args.rule_id}")
    return 0


def cmd_rule_test(args: argparse.Namespace) -> int:
    """Test a routing rule against recent threads (dry run)."""
    from .routing_rules import (
        RuleAction,
        RuleCondition,
        RoutingRule,
        evaluate_rule,
        load_rules,
    )

    target_rule = None

    if args.rule_json:
        try:
            r = json.loads(args.rule_json)

            cond_data = r.get("conditions", {})
            conditions = RuleCondition(
                match_all=cond_data.get("match_all"),
                match_any=cond_data.get("match_any"),
            )
            
            act_data = r.get("actions", {})
            actions = RuleAction(
                set_state=act_data.get("set_state"),
                set_waiting_on=act_data.get("set_waiting_on"),
                skip_phase4=act_data.get("skip_phase4", False),
            )
            
            target_rule = RoutingRule(
                id=r.get("id", "test_rule"),
                name=r.get("name", "Test Rule"),
                active=r.get("active", True),
                conditions=conditions,
                actions=actions,
            )
        except Exception as e:
            print(f"错误: 无法解析 rule-json - {e}", file=sys.stderr)
            return 1
    elif args.rule_id:
        rules_path = _get_rules_path()
        rules = load_rules(rules_path)
        target_rule = next((r for r in rules if r.id == args.rule_id), None)
        if not target_rule:
            print(f"错误: 未找到激活的规则 '{args.rule_id}'", file=sys.stderr)
            return 1
    else:
        print("错误: 必须提供 --rule-id 或 --rule-json", file=sys.stderr)
        return 1

    # Load recent threads from Phase 3 context pack
    phase3_context_path = _state_root() / "runtime" / "validation" / "phase-3" / "context-pack.json"
    if not phase3_context_path.exists():
        print("错误: 找不到 Phase 3 context-pack.json。请先运行 pipeline。", file=sys.stderr)
        return 1

    try:
        context = json.loads(phase3_context_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"错误: 无法解析 Phase 3 context-pack.json - {e}", file=sys.stderr)
        return 1

    threads = context.get("top_threads", [])
    if not threads:
        print("没有可用于测试的线程数据。")
        return 0

    print(f"正在测试规则: [{target_rule.id}] {target_rule.name}")
    print(f"测试样本数: {len(threads)} 个近期线程\n")

    matched_threads = []
    env_file = _state_root() / ".env"
    
    for thread in threads:
        if evaluate_rule(target_rule, thread, env_file=env_file if env_file.exists() else None):
            matched_threads.append(thread)

    if args.json:
        output = {
            "rule_id": target_rule.id,
            "total_tested": len(threads),
            "matched_count": len(matched_threads),
            "matches": [
                {
                    "thread_key": t.get("thread_key"),
                    "subject": t.get("latest_subject"),
                    "recipient_role": t.get("recipient_role")
                } for t in matched_threads
            ]
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    lines = [
        f"测试结果: 命中 {len(matched_threads)} / {len(threads)} 个线程",
        "=" * 40,
    ]
    
    if not matched_threads:
        lines.append("没有线程命中该规则。")
    else:
        for idx, t in enumerate(matched_threads, 1):
            lines.extend([
                f"[{idx}] {t.get('thread_key', 'unknown')}",
                f"    主题: {t.get('latest_subject', '')}",
                f"    收件角色: {t.get('recipient_role', 'unknown')}",
                f"    发件人: {t.get('latest_from', 'unknown')}",
                "",
            ])
            
    print("\n".join(lines))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twinbox",
        description="Task-facing CLI for twinbox email copilot",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_daemon_parser(subparsers)
    register_vendor_parser(subparsers)
    register_loading_parser(subparsers)

    # context commands
    context_parser = subparsers.add_parser("context", help="Context management")
    context_sub = context_parser.add_subparsers(dest="context_command", required=True)

    import_mat = context_sub.add_parser("import-material", help="Import user material")
    import_mat.add_argument("source", help="Source file path")
    import_mat.add_argument("--intent", default="reference", choices=["reference", "template_hint"], help="Material intent")

    material_parser = context_sub.add_parser("material", help="Material management")
    material_sub = material_parser.add_subparsers(dest="material_command", required=True)
    material_sub.add_parser("list", help="List all materials")
    mat_set_intent = material_sub.add_parser("set-intent", help="Set material intent")
    mat_set_intent.add_argument("filename", help="Material filename")
    mat_set_intent.add_argument("intent", choices=["reference", "template_hint"], help="Intent type")
    mat_remove = material_sub.add_parser("remove", help="Remove material")
    mat_remove.add_argument("filename", help="Material filename")
    mat_preview = material_sub.add_parser("preview", help="Preview material impact")
    mat_preview.add_argument("filename", help="Material filename")

    upsert_fact = context_sub.add_parser("upsert-fact", help="Add or update manual fact")
    upsert_fact.add_argument("--id", required=True, help="Fact ID")
    upsert_fact.add_argument("--type", required=True, help="Fact type")
    upsert_fact.add_argument("--source", default="user_confirmed_fact", help="Fact source")
    upsert_fact.add_argument("--content", required=True, help="Fact content")

    profile_set = context_sub.add_parser("profile-set", help="Set user profile")
    profile_set.add_argument("profile", help="Profile name")
    profile_set.add_argument("--key", help="Config key (e.g., style.language)")
    profile_set.add_argument("--value", help="Config value")

    context_sub.add_parser("refresh", help="Refresh Phase 1 context-pack")

    # mailbox commands
    mailbox_parser = subparsers.add_parser("mailbox", help="Mailbox login and preflight")
    mailbox_sub = mailbox_parser.add_subparsers(dest="mailbox_command", required=True)

    mailbox_preflight = mailbox_sub.add_parser("preflight", help="Run read-only mailbox preflight")
    mailbox_preflight.add_argument("--state-root", help="Override twinbox state root")
    mailbox_preflight.add_argument("--account", default="", help="Override MAIL_ACCOUNT_NAME")
    mailbox_preflight.add_argument("--folder", default="INBOX", help="Folder for read-only envelope list")
    mailbox_preflight.add_argument("--page-size", default=5, type=int, help="Envelope page size")
    mailbox_preflight.add_argument("--json", action="store_true", help="Output as JSON")

    mailbox_detect = mailbox_sub.add_parser("detect", help="Auto-detect server config from email")
    mailbox_detect.add_argument("email", help="Email address to detect servers for")
    mailbox_detect.add_argument("--json", action="store_true", help="Output as JSON")

    mailbox_setup = mailbox_sub.add_parser("setup", help="Auto-detect + write twinbox.json (password from TWINBOX_SETUP_IMAP_PASS)")
    mailbox_setup.add_argument("--email", required=True, help="Email address to configure")
    mailbox_setup.add_argument("--imap-login", default="", help="Override IMAP login (default: email)")
    mailbox_setup.add_argument("--smtp-login", default="", help="Override SMTP login (default: email)")
    mailbox_setup.add_argument("--state-root", help="Override twinbox state root")
    mailbox_setup.add_argument("--json", action="store_true", help="Output as JSON")

    # config commands
    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)

    config_show = config_sub.add_parser("show", help="Show the single-source Twinbox config")
    config_show.add_argument("--json", action="store_true", help="Output as JSON")

    config_set_llm = config_sub.add_parser("set-llm", help="Configure LLM API (key from TWINBOX_SETUP_API_KEY)")
    config_set_llm.add_argument("--provider", default="openai", choices=["openai", "anthropic"], help="LLM provider")
    config_set_llm.add_argument("--model", default="", help="Model ID override")
    config_set_llm.add_argument("--api-url", default="", help="API URL override")
    config_set_llm.add_argument("--json", action="store_true", help="Output as JSON")

    config_mailbox_set = config_sub.add_parser("mailbox-set", help="Configure mailbox settings into twinbox.json")
    config_mailbox_set.add_argument("--email", required=True, help="Email address to configure")
    config_mailbox_set.add_argument("--imap-login", default="", help="Override IMAP login (default: email)")
    config_mailbox_set.add_argument("--smtp-login", default="", help="Override SMTP login (default: email)")
    config_mailbox_set.add_argument("--imap-host", default="", help="Override IMAP host (default: auto-detect)")
    config_mailbox_set.add_argument("--imap-port", default="", help="Override IMAP port (default: auto-detect)")
    config_mailbox_set.add_argument("--imap-encryption", default="", help="Override IMAP encryption (default: auto-detect)")
    config_mailbox_set.add_argument("--smtp-host", default="", help="Override SMTP host (default: auto-detect)")
    config_mailbox_set.add_argument("--smtp-port", default="", help="Override SMTP port (default: auto-detect)")
    config_mailbox_set.add_argument("--smtp-encryption", default="", help="Override SMTP encryption (default: auto-detect)")
    config_mailbox_set.add_argument("--state-root", help="Override twinbox state root")
    config_mailbox_set.add_argument("--json", action="store_true", help="Output as JSON")

    config_integration_set = config_sub.add_parser("integration-set", help="Configure integration defaults in twinbox.json")
    config_integration_set.add_argument("--fragment-path", default="", help="Fragment path to prefer")
    config_integration_set.add_argument("--use-fragment", default="", choices=["yes", "no"], help="Default fragment usage")
    config_integration_set.add_argument("--json", action="store_true", help="Output as JSON")

    config_openclaw_set = config_sub.add_parser("openclaw-set", help="Configure OpenClaw defaults in twinbox.json")
    config_openclaw_set.add_argument("--home", default="", help="Default OpenClaw home")
    config_openclaw_set.add_argument("--bin", default="", help="Default openclaw executable")
    config_openclaw_set.add_argument("--strict", action="store_true", help="Default deploy strict mode on")
    config_openclaw_set.add_argument("--no-strict", action="store_true", help="Default deploy strict mode off")
    config_openclaw_set.add_argument("--sync-env", action="store_true", help="Default deploy env sync on")
    config_openclaw_set.add_argument("--no-sync-env", action="store_true", help="Default deploy env sync off")
    config_openclaw_set.add_argument("--restart-gateway", action="store_true", help="Default gateway restart on")
    config_openclaw_set.add_argument("--no-restart-gateway", action="store_true", help="Default gateway restart off")
    config_openclaw_set.add_argument("--json", action="store_true", help="Output as JSON")

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Host-side deployment helpers (OpenClaw wiring)",
    )
    deploy_sub = deploy_parser.add_subparsers(dest="deploy_command", required=True)

    dep_oc = deploy_sub.add_parser(
        "openclaw",
        help="Init Twinbox roots, merge openclaw.json, copy SKILL.md, restart gateway "
        "(or --rollback to undo that wiring only)",
    )
    dep_oc.add_argument(
        "--rollback",
        action="store_true",
        help="Undo deploy openclaw: drop skills.entries.twinbox, remove ~/.openclaw/skills/twinbox/",
    )
    dep_oc.add_argument(
        "--remove-config",
        action="store_true",
        help="With --rollback: also remove ~/.config/twinbox (code-root/state-root pointers)",
    )
    dep_oc.add_argument(
        "--repo-root",
        default="",
        help="Twinbox git checkout (default: resolve from cwd via ~/.config/twinbox/code-root)",
    )
    dep_oc.add_argument(
        "--openclaw-home",
        default="",
        help="OpenClaw config dir (default: ~/.openclaw)",
    )
    dep_oc.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned steps without mutating files or restarting gateway",
    )
    dep_oc.add_argument(
        "--no-restart",
        action="store_true",
        help="Skip `openclaw gateway restart`",
    )
    dep_oc.add_argument(
        "--no-env-sync",
        action="store_true",
        help="Only set skills.entries.twinbox.enabled; do not copy mailbox keys from the Twinbox config",
    )
    dep_oc.add_argument(
        "--strict",
        action="store_true",
        help="With env sync (default): fail if the Twinbox config lacks any OpenClaw-required mail key "
        "(SKILL.md requires.env); skips writing openclaw.json / later steps",
    )
    dep_oc.add_argument(
        "--fragment",
        default="",
        metavar="PATH",
        help="JSON file to deep-merge into openclaw.json before skills.entries.twinbox "
        "(default: use openclaw-skill/openclaw.fragment.json if that file exists)",
    )
    dep_oc.add_argument(
        "--no-fragment",
        action="store_true",
        help="Do not load openclaw-skill/openclaw.fragment.json",
    )
    dep_oc.add_argument(
        "--openclaw-bin",
        default="openclaw",
        help="openclaw executable for gateway restart",
    )
    dep_oc.add_argument("--json", action="store_true", help="Output as JSON")

    onboard_parser = subparsers.add_parser("onboard", help="Guided onboarding helpers")
    onboard_sub = onboard_parser.add_subparsers(dest="onboard_command", required=True)

    onboard_oc = onboard_sub.add_parser(
        "openclaw",
        help="Guided OpenClaw host wiring, validation, and handoff to conversational onboarding",
    )
    onboard_oc.add_argument(
        "--repo-root",
        default="",
        help="Twinbox git checkout (default: resolve from cwd via ~/.config/twinbox/code-root)",
    )
    onboard_oc.add_argument(
        "--openclaw-home",
        default="",
        help="OpenClaw config dir (default: ~/.openclaw)",
    )
    onboard_oc.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan the onboarding flow without mutating files or restarting gateway",
    )
    onboard_oc.add_argument(
        "--openclaw-bin",
        default="openclaw",
        help="openclaw executable for validation and gateway restart",
    )
    onboard_oc.add_argument("--json", action="store_true", help="Output as JSON")

    onboard_oc_v2 = onboard_sub.add_parser(
        "openclaw-v2",
        help=argparse.SUPPRESS,
    )
    onboard_oc_v2.add_argument(
        "--repo-root",
        default="",
        help="Twinbox git checkout (default: resolve from cwd via ~/.config/twinbox/code-root)",
    )
    onboard_oc_v2.add_argument(
        "--openclaw-home",
        default="",
        help="OpenClaw config dir (default: ~/.openclaw)",
    )
    onboard_oc_v2.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan the onboarding flow without mutating files or restarting gateway",
    )
    onboard_oc_v2.add_argument(
        "--openclaw-bin",
        default="openclaw",
        help="openclaw executable for validation and gateway restart",
    )
    onboard_oc_v2.add_argument("--json", action="store_true", help="Output as JSON")

    # onboarding commands
    onboarding_parser = subparsers.add_parser("onboarding", help="Conversational onboarding flow")
    onboarding_sub = onboarding_parser.add_subparsers(dest="onboarding_command", required=True)

    onboarding_start = onboarding_sub.add_parser("start", help="Start onboarding flow")
    onboarding_start.add_argument("--json", action="store_true", help="Output as JSON")

    onboarding_status = onboarding_sub.add_parser("status", help="Show onboarding progress")
    onboarding_status.add_argument("--json", action="store_true", help="Output as JSON")

    onboarding_next = onboarding_sub.add_parser("next", help="Complete current stage and move to next")
    onboarding_next.add_argument("--json", action="store_true", help="Output as JSON")

    # push commands
    push_parser = subparsers.add_parser("push", help="Push notification subscriptions")
    push_sub = push_parser.add_subparsers(dest="push_command", required=True)

    push_subscribe = push_sub.add_parser("subscribe", help="Subscribe to push notifications")
    push_subscribe.add_argument("session_id", help="OpenClaw session ID")
    push_subscribe.add_argument("--min-urgency", choices=["high", "medium", "low"], help="Minimum urgency filter")
    push_subscribe.add_argument("--json", action="store_true", help="Output as JSON")

    push_unsubscribe = push_sub.add_parser("unsubscribe", help="Unsubscribe from push")
    push_unsubscribe.add_argument("session_id", help="OpenClaw session ID")
    push_unsubscribe.add_argument("--json", action="store_true", help="Output as JSON")

    push_list = push_sub.add_parser("list", help="List all subscriptions")
    push_list.add_argument("--json", action="store_true", help="Output as JSON")

    push_dispatch = push_sub.add_parser("dispatch", help="Manually trigger push dispatch")
    push_dispatch.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw binary path")
    push_dispatch.add_argument("--json", action="store_true", help="Output as JSON")

    # queue commands
    queue_parser = subparsers.add_parser("queue", help="Queue management")
    queue_sub = queue_parser.add_subparsers(dest="queue_command", required=True)

    queue_list = queue_sub.add_parser("list", help="List all queues")
    queue_list.add_argument("--json", action="store_true", help="Output as JSON")

    queue_show = queue_sub.add_parser("show", help="Show queue details")
    queue_show.add_argument("queue_type", help="Queue type (urgent/pending/sla_risk)")
    queue_show.add_argument("--json", action="store_true", help="Output as JSON")

    queue_sub.add_parser("explain", help="Explain queue projection")

    queue_dismiss = queue_sub.add_parser("dismiss", help="Dismiss a thread from queue views")
    queue_dismiss.add_argument("thread_id", help="Thread key to dismiss")
    queue_dismiss.add_argument("--reason", default="已处理", help="Why this thread is being dismissed")
    queue_dismiss.add_argument("--json", action="store_true", help="Output as JSON")

    queue_complete = queue_sub.add_parser("complete", help="Mark a thread as completed")
    queue_complete.add_argument("thread_id", help="Thread key to complete")
    queue_complete.add_argument("--action-taken", default="已完成", help="Action that closed the thread")
    queue_complete.add_argument("--json", action="store_true", help="Output as JSON")

    queue_restore = queue_sub.add_parser("restore", help="Restore a dismissed or completed thread")
    queue_restore.add_argument("thread_id", help="Thread key to restore")
    queue_restore.add_argument("--json", action="store_true", help="Output as JSON")

    schedule_parser = subparsers.add_parser("schedule", help="Schedule override management")
    schedule_sub = schedule_parser.add_subparsers(dest="schedule_command", required=True)

    schedule_list = schedule_sub.add_parser("list", help="List effective schedules")
    schedule_list.add_argument("--json", action="store_true", help="Output as JSON")

    schedule_update = schedule_sub.add_parser("update", help="Update one schedule override")
    schedule_update.add_argument("job_name", help="Schedule name to override")
    schedule_update.add_argument("--cron", required=True, help="5-field cron expression")
    schedule_update.add_argument("--json", action="store_true", help="Output as JSON")

    schedule_reset = schedule_sub.add_parser("reset", help="Reset one schedule override")
    schedule_reset.add_argument("job_name", help="Schedule name to reset")
    schedule_reset.add_argument("--json", action="store_true", help="Output as JSON")

    schedule_enable = schedule_sub.add_parser("enable", help="Enable a schedule and create OpenClaw cron job")
    schedule_enable.add_argument("job_name", help="Schedule name to enable")
    schedule_enable.add_argument("--json", action="store_true", help="Output as JSON")

    schedule_disable = schedule_sub.add_parser("disable", help="Disable a schedule and delete OpenClaw cron job")
    schedule_disable.add_argument("job_name", help="Schedule name to disable")
    schedule_disable.add_argument("--json", action="store_true", help="Output as JSON")

    # thread commands
    thread_parser = subparsers.add_parser("thread", help="Thread inspection")
    thread_sub = thread_parser.add_subparsers(dest="thread_command", required=True)

    thread_inspect = thread_sub.add_parser("inspect", help="Inspect thread state")
    thread_inspect.add_argument("thread_id", help="Thread ID")
    thread_inspect.add_argument("--json", action="store_true", help="Output as JSON")

    thread_progress = thread_sub.add_parser("progress", help="Search thread progress from activity pulse")
    thread_progress.add_argument("query", help="Thread key, subject fragment, or business keyword")
    thread_progress.add_argument("--limit", type=int, default=5, help="Max matches")
    thread_progress.add_argument("--json", action="store_true", help="Output as JSON")

    thread_explain = thread_sub.add_parser("explain", help="Explain thread state reasoning")
    thread_explain.add_argument("thread_id", help="Thread ID")
    thread_explain.add_argument("--json", action="store_true", help="Output as JSON")

    # digest commands
    digest_parser = subparsers.add_parser("digest", help="Digest views")
    digest_sub = digest_parser.add_subparsers(dest="digest_command", required=True)

    digest_daily = digest_sub.add_parser("daily", help="Show daily digest")
    digest_daily.add_argument("--json", action="store_true", help="Output as JSON")

    digest_pulse = digest_sub.add_parser("pulse", help="Show daytime activity pulse")
    digest_pulse.add_argument("--json", action="store_true", help="Output as JSON")

    digest_weekly = digest_sub.add_parser("weekly", help="Show weekly digest")
    digest_weekly.add_argument("--json", action="store_true", help="Output as JSON")

    # task commands
    task_parser = subparsers.add_parser("task", help="Deterministic task routing on top of existing Twinbox views")
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)

    task_latest = task_sub.add_parser("latest-mail", help="Show the latest mail situation from activity pulse")
    task_latest.add_argument("--json", action="store_true", help="Output as JSON")
    task_latest.add_argument("--unread-only", action="store_true", help="Only show threads with unread emails")

    task_todo = task_sub.add_parser("todo", help="Show urgent/pending todo items")
    task_todo.add_argument("--json", action="store_true", help="Output as JSON")

    task_progress = task_sub.add_parser("progress", help="Look up progress by thread key, subject, or keyword")
    task_progress.add_argument("query", help="Thread key, subject fragment, or business keyword")
    task_progress.add_argument("--limit", type=int, default=5, help="Max matches")
    task_progress.add_argument("--json", action="store_true", help="Output as JSON")

    task_weekly = task_sub.add_parser("weekly", help="Show weekly digest through the task route")
    task_weekly.add_argument("--json", action="store_true", help="Output as JSON")

    task_mailbox = task_sub.add_parser("mailbox-status", help="Run mailbox preflight through the task route")
    task_mailbox.add_argument("--state-root", help="Override twinbox state root")
    task_mailbox.add_argument("--account", default="", help="Override MAIL_ACCOUNT_NAME")
    task_mailbox.add_argument("--folder", default="INBOX", help="Folder for read-only envelope list")
    task_mailbox.add_argument("--page-size", default=5, type=int, help="Envelope page size")
    task_mailbox.add_argument("--json", action="store_true", help="Output as JSON")

    # action commands
    action_parser = subparsers.add_parser("action", help="Action suggestions")
    action_sub = action_parser.add_subparsers(dest="action_command", required=True)

    action_suggest = action_sub.add_parser("suggest", help="Suggest actions from queue state")
    action_suggest.add_argument("--json", action="store_true", help="Output as JSON")

    action_materialize = action_sub.add_parser("materialize", help="Materialize a specific action")
    action_materialize.add_argument("action_id", help="Action ID to materialize")
    action_materialize.add_argument("--json", action="store_true", help="Output as JSON")

    # review commands
    review_parser = subparsers.add_parser("review", help="Review surface")
    review_sub = review_parser.add_subparsers(dest="review_command", required=True)

    review_list = review_sub.add_parser("list", help="List items needing review")
    review_list.add_argument("--json", action="store_true", help="Output as JSON")

    review_show = review_sub.add_parser("show", help="Show a specific review item")
    review_show.add_argument("review_id", help="Review ID")
    review_show.add_argument("--json", action="store_true", help="Output as JSON")

    # rule commands
    rule_parser = subparsers.add_parser("rule", help="Semantic routing rules management")
    rule_sub = rule_parser.add_subparsers(dest="rule_command", required=True)

    rule_list = rule_sub.add_parser("list", help="List all routing rules")
    rule_list.add_argument("--json", action="store_true", help="Output as JSON")

    rule_add = rule_sub.add_parser("add", help="Add or update a routing rule")
    rule_add.add_argument("--rule-json", required=True, help="Rule definition in JSON format")
    rule_add.add_argument("--json", action="store_true", help="Output as JSON")

    rule_remove = rule_sub.add_parser("remove", help="Remove a routing rule")
    rule_remove.add_argument("rule_id", help="Rule ID to remove")
    rule_remove.add_argument("--json", action="store_true", help="Output as JSON")

    rule_test = rule_sub.add_parser("test", help="Test a routing rule against recent threads")
    group = rule_test.add_mutually_exclusive_group(required=True)
    group.add_argument("--rule-id", help="Rule ID to test")
    group.add_argument("--rule-json", help="Rule definition in JSON format to test without saving")
    rule_test.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


def _apply_cli_profile(name: str) -> None:
    base = Path.home() / ".twinbox"
    base.mkdir(parents=True, exist_ok=True)
    st = base / "profiles" / name / "state"
    st.mkdir(parents=True, exist_ok=True)
    os.environ["TWINBOX_HOME"] = str(base.resolve())
    os.environ["TWINBOX_STATE_ROOT"] = str(st.resolve())


def _strip_profile_from_argv(argv: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--profile" and i + 1 < len(argv):
            _apply_cli_profile(argv[i + 1])
            i += 2
            continue
        if argv[i].startswith("--profile="):
            _apply_cli_profile(argv[i].split("=", 1)[1])
            i += 1
            continue
        out.append(argv[i])
        i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    """Main entry point for task-facing CLI."""
    raw = list(sys.argv[1:] if argv is None else argv)
    rest = _strip_profile_from_argv(raw)
    parser = _build_parser()
    args = parser.parse_args(rest)

    try:
        if args.command == "daemon":
            return dispatch_daemon(args)
        if args.command == "vendor":
            return dispatch_vendor(args)
        if args.command == "loading":
            return dispatch_loading(args)
        if args.command == "context":
            if args.context_command == "import-material":
                return cmd_context_import_material(args)
            elif args.context_command == "material":
                if args.material_command == "list":
                    return cmd_material_list(args)
                elif args.material_command == "set-intent":
                    return cmd_material_set_intent(args)
                elif args.material_command == "remove":
                    return cmd_material_remove(args)
                elif args.material_command == "preview":
                    return cmd_material_preview(args)
            elif args.context_command == "upsert-fact":
                return cmd_context_upsert_fact(args)
            elif args.context_command == "profile-set":
                return cmd_context_profile_set(args)
            elif args.context_command == "refresh":
                return cmd_context_refresh(args)
        elif args.command == "mailbox":
            if args.mailbox_command == "preflight":
                return cmd_mailbox_preflight(args)
            elif args.mailbox_command == "detect":
                return cmd_mailbox_detect(args)
            elif args.mailbox_command == "setup":
                return cmd_mailbox_setup(args)
        elif args.command == "config":
            if args.config_command == "show":
                return cmd_config_show(args)
            if args.config_command == "set-llm":
                return cmd_config_set_llm(args)
            if args.config_command == "mailbox-set":
                return cmd_config_mailbox_set(args)
            if args.config_command == "integration-set":
                return cmd_config_set_integration(args)
            if args.config_command == "openclaw-set":
                return cmd_config_set_openclaw(args)
        elif args.command == "deploy":
            if args.deploy_command == "openclaw":
                return cmd_deploy_openclaw(args)
        elif args.command == "onboard":
            if args.onboard_command == "openclaw":
                return cmd_onboard_openclaw(args)
            elif args.onboard_command == "openclaw-v2":
                return cmd_onboard_openclaw_v2(args)
        elif args.command == "onboarding":
            if args.onboarding_command == "start":
                return cmd_onboarding_start(args)
            elif args.onboarding_command == "status":
                return cmd_onboarding_status(args)
            elif args.onboarding_command == "next":
                return cmd_onboarding_next(args)
        elif args.command == "push":
            if args.push_command == "subscribe":
                return cmd_push_subscribe(args)
            elif args.push_command == "unsubscribe":
                return cmd_push_unsubscribe(args)
            elif args.push_command == "list":
                return cmd_push_list(args)
            elif args.push_command == "dispatch":
                return cmd_push_dispatch(args)
        elif args.command == "queue":
            if args.queue_command == "list":
                return cmd_queue_list(args)
            elif args.queue_command == "show":
                return cmd_queue_show(args)
            elif args.queue_command == "explain":
                return cmd_queue_explain(args)
            elif args.queue_command == "dismiss":
                return cmd_queue_dismiss(args)
            elif args.queue_command == "complete":
                return cmd_queue_complete(args)
            elif args.queue_command == "restore":
                return cmd_queue_restore(args)
        elif args.command == "schedule":
            if args.schedule_command == "list":
                return cmd_schedule_list(args)
            elif args.schedule_command == "update":
                return cmd_schedule_update(args)
            elif args.schedule_command == "reset":
                return cmd_schedule_reset(args)
            elif args.schedule_command == "enable":
                return cmd_schedule_enable(args)
            elif args.schedule_command == "disable":
                return cmd_schedule_disable(args)
        elif args.command == "thread":
            if args.thread_command == "inspect":
                return cmd_thread_inspect(args)
            elif args.thread_command == "progress":
                return cmd_thread_progress(args)
            elif args.thread_command == "explain":
                return cmd_thread_explain(args)
        elif args.command == "digest":
            if args.digest_command == "daily":
                return cmd_digest_daily(args)
            elif args.digest_command == "pulse":
                return cmd_digest_pulse(args)
            elif args.digest_command == "weekly":
                return cmd_digest_weekly(args)
        elif args.command == "task":
            if args.task_command == "latest-mail":
                return cmd_task_latest_mail(args)
            elif args.task_command == "todo":
                return cmd_task_todo(args)
            elif args.task_command == "progress":
                return cmd_task_progress(args)
            elif args.task_command == "weekly":
                return cmd_task_weekly(args)
            elif args.task_command == "mailbox-status":
                return cmd_task_mailbox_status(args)
        elif args.command == "action":
            if args.action_command == "suggest":
                return cmd_action_suggest(args)
            elif args.action_command == "materialize":
                return cmd_action_materialize(args)
        elif args.command == "review":
            if args.review_command == "list":
                return cmd_review_list(args)
            elif args.review_command == "show":
                return cmd_review_show(args)
        elif args.command == "rule":
            if args.rule_command == "list":
                return cmd_rule_list(args)
            elif args.rule_command == "add":
                return cmd_rule_add(args)
            elif args.rule_command == "remove":
                return cmd_rule_remove(args)
            elif args.rule_command == "test":
                return cmd_rule_test(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
