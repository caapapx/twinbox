"""R4 case-lifecycle ledger slice: append-only, current view, derived states."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from twinbox_core import case_ledger
from twinbox_core.pulse import normalize_thread_key, write_activity_pulse

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _iso(day: str) -> str:
    return f"{day}T08:00:00+08:00"


def _seed_thread(root: Path, *, subject: str = "Deploy review", email_day: str = "2030-03-01") -> str:
    """Write one envelope + an urgent tag so the thread lands in needs_attention."""
    tk = normalize_thread_key(subject)
    env = {
        "id": "7",
        "folder": "INBOX",
        "subject": subject,
        "date": _iso(email_day),
        "flags": [],
        "from_addr": "boss@example.com",
        "recipient_role": "to",
    }
    raw = root / "runtime" / "validation" / "phase-1" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "envelopes-merged.json").write_text(json.dumps([env]), encoding="utf-8")
    ctx = root / "runtime" / "context" / "phase1-context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(json.dumps({"envelopes": [env], "sampled_bodies": {}}), encoding="utf-8")
    phase4 = root / "runtime" / "validation" / "phase-4"
    phase4.mkdir(parents=True, exist_ok=True)
    (phase4 / "daily-urgent.yaml").write_text(
        f"generated_at: '2030-03-01T08:00:00+08:00'\ndaily_urgent:\n  - thread_key: '{tk}'\n"
        "    why: need reply\n",
        encoding="utf-8",
    )
    return tk


def _write_envelopes(root: Path, envelopes: list[dict[str, Any]]) -> None:
    raw = root / "runtime" / "validation" / "phase-1" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "envelopes-merged.json").write_text(json.dumps(envelopes), encoding="utf-8")
    ctx = root / "runtime" / "context" / "phase1-context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(json.dumps({"envelopes": envelopes, "sampled_bodies": {}}), encoding="utf-8")


class TestAppendOnly(unittest.TestCase):
    def test_append_does_not_rewrite_old_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_ledger.append_record(
                root, case_ref="case_a", attribute="lifecycle_state", value="open",
                valid_from=_iso("2030-01-01"), evidence_ref="INBOX#1",
            )
            case_ledger.append_record(
                root, case_ref="case_a", attribute="lifecycle_state", value="closed",
                valid_from=_iso("2030-02-01"), evidence_ref="INBOX#2",
            )
            lines = case_ledger.case_ledger_path(root).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            records = [json.loads(line) for line in lines]
            self.assertEqual([r["value"] for r in records], ["open", "closed"])
            # The first line is byte-identical to what was appended first.
            self.assertEqual(records[0]["valid_from"], _iso("2030-01-01"))


class TestCurrentView(unittest.TestCase):
    def test_older_valid_from_does_not_replace_newer_current_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = "case_a"
            case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state", value="open",
                                      valid_from=_iso("2030-02-01"))
            case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state", value="waiting_on_me",
                                      valid_from=_iso("2030-03-01"))
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "waiting_on_me")
            # Backfill: appended later but with an older valid_from.
            case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state", value="closed",
                                      valid_from=_iso("2030-01-01"))
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "waiting_on_me")
            # Both the backfill line and the current lines remain on disk.
            records = case_ledger.load_records(root)
            self.assertEqual(len(records), 3)

    def test_supersede_only_affects_same_case_and_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = "case_b"
            case_ledger.append_record(root, case_ref=ref, attribute="stage_a", value="open",
                                      valid_from=_iso("2030-02-01"))
            case_ledger.append_record(root, case_ref=ref, attribute="stage_b", value="waiting_on_me",
                                      valid_from=_iso("2030-03-01"))
            # Supersede stage_a only.
            case_ledger.append_record(root, case_ref=ref, attribute="stage_a", value="closed",
                                      valid_from=_iso("2030-04-01"))
            self.assertEqual(case_ledger.current_value(root, ref, "stage_a"), "closed")
            self.assertEqual(case_ledger.current_value(root, ref, "stage_b"), "waiting_on_me")

    def test_illegal_value_is_needs_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = "case_c"
            # No pack: only the four states are legal.
            bad = case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state",
                                            value="archived", valid_from=_iso("2030-01-01"))
            self.assertEqual(bad["status"], "needs_confirmation")
            self.assertIsNone(case_ledger.current_value(root, ref, "lifecycle_state"))
            # closed -> non-reopen is also illegal.
            case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state", value="closed",
                                      valid_from=_iso("2030-02-01"))
            transition = case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state",
                                                   value="waiting_on_me", valid_from=_iso("2030-03-01"))
            self.assertEqual(transition["status"], "needs_confirmation")
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "closed")


class TestClosedAttention(unittest.TestCase):
    def test_closed_leaves_needs_attention_and_remains_queryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed_thread(root)
            # A pending row resolved by reply derives the closed state.
            phase4 = root / "runtime" / "validation" / "phase-4"
            (phase4 / "pending-replies.yaml").write_text(
                f"generated_at: '2030-03-02T08:00:00+08:00'\npending_replies:\n"
                f"  - thread_key: '{tk}'\n    resolved_by_reply: true\n    waiting_on_me: false\n",
                encoding="utf-8",
            )
            appended = case_ledger.sync_derived_states(root)
            self.assertEqual(len(appended), 1)
            self.assertEqual(appended[0]["value"], "closed")

            payload, _ = write_activity_pulse(root)
            self.assertFalse(any(c.get("thread_key") == tk for c in payload.get("needs_attention") or []))
            self.assertTrue(any(c.get("thread_key") == tk for c in payload.get("thread_index") or []))
            # Still visible from a current-view reader.
            ref = case_ledger.case_ref(root.name, tk)
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "closed")

    def test_closed_stays_closed_across_full_window_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = "Deploy review"
            tk = normalize_thread_key(subject)
            phase4 = root / "runtime" / "validation" / "phase-4"
            phase4.mkdir(parents=True, exist_ok=True)
            # Initial mail is a normal human message, later resolved by reply.
            _write_envelopes(root, [{
                "id": "7", "folder": "INBOX", "subject": subject,
                "date": _iso("2030-03-01"), "flags": [], "from_addr": "boss@example.com",
                "recipient_role": "to",
            }])
            (phase4 / "pending-replies.yaml").write_text(
                f"generated_at: '2030-03-01T08:00:00+08:00'\npending_replies:\n"
                f"  - thread_key: '{tk}'\n    resolved_by_reply: true\n    waiting_on_me: false\n",
                encoding="utf-8",
            )
            appended = case_ledger.sync_derived_states(root)
            self.assertEqual([a["value"] for a in appended], ["closed"])
            ref = case_ledger.case_ref(root.name, tk)
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "closed")

            # Nightly full-window rewrite: the thread is re-analysed as needing
            # action (not resolved), but the newest mail is an auto-reply, which
            # is NOT a valid reopen per the existing reopen rule.
            _write_envelopes(root, [
                {
                    "id": "7", "folder": "INBOX", "subject": subject,
                    "date": _iso("2030-03-01"), "flags": [], "from_addr": "boss@example.com",
                    "recipient_role": "to",
                },
                {
                    "id": "8", "folder": "INBOX", "subject": subject,
                    "date": _iso("2030-03-05"), "flags": [], "from_addr": "auto@example.com",
                    "recipient_role": "to", "auto_submitted": "auto-replied",
                },
            ])
            (phase4 / "pending-replies.yaml").write_text(
                "generated_at: '2030-03-05T08:00:00+08:00'\npending_replies: []\n",
                encoding="utf-8",
            )
            (phase4 / "daily-urgent.yaml").write_text(
                f"generated_at: '2030-03-05T08:00:00+08:00'\ndaily_urgent:\n"
                f"  - thread_key: '{tk}'\n    why: need action\n",
                encoding="utf-8",
            )
            rewritten = case_ledger.sync_derived_states(root)
            self.assertEqual(rewritten, [])
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "closed")

            # A once-closed thread is not put back into needs_attention.
            payload, _ = write_activity_pulse(root)
            self.assertFalse(any(c.get("thread_key") == tk for c in payload.get("needs_attention") or []))
            self.assertTrue(any(c.get("thread_key") == tk for c in payload.get("thread_index") or []))

    def test_valid_reopen_moves_closed_back_to_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject = "Deploy review"
            tk = normalize_thread_key(subject)
            phase4 = root / "runtime" / "validation" / "phase-4"
            phase4.mkdir(parents=True, exist_ok=True)
            _write_envelopes(root, [{
                "id": "7", "folder": "INBOX", "subject": subject,
                "date": _iso("2030-03-01"), "flags": [], "from_addr": "boss@example.com",
                "recipient_role": "to",
            }])
            (phase4 / "pending-replies.yaml").write_text(
                f"generated_at: '2030-03-01T08:00:00+08:00'\npending_replies:\n"
                f"  - thread_key: '{tk}'\n    resolved_by_reply: true\n    waiting_on_me: false\n",
                encoding="utf-8",
            )
            case_ledger.sync_derived_states(root)
            ref = case_ledger.case_ref(root.name, tk)
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "closed")

            # A fresh human reply is a valid reopen, so the case moves back to open.
            _write_envelopes(root, [
                {
                    "id": "7", "folder": "INBOX", "subject": subject,
                    "date": _iso("2030-03-01"), "flags": [], "from_addr": "boss@example.com",
                    "recipient_role": "to",
                },
                {
                    "id": "9", "folder": "INBOX", "subject": subject,
                    "date": _iso("2030-03-06"), "flags": [], "from_addr": "collaborator@partner.example.com",
                    "recipient_role": "to",
                },
            ])
            (phase4 / "pending-replies.yaml").write_text(
                "generated_at: '2030-03-06T08:00:00+08:00'\npending_replies: []\n",
                encoding="utf-8",
            )
            (phase4 / "daily-urgent.yaml").write_text(
                f"generated_at: '2030-03-06T08:00:00+08:00'\ndaily_urgent:\n"
                f"  - thread_key: '{tk}'\n    why: need action\n",
                encoding="utf-8",
            )
            case_ledger.sync_derived_states(root)
            self.assertEqual(case_ledger.current_value(root, ref, "lifecycle_state"), "open")


class TestLedgerCurrentViewCli(unittest.TestCase):
    def test_cli_current_view_contains_closed_and_omits_needs_confirmation(self) -> None:
        import contextlib
        import io
        import os
        from unittest import mock

        from twinbox_core import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"TWINBOX_STATE_ROOT": str(root)}):
                ref = "case_a"
                case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state",
                                          value="closed", valid_from=_iso("2030-02-01"))
                # Latest valid_from but an illegal closed -> non-reopen transition,
                # so it is stored as needs_confirmation and must not become current.
                case_ledger.append_record(root, case_ref=ref, attribute="lifecycle_state",
                                          value="waiting_on_me", valid_from=_iso("2030-03-01"))

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cli.main(["case-ledger", "--json"])
                self.assertEqual(rc, 0)
                payload = json.loads(buf.getvalue())

            cases = payload["cases"]
            ref_cases = [c for c in cases if c["case_ref"] == ref]
            self.assertEqual([c["value"] for c in ref_cases], ["closed"])
            self.assertEqual([c.get("status") for c in ref_cases], ["valid"])
            self.assertNotIn("needs_confirmation", [c.get("status") for c in cases])


class TestNoStageNamesInCore(unittest.TestCase):
    def test_twinbox_core_contains_no_fixture_stage_names(self) -> None:
        from tests.fixtures.case_ledger_stages import CASE_STAGE_NAMES
        from pathlib import Path as P

        core = P(__file__).resolve().parents[1] / "twinbox_core"
        haystack = "\n".join(p.read_text(encoding="utf-8") for p in core.rglob("*.py"))
        for name in CASE_STAGE_NAMES:
            self.assertNotIn(name, haystack, f"domain stage name {name!r} leaked into twinbox_core")


if __name__ == "__main__":
    unittest.main()
