"""JSON-RPC 2.0 line framing helpers (testable without a live socket)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from typing import Any

from twinbox_core.daemon import TWINBOX_PROTOCOL_VERSION

logger = logging.getLogger(__name__)

DEFAULT_MAX_REQUEST_BYTES = 256 * 1024


def build_jsonrpc_response(
    req_id: Any,
    result: Any | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": req_id,
        "twinbox_version": TWINBOX_PROTOCOL_VERSION,
    }
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def fold_chunks_into_first_line(chunks: Iterable[bytes], max_bytes: int) -> bytes:
    """Concatenate chunks until the first ``\\n`` (excluded), EOF, or *max_bytes*."""
    buf = bytearray()
    for chunk in chunks:
        if not chunk:
            break
        if len(buf) >= max_bytes:
            break
        take = min(len(chunk), max_bytes - len(buf))
        piece = chunk[:take]
        nl = piece.find(b"\n")
        if nl >= 0:
            buf.extend(piece[:nl])
            return bytes(buf)
        buf.extend(piece)
        if len(buf) >= max_bytes:
            break
    return bytes(buf)


def process_rpc_line(
    raw: bytes,
    dispatch: Callable[[str, dict[str, Any]], Any],
    *,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
) -> dict[str, Any] | None:
    """Parse one newline-delimited JSON-RPC request and build the response dict.

    Returns ``None`` when the line is empty/whitespace (caller sends nothing).
    """
    if len(raw) > max_request_bytes:
        raw = raw[:max_request_bytes]

    if not raw.strip():
        return None

    try:
        req = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return build_jsonrpc_response(
            None,
            error={"code": -32700, "message": "Parse error", "data": str(exc)},
        )

    if not isinstance(req, dict):
        return build_jsonrpc_response(None, error={"code": -32600, "message": "Invalid Request"})

    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if req.get("jsonrpc") != "2.0":
        return build_jsonrpc_response(req_id, error={"code": -32600, "message": "Invalid Request"})
    if not isinstance(method, str):
        return build_jsonrpc_response(req_id, error={"code": -32600, "message": "Invalid method"})
    if not isinstance(params, dict):
        return build_jsonrpc_response(req_id, error={"code": -32602, "message": "Invalid params"})

    try:
        result = dispatch(method, params)
    except Exception as exc:
        logger.exception("handler error")
        return build_jsonrpc_response(req_id, error={"code": -32603, "message": str(exc)})
    return build_jsonrpc_response(req_id, result=result)
