"""TTY onboarding: optional LLM polish of user paste into human-context + material extracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from twinbox_core.human_context_store import update_human_context_store
from twinbox_core.llm import LLMError, call_llm
from twinbox_core.material_extract import MAX_EXTRACT_CHARS


def polish_profile_notes(raw: str, *, env_file: Path, max_input_chars: int = 12000) -> str:
    """Normalize messy user prose into clear Markdown for profile_notes (single LLM call)."""
    text = (raw or "").strip()
    if not text:
        return ""
    clipped = text[:max_input_chars]
    system = (
        "You normalize onboarding notes. Output ONLY valid Markdown (no code fences, no preamble). "
        "Use short headings and bullets. Preserve facts; fix grammar and structure; do not invent employers or people."
    )
    user = (
        "User draft (may be unstructured or low quality):\n\n"
        f"{clipped}\n\n"
        "Rewrite as concise profile notes for an email assistant."
    )
    out = call_llm(user, max_tokens=2048, system_prompt=system, env_file=str(env_file))
    return out.strip()


def polish_freeform_reference(raw: str, *, env_file: Path, max_input_chars: int = 48000) -> str:
    """Normalize pasted reference / table-as-text into readable Markdown (no table parsing)."""
    text = (raw or "").strip()
    if not text:
        return ""
    clipped = text[:max_input_chars]
    system = (
        "You format reference material for an email assistant. Output ONLY Markdown (no fences). "
        "Preserve facts and numbers; fix headings/lists; do not invent data."
    )
    user = (
        "User pasted text (may include rough tables or notes):\n\n"
        f"{clipped}\n\n"
        "Rewrite as clear Markdown suitable for weekly/digest context."
    )
    out = call_llm(user, max_tokens=4096, system_prompt=system, env_file=str(env_file))
    return out.strip()


def polish_calibration_notes(raw: str, *, env_file: Path, max_input_chars: int = 8000) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    clipped = text[:max_input_chars]
    system = (
        "You normalize calibration hints for email triage. Output ONLY Markdown. "
        "No code fences. Keep user intent; improve clarity; do not add new policies."
    )
    user = (
        "User draft:\n\n"
        f"{clipped}\n\n"
        "Rewrite as short calibration notes (what to prioritize / deprioritize)."
    )
    out = call_llm(user, max_tokens=1536, system_prompt=system, env_file=str(env_file))
    return out.strip()


_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_stem(label: str, *, max_len: int = 48) -> str:
    s = _SLUG_RE.sub("-", (label or "paste").strip().lower()).strip("-")
    if not s:
        s = "paste"
    return s[:max_len].rstrip("-")


def persist_paste_as_material(
    state_root: Path,
    body: str,
    *,
    label: str,
    intent: str,
) -> dict[str, Any]:
    """
    Write pasted text as .md under material-extracts, update manifest, write .extracted.md (truncate like file import).
    """
    import json
    from datetime import datetime

    materials_dir = state_root / "runtime" / "context" / "material-extracts"
    materials_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(label)
    filename = f"{stem}.md"
    dest_path = materials_dir / filename
    if dest_path.exists():
        filename = f"{stem}-{datetime.now().strftime('%H%M%S')}.md"
        dest_path = materials_dir / filename

    dest_path.write_text(body, encoding="utf-8")

    manifest_path = state_root / "runtime" / "context" / "material-manifest.json"
    manifest: dict[str, Any] = {"generated_at": "", "materials": []}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {"generated_at": "", "materials": []}
    if not isinstance(manifest, dict):
        manifest = {"generated_at": "", "materials": []}
    materials = manifest.setdefault("materials", [])
    if not isinstance(materials, list):
        materials = []
        manifest["materials"] = materials

    now = datetime.now().isoformat()
    materials.append(
        {
            "filename": filename,
            "imported_at": now,
            "source": f"paste:{label}",
            "intent": intent if intent in ("reference", "template_hint") else "reference",
        }
    )
    manifest["generated_at"] = now

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    extract_name = f"{Path(filename).stem}.md.extracted.md"
    extract_path = materials_dir / extract_name
    md_body = f"# Pasted material: {filename}\n\n{body}"
    if len(md_body) > MAX_EXTRACT_CHARS:
        md_body = (
            md_body[: MAX_EXTRACT_CHARS - 120]
            + "\n\n…(truncated; shorten paste or split into multiple steps)\n"
        )
    extract_path.write_text(md_body, encoding="utf-8")

    return {
        "filename": filename,
        "dest_path": str(dest_path),
        "extract_path": str(extract_path),
        "manifest_path": str(manifest_path),
    }


def apply_onboarding_paste_bundle(
    state_root: Path,
    *,
    env_file: Path,
    profile_raw: str,
    calibration_raw: str,
    material_raw: str,
    material_label: str,
    material_intent: str,
    polish: bool,
) -> dict[str, Any]:
    """
    Persist profile/calibration to human-context.yaml; optional material file + manifest.
    When polish=True and LLM fails, falls back to raw text for that field.
    """
    profile_final = profile_raw.strip()
    calibration_final = calibration_raw.strip()
    material_final = material_raw.strip()

    if polish and profile_final:
        try:
            profile_final = polish_profile_notes(profile_final, env_file=env_file)
        except LLMError:
            pass
    if polish and calibration_final:
        try:
            calibration_final = polish_calibration_notes(calibration_final, env_file=env_file)
        except LLMError:
            pass

    if profile_final or calibration_final:
        update_human_context_store(
            state_root,
            profile_notes=profile_final if profile_final else None,
            calibration=calibration_final if calibration_final else None,
        )

    material_info: dict[str, Any] | None = None
    if material_final:
        if polish:
            try:
                material_final = polish_freeform_reference(
                    material_final,
                    env_file=env_file,
                    max_input_chars=MAX_EXTRACT_CHARS - 2000,
                )
            except LLMError:
                pass
        material_info = persist_paste_as_material(
            state_root,
            material_final,
            label=material_label or "context",
            intent=material_intent,
        )

    return {
        "profile_saved": bool(profile_final),
        "calibration_saved": bool(calibration_final),
        "material": material_info,
        "polish": polish,
    }
