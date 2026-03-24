"""Convert imported user files (CSV/XLSX/Office/text) to Markdown for Phase 4 human_context."""

from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# OOXML namespaces
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

# Cap per-file extract; Phase 4 node further truncates when injecting context-pack.
MAX_EXTRACT_CHARS = 48000


class MaterialExtractError(Exception):
    """User-fixable errors (missing optional dependency, unsupported type)."""


def _truncate(s: str) -> str:
    if len(s) <= MAX_EXTRACT_CHARS:
        return s
    return (
        s[: MAX_EXTRACT_CHARS - 120]
        + "\n\n…(内容过长已截断，请精简源表或拆分多文件后重新 import-material)\n"
    )


def _md_escape_cell(cell: object) -> str:
    return str(cell).replace("|", "\\|").replace("\n", "<br>")


def csv_to_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return f"# 自上传表格: {path.name}\n\n_(空)_\n"
    header = rows[0]
    body = rows[1:400]
    lines = [
        f"# 自上传表格: {path.name}\n",
        "",
        "| " + " | ".join(_md_escape_cell(h) for h in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for r in body:
        padded = list(r) + [""] * max(0, len(header) - len(r))
        lines.append(
            "| "
            + " | ".join(_md_escape_cell(padded[i]) for i in range(len(header)))
            + " |"
        )
    return _truncate("\n".join(lines) + "\n")


def xlsx_to_markdown(path: Path) -> str:
    try:
        import openpyxl
    except ImportError as exc:
        raise MaterialExtractError(
            "读取 .xlsx 需要 openpyxl。请执行: pip install openpyxl"
        ) from exc

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = wb.active
        rows: list[list[object]] = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= 401:
                break
            rows.append(list(row))
    finally:
        wb.close()

    if not rows:
        return f"# 自上传表格: {path.name}\n\n_(空工作表)_\n"
    header = ["" if c is None else str(c) for c in rows[0]]
    lines = [
        f"# 自上传表格: {path.name}（首工作表）\n",
        "",
        "| " + " | ".join(_md_escape_cell(h) for h in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for r in rows[1:]:
        cells = []
        for j in range(len(header)):
            v = r[j] if j < len(r) else None
            cells.append("" if v is None else _md_escape_cell(v))
        lines.append("| " + " | ".join(cells) + " |")
    return _truncate("\n".join(lines) + "\n")


def text_like_to_markdown(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return _truncate(f"# 自上传文本: {path.name}\n\n{raw}\n")


def docx_to_markdown(path: Path) -> str:
    """Extract plaintext from .docx (OOXML) without python-docx."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                raise MaterialExtractError(f"不是有效的 .docx: {path.name}")
            raw = zf.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise MaterialExtractError(f"无法作为 ZIP/OOXML 读取: {path.name}") from exc

    root = ET.fromstring(raw)
    wp = f"{{{_W_NS}}}p"
    wt = f"{{{_W_NS}}}t"
    lines: list[str] = [f"# 自上传文档: {path.name}\n", ""]
    for para in root.iter(wp):
        parts = [t.text for t in para.iter(wt) if t.text]
        if parts:
            lines.append("".join(parts))
            lines.append("")
    body = "\n".join(lines).strip()
    if len(body) < len(path.name) + 5:
        return f"# 自上传文档: {path.name}\n\n_(未解析到段落文本，可能主要为图片/表格对象)_\n"
    return _truncate(body + "\n")


def pptx_to_markdown(path: Path) -> str:
    """Extract text from each slide in .pptx (OOXML) without python-pptx."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = sorted(
                n
                for n in zf.namelist()
                if re.match(r"ppt/slides/slide\d+\.xml$", n, re.I)
            )
            if not names:
                raise MaterialExtractError(f"不是有效的 .pptx 或无幻灯片 XML: {path.name}")
            slide_xmls = [(n, zf.read(n)) for n in names]
    except zipfile.BadZipFile as exc:
        raise MaterialExtractError(f"无法作为 ZIP/OOXML 读取: {path.name}") from exc

    ta = f"{{{_A_NS}}}t"
    lines: list[str] = [f"# 自上传演示稿: {path.name}\n"]
    for idx, (_, raw) in enumerate(slide_xmls, start=1):
        root = ET.fromstring(raw)
        chunks: list[str] = []
        for t in root.iter(ta):
            if t.text and t.text.strip():
                chunks.append(t.text.strip())
        if chunks:
            lines.append(f"\n## 幻灯片 {idx}\n")
            lines.extend(chunks)
    if len(lines) <= 1:
        return f"# 自上传演示稿: {path.name}\n\n_(未解析到文本，可能主要为图片)_\n"
    return _truncate("\n".join(lines) + "\n")


def material_source_to_markdown(source: Path) -> str:
    suf = source.suffix.lower()
    if suf == ".csv":
        return csv_to_markdown(source)
    if suf in (".xlsx", ".xlsm"):
        return xlsx_to_markdown(source)
    if suf == ".docx":
        return docx_to_markdown(source)
    if suf == ".pptx":
        return pptx_to_markdown(source)
    if suf in (".md", ".txt"):
        return text_like_to_markdown(source)
    if suf in (".doc", ".ppt"):
        raise MaterialExtractError(
            f"不支持旧版二进制 {suf}，请在 Office/WPS 中另存为 .docx / .pptx 后再 import-material"
        )
    raise MaterialExtractError(
        f"暂不支持的格式: {suf}（可用 .csv / .xlsx / .xlsm / .docx / .pptx / .md / .txt）"
    )


def extract_output_path(source_path: Path, extracts_dir: Path) -> Path:
    """Unique name so 工作簿1.csv 与 工作簿1.xlsx 不会互相覆盖。"""
    ext = source_path.suffix.lower().replace(".", "_")
    return extracts_dir / f"{source_path.stem}{ext}.extracted.md"


def write_extract_for_import(source_path: Path, extracts_dir: Path) -> Path | None:
    """
    Write Markdown extract for tabular / Office / text types. Returns path written, or None if skipped.
    """
    suf = source_path.suffix.lower()
    if suf not in (
        ".csv",
        ".xlsx",
        ".xlsm",
        ".docx",
        ".pptx",
        ".md",
        ".txt",
    ):
        return None
    md = material_source_to_markdown(source_path)
    out = extract_output_path(source_path, extracts_dir)
    out.write_text(md, encoding="utf-8")
    return out
