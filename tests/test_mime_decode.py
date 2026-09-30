"""MIME decode regression (no IMAP)."""

from __future__ import annotations

import unittest
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from twinbox_core.imap_fetch import decode_message_bytes


def _gb2312_multipart() -> bytes:
    msg = MIMEMultipart()
    msg["Subject"] = "请登记处理"
    msg["From"] = "boss@example.com"
    body = MIMEText("请尽快完成验收登记。", "plain", "gb2312")
    msg.attach(body)
    attach = MIMEText("fake-bytes", "plain", "utf-8")
    attach.add_header("Content-Disposition", "attachment", filename="note.txt")
    msg.attach(attach)
    return msg.as_bytes()


class TestMimeDecode(unittest.TestCase):
    def test_gb2312_readable_no_mime_residue(self) -> None:
        decoded = decode_message_bytes(_gb2312_multipart())
        self.assertIn("验收登记", decoded["body_text"])
        self.assertNotIn("Content-Type", decoded["body_text"])
        names = [a["filename"] for a in decoded["attachments"]]
        self.assertTrue(any("note" in n for n in names))

    def test_gbk_mislabelled_as_latin1_still_readable(self) -> None:
        from twinbox_core.imap_fetch import _decode_charset

        raw = "请各位领导审阅同步方案。".encode("gbk")
        text, enc = _decode_charset(raw, "latin-1")
        self.assertIn("领导", text)
        self.assertIn("同步", text)
        self.assertEqual(enc, "gb18030")

    def test_html_only(self) -> None:
        msg = EmailMessage()
        msg["Subject"] = "html"
        msg.set_content("<p>你好</p>", subtype="html", charset="utf-8")
        decoded = decode_message_bytes(msg.as_bytes())
        self.assertIn("你好", decoded["body_text"])
        self.assertNotIn("<p>", decoded["body_text"])


if __name__ == "__main__":
    unittest.main()
