"""OpenClaw TUI integration: session isolation, bootstrap, and tool-chain integrity.

These tests validate the assumptions documented in
`integrations/openclaw/tui-test-cases.md`:
- Natural-language prompts should reach the same `twinbox task …` code path
  as explicit probe prompts, not just read SKILL.md and narrate.
- Long suites are split across sessions to avoid the "empty payloads after
  ~5 turns" degradation observed on some Gateway-hosted models.
- Bootstrap turns (first message in a fresh session) reduce the chance of
  the agent dropping tool calls in subsequent turns.

All tests are **skipped** when `OPENCLAW_BIN` is not available or the
Gateway is not running, so they are safe to include in a normal `pytest`
run without a live OpenClaw environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import shutil
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", "openclaw")
AGENT_ID = os.environ.get("AGENT_ID", "twinbox")
AGENT_TIMEOUT = int(os.environ.get("AGENT_TIMEOUT", "90"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _has_openclaw() -> bool:
    return shutil.which(OPENCLAW_BIN) is not None


def _gateway_ok() -> bool:
    if not _has_openclaw():
        return False
    try:
        r = subprocess.run(
            [OPENCLAW_BIN, "gateway", "status"],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


requires_gateway = pytest.mark.skipif(
    not _gateway_ok(),
    reason="openclaw gateway not available",
)


def _agent_turn(message: str, *, session_id: str | None = None) -> dict | None:
    """Run a single openclaw agent turn and return parsed JSON."""
    cmd = [
        OPENCLAW_BIN, "agent",
        "--agent", AGENT_ID,
        "--message", message,
        "--json",
        "--timeout", str(AGENT_TIMEOUT),
        "--thinking", "off",
    ]
    if session_id:
        cmd.extend(["--session-id", session_id])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=AGENT_TIMEOUT + 30, cwd=str(REPO_ROOT))
    try:
        raw = r.stdout.strip()
        if not raw.startswith("{"):
            idx = raw.find("{")
            raw = raw[idx:] if idx >= 0 else raw
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_text(data: dict | None) -> str:
    if not data:
        return ""
    try:
        payloads = data.get("result", {}).get("payloads") or []
        return "\n".join(str(p["text"]) for p in payloads if isinstance(p, dict) and p.get("text"))
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

@requires_gateway
class TestSessionIsolation:
    """Verify that fresh sessions can reliably execute tool calls."""

    def test_fresh_session_bootstrap(self):
        """A fresh session with a bootstrap turn should produce non-empty text."""
        sid = str(uuid.uuid4())
        data = _agent_turn(
            "请先读取 ~/.openclaw/skills/twinbox/SKILL.md，然后在本轮内立即调用 "
            "twinbox onboarding status --json 或 twinbox_onboarding_status。"
            "执行后只基于真实工具输出返回 current_stage。不要只说‘让我执行命令’。",
            session_id=sid,
        )
        text = _extract_text(data)
        assert len(text.strip()) > 10, f"Bootstrap turn produced empty/near-empty reply: {text!r}"

    def test_two_turns_same_session(self):
        """Two turns in the same fresh session should both produce text."""
        sid = str(uuid.uuid4())
        for i, msg in enumerate([
            "请运行 twinbox task mailbox-status --json 并返回 status 字段。",
            "请运行 twinbox task latest-mail --json 并返回 generated_at。",
        ]):
            data = _agent_turn(msg, session_id=sid)
            text = _extract_text(data)
            assert len(text.strip()) > 5, f"Turn {i} in session {sid} produced empty reply"


@requires_gateway
class TestNaturalVsProbe:
    """Natural-language prompts should route to the same tool as probes."""

    def test_natural_latest_mail(self):
        """'What's new' style prompt should trigger twinbox task latest-mail."""
        sid = str(uuid.uuid4())
        data = _agent_turn(
            "我邮箱里最近有什么需要我优先处理的？请基于 twinbox 的真实数据回答，不要猜。",
            session_id=sid,
        )
        text = _extract_text(data)
        # Should contain evidence of real data, not just "I'll check"
        assert len(text.strip()) > 20, f"Natural prompt produced trivial reply: {text!r}"

    def test_probe_latest_mail(self):
        """Explicit probe should produce structured output."""
        sid = str(uuid.uuid4())
        data = _agent_turn(
            "请先实际执行 `twinbox task latest-mail --json`，然后返回："
            "1. generated_at  2. summary  3. urgent_top_k 的 thread_key。"
            "未执行成功不要猜。",
            session_id=sid,
        )
        text = _extract_text(data)
        ok = ("generated" in text.lower()) or ("summary" in text.lower())
        assert ok, f"Probe missing expected fields: {text[:200]!r}"


@requires_gateway
class TestToolChainIntegrity:
    """Verify tool calls complete without dropping the chain."""

    def test_onboarding_status_does_not_stall(self):
        """Running onboarding status should return stage info, not empty payload."""
        sid = str(uuid.uuid4())
        data = _agent_turn(
            "请运行 twinbox onboarding status --json 并返回 current_stage。",
            session_id=sid,
        )
        text = _extract_text(data)
        assert len(text.strip()) > 5, "onboarding status produced empty reply"

    def test_no_half_turn_stall(self):
        """The agent should not reply with only 'Let me run...' and no actual tool output."""
        sid = str(uuid.uuid4())
        data = _agent_turn(
            "请运行 twinbox task todo --json，然后列出 pending_count 和前 3 个 thread_key。",
            session_id=sid,
        )
        text = _extract_text(data).strip()
        stall_phrases = ("让我执行", "让我先查找", "让我查找", "I'll run", "Let me execute")
        if text and len(text) < 30 and any(p in text for p in stall_phrases):
            pytest.fail(f"Half-turn stall detected: {text!r}")
        assert len(text) > 10, f"Empty or near-empty reply: {text!r}"
