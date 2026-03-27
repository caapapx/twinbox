from __future__ import annotations

import unittest

from twinbox_core.mail_env_contract import (
    OPENCLAW_ENV_KEYS,
    OPENCLAW_IMAP_SMTP_ENV_KEYS,
    OPENCLAW_OPTIONAL_MAIL_KEYS,
    OPENCLAW_REQUIRES_ENV_KEYS,
    missing_required_mail_values,
)


class MailEnvContractTest(unittest.TestCase):
    def test_requires_matches_skill_metadata_order(self) -> None:
        # SKILL.md metadata.openclaw.requires.env (keep in sync when SKILL changes)
        skill_requires = (
            "IMAP_HOST",
            "IMAP_PORT",
            "IMAP_LOGIN",
            "IMAP_PASS",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_LOGIN",
            "SMTP_PASS",
            "MAIL_ADDRESS",
        )
        self.assertEqual(OPENCLAW_REQUIRES_ENV_KEYS, skill_requires)

    def test_imap_smtp_subset(self) -> None:
        self.assertEqual(
            OPENCLAW_IMAP_SMTP_ENV_KEYS,
            OPENCLAW_REQUIRES_ENV_KEYS[:-1],
        )
        self.assertEqual(OPENCLAW_REQUIRES_ENV_KEYS[-1], "MAIL_ADDRESS")

    def test_openclaw_env_keys_concatenation(self) -> None:
        self.assertEqual(
            OPENCLAW_ENV_KEYS,
            OPENCLAW_REQUIRES_ENV_KEYS + OPENCLAW_OPTIONAL_MAIL_KEYS,
        )

    def test_missing_required_mail_values(self) -> None:
        self.assertEqual(
            missing_required_mail_values({"IMAP_HOST": "h", "MAIL_ADDRESS": ""}),
            ["IMAP_PORT", "IMAP_LOGIN", "IMAP_PASS", "SMTP_HOST", "SMTP_PORT", "SMTP_LOGIN", "SMTP_PASS", "MAIL_ADDRESS"],
        )
        self.assertEqual(missing_required_mail_values({k: "x" for k in OPENCLAW_REQUIRES_ENV_KEYS}), [])


if __name__ == "__main__":
    unittest.main()
