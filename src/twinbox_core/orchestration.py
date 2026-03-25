"""Shared orchestration contract for local CLI execution."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from twinbox_core.daytime_slice import DaytimeSliceError, write_activity_pulse
from twinbox_core.openclaw_bridge import OpenClawBridgeError, poll_openclaw_bridge
from twinbox_core.paths import PathResolutionError, resolve_existing_dir, resolve_state_root


@dataclass(frozen=True)
class StepContract:
    """One runnable step inside a phase."""

    id: str
    label: str
    script_path: str
    outputs: tuple[str, ...]
    notes: str | None = None

    def argv(self, code_root: Path) -> list[str]:
        return ["bash", str(code_root / self.script_path)]

    def payload(self, code_root: Path) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "script": self.script_path,
            "argv": self.argv(code_root),
            "outputs": list(self.outputs),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class PhaseContract:
    """Shared metadata for one pipeline phase."""

    number: int
    slug: str
    title: str
    depends_on: tuple[int, ...]
    required_artifacts: tuple[str, ...]
    produced_artifacts: tuple[str, ...]
    loading: StepContract
    thinking: StepContract
    parallel_thinking: StepContract | None = None

    def selected_steps(self, *, serial_phase4: bool) -> list[StepContract]:
        steps = [self.loading]
        if self.number == 4 and not serial_phase4 and self.parallel_thinking is not None:
            steps.append(self.parallel_thinking)
        else:
            steps.append(self.thinking)
        return steps

    def payload(self, code_root: Path, *, serial_phase4: bool) -> dict[str, object]:
        return {
            "number": self.number,
            "slug": self.slug,
            "title": self.title,
            "depends_on": list(self.depends_on),
            "required_artifacts": list(self.required_artifacts),
            "produced_artifacts": list(self.produced_artifacts),
            "default_mode": "serial" if self.number != 4 or serial_phase4 else "parallel",
            "steps": [step.payload(code_root) for step in self.selected_steps(serial_phase4=serial_phase4)],
            "alternative_steps": (
                []
                if self.number != 4 or self.parallel_thinking is None
                else [self.parallel_thinking.payload(code_root), self.thinking.payload(code_root)]
            ),
        }


@dataclass(frozen=True)
class ScheduledJob:
    """Host-scheduler job mapped from OpenClaw/system events."""

    id: str
    label: str
    description: str
    archive_on_success: bool
    updates_dedupe: bool


@dataclass(frozen=True)
class BridgeEvent:
    """Parsed Twinbox host-bridge event text."""

    kind: str
    version: int
    job_id: str
    event_source: str
    top_k: int
    retry_once: bool
    raw_text: str


PHASE_CONTRACTS: tuple[PhaseContract, ...] = (
    PhaseContract(
        number=1,
        slug="phase1",
        title="Intent Classification",
        depends_on=(),
        required_artifacts=(),
        produced_artifacts=(
            "runtime/context/phase1-context.json",
            "runtime/validation/phase-1/intent-classification.json",
            "docs/validation/phase-1-report.md",
        ),
        loading=StepContract(
            id="loading",
            label="Phase 1 Loading",
            script_path="scripts/phase1_loading.sh",
            outputs=("runtime/context/phase1-context.json",),
        ),
        thinking=StepContract(
            id="thinking",
            label="Phase 1 Thinking",
            script_path="scripts/phase1_thinking.sh",
            outputs=(
                "runtime/validation/phase-1/intent-classification.json",
                "docs/validation/phase-1-report.md",
            ),
        ),
    ),
    PhaseContract(
        number=2,
        slug="phase2",
        title="Persona Inference",
        depends_on=(1,),
        required_artifacts=(
            "runtime/context/phase1-context.json",
            "runtime/validation/phase-1/intent-classification.json",
        ),
        produced_artifacts=(
            "runtime/validation/phase-2/context-pack.json",
            "runtime/validation/phase-2/persona-hypotheses.yaml",
            "runtime/validation/phase-2/business-hypotheses.yaml",
            "docs/validation/phase-2-report.md",
        ),
        loading=StepContract(
            id="loading",
            label="Phase 2 Loading",
            script_path="scripts/phase2_loading.sh",
            outputs=("runtime/validation/phase-2/context-pack.json",),
        ),
        thinking=StepContract(
            id="thinking",
            label="Phase 2 Thinking",
            script_path="scripts/phase2_thinking.sh",
            outputs=(
                "runtime/validation/phase-2/persona-hypotheses.yaml",
                "runtime/validation/phase-2/business-hypotheses.yaml",
                "docs/validation/phase-2-report.md",
            ),
        ),
    ),
    PhaseContract(
        number=3,
        slug="phase3",
        title="Lifecycle Modeling",
        depends_on=(1, 2),
        required_artifacts=(
            "runtime/validation/phase-1/intent-classification.json",
            "runtime/validation/phase-2/persona-hypotheses.yaml",
            "runtime/validation/phase-2/business-hypotheses.yaml",
        ),
        produced_artifacts=(
            "runtime/validation/phase-3/context-pack.json",
            "runtime/validation/phase-3/lifecycle-model.yaml",
            "runtime/validation/phase-3/thread-stage-samples.json",
            "docs/validation/phase-3-report.md",
        ),
        loading=StepContract(
            id="loading",
            label="Phase 3 Loading",
            script_path="scripts/phase3_loading.sh",
            outputs=("runtime/validation/phase-3/context-pack.json",),
        ),
        thinking=StepContract(
            id="thinking",
            label="Phase 3 Thinking",
            script_path="scripts/phase3_thinking.sh",
            outputs=(
                "runtime/validation/phase-3/lifecycle-model.yaml",
                "runtime/validation/phase-3/thread-stage-samples.json",
                "docs/validation/phase-3-report.md",
            ),
        ),
    ),
    PhaseContract(
        number=4,
        slug="phase4",
        title="Value Outputs",
        depends_on=(1, 2, 3),
        required_artifacts=(
            "runtime/validation/phase-1/intent-classification.json",
            "runtime/validation/phase-2/persona-hypotheses.yaml",
            "runtime/validation/phase-3/lifecycle-model.yaml",
        ),
        produced_artifacts=(
            "runtime/validation/phase-4/context-pack.json",
            "runtime/validation/phase-4/daily-urgent.yaml",
            "runtime/validation/phase-4/pending-replies.yaml",
            "runtime/validation/phase-4/sla-risks.yaml",
            "runtime/validation/phase-4/weekly-brief.md",
        ),
        loading=StepContract(
            id="loading",
            label="Phase 4 Loading",
            script_path="scripts/phase4_loading.sh",
            outputs=("runtime/validation/phase-4/context-pack.json",),
        ),
        thinking=StepContract(
            id="thinking",
            label="Phase 4 Thinking",
            script_path="scripts/phase4_thinking.sh",
            outputs=(
                "runtime/validation/phase-4/daily-urgent.yaml",
                "runtime/validation/phase-4/pending-replies.yaml",
                "runtime/validation/phase-4/sla-risks.yaml",
                "runtime/validation/phase-4/weekly-brief.md",
            ),
            notes="Single-process fallback that runs all value outputs in one pass.",
        ),
        parallel_thinking=StepContract(
            id="parallel-thinking",
            label="Phase 4 Thinking (parallel)",
            script_path="scripts/phase4_thinking_parallel.sh",
            outputs=(
                "runtime/validation/phase-4/daily-urgent.yaml",
                "runtime/validation/phase-4/pending-replies.yaml",
                "runtime/validation/phase-4/sla-risks.yaml",
                "runtime/validation/phase-4/weekly-brief.md",
            ),
            notes="Default local mode: fan out urgent/sla/brief, then merge.",
        ),
    ),
)

CLI_ENTRYPOINT = "scripts/twinbox_orchestrate.sh"
LEGACY_ENTRYPOINT = "scripts/run_pipeline.sh"
SCHEDULED_JOBS: tuple[ScheduledJob, ...] = (
    ScheduledJob(
        id="daytime-sync",
        label="Daytime Sync",
        description="Refresh lightweight daytime truth and emit activity pulse for hourly push.",
        archive_on_success=False,
        updates_dedupe=True,
    ),
    ScheduledJob(
        id="nightly-full",
        label="Nightly Full Refresh",
        description="Run the full pipeline and archive refreshed value artifacts.",
        archive_on_success=True,
        updates_dedupe=False,
    ),
    ScheduledJob(
        id="friday-weekly",
        label="Friday Weekly Refresh",
        description="Run the full pipeline for the formal weekly brief and archive the snapshot.",
        archive_on_success=True,
        updates_dedupe=False,
    ),
)


class OrchestrationError(RuntimeError):
    """Raised when the orchestration contract cannot be executed."""


def _default_code_root() -> Path:
    override = os.environ.get("TWINBOX_CODE_ROOT")
    if override:
        return resolve_existing_dir(override)
    # orchestration.py lives at <code_root>/src/twinbox_core/orchestration.py
    return resolve_existing_dir(Path(__file__).resolve().parents[2])


def resolve_roots(code_root_override: str | None = None) -> tuple[Path, Path]:
    code_root = resolve_existing_dir(code_root_override) if code_root_override else _default_code_root()
    state_root = resolve_state_root(code_root)
    return code_root, state_root


def get_phase_contract(number: int) -> PhaseContract:
    for contract in PHASE_CONTRACTS:
        if contract.number == number:
            return contract
    raise OrchestrationError(f"Unknown phase: {number}")


def selected_phase_contracts(phase: int | None) -> list[PhaseContract]:
    if phase is None:
        return list(PHASE_CONTRACTS)
    return [get_phase_contract(phase)]


def get_scheduled_job(job_id: str) -> ScheduledJob:
    for job in SCHEDULED_JOBS:
        if job.id == job_id:
            return job
    raise OrchestrationError(f"Unknown scheduled job: {job_id}")


def contract_payload(
    code_root: Path,
    state_root: Path,
    *,
    phase: int | None,
    serial_phase4: bool,
) -> dict[str, object]:
    phases = [contract.payload(code_root, serial_phase4=serial_phase4) for contract in selected_phase_contracts(phase)]
    return {
        "code_root": str(code_root),
        "state_root": str(state_root),
        "entrypoints": {
            "cli": CLI_ENTRYPOINT,
            "legacy_fallback": LEGACY_ENTRYPOINT,
        },
        "phases": phases,
    }


def render_contract_text(
    code_root: Path,
    state_root: Path,
    *,
    phase: int | None,
    serial_phase4: bool,
) -> str:
    payload = contract_payload(code_root, state_root, phase=phase, serial_phase4=serial_phase4)
    lines = [
        "Twinbox Orchestration Contract",
        f"code_root: {payload['code_root']}",
        f"state_root: {payload['state_root']}",
        f"cli: {CLI_ENTRYPOINT}",
        f"legacy_fallback: {LEGACY_ENTRYPOINT}",
        "",
    ]
    for phase_data in payload["phases"]:
        lines.append(f"Phase {phase_data['number']} - {phase_data['title']}")
        lines.append(f"  depends_on: {phase_data['depends_on'] or '[]'}")
        lines.append(f"  required_artifacts: {len(phase_data['required_artifacts'])}")
        lines.append(f"  produced_artifacts: {len(phase_data['produced_artifacts'])}")
        lines.append(f"  default_mode: {phase_data['default_mode']}")
        for step in phase_data["steps"]:
            lines.append(f"  - {step['label']}: {shlex.join(step['argv'])}")
        lines.append("")
    return "\n".join(lines).rstrip()


def run_steps(
    code_root: Path,
    state_root: Path,
    *,
    phase: int | None,
    dry_run: bool,
    serial_phase4: bool,
) -> int:
    env = os.environ.copy()
    env["TWINBOX_CODE_ROOT"] = str(code_root)
    env["TWINBOX_STATE_ROOT"] = str(state_root)
    env["TWINBOX_CANONICAL_ROOT"] = str(state_root)

    for contract in selected_phase_contracts(phase):
        for step in contract.selected_steps(serial_phase4=serial_phase4):
            argv = step.argv(code_root)
            if dry_run:
                print(f"[dry-run] {step.label}: {shlex.join(argv)}")
                continue

            print(f"=== {step.label} ===")
            completed = subprocess.run(argv, env=env, check=False)
            if completed.returncode != 0:
                return completed.returncode
            print("")

    if not dry_run:
        print("=== Pipeline complete ===")
    return 0


def _schedule_lock_path(state_root: Path) -> Path:
    return state_root / "runtime" / "tmp" / "schedule.lock"


def _schedule_log_path(state_root: Path) -> Path:
    return state_root / "runtime" / "audit" / "schedule-runs.jsonl"


def _phase4_dir(state_root: Path) -> Path:
    return state_root / "runtime" / "validation" / "phase-4"


def _phase1_raw_dir(state_root: Path) -> Path:
    return state_root / "runtime" / "validation" / "phase-1" / "raw"


def _archive_root(state_root: Path) -> Path:
    return state_root / "runtime" / "archive" / "phase-4"


def _timestamp_slug() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S")


def _scheduled_job_steps(job: ScheduledJob, code_root: Path) -> list[tuple[str, list[str]]]:
    if job.id == "daytime-sync":
        return [
            (
                "Phase 1 Loading (daytime)",
                ["bash", str(code_root / "scripts/phase1_loading.sh"), "--sample-body-count", "30"],
            )
        ]

    steps: list[tuple[str, list[str]]] = []
    for contract in selected_phase_contracts(None):
        for step in contract.selected_steps(serial_phase4=False):
            steps.append((step.label, step.argv(code_root)))
    return steps


def _run_scheduled_steps(
    steps: list[tuple[str, list[str]]],
    *,
    env: dict[str, str],
    dry_run: bool,
) -> tuple[int, list[dict[str, object]]]:
    results: list[dict[str, object]] = []
    for label, argv in steps:
        if dry_run:
            results.append({"label": label, "argv": argv, "returncode": 0})
            continue

        completed = subprocess.run(argv, env=env, check=False, capture_output=True, text=True)
        result = {
            "label": label,
            "argv": argv,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        results.append(result)
        if completed.returncode != 0:
            return completed.returncode, results
    return 0, results


def parse_bridge_event_text(text: str) -> BridgeEvent:
    """Parse OpenClaw/system-event text into a scheduled Twinbox job."""
    raw_text = text.strip()
    if not raw_text:
        raise OrchestrationError("Bridge event text is empty.")

    if raw_text.startswith("{"):
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise OrchestrationError(f"Invalid bridge event JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise OrchestrationError("Bridge event JSON must be an object.")
        if payload.get("kind") != "twinbox.schedule":
            raise OrchestrationError("Bridge event JSON kind must be `twinbox.schedule`.")
        job_id = str(payload.get("job", "")).strip()
        if not job_id:
            raise OrchestrationError("Bridge event JSON is missing `job`.")
        top_k = payload.get("top_k", 3)
        if not isinstance(top_k, int) or top_k <= 0:
            raise OrchestrationError("Bridge event `top_k` must be a positive integer.")
        return BridgeEvent(
            kind="twinbox.schedule",
            version=int(payload.get("version", 1)),
            job_id=job_id,
            event_source=str(payload.get("event_source", "openclaw.system-event")).strip() or "openclaw.system-event",
            top_k=top_k,
            retry_once=bool(payload.get("retry_once", True)),
            raw_text=raw_text,
        )

    for prefix in ("twinbox.schedule:", "twinbox.schedule "):
        if raw_text.startswith(prefix):
            job_id = raw_text[len(prefix):].strip()
            if not job_id:
                raise OrchestrationError("Bridge event text is missing a job id.")
            return BridgeEvent(
                kind="twinbox.schedule",
                version=1,
                job_id=job_id,
                event_source="openclaw.system-event",
                top_k=3,
                retry_once=True,
                raw_text=raw_text,
            )

    raise OrchestrationError(
        "Unrecognized bridge event text. Use JSON "
        "`{\"kind\":\"twinbox.schedule\",\"job\":\"daytime-sync\"}` "
        "or compact `twinbox.schedule:daytime-sync`."
    )


def dispatch_bridge_event(
    code_root: Path,
    state_root: Path,
    *,
    event_text: str,
    dry_run: bool,
) -> tuple[int, dict[str, object]]:
    """Dispatch one host-bridge event into the scheduled job surface."""
    event = parse_bridge_event_text(event_text)
    exit_code, payload = run_scheduled_job(
        code_root,
        state_root,
        job_id=event.job_id,
        event_source=event.event_source,
        dry_run=dry_run,
        top_k=event.top_k,
        retry_once=event.retry_once,
    )
    return exit_code, {
        "bridge_event": {
            "kind": event.kind,
            "version": event.version,
            "job": event.job_id,
            "event_source": event.event_source,
            "top_k": event.top_k,
            "retry_once": event.retry_once,
            "raw_text": event.raw_text,
        },
        "schedule": payload,
    }


def poll_bridge_events(
    code_root: Path,
    state_root: Path,
    *,
    dry_run: bool,
    limit: int,
    openclaw_bin: str,
) -> tuple[int, dict[str, object]]:
    """Poll OpenClaw cron runs and dispatch newly finished Twinbox bridge events."""

    def _dispatch(event_text: str, poll_dry_run: bool) -> tuple[int, dict[str, object]]:
        return dispatch_bridge_event(
            code_root,
            state_root,
            event_text=event_text,
            dry_run=poll_dry_run,
        )

    return poll_openclaw_bridge(
        state_root,
        dry_run=dry_run,
        limit=limit,
        openclaw_bin=openclaw_bin,
        dispatch_event=_dispatch,
    )


def _append_schedule_log(state_root: Path, record: dict[str, object]) -> Path:
    path = _schedule_log_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _archive_schedule_snapshot(
    state_root: Path,
    *,
    job: ScheduledJob,
    run_id: str,
    include_failure_snapshot: bool,
) -> str | None:
    if not include_failure_snapshot and not job.archive_on_success:
        return None

    root = _archive_root(state_root) / f"{_timestamp_slug()}-{job.id}-{run_id[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    phase4_dir = _phase4_dir(state_root)
    if phase4_dir.is_dir():
        shutil.copytree(phase4_dir, root / "phase-4", dirs_exist_ok=True)

    if include_failure_snapshot:
        phase1_raw_dir = _phase1_raw_dir(state_root)
        if phase1_raw_dir.is_dir():
            shutil.copytree(phase1_raw_dir, root / "phase-1-raw", dirs_exist_ok=True)

    return str(root)


def _with_schedule_lock(state_root: Path):
    lock_path = _schedule_lock_path(state_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def run_scheduled_job(
    code_root: Path,
    state_root: Path,
    *,
    job_id: str,
    event_source: str,
    dry_run: bool,
    top_k: int,
    retry_once: bool,
) -> tuple[int, dict[str, object]]:
    job = get_scheduled_job(job_id)
    env = os.environ.copy()
    env["TWINBOX_CODE_ROOT"] = str(code_root)
    env["TWINBOX_STATE_ROOT"] = str(state_root)
    env["TWINBOX_CANONICAL_ROOT"] = str(state_root)
    run_id = uuid4().hex
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    with _with_schedule_lock(state_root):
        attempts: list[dict[str, object]] = []
        attempt_total = 2 if retry_once else 1
        archive_path: str | None = None
        pulse_path: str | None = None
        pulse_payload: dict[str, object] | None = None
        final_exit = 1

        for attempt_index in range(1, attempt_total + 1):
            step_exit, step_results = _run_scheduled_steps(
                _scheduled_job_steps(job, code_root),
                env=env,
                dry_run=dry_run,
            )
            attempt_record: dict[str, object] = {
                "attempt": attempt_index,
                "steps": step_results,
                "returncode": step_exit,
            }

            if step_exit == 0 and not dry_run:
                try:
                    pulse_payload, pulse_file = write_activity_pulse(
                        state_root,
                        top_k=top_k,
                        update_dedupe=job.updates_dedupe,
                    )
                    pulse_path = str(pulse_file)
                    attempt_record["activity_pulse"] = pulse_path
                except DaytimeSliceError as exc:
                    step_exit = 1
                    attempt_record["returncode"] = 1
                    attempt_record["pulse_error"] = str(exc)

            attempts.append(attempt_record)
            final_exit = step_exit
            if step_exit == 0:
                break

        finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        status = "success" if final_exit == 0 else "failed"
        archive_path = None if dry_run else _archive_schedule_snapshot(
            state_root,
            job=job,
            run_id=run_id,
            include_failure_snapshot=final_exit != 0,
        )
        log_path = None
        if not dry_run:
            record = {
                "run_id": run_id,
                "job": job.id,
                "label": job.label,
                "event_source": event_source,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status,
                "retry_once": retry_once,
                "attempts": attempts,
                "archive_path": archive_path,
                "activity_pulse_path": pulse_path,
            }
            log_path = _append_schedule_log(state_root, record)

        payload = {
            "run_id": run_id,
            "job": job.id,
            "label": job.label,
            "event_source": event_source,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "retry_attempted": len(attempts) > 1,
            "alert_required": final_exit != 0,
            "artifact_paths": {
                "activity_pulse": pulse_path,
                "archive": archive_path,
                "schedule_log": None if log_path is None else str(log_path),
            },
            "notify_payload": (
                {"generated_at": started_at, "stale": False, "urgent_top_k": [], "pending_count": 0, "summary": "dry-run"}
                if dry_run
                else (pulse_payload or {}).get("notify_payload", {})
            ),
            "attempts": [
                {
                    "attempt": attempt["attempt"],
                    "returncode": attempt["returncode"],
                    "pulse_error": attempt.get("pulse_error"),
                    "steps": [
                        {
                            "label": step["label"],
                            "argv": step["argv"],
                            "returncode": step["returncode"],
                        }
                        for step in attempt["steps"]
                    ],
                }
                for attempt in attempts
            ],
        }
        return final_exit, payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    roots = subparsers.add_parser("roots")
    roots.add_argument("--code-root")

    contract = subparsers.add_parser("contract")
    contract.add_argument("--code-root")
    contract.add_argument("--phase", type=int, choices=range(1, 5))
    contract.add_argument("--serial-phase4", action="store_true")
    contract.add_argument("--format", choices=("text", "json"), default="text")

    run = subparsers.add_parser("run")
    run.add_argument("--code-root")
    run.add_argument("--phase", type=int, choices=range(1, 5))
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--serial", action="store_true")
    run.add_argument("--serial-phase4", action="store_true")

    schedule = subparsers.add_parser("schedule")
    schedule.add_argument("--code-root")
    schedule.add_argument("--job", required=True, choices=[job.id for job in SCHEDULED_JOBS])
    schedule.add_argument("--event-source", default="system-event")
    schedule.add_argument("--format", choices=("text", "json"), default="text")
    schedule.add_argument("--dry-run", action="store_true")
    schedule.add_argument("--top-k", type=int, default=3)
    schedule.add_argument("--no-retry", action="store_true")

    bridge = subparsers.add_parser("bridge")
    bridge.add_argument("--code-root")
    event_source = bridge.add_mutually_exclusive_group(required=True)
    event_source.add_argument("--event-text")
    event_source.add_argument("--event-file")
    bridge.add_argument("--format", choices=("text", "json"), default="text")
    bridge.add_argument("--dry-run", action="store_true")

    bridge_poll = subparsers.add_parser("bridge-poll")
    bridge_poll.add_argument("--code-root")
    bridge_poll.add_argument("--format", choices=("text", "json"), default="text")
    bridge_poll.add_argument("--dry-run", action="store_true")
    bridge_poll.add_argument("--limit", type=int, default=50)
    bridge_poll.add_argument("--openclaw-bin", default="openclaw")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        code_root, state_root = resolve_roots(getattr(args, "code_root", None))
        if args.command == "roots":
            print(f"code_root={code_root}")
            print(f"state_root={state_root}")
            return 0

        if args.command == "contract":
            if args.format == "json":
                print(
                    json.dumps(
                        contract_payload(
                            code_root,
                            state_root,
                            phase=args.phase,
                            serial_phase4=args.serial_phase4,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(
                    render_contract_text(
                        code_root,
                        state_root,
                        phase=args.phase,
                        serial_phase4=args.serial_phase4,
                    )
                )
            return 0

        if args.command == "run":
            return run_steps(
                code_root,
                state_root,
                phase=args.phase,
                dry_run=args.dry_run,
                serial_phase4=args.serial or args.serial_phase4,
            )

        if args.command == "schedule":
            exit_code, payload = run_scheduled_job(
                code_root,
                state_root,
                job_id=args.job,
                event_source=args.event_source,
                dry_run=args.dry_run,
                top_k=args.top_k,
                retry_once=not args.no_retry,
            )
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                lines = [
                    f"job: {payload['job']}",
                    f"status: {payload['status']}",
                    f"run_id: {payload['run_id']}",
                    f"event_source: {payload['event_source']}",
                    f"started_at: {payload['started_at']}",
                    f"finished_at: {payload['finished_at']}",
                    f"retry_attempted: {payload['retry_attempted']}",
                    f"alert_required: {payload['alert_required']}",
                ]
                notify_payload = payload.get("notify_payload", {})
                if isinstance(notify_payload, dict) and notify_payload:
                    lines.append(f"notify_summary: {notify_payload.get('summary', '')}")
                    lines.append(f"urgent_top_k: {len(notify_payload.get('urgent_top_k', []))}")
                artifact_paths = payload.get("artifact_paths", {})
                if isinstance(artifact_paths, dict):
                    for key, value in artifact_paths.items():
                        if value:
                            lines.append(f"{key}: {value}")
                print("\n".join(lines))
            return exit_code

        if args.command == "bridge":
            if args.event_file:
                event_text = Path(args.event_file).read_text(encoding="utf-8")
            else:
                event_text = args.event_text or ""
            exit_code, payload = dispatch_bridge_event(
                code_root,
                state_root,
                event_text=event_text,
                dry_run=args.dry_run,
            )
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                event = payload["bridge_event"]
                schedule = payload["schedule"]
                lines = [
                    f"bridge_kind: {event['kind']}",
                    f"bridge_job: {event['job']}",
                    f"bridge_event_source: {event['event_source']}",
                    f"schedule_status: {schedule['status']}",
                    f"run_id: {schedule['run_id']}",
                ]
                notify_payload = schedule.get("notify_payload", {})
                if isinstance(notify_payload, dict) and notify_payload:
                    lines.append(f"notify_summary: {notify_payload.get('summary', '')}")
                print("\n".join(lines))
            return exit_code

        if args.command == "bridge-poll":
            exit_code, payload = poll_bridge_events(
                code_root,
                state_root,
                dry_run=args.dry_run,
                limit=args.limit,
                openclaw_bin=args.openclaw_bin,
            )
            if args.format == "json":
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                lines = [
                    f"status: {payload['status']}",
                    f"started_at: {payload['started_at']}",
                    f"finished_at: {payload['finished_at']}",
                    f"scanned_entries: {payload['scanned_entries']}",
                    f"processed_skipped: {payload['processed_skipped']}",
                    f"ignored_entries: {payload['ignored_entries']}",
                    f"dispatched_count: {payload['dispatched_count']}",
                    f"failed_count: {payload['failed_count']}",
                ]
                artifact_paths = payload.get("artifact_paths", {})
                if isinstance(artifact_paths, dict):
                    for key, value in artifact_paths.items():
                        if value:
                            lines.append(f"{key}: {value}")
                print("\n".join(lines))
            return exit_code

        parser.error(f"unknown command: {args.command}")
    except (OpenClawBridgeError, OrchestrationError, PathResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
