from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from twinbox_core.orchestration import (
    CLI_ENTRYPOINT,
    LEGACY_ENTRYPOINT,
    contract_payload,
    get_phase_contract,
    render_contract_text,
    resolve_roots,
    run_steps,
)


class OrchestrationTest(unittest.TestCase):
    def setUp(self) -> None:
        # tests/test_orchestration.py -> repo root is parents[1]
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_resolve_roots_default_points_at_repo_with_scripts(self) -> None:
        import os

        old = os.environ.pop("TWINBOX_CODE_ROOT", None)
        try:
            code_root, _state = resolve_roots(None)
            self.assertTrue((code_root / "scripts" / "phase4_loading.sh").is_file())
        finally:
            if old is not None:
                os.environ["TWINBOX_CODE_ROOT"] = old

    def test_contract_payload_exposes_cli_entrypoints(self) -> None:
        payload = contract_payload(self.repo_root, self.repo_root, phase=None, serial_phase4=False)

        self.assertEqual(payload["entrypoints"]["cli"], CLI_ENTRYPOINT)
        self.assertEqual(payload["entrypoints"]["legacy_fallback"], LEGACY_ENTRYPOINT)
        self.assertEqual(len(payload["phases"]), 4)
        self.assertNotIn("gastown_adapter", payload["phases"][3])

    def test_phase4_defaults_to_parallel_step(self) -> None:
        phase4 = get_phase_contract(4)

        parallel_steps = [step.id for step in phase4.selected_steps(serial_phase4=False)]
        serial_steps = [step.id for step in phase4.selected_steps(serial_phase4=True)]

        self.assertEqual(parallel_steps, ["loading", "parallel-thinking"])
        self.assertEqual(serial_steps, ["loading", "thinking"])

    def test_run_steps_dry_run_uses_shared_cli_contract(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = run_steps(
                self.repo_root,
                phase=4,
                dry_run=True,
                serial_phase4=False,
            )

        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("Phase 4 Loading", output)
        self.assertIn("phase4_thinking_parallel.sh", output)

    def test_render_contract_text_mentions_cli_surface(self) -> None:
        rendered = render_contract_text(self.repo_root, self.repo_root, phase=2, serial_phase4=False)

        self.assertIn("Twinbox Orchestration Contract", rendered)
        self.assertIn(CLI_ENTRYPOINT, rendered)
        self.assertIn("Phase 2 - Persona Inference", rendered)


if __name__ == "__main__":
    unittest.main()
