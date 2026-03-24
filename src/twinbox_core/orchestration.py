"""Shared orchestration contract for local CLI execution."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from twinbox_core.paths import PathResolutionError, resolve_canonical_root, resolve_existing_dir


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


class OrchestrationError(RuntimeError):
    """Raised when the orchestration contract cannot be executed."""


def _default_code_root() -> Path:
    override = os.environ.get("TWINBOX_CODE_ROOT")
    if override:
        return resolve_existing_dir(override)
    return resolve_existing_dir(Path(__file__).resolve().parents[3])


def resolve_roots(code_root_override: str | None = None) -> tuple[Path, Path]:
    code_root = resolve_existing_dir(code_root_override) if code_root_override else _default_code_root()
    state_root = resolve_canonical_root(code_root)
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
    *,
    phase: int | None,
    dry_run: bool,
    serial_phase4: bool,
) -> int:
    env = os.environ.copy()
    env["TWINBOX_CODE_ROOT"] = str(code_root)

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
                phase=args.phase,
                dry_run=args.dry_run,
                serial_phase4=args.serial or args.serial_phase4,
            )

        parser.error(f"unknown command: {args.command}")
    except (OrchestrationError, PathResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
