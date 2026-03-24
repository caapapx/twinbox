from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import unittest

from twinbox_core.material_extract import (
    MaterialExtractError,
    docx_to_markdown,
    material_source_to_markdown,
    pptx_to_markdown,
    write_extract_for_import,
)


class MaterialExtractTest(unittest.TestCase):
    def test_docx_minimal_ooxml(self) -> None:
        doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>台账</w:t><w:t>行一</w:t></w:r></w:p>
    <w:p><w:r><w:t>第二段</w:t></w:r></w:p>
  </w:body>
</w:document>"""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            p = Path(f.name)
        try:
            with zipfile.ZipFile(p, "w") as zf:
                zf.writestr("word/document.xml", doc_xml)
            md = docx_to_markdown(p)
            self.assertIn("台账行一", md)
            self.assertIn("第二段", md)
        finally:
            p.unlink(missing_ok=True)

    def test_pptx_minimal_ooxml(self) -> None:
        slide = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <a:t>标题块</a:t>
      <a:t>要点</a:t>
    </p:spTree>
  </p:cSld>
</p:sld>"""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            p = Path(f.name)
        try:
            with zipfile.ZipFile(p, "w") as zf:
                zf.writestr("ppt/slides/slide1.xml", slide)
            md = pptx_to_markdown(p)
            self.assertIn("幻灯片 1", md)
            self.assertIn("标题块", md)
            self.assertIn("要点", md)
        finally:
            p.unlink(missing_ok=True)

    def test_reject_legacy_doc(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as f:
            f.write(b"not a zip")
            p = Path(f.name)
        try:
            with self.assertRaises(MaterialExtractError):
                material_source_to_markdown(p)
        finally:
            p.unlink(missing_ok=True)

    def test_write_extract_skips_unknown_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "x.bin"
            src.write_bytes(b"\0")
            out = write_extract_for_import(src, Path(tmp))
            self.assertIsNone(out)

    def test_write_extract_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "t.csv"
            src.write_text("a,b\n1,2\n", encoding="utf-8")
            out_dir = Path(tmp) / "ex"
            out_dir.mkdir()
            out = write_extract_for_import(src, out_dir)
            assert out is not None
            self.assertTrue(out.name.endswith(".extracted.md"))
            self.assertIn("1", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
