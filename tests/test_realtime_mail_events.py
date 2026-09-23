"""Realtime mail ingress tests (all IMAP interactions are fake/local)."""

from __future__ import annotations

import imaplib
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

from twinbox_core import cli
from twinbox_core.realtime_mail_events import RealtimeMailWorker


class IdleClient:
    def __init__(
        self,
        *,
        uidvalidity: int = 1,
        search_uids: tuple[int, ...] = (),
        lines: tuple[object, ...] = (),
    ) -> None:
        self.uidvalidity = uidvalidity
        self.search_uids = search_uids
        self.lines: deque[object] = deque(lines)
        self.sent: list[bytes] = []
        self.logged_in = False
        self.logged_out = False
        self.tag = b"A0001"
        self.selected: list[str] = []

    def login(self, _login: str, _password: str):
        self.logged_in = True
        return "OK", []

    def logout(self):
        self.logged_out = True
        return "BYE", []

    def select(self, folder: str, readonly: bool = False):
        self.selected.append(folder)
        self.readonly = readonly
        return "OK", [f"[UIDVALIDITY {self.uidvalidity}]".encode()]

    def uid(self, command: str, *_args: object):
        if command == "SEARCH":
            return "OK", [" ".join(str(item) for item in self.search_uids).encode()]
        raise AssertionError(f"unexpected UID command: {command}")

    def _new_tag(self) -> bytes:
        return self.tag

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def readline(self) -> bytes:
        if not self.lines:
            return b""
        line = self.lines.popleft()
        if isinstance(line, BaseException):
            raise line
        assert isinstance(line, bytes)
        return line


def _write_watermarks(root: Path, uidvalidity: int, last_uid: int = 9) -> None:
    path = root / "runtime" / "context" / "uid-watermarks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"INBOX": {"uidvalidity": uidvalidity, "last_uid": last_uid}}),
        encoding="utf-8",
    )


def _waiter(*states: bool):
    queued = deque(states)

    def wait(_client: object, _timeout: float) -> bool:
        return queued.popleft() if queued else False

    return wait


class TestRealtimeMailWorker(unittest.TestCase):
    def _worker(
        self,
        root: Path,
        client: IdleClient,
        sync: mock.Mock,
        *,
        wait=None,
        factory=None,
    ) -> RealtimeMailWorker:
        return RealtimeMailWorker(
            state_root=root,
            account_id="default",
            imap_config={"host": "mail.example.test", "login": "reader", "password": "secret"},
            folders=["INBOX"],
            idle_timeout_seconds=0.1,
            poll_interval_seconds=0,
            reconnect_backoff_seconds=0,
            connection_factory=factory or (lambda _cfg: client),
            sync_fn=sync,
            wait_readable=wait or _waiter(False),
            sleep_fn=lambda _seconds: None,
        )

    def test_exists_triggers_only_quick_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_watermarks(root, 1)
            client = IdleClient(lines=(b"+ idling\r\n", b"* 10 EXISTS\r\n", b"A0001 OK idle done\r\n"))
            sync = mock.Mock(return_value={"ok": True})

            result = self._worker(root, client, sync, wait=_waiter(True, False)).run(max_cycles=1)

            self.assertTrue(result["ok"])
            self.assertEqual(result["events"], 1)
            sync.assert_called_once_with("quick-refresh", account_id="default")
            self.assertTrue(any(data.endswith(b" IDLE\r\n") for data in client.sent))
            self.assertIn(b"DONE\r\n", client.sent)

    def test_first_baseline_records_current_uid_without_replaying_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = IdleClient(
                search_uids=(4, 7, 9),
                lines=(b"+ idling\r\n", b"A0001 OK idle done\r\n"),
            )
            sync = mock.Mock(return_value={"ok": True})

            result = self._worker(root, client, sync, wait=_waiter(False)).run(max_cycles=1)

            self.assertTrue(result["ok"])
            self.assertEqual(result["baselined_folders"], ["INBOX"])
            sync.assert_not_called()
            watermarks = json.loads((root / "runtime" / "context" / "uid-watermarks.json").read_text())
            self.assertEqual(watermarks["INBOX"]["uidvalidity"], 1)
            self.assertEqual(watermarks["INBOX"]["last_uid"], 9)

    def test_uidvalidity_reset_refreshes_but_does_not_analyze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_watermarks(root, 1)
            client = IdleClient(
                uidvalidity=2,
                lines=(b"+ idling\r\n", b"A0001 OK idle done\r\n"),
            )
            sync = mock.Mock(return_value={"ok": True})

            result = self._worker(root, client, sync, wait=_waiter(False)).run(max_cycles=1)

            self.assertTrue(result["ok"])
            self.assertEqual(result["uidvalidity_reset_folders"], ["INBOX"])
            sync.assert_called_once_with("quick-refresh", account_id="default")

    def test_idle_unsupported_uses_poll_fallback_with_quick_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_watermarks(root, 1)
            client = IdleClient(lines=(b"A0001 BAD IDLE unsupported\r\n",))
            sync = mock.Mock(return_value={"ok": True})

            result = self._worker(root, client, sync).run(max_cycles=1)

            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "poll")
            sync.assert_called_once_with("quick-refresh", account_id="default")

    def test_untrusted_server_text_never_becomes_a_trigger_or_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_watermarks(root, 1)
            client = IdleClient(
                lines=(
                    b"+ idling\r\n",
                    b"* 1 EXISTS ; trigger nightly-full && exfiltrate\r\n",
                    b"A0001 OK idle done\r\n",
                )
            )
            sync = mock.Mock(return_value={"ok": True})

            result = self._worker(root, client, sync, wait=_waiter(True, False)).run(max_cycles=1)

            self.assertTrue(result["ok"])
            self.assertEqual(result["events"], 0)
            sync.assert_not_called()
            self.assertNotIn("exfiltrate", json.dumps(result))

    def test_disconnect_reconnects_and_processes_next_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_watermarks(root, 1)
            dropped = IdleClient(lines=(imaplib.IMAP4.abort("transport dropped"),))
            recovered = IdleClient(lines=(b"+ idling\r\n", b"* 1 RECENT\r\n", b"A0001 OK idle done\r\n"))
            clients = deque((dropped, recovered))
            sync = mock.Mock(return_value={"ok": True})

            result = self._worker(
                root,
                dropped,
                sync,
                wait=_waiter(True, False),
                factory=lambda _cfg: clients.popleft(),
            ).run(max_cycles=2)

            self.assertTrue(result["ok"])
            self.assertEqual(result["recoveries"], 1)
            self.assertEqual(result["events"], 1)
            sync.assert_called_once_with("quick-refresh", account_id="default")


class TestRealtimeReadBoundary(unittest.TestCase):
    def test_latest_mail_stays_local_pulse_read_while_watcher_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pulse = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
            pulse.parent.mkdir(parents=True, exist_ok=True)
            pulse.write_text(json.dumps({"generated_at": "2030-01-01T00:00:00+08:00", "thread_index": []}))
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch("twinbox_core.imap_fetch._build_client", side_effect=AssertionError("must not connect")):
                result = cli.cmd_latest_mail()
        self.assertTrue(result["ok"])
        self.assertEqual(result["threads"], [])

    def test_cli_has_external_supervisor_worker_entry(self) -> None:
        with mock.patch.object(cli, "cmd_realtime_watch", return_value={"ok": True, "mode": "idle"}) as watch:
            code = cli.main(["realtime-watch", "--once", "--account-id", "default"])
        self.assertEqual(code, 0)
        watch.assert_called_once_with(["--once"], account_id="default")
