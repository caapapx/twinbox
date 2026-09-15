"""Candidate selection + compact latest-mail/todo cards."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

LLM_JSON = (
    '{"daily_urgent": [], "pending_replies": [], '
    '"sla_risks": [], "weekly_brief": {}}'
)


class TestChooseCandidates(unittest.TestCase):
    def test_hint_thread_ranks_first(self) -> None:
        from twinbox_core.select import choose_candidates

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packs").mkdir()
            (root / "packs" / "user.yaml").write_text(
                "id: user\nversion: '1'\nattention_hints:\n"
                "- id: h\n  utterances: [验收]\n",
                encoding="utf-8",
            )
            context = {
                "envelopes": [
                    {
                        "subject": "noise",
                        "date": "2026-09-08T00:00:00+08:00",
                        "id": "1",
                        "folder": "INBOX",
                        "flags": [],
                        "recipient_role": "to",
                    },
                    {
                        "subject": "验收登记",
                        "date": "2020-01-01T00:00:00+08:00",
                        "id": "2",
                        "folder": "INBOX",
                        "flags": ["Seen"],
                    },
                ]
            }

            def vec(_state, _folder, uid):
                return [1.0, 0.0] if uid == "2" else [0.0, 1.0]

            with mock.patch("twinbox_core.select.embed_texts", return_value=[[1.0, 0.0]]), \
                    mock.patch("twinbox_core.select.load_vector", side_effect=vec):
                picked, diag = choose_candidates(context, root, limit=1)
            self.assertEqual(picked[0]["id"], "2")
            self.assertFalse(diag["embeddings_degraded"])

    def test_embed_failure_falls_back_structural(self) -> None:
        from twinbox_core.select import choose_candidates

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packs").mkdir()
            (root / "packs" / "user.yaml").write_text(
                "id: user\nversion: '1'\nattention_hints:\n"
                "- id: h\n  utterances: [验收]\n",
                encoding="utf-8",
            )
            context = {
                "envelopes": [
                    {
                        "subject": "new",
                        "date": "2026-09-08T00:00:00+08:00",
                        "id": "2",
                        "folder": "INBOX",
                        "flags": [],
                        "recipient_role": "to",
                    },
                    {
                        "subject": "old",
                        "date": "2020-01-01T00:00:00+08:00",
                        "id": "1",
                        "folder": "INBOX",
                        "flags": ["Seen"],
                    },
                ]
            }
            with mock.patch("twinbox_core.select.embed_texts", side_effect=RuntimeError("down")):
                picked, diag = choose_candidates(context, root, limit=2)
            self.assertTrue(diag["embeddings_degraded"])
            self.assertEqual(picked[0]["id"], "2")


class TestAnalyzeSelect(unittest.TestCase):
    def test_keeps_all_envelopes_in_picked_threads(self) -> None:
        from twinbox_core.analyze import _build_prompt, _envelopes_for_threads

        context = {
            "envelopes": [
                {"subject": "合同审批", "date": "2026-09-01T10:00:00+08:00", "id": "1", "folder": "INBOX"},
                {"subject": "Re: 合同审批", "date": "2026-09-02T10:00:00+08:00", "id": "2", "folder": "INBOX"},
                {"subject": "无关", "date": "2026-09-03T10:00:00+08:00", "id": "3", "folder": "INBOX"},
            ],
            "lookback_days": 7,
        }
        narrowed = _envelopes_for_threads(context, [context["envelopes"][1]], set())
        ids = {str(env["id"]) for env in narrowed["envelopes"]}
        self.assertEqual(ids, {"1", "2"})
        prompt = _build_prompt(narrowed)
        self.assertIn("messages=2", prompt)
        self.assertNotIn("无关", prompt)

    def test_select_error_marks_degraded_and_still_analyzes(self) -> None:
        from twinbox_core.analyze import run_analysis

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context" / "phase1-context.json"
            ctx.parent.mkdir(parents=True)
            context = {
                "envelopes": [
                    {"subject": "a", "id": "1", "folder": "INBOX", "date": "2026-09-01T00:00:00+08:00"},
                ],
                "lookback_days": 7,
            }
            ctx.write_text(json.dumps(context), encoding="utf-8")
            seen: dict = {}
            from twinbox_core import analyze as analyze_mod
            orig_build = analyze_mod._build_prompt

            def wrap(ctx, human=None):
                seen["stats"] = dict(ctx.get("stats") or {})
                prompt = orig_build(ctx, human)
                seen["prompt"] = prompt
                return prompt

            def fake_llm(prompt, **_kwargs):
                return LLM_JSON

            with mock.patch("twinbox_core.select.choose_candidates", side_effect=RuntimeError("boom")), \
                    mock.patch("twinbox_core.analyze.call_llm", fake_llm), \
                    mock.patch.object(analyze_mod, "_build_prompt", wrap):
                result = run_analysis(root)
            self.assertTrue(result["ok"])
            self.assertTrue(seen["stats"].get("embeddings_degraded"))
            self.assertEqual(seen["stats"].get("select_error"), "RuntimeError")
            self.assertIn("thread_key=", seen["prompt"])

    def test_events_error_does_not_undo_candidates(self) -> None:
        from twinbox_core.analyze import run_analysis

        envs = [
            {"subject": "合同审批", "date": "2026-09-01T10:00:00+08:00", "id": "1", "folder": "INBOX"},
            {"subject": "Re: 合同审批", "date": "2026-09-02T10:00:00+08:00", "id": "2", "folder": "INBOX"},
            {"subject": "无关", "date": "2026-09-03T10:00:00+08:00", "id": "3", "folder": "INBOX"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context" / "phase1-context.json"
            ctx.parent.mkdir(parents=True)
            ctx.write_text(json.dumps({"envelopes": envs, "lookback_days": 7}), encoding="utf-8")
            seen: dict = {}
            from twinbox_core import analyze as analyze_mod
            orig_build = analyze_mod._build_prompt

            def wrap_build(ctx, human=None):
                seen["subjects"] = [e.get("subject") for e in ctx.get("envelopes", [])]
                seen["stats"] = dict(ctx.get("stats") or {})
                return orig_build(ctx, human)

            with mock.patch(
                "twinbox_core.select.choose_candidates",
                return_value=([envs[1]], {"embeddings_degraded": False}),
            ), mock.patch("twinbox_core.events.extract_events", side_effect=RuntimeError("ev")), \
                    mock.patch("twinbox_core.analyze.call_llm", return_value=LLM_JSON), \
                    mock.patch.object(analyze_mod, "_build_prompt", wrap_build):
                result = run_analysis(root)
            self.assertTrue(result["ok"])
            self.assertEqual(set(seen["subjects"]), {"合同审批", "Re: 合同审批"})
            self.assertEqual(seen["stats"].get("events_error"), "RuntimeError")


class TestMailCards(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"TWINBOX_STATE_ROOT": str(self.root)})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _write_pulse(self) -> None:
        path = self.root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
        path.parent.mkdir(parents=True)
        threads = []
        for i in range(8):
            threads.append({
                "thread_key": f"t{i}",
                "latest_subject": f"s{i}",
                "last_activity_at": f"2026-09-0{i+1}T00:00:00+08:00" if i < 9 else "2026-09-10T00:00:00+08:00",
                "latest_message_ref": f"INBOX#{i}",
                "unread_count": i,
                "fingerprint": "drop-me",
                "query_terms": ["noise"],
                "axes": {"urgency": "low"},
                "why": "because",
                "score": i,
                "projection": "watch",
            })
        path.write_text(
            json.dumps({
                "generated_at": "2026-09-15T12:00:00+08:00",
                "summary": {"tracked_threads": 8},
                "thread_index": threads,
                "needs_attention": threads[:3],
                "recent_activity": threads[:2],
                "projections": {
                    "watch": [{"thread_key": "t0", "fingerprint": "x", "why": "w", "projection": "watch"}]
                },
            }),
            encoding="utf-8",
        )

    def test_latest_mail_is_a_card(self) -> None:
        from twinbox_core import cli

        self._write_pulse()
        out = cli.cmd_latest_mail()
        self.assertTrue(out["ok"])
        self.assertIn("latest", out)
        self.assertLessEqual(len(out["threads"]), 5)
        self.assertNotIn("needs_attention", out)
        self.assertNotIn("recent_activity", out)
        self.assertNotIn("projections", out)
        self.assertEqual(out["latest"]["thread_key"], "t7")
        self.assertNotIn("query_terms", out["latest"])
        self.assertNotIn("fingerprint", out["latest"])
        self.assertNotIn("query_terms", out["threads"][0])

    def test_todo_drops_fingerprint(self) -> None:
        from twinbox_core import cli

        self._write_pulse()
        out = cli.cmd_todo()
        self.assertEqual(out["count"], 3)
        self.assertNotIn("fingerprint", out["needs_attention"][0])
        self.assertNotIn("query_terms", out["needs_attention"][0])
        self.assertNotIn("fingerprint", out["projections"]["watch"][0])


if __name__ == "__main__":
    unittest.main()
