"""Local synthetic 013 read-path benchmark; no mailbox, network, or ROI claims.

The legacy comparator is the raw classification-snapshot reader that existed
before the 013 client projection.  The candidate is the 013 semantic single-case
projection. Both read the same classification snapshot from one temporary state
root after identical warm-up; unlike the activity-pulse reader, their input and
scope are therefore directly comparable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any, Callable

# Allow the documented ``python tests/evaluations/<runner>.py`` form when
# launched from the repository root; pytest already supplies this path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from twinbox_core.adapter import build_ingest_envelopes
from twinbox_core.classification_store import classification_path, load_classifications, publish_classifications
from twinbox_core.semantic_client import project_semantics


SAMPLE_COUNT = 100
WARMUP_COUNT = 3
P95_GATE_RATIO = 1.2


def p95_ms(values: list[float]) -> float:
    """Return nearest-rank p95 milliseconds so the recorded calculation is stable."""
    if not values:
        raise ValueError("cannot calculate p95 from no samples")
    ordered = sorted(values)
    return round(ordered[max(0, int(len(ordered) * 0.95 + 0.999999) - 1)] * 1000, 3)


def _summary(samples: list[float]) -> dict[str, Any]:
    if not samples:
        raise ValueError("cannot summarize no samples")
    milliseconds = [round(value * 1000, 3) for value in samples]
    return {
        "samples_ms": milliseconds,
        "min_ms": min(milliseconds),
        "median_ms": round(statistics.median(milliseconds), 3),
        "p95_ms": p95_ms(samples),
        "max_ms": max(milliseconds),
    }


def _measure(reader: Callable[[], Any], *, samples: int) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("samples must be positive")
    # Do not compare setup or first-import effects: every path gets the same warm-up.
    for _ in range(WARMUP_COUNT):
        reader()
    durations: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        reader()
        durations.append(time.perf_counter() - started)
    return _summary(durations)


def _write_fixture(root: Path, *, count: int) -> tuple[dict[str, Any], str]:
    (root / "packs").mkdir()
    (root / "packs/user.yaml").write_text(
        "id: scale\nversion: 1.0.0\nclassification:\n  event_types: []\n",
        encoding="utf-8",
    )
    cases = [
        {"case_key": f"case-{i}", "mail_refs": [f"mail-{i}"], "evidence_refs": [f"mail-{i}:e1"]}
        for i in range(count)
    ]
    classifications = [
        {"case_key": f"case-{i}", "status": "classified", "primary_event_type": "synthetic.review"}
        for i in range(count)
    ]
    started = time.perf_counter()
    published = publish_classifications(
        root, scope_id="scale-scope", cases=cases, classifications=classifications,
        coverage={"state": "synthetic-complete"}, pack_fingerprint="scale-pack",
        classifier_version="scale-v1", source_revision=1,
        observed_at="2026-09-20T00:00:00Z",
    )
    pulse = root / "runtime/validation/phase-4/activity-pulse.json"
    pulse.parent.mkdir(parents=True, exist_ok=True)
    pulse.write_text(json.dumps({
        "generated_at": "2026-09-20T00:00:00Z",
        "thread_index": [
            {"thread_key": f"thread-{i}", "latest_message_ref": f"mail-{i}"}
            for i in range(count)
        ],
    }), encoding="utf-8")
    return {"published": published, "publish_ms": round((time.perf_counter() - started) * 1000, 3)}, \
        published["active_snapshot"]["cases"][-1]["case_ref"]


def probe(count: int, *, samples: int = SAMPLE_COUNT) -> dict[str, Any]:
    """Measure frozen legacy/new readers over one equally sized synthetic fixture."""
    if count < 1:
        raise ValueError("count must be positive")
    with tempfile.TemporaryDirectory(prefix=f"twinbox-scale-{count}-") as raw:
        root = Path(raw)
        fixture, target = _write_fixture(root, count=count)
        # Baseline is intentionally the raw snapshot read: it consumes the
        # same persisted classifications as the candidate, without 013's client
        # presentation layer. Comparing it with an activity-pulse read would
        # compare different data contracts and produce a misleading ratio.
        legacy = _measure(lambda: load_classifications(root, "scale-scope"), samples=samples)
        semantic = _measure(
            lambda: project_semantics(root, scope_id="scale-scope", action="get", case_ref=target),
            samples=samples,
        )
        started = time.perf_counter()
        page = build_ingest_envelopes(root, account_id="scale-scope", limit=200)
        cursor_ms = round((time.perf_counter() - started) * 1000, 3)
        cache_files = list((root / "runtime/context/ingest-cursors").glob("*.json"))
        ratio = round(semantic["p95_ms"] / legacy["p95_ms"], 3) if legacy["p95_ms"] else None
        return {
            "schema_version": "1.1",
            "synthetic": True,
            "fixture": {
                "cases": count,
                "samples_per_path": samples,
                "warmup_per_path": WARMUP_COUNT,
                "legacy_path": "classification_store.load_classifications",
                "candidate_path": "semantic_client.project_semantics(action=get)",
                "same_state_root": True,
            },
            "publish_ms": fixture["publish_ms"],
            "snapshot_bytes": classification_path(root).stat().st_size,
            "legacy_snapshot_read": legacy,
            "semantic_get_read": semantic,
            "comparison": {
                "p95_ratio_new_over_legacy": ratio,
                "p95_gate_ratio": P95_GATE_RATIO,
                "gate": "pass" if ratio is not None and ratio <= P95_GATE_RATIO else "fail",
            },
            "cursor_first_page_ms": cursor_ms,
            "cursor_cache_bytes": sum(path.stat().st_size for path in cache_files),
            "cursor_cache_files": len(cache_files),
            "cursor_page_count": page["count"],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=SAMPLE_COUNT)
    parser.add_argument("--counts", type=int, nargs="+", default=[5_000, 20_000])
    args = parser.parse_args()
    print(json.dumps({
        "schema_version": "1.1",
        "synthetic": True,
        "results": [probe(count, samples=args.samples) for count in args.counts],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
