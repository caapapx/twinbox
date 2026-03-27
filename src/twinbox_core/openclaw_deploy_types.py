"""Shared datatypes for OpenClaw deploy / rollback reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeployStepResult:
    id: str
    status: str  # ok | skipped | failed | dry_run
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenClawDeployReport:
    ok: bool
    steps: list[DeployStepResult] = field(default_factory=list)
    code_root: str = ""
    openclaw_home: str = ""
    state_root: str = ""
    skill_dest: str = ""
    skill_canonical_dest: str = ""
    openclaw_json: str = ""
    deploy_host_system: str = ""
    deploy_host_machine: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code_root": self.code_root,
            "openclaw_home": self.openclaw_home,
            "state_root": self.state_root,
            "skill_dest": self.skill_dest,
            "skill_canonical_dest": self.skill_canonical_dest,
            "openclaw_json": self.openclaw_json,
            "deploy_host_system": self.deploy_host_system,
            "deploy_host_machine": self.deploy_host_machine,
            "steps": [
                {
                    "id": s.id,
                    "status": s.status,
                    "message": s.message,
                    "detail": s.detail,
                }
                for s in self.steps
            ],
        }
