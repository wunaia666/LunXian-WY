"""检查工具能识别损坏关系，并且不会把静态检查误报为已打开或已视觉验收。"""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.util import Inches


spec = importlib.util.spec_from_file_location("audit_pptx", Path(__file__).parents[1] / "scripts" / "audit_pptx.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample(path):
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string("F4F6F8")
    shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, Inches(1), Inches(1), Inches(4), Inches(1))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string("16724B")
    shape.text = "原生色框与文字"
    custom = slide.shapes.build_freeform(0, 0)
    custom.add_line_segments([(1800000, 0), (1600000, 700000), (0, 700000)], close=True)
    custom.convert_to_shape(Inches(2), Inches(3)).text = "可编辑轮廓"
    deck.save(path)


class AuditTests(unittest.TestCase):
    def test_native_objects_are_recorded_without_claiming_office_or_visual_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.pptx"
            sample(path)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = module.audit(path)
            self.assertEqual(result["包结构检查"]["状态"], "已验证")
            self.assertEqual(result["实际打开与原生检查"]["状态"], "待确认")
            self.assertEqual(result["人工功能与视觉验收"]["状态"], "待确认")
            rows = result["对象清点"]["页面"][0]["对象"]
            self.assertEqual([row["文字"] for row in rows], ["原生色框与文字", "可编辑轮廓"])
            self.assertGreater(rows[1]["自定义几何操作数"], 0)
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_missing_media_relationship_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.pptx"
            sample(path)
            with zipfile.ZipFile(path) as archive:
                contents = {name: archive.read(name) for name in archive.namelist()}
            contents["ppt/slides/_rels/slide1.xml.rels"] = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="missing" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/missing.png"/></Relationships>'
            with zipfile.ZipFile(path, "w") as archive:
                for name, data in contents.items():
                    archive.writestr(name, data)
            result = module.audit(path)
            self.assertEqual(result["包结构检查"]["状态"], "未通过")
            self.assertTrue(any("missing.png" in problem for problem in result["包结构检查"]["问题"]))
            self.assertNotIn("对象清点", result)

    def test_unreadable_file_is_not_valid_package(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.pptx"
            path.write_bytes(b"invalid")
            with self.assertRaises(zipfile.BadZipFile):
                module.inspect_package(path)


if __name__ == "__main__":
    unittest.main()
