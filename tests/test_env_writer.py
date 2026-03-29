"""Unit tests for twinbox_core.env_writer."""

import os
import stat
import tempfile
from pathlib import Path

import pytest

from twinbox_core.env_writer import (
    load_env_file,
    mask_secret,
    merge_env_file,
    write_env_file,
)


# --- mask_secret ---

def test_mask_secret_long():
    assert mask_secret("sk-abcdef1234") == "***...1234"


def test_mask_secret_short():
    assert mask_secret("abc") == "***"
    assert mask_secret("") == "***"
    assert mask_secret("12345") == "***"


def test_mask_secret_exactly_six():
    # len=6: last 4 chars are "3456", first 2 are "12"
    assert mask_secret("123456") == "***...3456"


# --- load_env_file ---

def test_load_env_file_basic(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO=bar\nBAZ=qux\n")
    assert load_env_file(p) == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# This is a comment\nFOO=bar\n# Another comment\n")
    assert load_env_file(p) == {"FOO": "bar"}


def test_load_env_file_export_prefix(tmp_path):
    p = tmp_path / ".env"
    p.write_text("export FOO=bar\nexport BAZ=qux\n")
    assert load_env_file(p) == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_file_double_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text('FOO="bar baz"\n')
    assert load_env_file(p) == {"FOO": "bar baz"}


def test_load_env_file_single_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO='bar baz'\n")
    assert load_env_file(p) == {"FOO": "bar baz"}


def test_load_env_file_not_exists(tmp_path):
    p = tmp_path / "nonexistent.env"
    assert load_env_file(p) == {}


def test_load_env_file_skips_no_equals(tmp_path):
    p = tmp_path / ".env"
    p.write_text("JUSTKEY\nFOO=bar\n")
    assert load_env_file(p) == {"FOO": "bar"}


def test_load_env_file_empty_value(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO=\n")
    assert load_env_file(p) == {"FOO": ""}


# --- merge_env_file ---

def test_merge_env_file_preserves_existing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("EXISTING=keep\nFOO=old\n")
    result = merge_env_file(p, {"FOO": "new"})
    assert result["EXISTING"] == "keep"
    assert result["FOO"] == "new"


def test_merge_env_file_adds_new_key(tmp_path):
    p = tmp_path / ".env"
    p.write_text("EXISTING=keep\n")
    result = merge_env_file(p, {"NEW_KEY": "value"})
    assert result["EXISTING"] == "keep"
    assert result["NEW_KEY"] == "value"


def test_merge_env_file_new_file(tmp_path):
    p = tmp_path / "nonexistent.env"
    result = merge_env_file(p, {"KEY": "val"})
    assert result == {"KEY": "val"}


# --- write_env_file ---

def test_write_env_file_basic(tmp_path):
    p = tmp_path / "secrets.env"
    write_env_file(p, {"FOO": "bar", "BAZ": "qux"})
    content = p.read_text()
    assert "FOO=bar" in content
    assert "BAZ=qux" in content


def test_write_env_file_permissions(tmp_path):
    p = tmp_path / "secrets.env"
    write_env_file(p, {"KEY": "val"})
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600


def test_write_env_file_quotes_values_with_spaces(tmp_path):
    p = tmp_path / "secrets.env"
    write_env_file(p, {"FOO": "hello world"})
    content = p.read_text()
    assert '"hello world"' in content


def test_write_env_file_round_trip(tmp_path):
    p = tmp_path / "secrets.env"
    original = {"IMAP_HOST": "imap.gmail.com", "IMAP_PORT": "993", "IMAP_PASS": "app_secret"}
    write_env_file(p, original)
    loaded = load_env_file(p)
    assert loaded == original


def test_write_env_file_atomic(tmp_path):
    """File should not have tmp files left over."""
    p = tmp_path / "secrets.env"
    write_env_file(p, {"KEY": "val"})
    remaining = list(tmp_path.iterdir())
    assert len(remaining) == 1
    assert remaining[0].name == "secrets.env"


def test_write_env_file_creates_parent_dirs(tmp_path):
    p = tmp_path / "deep" / "nested" / "secrets.env"
    write_env_file(p, {"KEY": "val"})
    assert p.exists()
