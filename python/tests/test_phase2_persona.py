from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from twinbox_core.llm import BackendConfig
from twinbox_core.phase2_persona import Phase2RunConfig, run_phase2_persona


class Phase2PersonaTest(unittest.TestCase):
    def test_run_writes_phase2_outputs(self) -> None:
        context = {
            "mailbox_summary": {
                "total_envelopes": 12,
                "internal_external": {"internal": 9, "external": 2, "unknown": 1},
            },
            "intent_distribution": [{"key": "release", "count": 6}],
            "top_contacts": [{"key": "alice@example.com", "count": 4}],
            "top_domains": [{"key": "example.com", "count": 10}],
        }
        llm_response = {
            "persona_hypotheses": [
                {
                    "id": "P1",
                    "type": "role",
                    "hypothesis": "负责项目交付推进",
                    "confidence": 0.91,
                    "evidence": ["release(6)"],
                }
            ],
            "business_hypotheses": [
                {
                    "id": "B1",
                    "hypothesis": "公司围绕项目交付协同运转",
                    "confidence": 0.82,
                    "evidence": ["alice@example.com(4)"],
                    "ai_entry_points": ["生成周报"],
                }
            ],
            "confirmation_questions": ["是否负责审批资源申请？"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context_path = root / "context-pack.json"
            output_dir = root / "runtime/validation/phase-2"
            doc_dir = root / "docs/validation"
            diagram_dir = doc_dir / "diagrams"
            context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")

            with mock.patch(
                "twinbox_core.phase2_persona.resolve_backend",
                return_value=BackendConfig("openai", "test-model", "https://example.com", "key", 10, 1),
            ), mock.patch(
                "twinbox_core.phase2_persona.call_llm",
                return_value=json.dumps(llm_response, ensure_ascii=False),
            ):
                run_phase2_persona(
                    Phase2RunConfig(
                        context_path=context_path,
                        output_dir=output_dir,
                        doc_dir=doc_dir,
                        diagram_dir=diagram_dir,
                        dry_run=False,
                        env_file=None,
                        model_override=None,
                    )
                )

            self.assertIn("负责项目交付推进", (output_dir / "persona-hypotheses.yaml").read_text(encoding="utf-8"))
            self.assertIn("生成周报", (output_dir / "business-hypotheses.yaml").read_text(encoding="utf-8"))
            self.assertIn("Phase 2 Report", (doc_dir / "phase-2-report.md").read_text(encoding="utf-8"))
            self.assertIn("graph TD", (diagram_dir / "phase-2-relationship-map.mmd").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
