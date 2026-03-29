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
    phase2_ready: bool | None = None
    plugin_tools: dict[str, Any] = field(default_factory=dict)
    bridge: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "code_root": self.code_root,
            "openclaw_home": self.openclaw_home,
            "state_root": self.state_root,
            "skill_dest": self.skill_dest,
            "skill_canonical_dest": self.skill_canonical_dest,
            "openclaw_json": self.openclaw_json,
            "deploy_host_system": self.deploy_host_system,
            "deploy_host_machine": self.deploy_host_machine,
            "phase2_ready": self.phase2_ready,
            "plugin_tools": self.plugin_tools,
            "bridge": self.bridge,
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
        if self.plugin_tools:
            payload["plugin_tools.status"] = self.plugin_tools.get("status")
            payload["plugin_tools.loaded_names"] = self.plugin_tools.get("loaded_names", [])
        if self.bridge:
            inst = self.bridge.get("install") if isinstance(self.bridge.get("install"), dict) else {}
            sysd = self.bridge.get("systemd") if isinstance(self.bridge.get("systemd"), dict) else {}
            payload["bridge.status"] = self.bridge.get("status")
            payload["bridge.timer_enabled"] = sysd.get("timer_enabled")
            payload["bridge.timer_active"] = sysd.get("timer_active")
            payload["bridge.last_health_check"] = self.bridge.get("last_health_check")
            payload["bridge.twinbox_bin"] = inst.get("twinbox_bin")
            payload["bridge.openclaw_bin"] = inst.get("openclaw_bin")
        return payload
