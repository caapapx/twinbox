"""Read default LLM from OpenClaw ``openclaw.json`` for Twinbox ``config`` import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class OpenClawLlmImportError(ValueError):
    """Raised when OpenClaw config cannot be mapped to Twinbox LLM fields."""


def _secret_value(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _resolve_primary_model_ref(cfg: dict[str, Any]) -> str:
    agents = cfg.get("agents")
    if not isinstance(agents, dict):
        return ""
    defaults = agents.get("defaults")
    if not isinstance(defaults, dict):
        return ""
    model_field = defaults.get("model")
    if isinstance(model_field, str):
        return model_field.strip()
    if isinstance(model_field, dict):
        return str(model_field.get("primary") or "").strip()
    return ""


def import_llm_from_openclaw_dict(cfg: dict[str, Any]) -> dict[str, Any]:
    """Map OpenClaw host config to Twinbox ``set-llm``-compatible fields.

    Returns a dict with keys: ``twinbox_provider`` (``openai`` | ``anthropic``),
    ``api_key``, ``model``, ``api_url``, ``openclaw_provider_id``, ``openclaw_model_ref``.
    """
    primary = _resolve_primary_model_ref(cfg)
    if not primary or "/" not in primary:
        raise OpenClawLlmImportError(
            "Could not find agents.defaults.model.primary as 'providerId/modelId' in openclaw.json"
        )

    provider_id, _, model_id = primary.partition("/")
    provider_id = provider_id.strip()
    model_id = model_id.strip()
    if not provider_id or not model_id:
        raise OpenClawLlmImportError(f"Invalid OpenClaw model ref: {primary!r}")

    models_block = cfg.get("models")
    if not isinstance(models_block, dict):
        raise OpenClawLlmImportError("Missing models block in openclaw.json")
    providers = models_block.get("providers")
    if not isinstance(providers, dict):
        raise OpenClawLlmImportError("Missing models.providers in openclaw.json")

    prov = providers.get(provider_id)
    if not isinstance(prov, dict):
        raise OpenClawLlmImportError(f"Unknown OpenClaw provider id: {provider_id!r}")

    api_key = _secret_value(prov.get("apiKey"))
    if not api_key:
        raise OpenClawLlmImportError(
            f"Provider {provider_id!r} has no usable apiKey string (ref-based secrets are not resolved here)"
        )

    base_url = str(prov.get("baseUrl") or "").strip().rstrip("/")
    if not base_url:
        raise OpenClawLlmImportError(f"Provider {provider_id!r} has empty baseUrl")

    api_kind = str(prov.get("api") or "").strip()

    if api_kind in ("openai-completions", "openai-responses", "openai-codex-responses", ""):
        twinbox_provider = "openai"
    elif api_kind == "anthropic-messages":
        twinbox_provider = "anthropic"
    else:
        raise OpenClawLlmImportError(
            f"Unsupported OpenClaw models.providers[{provider_id!r}].api: {api_kind!r} "
            "(supported: openai-completions, openai-responses, openai-codex-responses, anthropic-messages)"
        )

    return {
        "twinbox_provider": twinbox_provider,
        "api_key": api_key,
        "model": model_id,
        "api_url": base_url,
        "openclaw_provider_id": provider_id,
        "openclaw_model_ref": primary,
    }


def import_llm_from_openclaw_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OpenClawLlmImportError(f"OpenClaw config not found: {path}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OpenClawLlmImportError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise OpenClawLlmImportError("openclaw.json root must be an object")
    return import_llm_from_openclaw_dict(cfg)
