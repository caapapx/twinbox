"""Python loading pipeline for Phase 1-4 mailbox preparation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .artifacts import generated_at
from .context_builder import _normalize_thread, run_phase2_loading, run_phase3_loading
from .mailbox import build_effective_env, find_himalaya_binary, render_himalaya_config, resolve_mailbox_paths
from .onboarding import load_state
from .paths import resolve_state_root
from .routing_rules import apply_routing_rules


class LoadingPipelineError(RuntimeError):
    """Raised when a loading step cannot complete."""


def _parse_date(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_ndjson(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _resolve_mail_runtime(state_root: Path) -> tuple[dict[str, str], str, Path]:
    paths = resolve_mailbox_paths(state_root=state_root)
    effective_env, _defaults_applied, _file_env, _sources = build_effective_env(paths, env={})
    missing = [key for key in ("MAIL_ADDRESS",) if not effective_env.get(key)]
    if missing:
        raise LoadingPipelineError(f"Missing required mailbox env: {', '.join(missing)}")
    config_path = render_himalaya_config(paths, effective_env)
    himalaya_bin = find_himalaya_binary(paths)
    return effective_env, himalaya_bin, config_path


def _run_himalaya_json(
    himalaya_bin: str,
    config_path: Path,
    command: list[str],
    *,
    check: bool = True,
) -> object:
    proc = subprocess.run(
        [himalaya_bin, "-c", str(config_path), *command],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise LoadingPipelineError(detail)
    output = proc.stdout.strip()
    if output == "":
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output


def _folder_names(payload: object) -> list[str]:
    if not isinstance(payload, list):
        raise LoadingPipelineError("Expected JSON array from himalaya folder list")
    names: list[str] = []
    for row in payload:
        if isinstance(row, dict) and row.get("name"):
            names.append(str(row["name"]))
    return names


def _normalize_envelope_row(row: dict[str, object], *, folder: str, page: int) -> dict[str, object]:
    normalized = dict(row)
    normalized["folder"] = str(row.get("folder") or folder or "INBOX")
    normalized["source_page"] = page
    if "id" in normalized:
        normalized["id"] = str(normalized["id"])
    return normalized


def _filter_envelopes_by_lookback(envelopes: list[dict[str, object]], lookback_days: int) -> list[dict[str, object]]:
    if lookback_days <= 0:
        return envelopes
    cutoff = datetime.now().astimezone() - timedelta(days=lookback_days)
    filtered: list[dict[str, object]] = []
    for row in envelopes:
        dt = _parse_date(row.get("date"))
        if dt is None:
            continue
        if dt >= cutoff:
            filtered.append(row)
    return filtered


def _sample_bodies(
    envelopes: list[dict[str, object]],
    himalaya_bin: str,
    config_path: Path,
    *,
    account: str,
    sample_body_count: int,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    samples: list[dict[str, str]] = []
    sample_map: dict[str, dict[str, str]] = {}
    for row in envelopes[: max(sample_body_count, 0)]:
        message_id = str(row.get("id", ""))
        payload = _run_himalaya_json(
            himalaya_bin,
            config_path,
            [
                "message",
                "read",
                "--preview",
                "--account",
                account,
                "--folder",
                str(row.get("folder") or "INBOX"),
                message_id,
                "--output",
                "json",
            ],
            check=False,
        )
        body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False) if payload is not None else ""
        sample = {
            "id": message_id,
            "folder": str(row.get("folder") or "INBOX"),
            "subject": str(row.get("subject", "") or ""),
            "body": str(body)[:3000],
        }
        samples.append(sample)
        sample_map[message_id] = {"subject": sample["subject"], "body": sample["body"]}
    return samples, sample_map


def run_phase1_loading(
    state_root: Path,
    *,
    account_override: str = "",
    folder_filter: str = "",
    max_pages_per_folder: int = 20,
    page_size: int = 50,
    sample_body_count: int = 30,
    lookback_days: int = 7,
) -> dict[str, object]:
    state_root = state_root.expanduser().resolve()
    raw_dir = state_root / "runtime" / "context" / "raw"
    context_dir = state_root / "runtime" / "context"
    phase1_raw_dir = state_root / "runtime" / "validation" / "phase-1" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)
    phase1_raw_dir.mkdir(parents=True, exist_ok=True)

    effective_env, himalaya_bin, config_path = _resolve_mail_runtime(state_root)
    account = account_override or str(effective_env.get("MAIL_ACCOUNT_NAME") or "myTwinbox")
    folders_payload = _run_himalaya_json(
        himalaya_bin,
        config_path,
        ["folder", "list", "--account", account, "--output", "json"],
    )
    folders_json_path = _write_json(raw_dir / "folders.json", folders_payload)
    folders = [folder_filter] if folder_filter else _folder_names(folders_payload)

    all_pages_refs: list[dict[str, object]] = []
    merged_envelopes: list[dict[str, object]] = []
    for folder in folders:
        safe_folder = folder.replace("/", "__").replace(" ", "__")
        for page in range(1, max_pages_per_folder + 1):
            page_path = raw_dir / f"envelopes-{safe_folder}-p{page}.json"
            payload = _run_himalaya_json(
                himalaya_bin,
                config_path,
                [
                    "envelope",
                    "list",
                    "--account",
                    account,
                    "--folder",
                    folder,
                    "--page",
                    str(page),
                    "--page-size",
                    str(page_size),
                    "--output",
                    "json",
                ],
                check=False,
            )
            page_rows = payload if isinstance(payload, list) else []
            _write_json(page_path, page_rows)
            if not page_rows:
                break
            merged_envelopes.extend(
                _normalize_envelope_row(row, folder=folder, page=page)
                for row in page_rows
                if isinstance(row, dict)
            )
            all_pages_refs.append({"folder": folder, "page": page, "path": str(page_path)})
            if len(page_rows) < page_size:
                break

    _write_ndjson(raw_dir / "all-pages.ndjson", all_pages_refs)
    filtered = _filter_envelopes_by_lookback(merged_envelopes, lookback_days)
    _write_json(raw_dir / "envelopes-merged.json", filtered)

    sample_rows, sample_map = _sample_bodies(
        filtered,
        himalaya_bin,
        config_path,
        account=account,
        sample_body_count=sample_body_count,
    )
    _write_json(raw_dir / "sample-bodies.json", sample_rows)

    owner_addr = str(effective_env.get("MAIL_ADDRESS", "") or "")
    owner_domain = owner_addr.split("@", 1)[1].lower() if "@" in owner_addr else ""
    context = {
        "generated_at": generated_at(),
        "owner_domain": owner_domain,
        "lookback_days": lookback_days if lookback_days > 0 else None,
        "stats": {
            "total_envelopes": len(filtered),
            "sampled_bodies": len(sample_rows),
            "folders_scanned": folders,
        },
        "envelopes": [
            {
                "id": str(row.get("id", "")),
                "folder": str(row.get("folder") or "INBOX"),
                "subject": str(row.get("subject", "") or ""),
                "from_name": str(((row.get("from") or {}) if isinstance(row.get("from"), dict) else {}).get("name", "") or row.get("from_name", "") or ""),
                "from_addr": str(((row.get("from") or {}) if isinstance(row.get("from"), dict) else {}).get("addr", "") or row.get("from_addr", "") or ""),
                "date": str(row.get("date", "") or ""),
                "has_attachment": bool(row.get("has_attachment", False)),
                "flags": row.get("flags", []) if isinstance(row.get("flags"), list) else [],
                "to": row.get("to"),
            }
            for row in filtered
        ],
        "sampled_bodies": sample_map,
    }
    _write_json(context_dir / "phase1-context.json", context)

    for name in ("envelopes-merged.json", "sample-bodies.json", "folders.json", "all-pages.ndjson"):
        source = raw_dir / name
        target = phase1_raw_dir / name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"Context-pack written: {context_dir / 'phase1-context.json'}")
    print(f"  {len(filtered)} envelopes, {len(sample_rows)} body samples")
    return context


def _read_material_extract_bundle(material_dir: Path, manifest_path: Path) -> str:
    if not material_dir.is_dir():
        return ""
    intent_map: dict[str, str] = {}
    if manifest_path.is_file():
        try:
            manifest = _read_json(manifest_path)
            materials = manifest.get("materials", []) if isinstance(manifest, dict) else []
            for row in materials:
                if not isinstance(row, dict):
                    continue
                filename = str(row.get("filename", ""))
                if not filename:
                    continue
                extract_name = filename.rsplit(".", 1)[0] + "_" + filename.rsplit(".", 1)[-1] + ".extracted.md" if "." in filename else filename + ".extracted.md"
                intent_map[extract_name] = str(row.get("intent", "reference") or "reference")
        except Exception:
            intent_map = {}
    parts: list[str] = []
    for path in sorted(material_dir.glob("*.extracted.md")):
        intent = intent_map.get(path.name, "reference")
        parts.append(f"<!-- {path.name} | intent={intent} -->\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)[:8000]


def _extract_persona_hypotheses(text: str, limit: int = 3) -> list[str]:
    import re

    return [match.group(1).strip() for match in re.finditer(r'hypothesis:\s*"([^"]+)"', text)][:limit]


def _thread_signal_score(subject: str, cached_body: str) -> int:
    import re

    haystack = f"{subject}\n{cached_body}".lower()
    score = 0
    if re.search(r"(部署结果反馈|资源反馈|部署反馈)", haystack):
        score += 6
    if re.search(r"(周报|工作周报|交付周报|台账)", haystack):
        score += 5
    if re.search(r"(一次成功|问题反馈|风险|漏洞|整改|联调)", haystack):
        score += 4
    return score


def _recipient_role_from_to_field(envelope: dict[str, object], owner_addr: str) -> str:
    owner = owner_addr.lower().strip()
    to_field = envelope.get("to")
    if isinstance(to_field, list):
        addrs = [str((item or {}).get("addr") or (item or {}).get("email") or "").lower() for item in to_field if isinstance(item, dict)]
        if owner in addrs:
            return "direct"
        if addrs:
            return "indirect"
    if isinstance(to_field, dict):
        addr = str(to_field.get("addr") or to_field.get("email") or "").lower()
        if addr == owner and addr:
            return "direct"
        if addr:
            return "indirect"
    return "unknown"


def run_phase4_loading(
    state_root: Path,
    *,
    account_override: str = "",
    lookback_days: int = 7,
    max_body_fetch: int = 24,
    max_thread_candidates: int = 45,
) -> dict[str, object]:
    state_root = state_root.expanduser().resolve()
    effective_env, himalaya_bin, config_path = _resolve_mail_runtime(state_root)
    account = account_override or str(effective_env.get("MAIL_ACCOUNT_NAME") or "myTwinbox")
    owner_addr = str(effective_env.get("MAIL_ADDRESS", "") or "")

    phase1_raw = state_root / "runtime" / "validation" / "phase-1" / "raw"
    phase3_dir = state_root / "runtime" / "validation" / "phase-3"
    phase4_dir = state_root / "runtime" / "validation" / "phase-4"
    runtime_context = state_root / "runtime" / "context"
    phase4_dir.mkdir(parents=True, exist_ok=True)

    envelopes_path = phase1_raw / "envelopes-merged.json"
    thread_samples_path = phase3_dir / "thread-stage-samples.json"
    if not envelopes_path.is_file() or not thread_samples_path.is_file():
        raise LoadingPipelineError("Missing Phase 1/3 outputs.\nRun Phase 1-3 first.")

    envelopes_payload = _read_json(envelopes_path)
    sample_bodies_payload = _read_json(phase1_raw / "sample-bodies.json") if (phase1_raw / "sample-bodies.json").is_file() else []
    thread_samples_payload = _read_json(thread_samples_path)
    lifecycle_raw = (phase3_dir / "lifecycle-model.yaml").read_text(encoding="utf-8") if (phase3_dir / "lifecycle-model.yaml").is_file() else ""
    persona_raw = (state_root / "runtime" / "validation" / "phase-2" / "persona-hypotheses.yaml").read_text(encoding="utf-8") if (state_root / "runtime" / "validation" / "phase-2" / "persona-hypotheses.yaml").is_file() else ""
    phase3_context = _read_json(phase3_dir / "context-pack.json") if (phase3_dir / "context-pack.json").is_file() else {}

    envelopes = [row for row in envelopes_payload if isinstance(row, dict)] if isinstance(envelopes_payload, list) else []
    sample_bodies = [row for row in sample_bodies_payload if isinstance(row, dict)] if isinstance(sample_bodies_payload, list) else []
    body_map = {str(row.get("id", "")): str(row.get("body", "") or "") for row in sample_bodies}
    phase3_role_map = {}
    if isinstance(phase3_context, dict):
        for row in phase3_context.get("top_threads", []):
            if isinstance(row, dict) and row.get("thread_key"):
                phase3_role_map[str(row["thread_key"]).lower()] = str(row.get("recipient_role", "") or "")

    now = datetime.now().astimezone()
    cutoff = now - timedelta(days=lookback_days)
    recent: list[dict[str, object]] = []
    for row in envelopes:
        dt = _parse_date(row.get("date"))
        if dt is None or dt < cutoff:
            continue
        recent.append(dict(row))

    thread_map: dict[str, list[dict[str, object]]] = {}
    for row in recent:
        key = _normalize_thread(row.get("subject", ""), strip_date_suffix=True)
        thread_map.setdefault(key, []).append(row)

    modeled_samples = thread_samples_payload.get("samples", []) if isinstance(thread_samples_payload, dict) else []
    modeled_map: dict[str, dict[str, object]] = {}
    for row in modeled_samples:
        if not isinstance(row, dict):
            continue
        key = _normalize_thread(str(row.get("thread_key", "")).replace("(0)", ""), strip_date_suffix=True)
        key = key.rsplit("(", 1)[0].strip() if key.endswith(")") and "(" in key else key
        modeled_map[key] = row

    ranked_threads: list[dict[str, object]] = []
    for key, rows in thread_map.items():
        rows.sort(key=lambda row: str(row.get("date", "")), reverse=True)
        latest = rows[0]
        cached_body = body_map.get(str(latest.get("id", "")), "")
        latest_dt = _parse_date(latest.get("date"))
        ranked_threads.append(
            {
                "key": key,
                "rows": rows,
                "count": len(rows),
                "latest": latest,
                "latest_ts": latest_dt.timestamp() if latest_dt is not None else 0.0,
                "modeled": key in modeled_map,
                "signal_score": _thread_signal_score(str(latest.get("subject", "")), cached_body),
            }
        )

    ranked_threads.sort(
        key=lambda item: (
            0 if item["modeled"] else 1,
            -int(item["signal_score"]),
            -int(item["count"]),
            -float(item["latest_ts"]),
        )
    )
    candidates = ranked_threads[:max_thread_candidates]

    fetched = 0
    thread_contexts: list[dict[str, object]] = []
    for item in candidates:
        latest = item["latest"]
        message_id = str(latest.get("id", ""))
        body_text = body_map.get(message_id, "")
        if not body_text and fetched < max_body_fetch:
            payload = _run_himalaya_json(
                himalaya_bin,
                config_path,
                [
                    "message",
                    "read",
                    "--preview",
                    "--no-headers",
                    "--account",
                    account,
                    "--folder",
                    str(latest.get("folder") or "INBOX"),
                    message_id,
                    "--output",
                    "json",
                ],
                check=False,
            )
            body_text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False) if payload is not None else ""
            if body_text:
                fetched += 1

        sample = modeled_map.get(str(item["key"]), {})
        recipient_role = phase3_role_map.get(str(item["key"]).lower(), "")
        if not recipient_role or recipient_role == "unknown":
            recipient_role = _recipient_role_from_to_field(latest, owner_addr)

        participants = list(
            dict.fromkeys(
                [
                    str(((row.get("from") or {}) if isinstance(row.get("from"), dict) else {}).get("addr", "") or row.get("from_addr", "") or "")
                    for row in item["rows"]
                    if str(((row.get("from") or {}) if isinstance(row.get("from"), dict) else {}).get("addr", "") or row.get("from_addr", "") or "")
                ]
            )
        )[:5]

        thread_contexts.append(
            {
                "thread_key": str(item["key"]),
                "count": int(item["count"]),
                "latest_subject": str(latest.get("subject", "") or ""),
                "latest_from": str(((latest.get("from") or {}) if isinstance(latest.get("from"), dict) else {}).get("addr", "") or latest.get("from_addr", "") or ""),
                "latest_date": str(latest.get("date", "") or ""),
                "folder": str(latest.get("folder", "") or ""),
                "recipient_role": recipient_role or "unknown",
                "lifecycle_flow": str(sample.get("flow", "UNMODELED") or "UNMODELED"),
                "lifecycle_stage": str(sample.get("inferred_stage", "unknown") or "unknown"),
                "lifecycle_stage_name": str(sample.get("stage_name", "") or ""),
                "lifecycle_confidence": sample.get("confidence", 0),
                "body_excerpt": str(body_text)[:600],
                "participants": participants,
            }
        )

    facts_raw = (runtime_context / "manual-facts.yaml").read_text(encoding="utf-8").strip() if (runtime_context / "manual-facts.yaml").is_file() else ""
    habits_raw = (runtime_context / "manual-habits.yaml").read_text(encoding="utf-8").strip() if (runtime_context / "manual-habits.yaml").is_file() else ""
    material_bundle = _read_material_extract_bundle(runtime_context / "material-extracts", runtime_context / "material-manifest.json")
    has_facts = bool(facts_raw and facts_raw != "facts: []")
    has_habits = bool(habits_raw and habits_raw != "habits: []")
    has_material_extracts = len(material_bundle.strip()) > 50

    ob_state = load_state(state_root)
    raw_notes = ob_state.profile_data.get("notes") if isinstance(ob_state.profile_data, dict) else None
    onboarding_notes = raw_notes.strip() if isinstance(raw_notes, str) and raw_notes.strip() else ""
    raw_calibration = ob_state.profile_data.get("calibration") if isinstance(ob_state.profile_data, dict) else None
    onboarding_calibration = (
        raw_calibration.strip() if isinstance(raw_calibration, str) and raw_calibration.strip() else ""
    )

    cal_path = runtime_context / "instance-calibration-notes.md"
    calibration_raw = (
        cal_path.read_text(encoding="utf-8").strip() if cal_path.is_file() else ""
    )
    if not calibration_raw and onboarding_calibration:
        calibration_raw = onboarding_calibration
    has_calibration = bool(calibration_raw)

    context = {
        "generated_at": generated_at(),
        "lookback_days": lookback_days,
        "mail_address": owner_addr,
        "recent_envelope_count": len(recent),
        "thread_candidates": len(thread_contexts),
        "bodies_fetched_live": fetched,
        "bodies_from_cache": sum(1 for row in thread_contexts if row.get("body_excerpt")) - fetched,
        "lifecycle_model_summary": lifecycle_raw[:2000] or None,
        "persona_summary": persona_raw[:2000] or None,
        "owner_focus": {
            "primary_role_hypotheses": _extract_persona_hypotheses(persona_raw, 3),
            "demote_categories": [
                "与当前岗位主线无关的广播类通知",
                "培训、HR、泛宣传邮件（除非本周明确要求本人处理）",
            ],
        },
        "threads": thread_contexts,
        "human_context": {
            "has_facts": has_facts,
            "has_habits": has_habits,
            "has_material_extracts": has_material_extracts,
            "manual_facts_raw": facts_raw if has_facts else None,
            "manual_habits_raw": habits_raw if has_habits else None,
            "material_extracts_notes": material_bundle if has_material_extracts else None,
            "has_onboarding_profile_notes": bool(onboarding_notes),
            "onboarding_profile_notes": onboarding_notes or None,
            "has_calibration": has_calibration,
            "calibration_notes": calibration_raw if has_calibration else None,
        },
    }
    output_path = _write_json(phase4_dir / "context-pack.json", context)
    apply_routing_rules(
        output_path,
        state_root / "config" / "routing-rules.yaml",
        output_path,
        state_root / ".env",
    )
    final_context = _read_json(output_path)
    print(f"Context pack: {len(thread_contexts)} threads, {len(recent)} recent envelopes")
    print(
        f"  bodies: {fetched} fetched live, "
        f"{sum(1 for row in thread_contexts if row.get('body_excerpt')) - fetched} from cache"
    )
    print(f"  -> {output_path}")
    return final_context if isinstance(final_context, dict) else context


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    phase1 = subparsers.add_parser("phase1")
    phase1.add_argument("--state-root", default="")
    phase1.add_argument("--account", default="")
    phase1.add_argument("--folder", default="")
    phase1.add_argument("--max-pages-per-folder", type=int, default=20)
    phase1.add_argument("--page-size", type=int, default=50)
    phase1.add_argument("--sample-body-count", type=int, default=30)
    phase1.add_argument("--lookback-days", type=int, default=7)

    phase2 = subparsers.add_parser("phase2")
    phase2.add_argument("--state-root", default="")

    phase3 = subparsers.add_parser("phase3")
    phase3.add_argument("--state-root", default="")

    phase4 = subparsers.add_parser("phase4")
    phase4.add_argument("--state-root", default="")
    phase4.add_argument("--account", default="")
    phase4.add_argument("--lookback-days", type=int, default=7)
    phase4.add_argument("--max-body-fetch", type=int, default=24)
    phase4.add_argument("--max-thread-candidates", type=int, default=45)
    return parser


def _resolve_state_root(raw: str) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return resolve_state_root(Path.cwd())


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    state_root = _resolve_state_root(getattr(args, "state_root", ""))
    try:
        if args.command == "phase1":
            run_phase1_loading(
                state_root,
                account_override=args.account,
                folder_filter=args.folder,
                max_pages_per_folder=args.max_pages_per_folder,
                page_size=args.page_size,
                sample_body_count=args.sample_body_count,
                lookback_days=args.lookback_days,
            )
            return 0
        if args.command == "phase2":
            run_phase2_loading(state_root)
            return 0
        if args.command == "phase3":
            run_phase3_loading(state_root)
            return 0
        if args.command == "phase4":
            run_phase4_loading(
                state_root,
                account_override=args.account,
                lookback_days=args.lookback_days,
                max_body_fetch=args.max_body_fetch,
                max_thread_candidates=args.max_thread_candidates,
            )
            return 0
    except (LoadingPipelineError, FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
