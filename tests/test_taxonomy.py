"""Induced taxonomy stays a draft until confirmed, and queries do not call a model."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures.taxonomy_labels import TAXONOMY_LABELS
from twinbox_core.pack import validate_pack
from twinbox_core.taxonomy import (
    WINDOWS,
    build_draft,
    classify_for_query,
    confirm,
    confirm_draft,
    drift_note,
    excerpt,
    induce,
    record_drift,
    stop_reason,
)


def _pack() -> dict:
    return validate_pack({"id": "user", "version": "1.0.0"})


class TestTaxonomyDraft(unittest.TestCase):
    def test_excerpt_is_bounded(self) -> None:
        self.assertEqual(len(excerpt("x" * 400)), 280)

    def test_draft_is_not_live_until_confirmed(self) -> None:
        draft = build_draft(
            [
                {"owner_action": "reply", "vector": [1.0, 0.0]},
                {"owner_action": "reply", "vector": [1.0, 0.0]},
                {"owner_action": "", "vector": [0.0, 1.0]},
            ]
        )
        self.assertEqual(draft["status"], "draft")
        pack = _pack()
        self.assertIsNone(classify_for_query(pack, [1.0, 0.0]))
        live = confirm_draft(pack, draft)
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(live["taxonomy"]["status"], "live")
        hit = classify_for_query(live, [1.0, 0.0])
        self.assertFalse(hit["defer"])
        self.assertTrue(hit["id"])

    def test_query_does_not_call_the_model(self) -> None:
        draft = build_draft([{"owner_action": "reply", "vector": [1.0, 0.0]}])
        live = confirm_draft(_pack(), draft)

        def _boom(*_args, **_kwargs):
            raise AssertionError("query path called embed_texts")

        with patch("twinbox_core.embeddings.embed_texts", _boom):
            classify_for_query(live, [1.0, 0.0])

    def test_close_scores_defer_without_a_model(self) -> None:
        draft = build_draft(
            [
                {"owner_action": "reply", "vector": [1.0, 0.0]},
                {"owner_action": "approve", "vector": [0.9, 0.1]},
            ]
        )
        live = confirm_draft(_pack(), draft)
        hit = classify_for_query(live, [1.0, 0.05], margin=0.5)
        self.assertTrue(hit["defer"])

    def test_stop_and_drift(self) -> None:
        self.assertEqual(stop_reason([2, 2, 2], budget_left=0), "budget")
        self.assertEqual(stop_reason([2], other_ratio=0.1), "coverage")
        self.assertEqual(stop_reason([1, 0, 1]), "stable")
        note = drift_note(["a"], ["a", "b"])
        self.assertEqual(note["added"], ["b"])
        self.assertEqual(note["removed"], [])

    def test_fixture_labels_absent_from_engine(self) -> None:
        root = Path(__file__).resolve().parents[1] / "twinbox_core"
        blob = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
        for label in TAXONOMY_LABELS:
            self.assertNotIn(label, blob)

    def test_induce_writes_draft_and_confirm_makes_query_live(self) -> None:
        import json
        import tempfile
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context"
            phase4 = root / "runtime" / "validation" / "phase-4"
            ctx.mkdir(parents=True)
            phase4.mkdir(parents=True)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            (ctx / "phase1-context.json").write_text(
                json.dumps({
                    "envelopes": [
                        {"folder": "INBOX", "id": "1", "subject": "请回复合同", "date": now},
                        {"folder": "INBOX", "id": "2", "subject": "周报", "date": now},
                    ],
                    "sampled_bodies": {},
                }),
                encoding="utf-8",
            )
            (phase4 / "pending-replies.yaml").write_text(
                "pending_replies:\n  - thread_key: 请回复合同\n    waiting_on: me\n",
                encoding="utf-8",
            )
            out = induce(root, lookback_days=7, budget=1)
            self.assertTrue(out["ok"])
            self.assertEqual(out["status"], "draft")
            self.assertEqual(out["stop"], "budget")
            self.assertIsNone(classify_for_query({"id": "user"}, [1.0, 0.0]))
            confirmed = confirm(root)
            self.assertTrue(confirmed["ok"])
            self.assertEqual(confirmed["status"], "live")
            pack_text = (root / "packs" / "user.yaml").read_text(encoding="utf-8")
            self.assertIn("status: live", pack_text)
            drift = record_drift(root)
            self.assertTrue(drift["ok"])
            self.assertEqual(drift["note"]["kind"], "taxonomy_drift")
            self.assertEqual(WINDOWS, (7, 30, 90))

    def test_onboard_triggers_a_draft(self) -> None:
        import tempfile
        from twinbox_core import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(cli, "_account_root", return_value=root):
                result = cli.main(["onboard", "--approvals", "审批", "--json"])
            self.assertEqual(result, 0)
            self.assertTrue((root / "packs" / "user.yaml").is_file())
            self.assertTrue((root / "packs" / "taxonomy-draft.yaml").is_file())

    def test_nightly_schedule_records_drift_without_replacing_live_pack(self) -> None:
        import tempfile
        from datetime import datetime
        from twinbox_core.schedule import run_due, SHANGHAI

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath("packs").mkdir()
            root.joinpath("packs", "user.yaml").write_text(
                "id: user\nversion: '1.0.0'\ntaxonomy:\n  status: live\n  categories: []\n",
                encoding="utf-8",
            )
            result = run_due(
                root,
                now=datetime(2026, 9, 8, 2, 0, tzinfo=SHANGHAI),
                sync_fn=lambda job: {"ok": True, "job": job},
            )
            nightly = next(row for row in result["ran"] if row["name"] == "nightly-full")
            self.assertTrue(nightly["taxonomy_drift"]["ok"])
            self.assertTrue((root / "runtime" / "context" / "taxonomy-drift.json").is_file())
            self.assertIn("status: live", (root / "packs" / "user.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
