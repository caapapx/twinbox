"""Multi-account registry + state isolation + vault wiring."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class TestAccounts(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"TWINBOX_STATE_ROOT": str(self.root)})
        self.env.start()
        import importlib
        import twinbox_core.config as config
        import twinbox_core.vault as vault

        importlib.reload(config)
        importlib.reload(vault)
        self.config = config

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_upsert_list_resolve_isolation(self) -> None:
        r1 = self.config.upsert_account(
            account_id="personal",
            email="me@example.com",
            host="imap.example.com",
            login="me@example.com",
            password="pass-one",
            make_default=True,
        )
        self.assertTrue(r1["ok"])
        r2 = self.config.upsert_account(
            account_id="shared-ops",
            email="ops@example.com",
            account_type="shared",
            host="imap.example.com",
            login="ops@example.com",
            password="pass-two",
        )
        self.assertTrue(r2["ok"])

        rows = self.config.list_accounts()
        self.assertEqual({r["account_id"] for r in rows}, {"personal", "shared-ops"})
        for row in rows:
            self.assertTrue(row["password_set"])
            self.assertNotIn("password", row)
            self.assertNotIn("password", row.get("imap", {}))

        cfg_text = (self.root / "twinbox.json").read_text(encoding="utf-8")
        self.assertNotIn("pass-one", cfg_text)
        self.assertNotIn("pass-two", cfg_text)

        a = self.config.resolve_imap_config("personal")
        b = self.config.resolve_imap_config("shared-ops")
        self.assertEqual(a["password"], "pass-one")
        self.assertEqual(b["password"], "pass-two")
        # Only literal account_id "default" keeps legacy root layout.
        self.assertEqual(self.config.account_state_root("personal"), (self.root / "accounts" / "personal").resolve())
        self.assertEqual(self.config.account_state_root("shared-ops"), (self.root / "accounts" / "shared-ops").resolve())
        self.assertEqual(self.config.account_state_root("default"), self.root.resolve())

    def test_set_default_and_remove_fallback(self) -> None:
        self.config.upsert_account(
            account_id="personal",
            email="me@example.com",
            host="imap.example.com",
            login="me@example.com",
            password="pass-one",
            make_default=True,
        )
        self.config.upsert_account(
            account_id="shared-ops",
            email="ops@example.com",
            account_type="shared",
            host="imap.example.com",
            login="ops@example.com",
            password="pass-two",
        )
        by_id = {r["account_id"]: r for r in self.config.list_accounts()}
        self.assertTrue(by_id["personal"]["is_default"])
        self.assertFalse(by_id["shared-ops"]["is_default"])

        switched = self.config.set_default_account("shared-ops")
        self.assertTrue(switched["ok"])
        self.assertEqual(self.config.default_account_id(), "shared-ops")
        self.assertEqual(self.config.resolve_imap_config()["login"], "ops@example.com")
        self.assertEqual(
            self.config.account_state_root(None),
            (self.root / "accounts" / "shared-ops").resolve(),
        )
        cfg = json.loads((self.root / "twinbox.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["mailbox"]["imap"]["login"], "ops@example.com")
        by_id = {r["account_id"]: r for r in self.config.list_accounts()}
        self.assertTrue(by_id["shared-ops"]["is_default"])
        self.assertFalse(by_id["personal"]["is_default"])

        back = self.config.set_default_account("personal")
        self.assertTrue(back["ok"])
        self.assertEqual(self.config.default_account_id(), "personal")

        self.config.set_default_account("shared-ops")
        removed = self.config.remove_account("shared-ops")
        self.assertTrue(removed["ok"])
        self.assertEqual(self.config.default_account_id(), "personal")
        leftover = self.config.list_accounts()
        self.assertEqual(len(leftover), 1)
        self.assertTrue(leftover[0]["is_default"])
        self.assertEqual(leftover[0]["account_id"], "personal")

        missing = self.config.set_default_account("nope")
        self.assertFalse(missing["ok"])

    def test_latest_mail_source_account_follows_default(self) -> None:
        from twinbox_core import cli

        self.config.upsert_account(
            account_id="personal",
            email="me@example.com",
            host="imap.example.com",
            login="me@example.com",
            password="pass-one",
            make_default=True,
        )
        self.config.upsert_account(
            account_id="shared-ops",
            email="ops@example.com",
            account_type="shared",
            host="imap.example.com",
            login="ops@example.com",
            password="pass-two",
        )
        self.config.set_default_account("shared-ops")
        root = self.config.account_state_root(None)
        pulse = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
        pulse.parent.mkdir(parents=True, exist_ok=True)
        pulse.write_text(
            json.dumps(
                {
                    "generated_at": "2030-01-01T00:00:00+08:00",
                    "thread_index": [],
                    "needs_attention": [],
                    "projections": {},
                    "summary": {},
                    "recent_activity": [],
                }
            ),
            encoding="utf-8",
        )
        latest = cli.cmd_latest_mail()
        self.assertTrue(latest["ok"])
        self.assertEqual(latest["source_account"], "shared-ops")
        todo = cli.cmd_todo()
        self.assertEqual(todo["source_account"], "shared-ops")
        listed = cli.cmd_accounts(["list"])
        self.assertEqual(listed["default_account_id"], "shared-ops")
        switched = cli.cmd_accounts(["set-default", "personal"])
        self.assertTrue(switched["ok"])
        self.assertEqual(self.config.default_account_id(), "personal")

    def test_legacy_mailbox_compat(self) -> None:
        (self.root / "twinbox.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "mailbox": {
                        "email": "legacy@example.com",
                        "imap": {
                            "host": "imap.legacy",
                            "port": 993,
                            "encryption": "tls",
                            "login": "legacy@example.com",
                            "password": "legacy-pass",
                        },
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        rows = self.config.list_accounts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_id"], "default")
        self.assertTrue(rows[0]["password_set"])
        cfg = self.config.resolve_imap_config()
        self.assertEqual(cfg["login"], "legacy@example.com")
        self.assertEqual(cfg["password"], "legacy-pass")


if __name__ == "__main__":
    unittest.main()
