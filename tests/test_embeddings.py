"""Embedding sidecar GC."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from twinbox_core.embeddings import prune_stale_sidecars, sidecar_path


class TestSidecarGc(unittest.TestCase):
    def test_prunes_ids_outside_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = sidecar_path(root, "INBOX", "1")
            drop = sidecar_path(root, "INBOX", "99")
            keep.parent.mkdir(parents=True)
            keep.write_text(json.dumps({"uid": "1", "vector": [0.1]}), encoding="utf-8")
            drop.write_text(json.dumps({"uid": "99", "vector": [0.2]}), encoding="utf-8")
            out = prune_stale_sidecars(root, [{"folder": "INBOX", "id": "1"}])
            self.assertEqual(out["pruned"], 1)
            self.assertTrue(keep.is_file())
            self.assertFalse(drop.is_file())

    def test_folder_names_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertNotEqual(
                sidecar_path(root, "Team/Inbox", "1"),
                sidecar_path(root, "Team_Inbox", "1"),
            )

    def test_uidvalidity_reset_invalidates_reused_active_uid_only_in_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reset = sidecar_path(root, "INBOX", "1")
            keep = sidecar_path(root, "Archive", "1")
            reset.parent.mkdir(parents=True)
            reset.write_text(json.dumps({"folder": "INBOX", "uid": "1", "vector": [0.1]}), encoding="utf-8")
            keep.write_text(json.dumps({"folder": "Archive", "uid": "1", "vector": [0.2]}), encoding="utf-8")
            out = prune_stale_sidecars(
                root,
                [
                    {"folder": "INBOX", "id": "1"},
                    {"folder": "Archive", "id": "1"},
                ],
                reset_folders={"INBOX"},
            )
            self.assertEqual(out["pruned"], 1)
            self.assertFalse(reset.exists())
            self.assertTrue(keep.is_file())

    def test_accounts_are_isolated_by_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root_a = base / "account-a"
            root_b = base / "account-b"
            stale_a = sidecar_path(root_a, "INBOX", "9")
            active_b = sidecar_path(root_b, "INBOX", "9")
            stale_a.parent.mkdir(parents=True)
            active_b.parent.mkdir(parents=True)
            stale_a.write_text("{}", encoding="utf-8")
            active_b.write_text("{}", encoding="utf-8")
            prune_stale_sidecars(root_a, [])
            self.assertFalse(stale_a.exists())
            self.assertTrue(active_b.is_file())


if __name__ == "__main__":
    unittest.main()
