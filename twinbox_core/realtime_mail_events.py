"""Supervised IMAP IDLE ingress that can only request a quick local refresh.

This module deliberately owns no daemon lifecycle.  A process supervisor invokes the
CLI entry point, while this worker reconnects only long enough to keep the mailbox
watch alive.  Raw server lines are control-plane input, never mail content or a
source of commands.
"""

from __future__ import annotations

import imaplib
import select
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .imap_fetch import (
    _build_client,
    _decode_uid_list,
    _load_json,
    _now_iso,
    _parse_uidvalidity,
    _watermarks_path,
    _write_json,
)
from .imap_utf7 import mailbox_for_wire


class IdleUnsupportedError(RuntimeError):
    """The server rejected the IDLE extension; caller must use bounded polling."""


@dataclass(frozen=True)
class BaselineResult:
    baselined_folders: tuple[str, ...]
    uidvalidity_reset_folders: tuple[str, ...]


def _default_wait_readable(client: object, timeout: float) -> bool:
    """Wait on the IMAP transport without interpreting server data."""
    sock = getattr(client, "sock", None) or getattr(client, "socket", None)
    if sock is None:
        raise OSError("imap_socket_missing")
    readable, _, _ = select.select([sock], [], [], max(0.0, timeout))
    return bool(readable)


def _is_idle_trigger(line: bytes) -> bool:
    """Accept only exact untagged EXISTS/RECENT notices, never arbitrary text."""
    parts = bytes(line or b"").strip().upper().split()
    return (
        len(parts) == 3
        and parts[0] == b"*"
        and parts[1].isdigit()
        and parts[2] in {b"EXISTS", b"RECENT"}
    )


def _max_uid(client: object) -> int:
    status, data = client.uid("SEARCH", None, "UID", "1:*")
    if status != "OK":
        raise OSError("uid_baseline_search_failed")
    uids = _decode_uid_list(data)
    return max(uids) if uids else 0


def establish_uid_baselines(
    state_root: Path,
    folders: list[str],
    client: object,
) -> BaselineResult:
    """Record a first watermark, but never replay existing mail as an event.

    A UIDVALIDITY change is intentionally *not* written here.  The following
    quick-refresh sees the old baseline, invalidates stale local rows, and rebuilds
    the local envelope window while suppressing those rebuilt rows as new work.
    """
    path = _watermarks_path(state_root)
    raw = _load_json(path, {})
    watermarks = dict(raw) if isinstance(raw, dict) else {}
    changed = False
    baselined: list[str] = []
    resets: list[str] = []

    for folder in folders:
        status, select_data = client.select(mailbox_for_wire(folder), readonly=True)
        if status != "OK":
            raise OSError("imap_select_failed")
        current_uv = _parse_uidvalidity(select_data)
        if current_uv <= 0:
            raise OSError("uidvalidity_missing")
        previous = watermarks.get(folder)
        previous = previous if isinstance(previous, dict) else {}
        try:
            previous_uv = int(previous.get("uidvalidity") or 0)
        except (TypeError, ValueError):
            previous_uv = 0

        if previous_uv == 0:
            watermarks[folder] = {
                "uidvalidity": current_uv,
                "last_uid": _max_uid(client),
                "last_sync_at": _now_iso(),
                "baseline_at": _now_iso(),
            }
            changed = True
            baselined.append(folder)
        elif previous_uv != current_uv:
            resets.append(folder)

    if changed:
        _write_json(path, watermarks)
    return BaselineResult(tuple(baselined), tuple(resets))


class RealtimeMailWorker:
    """A one-purpose supervised worker: IDLE/poll -> ``quick-refresh`` only."""

    def __init__(
        self,
        *,
        state_root: Path,
        account_id: str,
        imap_config: dict[str, Any],
        folders: list[str] | None = None,
        idle_timeout_seconds: float = 29 * 60,
        poll_interval_seconds: float = 5 * 60,
        reconnect_backoff_seconds: float = 5,
        connection_factory: Callable[[dict[str, Any]], object] | None = None,
        sync_fn: Callable[..., dict[str, Any]] | None = None,
        wait_readable: Callable[[object, float], bool] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.state_root = Path(state_root)
        self.account_id = str(account_id or "default")
        self.imap_config = dict(imap_config)
        self.folders = [str(folder) for folder in (folders or ["INBOX"]) if str(folder)] or ["INBOX"]
        self.idle_timeout_seconds = max(0.0, float(idle_timeout_seconds))
        self.poll_interval_seconds = max(0.0, float(poll_interval_seconds))
        self.reconnect_backoff_seconds = max(0.0, float(reconnect_backoff_seconds))
        self.connection_factory = connection_factory or _build_client
        if sync_fn is None:
            from .cli import cmd_sync
            sync_fn = cmd_sync
        self.sync_fn = sync_fn
        self.wait_readable = wait_readable or _default_wait_readable
        self.sleep_fn = sleep_fn or time.sleep

    def _finish_idle(self, client: object, tag: bytes) -> None:
        try:
            client.send(b"DONE\r\n")
        except Exception:
            return
        # The tagged completion may follow harmless unsolicited status lines.  Do
        # not surface any server text in results or logs.
        for _ in range(16):
            line = client.readline()
            if not line:
                return
            if bytes(line).startswith(tag):
                if b" OK" not in bytes(line).upper():
                    raise OSError("idle_finish_failed")
                return

    def _idle_for_folder(self, client: object, folder: str) -> bool:
        status, _select_data = client.select(mailbox_for_wire(folder), readonly=True)
        if status != "OK":
            raise OSError("imap_select_failed")
        tag = client._new_tag()
        if isinstance(tag, str):
            tag = tag.encode()
        client.send(tag + b" IDLE\r\n")
        continuation = client.readline()
        if not bytes(continuation).startswith(b"+"):
            # BAD/NO/non-continuation all mean the extension is not usable.  The
            # caller falls back to bounded polling; raw server text is discarded.
            raise IdleUnsupportedError("idle_rejected")

        triggered = False
        try:
            while self.wait_readable(client, self.idle_timeout_seconds):
                line = client.readline()
                if not line:
                    raise OSError("idle_connection_closed")
                if _is_idle_trigger(bytes(line)):
                    triggered = True
                    break
        finally:
            self._finish_idle(client, tag)
        return triggered

    def _quick_refresh(self) -> bool:
        result = self.sync_fn("quick-refresh", account_id=self.account_id)
        return bool(result.get("ok", True))

    def run_once(self) -> dict[str, Any]:
        client = self.connection_factory(self.imap_config)
        events = 0
        baselined: tuple[str, ...] = ()
        resets: tuple[str, ...] = ()
        mode = "idle"
        refresh_ok = True
        try:
            client.login(str(self.imap_config["login"]), str(self.imap_config["password"]))
            baseline = establish_uid_baselines(self.state_root, self.folders, client)
            baselined = baseline.baselined_folders
            resets = baseline.uidvalidity_reset_folders
            if resets:
                # fetch_incremental detects the stale UIDVALIDITY itself and
                # suppresses recreated rows from new_envelope_ids.
                refresh_ok = self._quick_refresh() and refresh_ok

            try:
                for folder in self.folders:
                    if self._idle_for_folder(client, folder):
                        events += 1
                        refresh_ok = self._quick_refresh() and refresh_ok
                        break
            except IdleUnsupportedError:
                mode = "poll"
                self.sleep_fn(self.poll_interval_seconds)
                refresh_ok = self._quick_refresh() and refresh_ok

            return {
                "ok": refresh_ok,
                "mode": mode,
                "events": events,
                "baselined_folders": list(baselined),
                "uidvalidity_reset_folders": list(resets),
            }
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def run(self, *, max_cycles: int | None = None) -> dict[str, Any]:
        """Run until an external supervisor stops the process, or for test cycles."""
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        attempts = 0
        successful_cycles = 0
        events = 0
        recoveries = 0
        mode = "idle"
        baselined: set[str] = set()
        resets: set[str] = set()
        last_ok = True

        while max_cycles is None or attempts < max_cycles:
            attempts += 1
            try:
                result = self.run_once()
            except (OSError, TimeoutError, ConnectionError, imaplib.IMAP4.abort, imaplib.IMAP4.error):
                recoveries += 1
                last_ok = False
                if max_cycles is None or attempts < max_cycles:
                    self.sleep_fn(self.reconnect_backoff_seconds)
                continue

            successful_cycles += 1
            last_ok = bool(result.get("ok", True))
            events += int(result.get("events") or 0)
            mode = str(result.get("mode") or mode)
            baselined.update(str(item) for item in result.get("baselined_folders", []) if item)
            resets.update(str(item) for item in result.get("uidvalidity_reset_folders", []) if item)

        return {
            "ok": successful_cycles > 0 and last_ok,
            "mode": mode,
            "events": events,
            "recoveries": recoveries,
            "baselined_folders": sorted(baselined),
            "uidvalidity_reset_folders": sorted(resets),
        }
