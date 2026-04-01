#!/usr/bin/env python3
"""
Run OpenClaw prompt-test.md cases in recommended order via `openclaw agent`.

Uses the same Gateway path as `openclaw agent --agent twinbox` (RPC to local Gateway).
For interactive multi-turn chat, use the OpenClaw Control UI or other clients; this script is the batch/CI equivalent.

Usage (from repo root):
  python3 scripts/run_openclaw_prompt_tests.py
  OPENCLAW_BIN=openclaw AGENT_TIMEOUT=180 python3 scripts/run_openclaw_prompt_tests.py

Env:
  OPENCLAW_BIN   default: openclaw
  AGENT_ID       default: twinbox
  AGENT_TIMEOUT  per-turn timeout seconds (default: 180)
  WALL_TIMEOUT   subprocess wall clock (default: AGENT_TIMEOUT+45)
  AGENT_THINKING  thinking level (default: off)
  OPENCLAW_PROMPT_TEST_NATURAL_SESSION_ID  optional fixed UUID for 自然话术段
  OPENCLAW_PROMPT_TEST_PROBE_SESSION_ID    optional fixed UUID for 探针段
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_MD = REPO_ROOT / "integrations" / "openclaw" / "tui-test-cases.md"

# Matches doc §「推荐顺序」；拆成两段会话，避免单会话过长导致后半段空包（长会话 + Gateway 常见）。
ORDER_NATURAL = ["P1", "P2", "P3", "P4", "P6"]
ORDER_PROBE = ["P8", "P0a", "P0b", "P0c", "P0d", "P7"]
ORDER = ORDER_NATURAL + ORDER_PROBE

# P8 走探针段重试链（read 路径）；不放入 NATURAL_IDS，避免与 P1 等混用同一套 retry 文案。
NATURAL_IDS = {"P1", "P2", "P3", "P4", "P5", "P6"}

RETRY_NATURAL = (
    "\n\n【系统约束】本轮内必须至少实际运行一次相关 twinbox 命令"
    "（例如 twinbox task latest-mail --json、todo、progress、weekly）"
    "或直接读取明确的 JSON 产物路径，并在同一条回复里用中文给出要点；"
    "禁止只写“我去查找/找目录”就结束。"
)

RETRY_PROBE = "\n\n请在本轮内直接运行上述 twinbox 命令，不要只复述 SKILL 或描述意图。"

# 与同一会话内连续多轮对齐：固定 session + 首轮 bootstrap，降低首条就空包概率。
BOOTSTRAP_NATURAL = (
    "（Twinbox 回归测试 · 自然话术段）接下来多轮为自然用户式提问。"
    "涉及邮件/线程/日内产物时，必须在本轮内直接运行对应的 twinbox task … --json"
    "（或读取明确 JSON 路径）再作答；禁止只承诺“要去查找”或空结束。本条仅回复：好。"
)

BOOTSTRAP_PROBE = (
    "（Twinbox 回归测试 · 探针段）接下来每条都要求你实际运行 twinbox 命令并贴出关键字段；"
    "禁止空回复。本条仅回复：好。"
)


def parse_prompts(md_path: Path) -> dict[str, str]:
    text = md_path.read_text(encoding="utf-8")
    pat = r"## (P\d+[a-z]?)\s+[^\n]*\n\n```text\n(.*?)```"
    found = dict(re.findall(pat, text, flags=re.DOTALL))
    missing = [pid for pid in ORDER if pid not in found]
    if missing:
        raise SystemExit(f"Missing prompt blocks in {md_path}: {missing}")
    return {k: v.strip() for k, v in found.items()}


def run_agent(
    openclaw: str,
    agent_id: str,
    message: str,
    timeout_sec: int,
    wall: int,
    session_id: str | None,
    thinking: str,
) -> tuple[int, dict | None, str]:
    cmd = [
        openclaw,
        "agent",
        "--agent",
        agent_id,
        "--message",
        message,
        "--json",
        "--timeout",
        str(timeout_sec),
        "--thinking",
        thinking,
    ]
    if session_id:
        cmd.extend(["--session-id", session_id])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=wall,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        return -1, None, "subprocess.TimeoutExpired"
    raw = (proc.stdout or "") + (proc.stderr or "")
    stdout = proc.stdout or ""
    try:
        if stdout.strip():
            candidate = stdout.strip()
            if not candidate.startswith("{"):
                idx = candidate.find("{")
                candidate = candidate[idx:] if idx >= 0 else candidate
            data = json.loads(candidate)
        else:
            data = None
    except json.JSONDecodeError:
        return proc.returncode, None, raw[:2000]
    return proc.returncode, data, raw


def extract_text(data: dict | None) -> str:
    if not data:
        return ""
    try:
        payloads = data.get("result", {}).get("payloads") or []
        parts = []
        for p in payloads:
            if isinstance(p, dict) and p.get("text"):
                parts.append(str(p["text"]))
        return "\n".join(parts)
    except (TypeError, AttributeError):
        return ""


def check_pass(pid: str, text: str) -> tuple[bool, str]:
    t = text.lower()
    if len(text.strip()) < 8:
        return False, "empty_or_tiny_reply"

    refusal_markers = (
        "无法使用 `exec`",
        "无法使用 exec",
        "不能使用 `exec`",
        "不能使用 exec",
        "请在您的终端中运行",
        "将输出粘贴给我",
        "粘贴给我即可",
        "我无法直接调用它",
    )
    if any(m in text for m in refusal_markers):
        return False, "tool_refusal_or_user_delegation"

    if pid == "P0a":
        ok = "generated_at" in text or "generated" in t
        ok = ok and ("summary" in t or "摘要" in text)
        ok = ok and ("pending" in t or "待处理" in text)
        return ok, "need generated/summary/pending"

    if pid == "P0b":
        ok = "pending" in t or "待" in text
        ok = ok and ("thread" in t or "线程" in text or "key" in t)
        return ok, "need pending + threads"

    if pid == "P0c":
        ok = "thread" in t or "主题" in text or "waiting" in t or "stage" in t or "进展" in text
        return ok, "need progress-like fields"

    if pid == "P0d":
        ok = ("login" in t and "stage" in t) or "login_stage" in text
        ok = ok or ("status" in t and "preflight" in t)
        return ok, "need login_stage / status"

    if pid == "P7":
        ok = "{" in text and (
            '"status"' in text
            or '"login_stage"' in text
            or "login_stage" in text
            or "mailbox-connected" in t
            or "unconfigured" in t
        )
        return ok, "need JSON-like preflight body"

    if pid == "P8":
        ok = ("generated_at" in text or "generated" in t) and ("summary" in t or "摘要" in text)
        return ok, "need pulse fields"

    # Natural / fuzzy
    if pid in NATURAL_IDS:
        # Heuristic: substantive reply; penalize pure intent without substance
        bad = len(text) < 80 and any(
            x in text for x in ("让我先查找", "我来查找", "找一下", "产物目录")
        )
        if bad and "twinbox" not in t and "exec" not in t:
            return False, "looks_like_stall_intent_only"
        ok = len(text.strip()) >= 40
        return ok, "need substantive text"

    return True, "ok"


def main() -> int:
    # Line-buffer stdout so log files are not empty during a run
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

    ap = argparse.ArgumentParser(
        description="Run OpenClaw prompt-test.md cases via openclaw agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print prompt order without running any agent turns.",
    )
    args = ap.parse_args()

    openclaw = os.environ.get("OPENCLAW_BIN", "openclaw")
    agent_id = os.environ.get("AGENT_ID", "twinbox")
    timeout_sec = int(os.environ.get("AGENT_TIMEOUT", "180"))
    wall = int(os.environ.get("WALL_TIMEOUT", str(timeout_sec + 45)))
    thinking = os.environ.get("AGENT_THINKING", "off")

    prompts = parse_prompts(PROMPT_MD)

    if args.dry_run:
        print(f"Prompt file: {PROMPT_MD}")
        print("Order:", ", ".join(ORDER))
        for pid in ORDER:
            print(f"  {pid}: {prompts.get(pid, 'MISSING')[:80]!r}")
        return 0

    failures: list[str] = []

    sid_a = os.environ.get("OPENCLAW_PROMPT_TEST_NATURAL_SESSION_ID") or str(uuid.uuid4())
    sid_b = os.environ.get("OPENCLAW_PROMPT_TEST_PROBE_SESSION_ID") or str(uuid.uuid4())

    print(f"Using {openclaw} agent={agent_id} timeout={timeout_sec}s wall={wall}s")
    print(f"thinking={thinking} natural_session={sid_a}")
    print(f"probe_session={sid_b}")
    print(f"Prompt file: {PROMPT_MD}")
    print("Order:", ", ".join(ORDER))
    print("---")

    def run_bootstrap(sid: str, body: str, label: str) -> bool:
        rc, data, _ = run_agent(
            openclaw,
            agent_id,
            body,
            min(timeout_sec, 90),
            min(wall, 120),
            sid,
            thinking,
        )
        ok_b = len(extract_text(data).strip()) >= 1 and rc == 0
        print(f"{'PASS' if ok_b else 'FAIL'} bootstrap-{label} rc={rc} reply={extract_text(data)[:40]!r}")
        return ok_b

    def run_block(sid: str, pids: list[str], label: str) -> None:
        print(f"=== session {label} id={sid} ===")
        for pid in pids:
            msg = prompts[pid]
            attempts = [(msg, "primary")]
            if pid in NATURAL_IDS:
                attempts.append((msg + RETRY_NATURAL, "retry_natural"))
                attempts.append(
                    (
                        "请先直接运行：`twinbox task latest-mail --json`；若与问题不够相关再运行 "
                        "`twinbox task todo --json` 或 `twinbox task progress … --json`。\n\n"
                        + msg,
                        "retry_command_hint",
                    ),
                )
            else:
                attempts.append((msg + RETRY_PROBE, "retry_probe"))
                attempts.append(("请直接运行命令并返回结果：\n\n" + msg, "retry_command_prefix"))
                if pid == "P8":
                    attempts.append(
                        (
                            "若读取 runtime/.../activity-pulse.json 失败，请改为直接运行："
                            "`twinbox digest pulse --json` 或 `twinbox task latest-mail --json`，"
                            "再只输出 generated_at、summary、urgent_top_k（thread_key）、pending_count。\n\n"
                            + msg,
                            "retry_pulse_fallback",
                        ),
                    )

            last_err = ""
            passed = False
            for body, label_attempt in attempts:
                rc, data, raw = run_agent(
                    openclaw, agent_id, body, timeout_sec, wall, sid, thinking
                )
                text = extract_text(data)
                ok, hint = check_pass(pid, text)
                status = "PASS" if ok and rc == 0 else "FAIL"

                preview = (text[:120] + "…") if len(text) > 120 else text
                print(f"{status} {pid} ({label_attempt}) rc={rc} check={hint} preview={preview!r}")

                if rc != 0:
                    last_err = f"exit {rc} {raw[:500]}"
                if ok and rc == 0:
                    passed = True
                    break

            if not passed:
                failures.append(f"{pid}: {last_err or 'check failed'}")

    run_bootstrap(sid_a, BOOTSTRAP_NATURAL, "natural")
    run_block(sid_a, ORDER_NATURAL, "natural")

    run_bootstrap(sid_b, BOOTSTRAP_PROBE, "probe")
    run_block(sid_b, ORDER_PROBE, "probe")

    print("---")
    if failures:
        print("FAILED:", len(failures))
        for f in failures:
            print(" ", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
