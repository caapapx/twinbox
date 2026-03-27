"""Tests for optional IMAP connection reuse."""

from __future__ import annotations

from twinbox_core import imap_pool


def test_pool_stats_disabled_by_default() -> None:
    st = imap_pool.pool_stats()
    assert st["enabled"] is False
    assert st["pooled"] is False


def test_reset_pool_for_tests() -> None:
    imap_pool.reset_pool_for_tests()
    imap_pool.reset_pool_for_tests()
