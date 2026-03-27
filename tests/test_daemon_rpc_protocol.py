"""Unit tests for daemon JSON-RPC line protocol (no subprocess / socket)."""

from __future__ import annotations

import json
from typing import Any

from twinbox_core.daemon import TWINBOX_PROTOCOL_VERSION
from twinbox_core.daemon.rpc_protocol import (
    build_jsonrpc_response,
    fold_chunks_into_first_line,
    process_rpc_line,
)


def test_fold_chunks_single_chunk() -> None:
    assert fold_chunks_into_first_line([b'{"a":1}\nrest'], 1024) == b'{"a":1}'


def test_fold_chunks_split_across_chunks() -> None:
    assert fold_chunks_into_first_line([b'{"a"', b':1}\n'], 1024) == b'{"a":1}'


def test_fold_chunks_respects_max_bytes() -> None:
    assert fold_chunks_into_first_line([b"x" * 100], 10) == b"x" * 10


def test_fold_chunks_eof_no_newline() -> None:
    assert fold_chunks_into_first_line([b"noline"], 1024) == b"noline"


def test_process_rpc_line_empty_returns_none() -> None:
    assert process_rpc_line(b"", lambda m, p: None) is None
    assert process_rpc_line(b"   \n", lambda m, p: None) is None


def test_process_rpc_line_parse_error() -> None:
    out = process_rpc_line(b"not-json\n", lambda m, p: None)
    assert out is not None
    assert out["error"]["code"] == -32700


def test_process_rpc_line_not_object() -> None:
    out = process_rpc_line(b"[1,2]\n", lambda m, p: None)
    assert out is not None
    assert out["error"]["code"] == -32600


def test_process_rpc_line_bad_jsonrpc() -> None:
    raw = json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping", "params": {}}).encode()
    out = process_rpc_line(raw, lambda m, p: None)
    assert out is not None
    assert out["error"]["code"] == -32600
    assert out["id"] == 1


def test_process_rpc_line_method_not_str() -> None:
    raw = json.dumps({"jsonrpc": "2.0", "id": 2, "method": 99, "params": {}}).encode()
    out = process_rpc_line(raw, lambda m, p: None)
    assert out is not None
    assert out["error"]["code"] == -32600


def test_process_rpc_line_params_not_object() -> None:
    raw = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": "bad"}).encode()
    out = process_rpc_line(raw, lambda m, p: None)
    assert out is not None
    assert out["error"]["code"] == -32602


def test_process_rpc_line_params_json_array_rejected() -> None:
    """Non-object params (e.g. JSON array) must be rejected; empty [] is falsy and coerces to {}."""
    raw = json.dumps({"jsonrpc": "2.0", "id": 31, "method": "ping", "params": [1, 2]}).encode()
    out = process_rpc_line(raw, lambda m, p: None)
    assert out is not None
    assert out["error"]["code"] == -32602


def test_process_rpc_line_missing_method() -> None:
    raw = json.dumps({"jsonrpc": "2.0", "id": 32, "params": {}}).encode()
    out = process_rpc_line(raw, lambda m, p: None)
    assert out is not None
    assert out["error"]["code"] == -32600


def test_process_rpc_line_dispatch_ok() -> None:
    def dispatch(method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert method == "ping"
        assert params == {}
        return {"status": "ok"}

    raw = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}}).encode()
    out = process_rpc_line(raw, dispatch)
    assert out == {
        "jsonrpc": "2.0",
        "id": 7,
        "twinbox_version": TWINBOX_PROTOCOL_VERSION,
        "result": {"status": "ok"},
    }


def test_process_rpc_line_dispatch_exception() -> None:
    def dispatch(_method: str, _params: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    raw = json.dumps({"jsonrpc": "2.0", "id": 8, "method": "x", "params": {}}).encode()
    out = process_rpc_line(raw, dispatch)
    assert out is not None
    assert out["error"]["code"] == -32603
    assert "boom" in out["error"]["message"]


def test_build_jsonrpc_response_round_trip() -> None:
    r = build_jsonrpc_response(1, result={"a": 1})
    assert r["jsonrpc"] == "2.0" and r["result"] == {"a": 1}


def test_build_jsonrpc_response_error_branch() -> None:
    r = build_jsonrpc_response(2, error={"code": -1, "message": "x"})
    assert r["jsonrpc"] == "2.0" and r["id"] == 2 and "result" not in r
    assert r["error"] == {"code": -1, "message": "x"}
