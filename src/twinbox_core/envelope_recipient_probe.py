"""Probe envelope JSON for protocol-layer recipient fields (To/Cc/List-Id).

Used by `scripts/verify_envelope_recipient_fields.sh` to validate what Himalaya
actually returns before wiring envelope-based `recipient_role`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def normalize_addr_field(field: Any) -> list[dict[str, str]]:
    """Normalize Himalaya-style to/cc: missing, single dict, or list of dicts."""
    if field is None:
        return []
    if isinstance(field, dict):
        addr = str(field.get("addr") or field.get("email") or "").strip()
        name = str(field.get("name") or "").strip()
        if addr or name:
            return [{"addr": addr.lower() if addr else "", "name": name}]
        return []
    if isinstance(field, list):
        out: list[dict[str, str]] = []
        for item in field:
            if isinstance(item, dict):
                addr = str(item.get("addr") or item.get("email") or "").strip()
                name = str(item.get("name") or "").strip()
                if addr or name:
                    out.append({"addr": addr.lower() if addr else "", "name": name})
        return out
    return []


def _norm_key(k: str) -> str:
    return str(k).lower().replace("-", "_")


def has_header_like_key(envelope: dict[str, Any], canonical: str) -> bool:
    """True if envelope has a key matching canonical (e.g. list_id / List-Id)."""
    want = _norm_key(canonical)
    for key in envelope:
        if _norm_key(str(key)) == want:
            return True
    return False


def summarize_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    to_entries = normalize_addr_field(envelope.get("to"))
    cc_entries = normalize_addr_field(envelope.get("cc"))
    return {
        "id": str(envelope.get("id", "")),
        "subject_preview": (str(envelope.get("subject", "")) or "")[:80],
        "top_level_keys": sorted(envelope.keys()),
        "to_entry_count": len(to_entries),
        "cc_entry_count": len(cc_entries),
        "to_addrs": [x["addr"] for x in to_entries if x["addr"]],
        "cc_addrs": [x["addr"] for x in cc_entries if x["addr"]],
        "has_list_id_key": has_header_like_key(envelope, "list_id"),
    }


def load_envelope_array(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected JSON array in {path}")
    return [x for x in raw if isinstance(x, dict)]


def fetch_live_envelopes(
    *,
    himalaya_bin: str,
    config: Path,
    account: str,
    folder: str,
    page_size: int,
) -> list[dict[str, Any]]:
    cmd = [
        himalaya_bin,
        "-c",
        str(config),
        "envelope",
        "list",
        "--account",
        account,
        "--folder",
        folder,
        "--page",
        "1",
        "--page-size",
        str(page_size),
        "--output",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"himalaya failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    data = json.loads(proc.stdout)
    if not isinstance(data, list):
        raise ValueError("Expected JSON array from himalaya envelope list")
    return [x for x in data if isinstance(x, dict)]


def print_report(envelopes: list[dict[str, Any]], limit: int) -> None:
    print(f"Envelopes: {len(envelopes)} (showing first {min(limit, len(envelopes))})")
    print()
    for i, env in enumerate(envelopes[:limit]):
        s = summarize_envelope(env)
        print(f"--- [{i}] id={s['id']!r} subject={s['subject_preview']!r}")
        print(f"    keys: {', '.join(s['top_level_keys'])}")
        print(
            f"    to: count={s['to_entry_count']} addrs={s['to_addrs']!r} | "
            f"cc: count={s['cc_entry_count']} addrs={s['cc_addrs']!r}"
        )
        print(f"    list_id-like key present: {s['has_list_id_key']}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect envelope JSON for To/Cc fields (Himalaya / envelopes-merged.json)."
    )
    parser.add_argument(
        "--json-file",
        type=Path,
        help="Path to envelopes-merged.json (array) or any JSON array of envelopes",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run himalaya envelope list (requires network + credentials)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Himalaya config.toml (default: state runtime/himalaya/config.toml)",
    )
    parser.add_argument("--account", default="", help="MAIL_ACCOUNT_NAME")
    parser.add_argument("--folder", default="INBOX", help="IMAP folder")
    parser.add_argument(
        "--himalaya-bin",
        default="himalaya",
        help="himalaya executable name or path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max envelopes to print",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=5,
        help="With --live, envelope list page size",
    )
    args = parser.parse_args(argv)

    if args.live:
        config = args.config
        if config is None:
            sr = os.environ.get("TWINBOX_STATE_ROOT") or os.environ.get("TWINBOX_CANONICAL_ROOT")
            if sr:
                config = Path(sr) / "runtime/himalaya/config.toml"
        if config is None or not config.is_file():
            print("error: --live requires --config pointing to himalaya config.toml", file=sys.stderr)
            return 2
        account = args.account or ""
        if not account:
            print("error: --live requires --account (MAIL_ACCOUNT_NAME)", file=sys.stderr)
            return 2
        try:
            envelopes = fetch_live_envelopes(
                himalaya_bin=args.himalaya_bin,
                config=config,
                account=account,
                folder=args.folder,
                page_size=max(1, args.page_size),
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print_report(envelopes, args.limit)
        return 0

    if args.json_file:
        try:
            envelopes = load_envelope_array(args.json_file)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print_report(envelopes, args.limit)
        return 0

    parser.print_help()
    print("\nProvide --json-file PATH or --live (with --config and --account).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
