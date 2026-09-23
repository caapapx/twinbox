"""R3 pack-declared value ranking: factors, sent-header proposals, onboarding."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from twinbox_core.onboard import answers_to_pack, propose_who_matters
from twinbox_core.pack import PackError, validate_pack
from twinbox_core.pulse import normalize_thread_key, write_activity_pulse

SHANGHAI = ZoneInfo("Asia/Shanghai")
BASELINE = {
    "recent_window": 10,
    "urgent": 40,
    "pending": 30,
    "sla_risk": 20,
    "sla_aging_48h": -25,
    "action_verb": 15,
}


def _seed(root: Path, *, subject: str = "Deploy review", tags: tuple[str, ...] = ("urgent", "pending")) -> str:
    tk = normalize_thread_key(subject)
    when = datetime.now(SHANGHAI) - timedelta(hours=2)
    env = {
        "id": "7",
        "folder": "INBOX",
        "subject": subject,
        "date": when.isoformat(timespec="seconds"),
        "flags": [],
        "from_addr": "boss@example.com",
        "recipient_role": "to",
    }
    raw_dir = root / "runtime" / "validation" / "phase-1" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "envelopes-merged.json").write_text(json.dumps([env]), encoding="utf-8")
    ctx = root / "runtime" / "context" / "phase1-context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(json.dumps({"envelopes": [env], "sampled_bodies": {}}), encoding="utf-8")
    phase4 = root / "runtime" / "validation" / "phase-4"
    phase4.mkdir(parents=True, exist_ok=True)
    if "urgent" in tags:
        (phase4 / "daily-urgent.yaml").write_text(
            f"generated_at: '2030-01-10T08:00:00+08:00'\ndaily_urgent:\n  - thread_key: '{tk}'\n"
            "    why: need reply\n",
            encoding="utf-8",
        )
    if "pending" in tags:
        (phase4 / "pending-replies.yaml").write_text(
            f"generated_at: '2030-01-10T08:00:00+08:00'\npending_replies:\n  - thread_key: '{tk}'\n"
            "    why: please reply\n",
            encoding="utf-8",
        )
    if "sla_risk" in tags:
        (phase4 / "sla-risks.yaml").write_text(
            f"generated_at: '2030-01-10T08:00:00+08:00'\nsla_risks:\n  - thread_key: '{tk}'\n"
            "    risk_description: stalled\n",
            encoding="utf-8",
        )
    return tk


def _card(payload: dict, tk: str) -> dict:
    return [c for c in payload["needs_attention"] if c["thread_key"] == tk][0]


class TestValueRankingFactors(unittest.TestCase):
    def test_no_pack_factors_keep_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed(root, tags=("urgent", "pending"))
            payload, _ = write_activity_pulse(root)
            self.assertEqual(_card(payload, tk)["score"], 10 + 40 + 30)
            self.assertEqual(payload["score_legend"], BASELINE)

    def test_pack_factor_override_changes_only_that_factor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed(root, tags=("urgent", "pending"))
            pack_dir = root / "packs"
            pack_dir.mkdir()
            (pack_dir / "user.yaml").write_text(
                "id: test\nversion: '0'\nclassification:\n  event_types: []\n  defaults:\n"
                "    broadcast: reference\nattention_hints: []\nvalue_ranking:\n  factors:\n"
                "    urgent: 50\n",
                encoding="utf-8",
            )
            payload, _ = write_activity_pulse(root)
            self.assertEqual(_card(payload, tk)["score"], 10 + 50 + 30)
            legend = payload["score_legend"]
            self.assertEqual(legend["urgent"], 50)
            self.assertEqual(legend["pending"], 30)
            self.assertEqual(legend["recent_window"], 10)
            self.assertEqual(legend["sla_risk"], 20)

    def test_action_verb_uses_pack_factor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed(root, subject="请审批 Deploy", tags=("urgent",))
            default, _ = write_activity_pulse(root)
            self.assertEqual(_card(default, tk)["score"], 10 + 40 + 15)
            pack_dir = root / "packs"
            pack_dir.mkdir()
            (pack_dir / "user.yaml").write_text(
                "id: test\nversion: '0'\nclassification:\n  event_types: []\n  defaults:\n"
                "    broadcast: reference\nattention_hints: []\nvalue_ranking:\n  factors:\n"
                "    action_verb: 5\n",
                encoding="utf-8",
            )
            updated, _ = write_activity_pulse(root)
            self.assertEqual(_card(updated, tk)["score"], 10 + 40 + 5)
            self.assertEqual(updated["score_legend"]["action_verb"], 5)


class TestProposeWhoMatters(unittest.TestCase):
    def test_ignores_missing_file(self) -> None:
        self.assertEqual(propose_who_matters(Path("/nonexistent")), [])

    def test_deterministic_counting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context"
            ctx.mkdir(parents=True)
            (ctx / "sent-headers.json").write_text(json.dumps({
                "headers": [
                    {"to": "a@x.com, b@y.com"},
                    {"to": "b@y.com"},
                    {"to": "Name <c@z.com>"},
                ]
            }), encoding="utf-8")
            self.assertEqual(propose_who_matters(root), [
                {"address": "b@y.com", "count": 2},
                {"address": "a@x.com", "count": 1},
                {"address": "c@z.com", "count": 1},
            ])


class TestOnboardingConfirmations(unittest.TestCase):
    def test_who_matters_and_pairwise_round_trip(self) -> None:
        who = ["a@x.com", "b@y.com"]
        pairs = [{"left_ref": "one", "right_ref": "two", "choice": "left"}]
        pack = answers_to_pack({"approvals": "验收"}, who_matters=who, pairwise=pairs)
        self.assertEqual(pack["who_matters"], who)
        self.assertEqual(pack["pairwise"], pairs)
        again = validate_pack(pack)
        self.assertEqual(again["who_matters"], who)
        self.assertEqual(again["pairwise"], pairs)
        raw = validate_pack({"id": "u", "who_matters": who, "pairwise": pairs})
        self.assertEqual(raw["who_matters"], who)
        self.assertEqual(raw["pairwise"], pairs)

    def test_rejects_executable_content_in_new_sections(self) -> None:
        with self.assertRaises(PackError):
            validate_pack({"id": "bad", "pairwise": [
                {"left_ref": "x", "right_ref": "y", "choice": "z", "script": "print(1)"}
            ]})
        with self.assertRaises(PackError):
            validate_pack({"id": "bad", "value_ranking": {"factors": {"urgent": "1 + 1"}}})


if __name__ == "__main__":
    unittest.main()
