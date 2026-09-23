"""Contract tests for the local-only 013 read-path performance probe."""
from __future__ import annotations

import runpy
from pathlib import Path


PROBE = runpy.run_path(
    str(Path(__file__).with_name("evaluations") / "semantic_store_scale.py")
)["probe"]


def test_probe_compares_frozen_legacy_and_semantic_read_paths() -> None:
    result = PROBE(24, samples=3)

    assert result["fixture"]["cases"] == 24
    assert result["fixture"]["samples_per_path"] == 3
    assert result["legacy_snapshot_read"]["samples_ms"]
    assert len(result["legacy_snapshot_read"]["samples_ms"]) == 3
    assert len(result["semantic_get_read"]["samples_ms"]) == 3
    assert result["comparison"]["p95_ratio_new_over_legacy"] >= 0
    assert result["comparison"]["gate"] in {"pass", "fail"}
