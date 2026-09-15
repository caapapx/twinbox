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
