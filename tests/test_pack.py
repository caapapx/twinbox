"""Pack / embeddings / rules / select / actions / schedule / onboard / project."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from twinbox_core.embeddings import cosine
from twinbox_core.onboard import answers_to_pack, save_user_pack
from twinbox_core.pack import PackError, load_pack_file, validate_pack
from twinbox_core.project import project_item
from twinbox_core.rules import hard_match, skip_llm_envelopes
from twinbox_core.schedule import due_jobs, missed_runs, run_due

SHANGHAI = ZoneInfo("Asia/Shanghai")


class TestPack(unittest.TestCase):
    def test_minimal_loads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pack = load_pack_file(root / "config" / "packs" / "minimal.yaml")
        self.assertEqual(pack["id"], "minimal")
        self.assertTrue(pack["fingerprint"])

    def test_rejects_script(self) -> None:
        with self.assertRaises(PackError):
            validate_pack({"id": "bad", "script": "print(1)"})


class TestEmbeddings(unittest.TestCase):
    def test_cosine_monotone(self) -> None:
        a = [1.0, 0.0]
        self.assertGreater(cosine(a, [1.0, 0.0]), cosine(a, [0.0, 1.0]))
        self.assertEqual(cosine([], [1.0]), 0.0)

    def test_no_numpy_import(self) -> None:
        import twinbox_core.embeddings as emb
        source = Path(emb.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import numpy", source)
        self.assertNotIn("import torch", source)


class TestRules(unittest.TestCase):
    def test_hard_skip(self) -> None:
        pack = {
            "routing_conditions": [
                {"skip_llm": True, "hard": {"from_addr_regex": "noreply@"}}
            ]
        }
        skipped = skip_llm_envelopes(pack, [{"from_addr": "noreply@x.com", "folder": "INBOX"}])
        self.assertEqual(len(skipped), 1)
        self.assertTrue(hard_match({"from_addr_regex": "noreply@"}, {"from_addr": "noreply@x.com"}))


class TestSelectFallback(unittest.TestCase):
    def test_rank_without_vectors(self) -> None:
        from twinbox_core.imap_fetch import rank_thread_candidates
        envs = [
            {"subject": "old", "date": "2020-01-01T00:00:00+08:00", "flags": ["Seen"], "id": "1", "folder": "INBOX"},
            {"subject": "new", "date": "2026-09-08T00:00:00+08:00", "flags": [], "id": "2", "folder": "INBOX", "recipient_role": "to"},
        ]
        ranked = rank_thread_candidates(envs, max_threads=2)
        self.assertEqual(ranked[0]["subject"], "new")


class TestOnboardProject(unittest.TestCase):
    def test_five_questions_pack(self) -> None:
        pack = answers_to_pack({"approvals": "验收", "watch": "周报", "broadcast": "跳过"})
        self.assertEqual(pack["id"], "user")
        self.assertTrue(pack["attention_hints"])

    def test_projections(self) -> None:
        pending = {"queue_tags": ["pending"], "why": "请回复", "recipient_role": "direct"}
        self.assertEqual(project_item(pending, None), "action_required")
        watch = {"queue_tags": ["urgent"], "why": "监控", "recipient_role": "cc_only"}
        self.assertEqual(project_item(watch, None), "watch")
        ref = {"queue_tags": [], "why": "制度", "recipient_role": "group_only"}
        self.assertEqual(project_item(ref, None), "reference")
        urgent_no_reply = {"queue_tags": ["urgent"], "why": "紧急无需回复", "recipient_role": "direct"}
        self.assertNotEqual(project_item(urgent_no_reply, None), "action_required")

    def test_save_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = save_user_pack(Path(tmp), {"approvals": "审批"})
            self.assertTrue(result["ok"])
            self.assertTrue(Path(result["path"]).is_file())


class TestActions(unittest.TestCase):
    def test_policy_miss_empty(self) -> None:
        from twinbox_core.actions import scan_proposals
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime" / "validation" / "phase-4").mkdir(parents=True)
            (root / "runtime" / "validation" / "phase-4" / "activity-pulse.json").write_text(
                json.dumps({"needs_attention": [{"thread_key": "x", "projection": "watch", "latest_message_ref": "INBOX#1"}]}),
                encoding="utf-8",
            )
            (root / "packs").mkdir()
            (root / "packs" / "user.yaml").write_text("id: user\nversion: '1'\naction_policy: []\n", encoding="utf-8")
            out = scan_proposals(root)
            self.assertEqual(out["proposals"], [])

    def test_hit_and_idempotent(self) -> None:
        from twinbox_core.actions import scan_proposals
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime" / "validation" / "phase-4").mkdir(parents=True)
            (root / "runtime" / "validation" / "phase-4" / "activity-pulse.json").write_text(
                json.dumps({"needs_attention": [{"thread_key": "验收", "projection": "action_required", "latest_message_ref": "INBOX#1", "why": "请登记"}]}),
                encoding="utf-8",
            )
            (root / "packs").mkdir()
            (root / "packs" / "user.yaml").write_text(
                "id: user\nversion: '1'\naction_policy:\n- id: notify-approval\n  enabled: true\n  action_type: notify\n  target_scope: [owner]\n  require_projection: action_required\n",
                encoding="utf-8",
            )
            first = scan_proposals(root)
            second = scan_proposals(root)
            self.assertEqual(len(first["proposals"]), 1)
            self.assertEqual(second["created"], 0)


class TestSchedule(unittest.TestCase):
    def test_due_and_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 9, 8, 9, 0, tzinfo=SHANGHAI)
            calls = {"n": 0}

            def fake_sync(job: str):
                calls["n"] += 1
                return {"ok": True, "job": job}

            first = run_due(root, now=now, sync_fn=fake_sync)
            second = run_due(root, now=now, sync_fn=fake_sync)
            self.assertTrue(first["ran"])
            self.assertEqual(second["ran"], [])
            self.assertEqual(calls["n"], len(first["ran"]))

    def test_missed_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 9, 8, 12, 0, tzinfo=SHANGHAI)
            misses = missed_runs(root, now=now)
            self.assertTrue(any(m["missed"] >= 2 for m in misses))


class TestAnalyzeResolved(unittest.TestCase):
    def test_prompt_marks_latest(self) -> None:
        from twinbox_core.analyze import _build_prompt
        prompt = _build_prompt({
            "envelopes": [
                {"subject": "验收登记", "date": "2026-09-03T10:00:00+08:00", "id": "1", "folder": "INBOX", "from_addr": "a@x.com"},
                {"subject": "Re: 验收登记", "date": "2026-09-03T12:00:00+08:00", "id": "2", "folder": "INBOX", "from_addr": "me@x.com"},
            ],
            "sampled_bodies": {"INBOX#2": {"body": "同意"}},
            "lookback_days": 7,
        })
        self.assertIn("is_latest=true", prompt)
        self.assertIn("同意", prompt)


if __name__ == "__main__":
    unittest.main()
