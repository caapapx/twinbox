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


def cmd_context_import_material(args: argparse.Namespace) -> int:
    """Import user material to runtime/context/materials/."""
    canonical_root = Path.cwd()
    if "TWINBOX_CANONICAL_ROOT" in os.environ:
        canonical_root = Path(os.environ["TWINBOX_CANONICAL_ROOT"]).expanduser()

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
    if source_path.name not in [m.get("filename") for m in manifest.get("materials", [])]:
        manifest.setdefault("materials", []).append({
            "filename": source_path.name,
            "imported_at": datetime.now().isoformat(),
            "source": str(source_path),
        })

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已导入材料: {source_path.name} -> {dest_path}")
    print(f"更新清单: {manifest_path}")
    return 0


def cmd_context_upsert_fact(args: argparse.Namespace) -> int:
    """Add or update manual fact to runtime/context/manual-facts.yaml."""
    canonical_root = Path.cwd()
    if "TWINBOX_CANONICAL_ROOT" in os.environ:
        canonical_root = Path(os.environ["TWINBOX_CANONICAL_ROOT"]).expanduser()

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
    canonical_root = Path.cwd()
    if "TWINBOX_CANONICAL_ROOT" in os.environ:
        canonical_root = Path(os.environ["TWINBOX_CANONICAL_ROOT"]).expanduser()

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
    print("提示: 使用 'twinbox orchestrate run phase1' 重新生成 Phase 1 artifacts")
    return 0


def _find_thread_in_artifacts(thread_id: str) -> dict | None:
    """Find thread information from Phase 3/4 artifacts."""
    canonical_root = Path.cwd()
    if "TWINBOX_CANONICAL_ROOT" in os.environ:
        canonical_root = Path(os.environ["TWINBOX_CANONICAL_ROOT"])

    validation_root = canonical_root / "runtime" / "validation"

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
                if item.get("thread_key") == thread_id:
                    return {
                        "thread_id": thread_id,
                        "queue_type": queue_key,
                        "data": item,
                        "source": str(artifact_path),
                    }

    return None


def cmd_thread_inspect(args: argparse.Namespace) -> int:
    """Inspect thread current state."""
    thread_info = _find_thread_in_artifacts(args.thread_id)

    if not thread_info:
        print(f"错误: 未找到线程 '{args.thread_id}'", file=sys.stderr)
        return 1

    data = thread_info["data"]

    if args.json:
        output = {
            "thread_id": thread_info["thread_id"],
            "state": data.get("stage", "unknown"),
            "waiting_on": data.get("waiting_on", "unknown"),
            "last_activity_at": data.get("last_activity_at", "unknown"),
            "confidence": data.get("urgency_score", 0) / 100.0,
            "evidence_refs": [data.get("evidence_source", "unknown")],
            "context_refs": [data.get("flow", "unknown")],
            "why": data.get("why", ""),
            "explainability": {
                "state_reasoning": data.get("why", ""),
                "confidence_factors": [
                    f"Urgency score: {data.get('urgency_score', 0)}",
                    f"Owner: {data.get('owner', 'unknown')}",
                    f"Action hint: {data.get('action_hint', 'none')}",
                ],
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"线程: {thread_info['thread_id']}",
            f"状态: {data.get('stage', 'unknown')}",
            f"等待: {data.get('waiting_on', 'unknown')}",
            f"置信度: {data.get('urgency_score', 0) / 100.0:.2f}",
            "",
            "证据:",
            f"- {data.get('evidence_source', 'unknown')}",
            "",
            "上下文:",
            f"- flow: {data.get('flow', 'unknown')}",
            f"- owner: {data.get('owner', 'unknown')}",
            "",
            f"原因: {data.get('why', '')}",
        ]
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


def cmd_digest_daily(args: argparse.Namespace) -> int:
    """Show daily digest."""
    canonical_root = Path.cwd()
    if "TWINBOX_CANONICAL_ROOT" in os.environ:
        canonical_root = Path(os.environ["TWINBOX_CANONICAL_ROOT"])

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


def cmd_digest_weekly(args: argparse.Namespace) -> int:
    """Show weekly digest."""
    canonical_root = Path.cwd()
    if "TWINBOX_CANONICAL_ROOT" in os.environ:
        canonical_root = Path(os.environ["TWINBOX_CANONICAL_ROOT"])

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twinbox",
        description="Task-facing CLI for twinbox email copilot",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # context commands
    context_parser = subparsers.add_parser("context", help="Context management")
    context_sub = context_parser.add_subparsers(dest="context_command", required=True)

    import_mat = context_sub.add_parser("import-material", help="Import user material")
    import_mat.add_argument("source", help="Source file path")

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

    # queue commands
    queue_parser = subparsers.add_parser("queue", help="Queue management")
    queue_sub = queue_parser.add_subparsers(dest="queue_command", required=True)

    queue_list = queue_sub.add_parser("list", help="List all queues")
    queue_list.add_argument("--json", action="store_true", help="Output as JSON")

    queue_show = queue_sub.add_parser("show", help="Show queue details")
    queue_show.add_argument("queue_type", help="Queue type (urgent/pending/sla_risk)")
    queue_show.add_argument("--json", action="store_true", help="Output as JSON")

    queue_explain = queue_sub.add_parser("explain", help="Explain queue projection")

    # thread commands
    thread_parser = subparsers.add_parser("thread", help="Thread inspection")
    thread_sub = thread_parser.add_subparsers(dest="thread_command", required=True)

    thread_inspect = thread_sub.add_parser("inspect", help="Inspect thread state")
    thread_inspect.add_argument("thread_id", help="Thread ID")
    thread_inspect.add_argument("--json", action="store_true", help="Output as JSON")

    thread_explain = thread_sub.add_parser("explain", help="Explain thread state reasoning")
    thread_explain.add_argument("thread_id", help="Thread ID")
    thread_explain.add_argument("--json", action="store_true", help="Output as JSON")

    # digest commands
    digest_parser = subparsers.add_parser("digest", help="Digest views")
    digest_sub = digest_parser.add_subparsers(dest="digest_command", required=True)

    digest_daily = digest_sub.add_parser("daily", help="Show daily digest")
    digest_daily.add_argument("--json", action="store_true", help="Output as JSON")

    digest_weekly = digest_sub.add_parser("weekly", help="Show weekly digest")
    digest_weekly.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for task-facing CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "context":
            if args.context_command == "import-material":
                return cmd_context_import_material(args)
            elif args.context_command == "upsert-fact":
                return cmd_context_upsert_fact(args)
            elif args.context_command == "profile-set":
                return cmd_context_profile_set(args)
            elif args.context_command == "refresh":
                return cmd_context_refresh(args)
        elif args.command == "queue":
            if args.queue_command == "list":
                return cmd_queue_list(args)
            elif args.queue_command == "show":
                return cmd_queue_show(args)
            elif args.queue_command == "explain":
                return cmd_queue_explain(args)
        elif args.command == "thread":
            if args.thread_command == "inspect":
                return cmd_thread_inspect(args)
            elif args.thread_command == "explain":
                return cmd_thread_explain(args)
        elif args.command == "digest":
            if args.digest_command == "daily":
                return cmd_digest_daily(args)
            elif args.digest_command == "weekly":
                return cmd_digest_weekly(args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

