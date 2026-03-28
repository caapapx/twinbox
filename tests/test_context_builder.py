from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from twinbox_core.context_builder import _parse_mime_recipient_role, run_phase2_loading, run_phase3_loading


class ContextBuilderTest(unittest.TestCase):
    def _write_phase1_inputs(self, root: Path) -> None:
        (root / "runtime/context").mkdir(parents=True, exist_ok=True)
        (root / "runtime/validation/phase-1").mkdir(parents=True, exist_ok=True)
        phase1_context = {
            "owner_domain": "example.com",
            "lookback_days": 7,
            "stats": {"folders_scanned": ["INBOX"]},
            "envelopes": [
                {
                    "id": "1",
                    "folder": "INBOX",
                    "subject": "Re: 资源申请 20260319",
                    "from_name": "Alice",
                    "from_addr": "alice@example.com",
                    "date": "2026-03-19 10:00+08:00",
                    "has_attachment": False,
                },
                {
                    "id": "2",
                    "folder": "INBOX",
                    "subject": "资源申请 20260319",
                    "from_name": "Bob",
                    "from_addr": "bob@vendor.com",
                    "date": "2026-03-18 09:00+08:00",
                    "has_attachment": True,
                },
            ],
            "sampled_bodies": {
                "1": {"subject": "Re: 资源申请 20260319", "body": "请审批资源。"},
                "2": {"subject": "资源申请 20260319", "body": "等待确认。"},
            },
        }
        intent_classification = {
            "classifications": [
                {"id": "1", "intent": "collaboration", "confidence": 0.9, "evidence": ["alice"]},
                {"id": "2", "intent": "support", "confidence": 0.5, "evidence": ["bob"]},
            ]
        }
        (root / "runtime/context/phase1-context.json").write_text(
            json.dumps(phase1_context, ensure_ascii=False),
            encoding="utf-8",
        )
        (root / "runtime/validation/phase-1/intent-classification.json").write_text(
            json.dumps(intent_classification, ensure_ascii=False),
            encoding="utf-8",
        )
        (root / "runtime/context/manual-facts.yaml").write_text(
            "facts:\n  - id: F1\n    value: owner handles approvals\n",
            encoding="utf-8",
        )
        (root / "runtime/context/manual-habits.yaml").write_text(
            "habits:\n  - id: H1\n    cadence: weekly\n",
            encoding="utf-8",
        )
        (root / "runtime/context/instance-calibration-notes.md").write_text(
            "This calibration note is long enough to be included.\n" * 4,
            encoding="utf-8",
        )

    def test_phase2_loading_writes_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)

            context = run_phase2_loading(root)

            output = json.loads(
                (root / "runtime/validation/phase-2/context-pack.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(output["enriched_samples"]), 2)
            self.assertEqual(output["mailbox_summary"]["total_envelopes"], 2)
            self.assertTrue(output["human_context"]["has_facts"])
            self.assertEqual(context["top_contacts"][0]["key"], "alice@example.com")

    def test_phase2_loading_includes_onboarding_profile_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)
            (root / "runtime").mkdir(parents=True, exist_ok=True)
            (root / "runtime/onboarding-state.json").write_text(
                json.dumps(
                    {
                        "current_stage": "material_import",
                        "completed_stages": ["profile_setup"],
                        "profile_data": {"notes": "  engineer; checks mail at 9:30  "},
                        "mailbox_config": {},
                        "materials": [],
                        "routing_rules": [],
                        "push_enabled": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            run_phase2_loading(root)
            output = json.loads(
                (root / "runtime/validation/phase-2/context-pack.json").read_text(encoding="utf-8")
            )
            hc = output["human_context"]
            self.assertTrue(hc["has_onboarding_profile_notes"])
            self.assertEqual(hc["onboarding_profile_notes"], "engineer; checks mail at 9:30")

    def test_phase3_loading_writes_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)
            phase2_dir = root / "runtime/validation/phase-2"
            phase2_dir.mkdir(parents=True, exist_ok=True)
            (phase2_dir / "persona-hypotheses.yaml").write_text("persona: yes\n", encoding="utf-8")
            (phase2_dir / "business-hypotheses.yaml").write_text("business: yes\n", encoding="utf-8")

            context = run_phase3_loading(root)

            output = json.loads(
                (root / "runtime/validation/phase-3/context-pack.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(output["top_threads"]), 1)
            self.assertEqual(output["top_threads"][0]["thread_key"], "资源申请")
            self.assertEqual(output["mailbox_summary"]["total_threads"], 1)

    def test_parse_mime_recipient_role_distinguishes_to_vs_cc(self) -> None:
        owner = "owner@example.com"
        body_to = (
            "From: Alice <alice@example.com>\n"
            "To: Owner <owner@example.com>\n"
            "Cc: Watcher <watcher@example.com>\n"
            "\n"
            "请审批资源。"
        )
        body_cc = (
            "From: Alice <alice@example.com>\n"
            "To: Team <team@example.com>\n"
            "Cc: Owner <owner@example.com>, Watcher <watcher@example.com>\n"
            "\n"
            "请知悉。"
        )
        body_group = (
            "From: Alice <alice@example.com>\n"
            "To: 项目组 <project@example.com>\n"
            "Cc: 数码项目交付部技术支持部公共支撑团队邮件组 <digital_xmjfb_devops_group@example.com>\n"
            "\n"
            "请关注资源申请。"
        )

        self.assertEqual(_parse_mime_recipient_role(body_to, owner), "to")
        self.assertEqual(_parse_mime_recipient_role(body_cc, owner), "cc")
        self.assertEqual(_parse_mime_recipient_role(body_group, owner), "group")

    def test_phase3_loading_marks_thread_cc_only_when_owner_only_in_cc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime/context").mkdir(parents=True, exist_ok=True)
            (root / "runtime/validation/phase-1").mkdir(parents=True, exist_ok=True)
            (root / "runtime/validation/phase-2").mkdir(parents=True, exist_ok=True)

            phase1_context = {
                "owner_domain": "example.com",
                "lookback_days": 7,
                "stats": {"folders_scanned": ["INBOX"]},
                "envelopes": [
                    {
                        "id": "1",
                        "folder": "INBOX",
                        "subject": "Re: 北京云平台部署资源申请",
                        "from_name": "Alice",
                        "from_addr": "alice@example.com",
                        "date": "2026-03-19 10:00+08:00",
                        "has_attachment": False,
                    },
                    {
                        "id": "2",
                        "folder": "INBOX",
                        "subject": "北京云平台部署资源申请",
                        "from_name": "Bob",
                        "from_addr": "bob@vendor.com",
                        "date": "2026-03-18 09:00+08:00",
                        "has_attachment": True,
                    },
                ],
                "sampled_bodies": {
                    "1": {
                        "subject": "Re: 北京云平台部署资源申请",
                        "body": (
                            "From: Alice <alice@example.com>\n"
                            "To: 项目组 <project@example.com>\n"
                            "Cc: Owner <owner@example.com>\n\n"
                            "请知悉最新进展。"
                        ),
                    },
                    "2": {
                        "subject": "北京云平台部署资源申请",
                        "body": (
                            "From: Bob <bob@vendor.com>\n"
                            "To: 项目组 <project@example.com>\n"
                            "Cc: Owner <owner@example.com>, PM <pm@example.com>\n\n"
                            "资源已准备。"
                        ),
                    },
                },
            }
            intent_classification = {
                "classifications": [
                    {"id": "1", "intent": "delivery", "confidence": 0.9, "evidence": ["alice"]},
                    {"id": "2", "intent": "delivery", "confidence": 0.8, "evidence": ["bob"]},
                ]
            }
            (root / "runtime/context/phase1-context.json").write_text(
                json.dumps(phase1_context, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "runtime/validation/phase-1/intent-classification.json").write_text(
                json.dumps(intent_classification, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "runtime/validation/phase-2/persona-hypotheses.yaml").write_text(
                "persona: yes\n",
                encoding="utf-8",
            )
            (root / "runtime/validation/phase-2/business-hypotheses.yaml").write_text(
                "business: yes\n",
                encoding="utf-8",
            )

            old = os.environ.get("MAIL_ADDRESS")
            os.environ["MAIL_ADDRESS"] = "owner@example.com"
            try:
                context = run_phase3_loading(root)
            finally:
                if old is None:
                    os.environ.pop("MAIL_ADDRESS", None)
                else:
                    os.environ["MAIL_ADDRESS"] = old

            self.assertEqual(len(context["top_threads"]), 1)
            self.assertEqual(context["top_threads"][0]["recipient_role"], "cc_only")

    def test_phase3_loading_marks_thread_direct_when_any_message_has_owner_in_to(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)
            phase2_dir = root / "runtime/validation/phase-2"
            phase2_dir.mkdir(parents=True, exist_ok=True)
            (phase2_dir / "persona-hypotheses.yaml").write_text("persona: yes\n", encoding="utf-8")
            (phase2_dir / "business-hypotheses.yaml").write_text("business: yes\n", encoding="utf-8")

            phase1_context = json.loads((root / "runtime/context/phase1-context.json").read_text(encoding="utf-8"))
            phase1_context["sampled_bodies"] = {
                "1": {
                    "subject": "Re: 资源申请 20260319",
                    "body": (
                        "From: Alice <alice@example.com>\n"
                        "To: Owner <owner@example.com>\n"
                        "Cc: PM <pm@example.com>\n\n"
                        "请审批资源。"
                    ),
                },
                "2": {
                    "subject": "资源申请 20260319",
                    "body": (
                        "From: Bob <bob@vendor.com>\n"
                        "To: 项目组 <project@example.com>\n"
                        "Cc: Owner <owner@example.com>\n\n"
                        "等待确认。"
                    ),
                },
            }
            (root / "runtime/context/phase1-context.json").write_text(
                json.dumps(phase1_context, ensure_ascii=False),
                encoding="utf-8",
            )

            old = os.environ.get("MAIL_ADDRESS")
            os.environ["MAIL_ADDRESS"] = "owner@example.com"
            try:
                context = run_phase3_loading(root)
            finally:
                if old is None:
                    os.environ.pop("MAIL_ADDRESS", None)
                else:
                    os.environ["MAIL_ADDRESS"] = old

            self.assertEqual(context["top_threads"][0]["recipient_role"], "direct")

    def test_phase3_loading_marks_thread_group_only_when_owner_not_in_to_or_cc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)
            phase2_dir = root / "runtime/validation/phase-2"
            phase2_dir.mkdir(parents=True, exist_ok=True)
            (phase2_dir / "persona-hypotheses.yaml").write_text("persona: yes\n", encoding="utf-8")
            (phase2_dir / "business-hypotheses.yaml").write_text("business: yes\n", encoding="utf-8")

            phase1_context = json.loads((root / "runtime/context/phase1-context.json").read_text(encoding="utf-8"))
            phase1_context["sampled_bodies"] = {
                "1": {
                    "subject": "Re: 资源申请 20260319",
                    "body": (
                        "From: Alice <alice@example.com>\n"
                        "To: Weiliu <weiliu84@example.com>\n"
                        "Cc: Team Group <digital_xmjfb_devops_group@example.com>\n\n"
                        "请知悉资源进展。"
                    ),
                },
                "2": {
                    "subject": "资源申请 20260319",
                    "body": (
                        "From: Bob <bob@vendor.com>\n"
                        "To: Weiliu <weiliu84@example.com>\n"
                        "Cc: Team Group <digital_xmjfb_devops_group@example.com>\n\n"
                        "资源申请处理中。"
                    ),
                },
            }
            (root / "runtime/context/phase1-context.json").write_text(
                json.dumps(phase1_context, ensure_ascii=False),
                encoding="utf-8",
            )

            old = os.environ.get("MAIL_ADDRESS")
            os.environ["MAIL_ADDRESS"] = "owner@example.com"
            try:
                context = run_phase3_loading(root)
            finally:
                if old is None:
                    os.environ.pop("MAIL_ADDRESS", None)
                else:
                    os.environ["MAIL_ADDRESS"] = old

            self.assertEqual(context["top_threads"][0]["recipient_role"], "group_only")

    def test_phase3_loading_reads_mail_address_from_state_root_env_when_process_env_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)
            phase2_dir = root / "runtime/validation/phase-2"
            phase2_dir.mkdir(parents=True, exist_ok=True)
            (phase2_dir / "persona-hypotheses.yaml").write_text("persona: yes\n", encoding="utf-8")
            (phase2_dir / "business-hypotheses.yaml").write_text("business: yes\n", encoding="utf-8")
            (root / ".env").write_text("MAIL_ADDRESS=owner@example.com\n", encoding="utf-8")

            phase1_context = json.loads((root / "runtime/context/phase1-context.json").read_text(encoding="utf-8"))
            phase1_context["sampled_bodies"] = {
                "1": {
                    "subject": "Re: 资源申请 20260319",
                    "body": (
                        "From: Alice <alice@example.com>\n"
                        "To: Weiliu <weiliu84@example.com>\n"
                        "Cc: Team Group <digital_xmjfb_devops_group@example.com>\n\n"
                        "请知悉资源进展。"
                    ),
                },
                "2": {
                    "subject": "资源申请 20260319",
                    "body": (
                        "From: Bob <bob@vendor.com>\n"
                        "To: Weiliu <weiliu84@example.com>\n"
                        "Cc: Team Group <digital_xmjfb_devops_group@example.com>\n\n"
                        "资源申请处理中。"
                    ),
                },
            }
            (root / "runtime/context/phase1-context.json").write_text(
                json.dumps(phase1_context, ensure_ascii=False),
                encoding="utf-8",
            )

            old = os.environ.pop("MAIL_ADDRESS", None)
            try:
                context = run_phase3_loading(root)
            finally:
                if old is not None:
                    os.environ["MAIL_ADDRESS"] = old

            self.assertEqual(context["top_threads"][0]["recipient_role"], "group_only")


if __name__ == "__main__":
    unittest.main()
