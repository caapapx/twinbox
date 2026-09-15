"""Vault encrypt/decrypt and no-plaintext storage."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class TestVault(unittest.TestCase):
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
        self.vault = vault

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_roundtrip_and_no_plaintext(self) -> None:
        secret = "super-secret-pass-xyz"
        self.vault.set_secret("default", "password", secret)
        self.assertEqual(self.vault.get_secret("default", "password"), secret)
        self.assertTrue(self.vault.has_secret("default", "password"))
        raw = self.vault.vault_path().read_bytes()
        self.assertNotIn(secret.encode("utf-8"), raw)
        flags = self.vault.public_secret_flags("default")
        self.assertEqual(flags, {"password_set": True})
        self.assertNotIn("password", flags)


if __name__ == "__main__":
    unittest.main()
