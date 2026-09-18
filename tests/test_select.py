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
                picked, diag = choose_candidates(context, root, limit=2)
            ids = {row["id"] for row in picked}
            self.assertEqual(ids, {"1", "2"})
            self.assertFalse(diag["embeddings_degraded"])

    def test_hint_similarity_changes_order_for_non_floor_candidates(self) -> None:
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
                        "subject": "普通通知",
                        "date": "2026-09-08T00:00:00+08:00",
                        "id": "noise",
                        "folder": "INBOX",
                        "flags": ["Seen"],
                    },
                    {
                        "subject": "验收登记",
                        "date": "2026-09-08T00:00:00+08:00",
                        "id": "hint",
                        "folder": "INBOX",
                        "flags": ["Seen"],
                    },
                ]
            }

            def vec(_state, _folder, uid):
                return [1.0, 0.0] if uid == "hint" else [0.0, 1.0]

            with mock.patch("twinbox_core.select.embed_texts", return_value=[[1.0, 0.0]]), \
                    mock.patch("twinbox_core.select.load_vector", side_effect=vec):
                picked, diag = choose_candidates(context, root, limit=1)
            self.assertEqual([row["id"] for row in picked], ["hint"])
            self.assertFalse(diag["embeddings_degraded"])

    def test_limit_zero_returns_empty(self) -> None:
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
                "envelopes": [{
                    "subject": "验收登记",
                    "date": "2026-09-08T00:00:00+08:00",
                    "id": "1",
                    "folder": "INBOX",
                    "flags": [],
                    "recipient_role": "to",
                }]
            }
            with mock.patch("twinbox_core.select.embed_texts", return_value=[[1.0, 0.0]]), \
                    mock.patch("twinbox_core.select.load_vector", return_value=[1.0, 0.0]):
                picked, _diag = choose_candidates(context, root, limit=0)
            self.assertEqual(picked, [])

    def test_negative_limit_returns_empty_without_embedding_work(self) -> None:
        from twinbox_core.select import choose_candidates

        context = {
            "envelopes": [{
                "subject": "验收登记",
                "date": "2026-09-08T00:00:00+08:00",
                "id": "1",
                "folder": "INBOX",
                "flags": [],
                "recipient_role": "to",
            }]
        }
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("twinbox_core.select.embed_texts") as embed, \
                mock.patch("twinbox_core.select.load_vector") as load:
            picked, diag = choose_candidates(context, Path(tmp), limit=-1)
        self.assertEqual(picked, [])
        self.assertFalse(diag["embeddings_degraded"])
        embed.assert_not_called()
        load.assert_not_called()

    def test_no_hints_uses_structure_without_embedding_degraded(self) -> None:
        from twinbox_core.select import choose_candidates

        context = {
            "envelopes": [{
                "subject": "普通通知",
                "date": "2026-09-08T00:00:00+08:00",
                "id": "1",
                "folder": "INBOX",
                "flags": ["Seen"],
            }]
        }
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("twinbox_core.select.embed_texts") as embed, \
                mock.patch("twinbox_core.select.load_vector") as load:
            root = Path(tmp)
            (root / "packs").mkdir()
            (root / "packs" / "user.yaml").write_text(
                "id: user\nversion: '1'\nattention_hints: []\n",
                encoding="utf-8",
            )
            picked, diag = choose_candidates(context, root, limit=1)
        self.assertEqual([row["id"] for row in picked], ["1"])
        self.assertFalse(diag["embeddings_degraded"])
        embed.assert_not_called()
        load.assert_not_called()

    def test_empty_hint_embedding_response_degrades_to_structure(self) -> None:
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
                        "subject": "older",
                        "date": "2026-09-07T00:00:00+08:00",
                        "id": "1",
                        "folder": "INBOX",
                        "flags": ["Seen"],
                    },
                    {
                        "subject": "new direct",
                        "date": "2026-09-08T00:00:00+08:00",
                        "id": "2",
                        "folder": "INBOX",
                        "flags": [],
                        "recipient_role": "to",
                    },
                ]
            }
            with mock.patch.dict(os.environ, {
                    "TWINBOX_EMBED_URL": "http://embed.invalid",
                    "TWINBOX_EMBED_MODEL": "test",
            }), mock.patch("twinbox_core.select.embed_texts", return_value=[]):
                picked, diag = choose_candidates(context, root, limit=2)
            self.assertTrue(diag["embeddings_degraded"])
            self.assertEqual(picked[0]["id"], "2")

    def test_sidecar_read_failure_degrades_to_structure(self) -> None:
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
                        "subject": "older",
                        "date": "2026-09-07T00:00:00+08:00",
                        "id": "1",
                        "folder": "INBOX",
                        "flags": ["Seen"],
                    },
                    {
                        "subject": "new direct",
                        "date": "2026-09-08T00:00:00+08:00",
                        "id": "2",
                        "folder": "INBOX",
                        "flags": [],
                        "recipient_role": "to",
                    },
                ]
            }
            with mock.patch("twinbox_core.select.embed_texts", return_value=[[1.0, 0.0]]), \
                    mock.patch("twinbox_core.select.load_vector", side_effect=ValueError("bad sidecar")):
                picked, diag = choose_candidates(context, root, limit=2)
            self.assertTrue(diag["embeddings_degraded"])
            self.assertEqual(picked[0]["id"], "2")

    def test_recall_floor_uses_any_message_in_thread(self) -> None:
        from twinbox_core.select import choose_candidates

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packs").mkdir()
            (root / "packs" / "user.yaml").write_text(
                "id: user\nversion: '1'\nattention_hints:\n"
                "- id: h\n  utterances: [验收]\n",
                encoding="utf-8",
            )
            envelopes = [
                {
                    "subject": f"noise-{i:02d}",
                    "date": "2026-09-08T00:00:00+08:00",
                    "id": str(i),
                    "folder": "INBOX",
                    "flags": ["Seen"],
                }
                for i in range(40)
            ]
            envelopes.extend([
                {
                    "subject": "Re: 关键审批",
                    "date": "2026-09-08T00:00:00+08:00",
                    "id": "latest",
                    "folder": "INBOX",
                    "flags": ["Seen"],
                },
                {
                    "subject": "关键审批",
                    "date": "2026-09-07T00:00:00+08:00",
                    "id": "older-floor",
                    "folder": "INBOX",
                    "flags": [],
                    "recipient_role": "to",
                },
            ])

            def vec(_state, _folder, uid):
                return [0.0, 1.0] if uid == "latest" else [1.0, 0.0]

            with mock.patch("twinbox_core.select.embed_texts", return_value=[[1.0, 0.0]]), \
                    mock.patch("twinbox_core.select.load_vector", side_effect=vec):
                picked, diag = choose_candidates({"envelopes": envelopes}, root, limit=40)
            self.assertIn("latest", {row["id"] for row in picked})
            self.assertEqual(len(picked), 40)
            self.assertFalse(diag["embeddings_degraded"])

    def test_limit_one_does_not_overflow_with_recall_floor(self) -> None:
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
                        "subject": "验收登记",
                        "date": "2026-09-08T00:00:00+08:00",
                        "id": "semantic",
                        "folder": "INBOX",
                        "flags": ["Seen"],
                    },
                    {
                        "subject": "direct unread",
                        "date": "2026-09-07T00:00:00+08:00",
                        "id": "floor",
                        "folder": "INBOX",
                        "flags": [],
                        "recipient_role": "to",
                    },
                ]
            }

            def vec(_state, _folder, uid):
                return [1.0, 0.0] if uid == "semantic" else [0.0, 1.0]

            with mock.patch("twinbox_core.select.embed_texts", return_value=[[1.0, 0.0]]), \
                    mock.patch("twinbox_core.select.load_vector", side_effect=vec):
                picked, _diag = choose_candidates(context, root, limit=1)
            self.assertEqual(len(picked), 1)
            self.assertEqual(picked[0]["id"], "floor")

    def test_unread_to_survives_high_cosine_crowd(self) -> None:
        from twinbox_core.select import choose_candidates

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packs").mkdir()
            (root / "packs" / "user.yaml").write_text(
                "id: user\nversion: '1'\nattention_hints:\n"
                "- id: h\n  utterances: [验收]\n",
                encoding="utf-8",
            )
            envelopes = [
                {
                    "subject": "noise-%02d" % i,
                    "date": "2026-09-01T00:00:00+08:00",
                    "id": str(i),
                    "folder": "INBOX",
                    "flags": ["Seen"],
                }
                for i in range(40)
            ]
            envelopes.append({
                "subject": "direct unread",
                "date": "2026-09-08T00:00:00+08:00",
                "id": "floor",
                "folder": "INBOX",
                "flags": [],
                "recipient_role": "to",
            })
            hint = [1.0, 0.0]
            noise = [1.0, 0.0]
            zero = [0.0, 1.0]

            def vec(_state, _folder, uid):
                return zero if uid == "floor" else noise

            with mock.patch("twinbox_core.select.embed_texts", return_value=[hint]), \
                    mock.patch("twinbox_core.select.load_vector", side_effect=vec):
                picked, diag = choose_candidates({"envelopes": envelopes}, root, limit=40)
            ids = {row["id"] for row in picked}
            self.assertIn("floor", ids)
            self.assertEqual(len(picked), 40)
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
            self.assertEqual(result["select"]["envelope_in"], 1)
            self.assertEqual(result["select"]["envelope_llm"], 1)
            self.assertEqual(result["select"]["candidate_threads"], 1)
            self.assertTrue(result["select"]["embeddings_degraded"])
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
            self.assertEqual(result["select"]["envelope_in"], 3)
            self.assertEqual(result["select"]["envelope_llm"], 2)
            self.assertEqual(result["select"]["candidate_threads"], 1)
            self.assertFalse(result["select"]["embeddings_degraded"])

    def test_llm_timeout_still_returns_select(self) -> None:
        from twinbox_core.analyze import run_analysis
        from twinbox_core.llm import LLMError

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
            with mock.patch(
                "twinbox_core.select.choose_candidates",
                return_value=([envs[1]], {"embeddings_degraded": False}),
            ), mock.patch("twinbox_core.analyze.call_llm", side_effect=LLMError("timed out")):
                result = run_analysis(root)
            self.assertFalse(result["ok"])
            self.assertIn("timed out", result["error"])
            self.assertEqual(result["select"]["envelope_in"], 3)
            self.assertEqual(result["select"]["envelope_llm"], 2)
            err = json.loads((root / "runtime/validation/phase-4/last-analysis-error.json").read_text())
            self.assertEqual(err["select"]["envelope_llm"], 2)


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
