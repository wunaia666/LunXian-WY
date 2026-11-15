"""检查差异工具拒绝掩盖错位，并在零误差时仍保留人工验收状态。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw


spec = importlib.util.spec_from_file_location("compare_visual", Path(__file__).parents[1] / "scripts" / "compare_visual.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VisualTests(unittest.TestCase):
    def inputs(self, root):
        source, actual, deck = root / "source.png", root / "actual.png", root / "test.pptx"
        image = Image.new("RGB", (100, 80), "white")
        ImageDraw.Draw(image).rectangle((20, 20, 49, 39), fill="#0066cc")
        image.save(source)
        image.save(actual)
        deck.write_bytes(b"test-provenance-only")
        return source, actual, deck

    def test_identical_pixels_still_require_editability_and_visual_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, actual, deck = self.inputs(root)
            before = source.read_bytes()
            result = module.compare(source, actual, deck, root / "evidence")
            self.assertEqual(result["整页误差"]["平均通道绝对差"], 0)
            self.assertEqual(result["状态"], "待确认")
            self.assertTrue((root / "evidence" / "_ai小图" / "半透明叠加.jpg").exists())
            self.assertEqual(source.read_bytes(), before)

    def test_size_mismatch_is_rejected_instead_of_resized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, actual, deck = self.inputs(root)
            Image.new("RGB", (99, 80), "white").save(actual)
            with self.assertRaisesRegex(ValueError, "尺寸不一致"):
                module.compare(source, actual, deck, root / "evidence")

    def test_shift_is_detected_in_registered_region_and_crop_is_generated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, actual, deck = self.inputs(root)
            image = Image.new("RGB", (100, 80), "white")
            ImageDraw.Draw(image).rectangle((24, 20, 53, 39), fill="#0066cc")
            image.save(actual)
            registry = root / "objects.json"
            registry.write_text(json.dumps({"原图尺寸": [100, 80], "对象": [{"对象编号": "o1", "原图坐标和尺寸": [15, 15, 45, 30]}]}, ensure_ascii=False), encoding="utf-8")
            result = module.compare(source, actual, deck, root / "evidence", registry, ["o1"])
            self.assertGreater(result["整页误差"]["平均通道绝对差"], 0)
            self.assertGreater(result["对象区域"][0]["误差"]["平均通道绝对差"], 0)
            self.assertTrue((root / "evidence" / "_ai小图" / "局部_001.jpg").exists())

    def test_stale_native_export_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, actual, deck = self.inputs(root)
            record = root / "audit.json"
            record.write_text(json.dumps({"文件摘要": "outdated", "检查期间文件版本一致": True, "实际打开与原生检查": {"状态": "已验证", "原尺寸对照": []}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "版本不一致"):
                module.compare(source, actual, deck, root / "evidence", audit_record=record)

    def test_wrong_source_registry_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, actual, deck = self.inputs(root)
            registry = root / "objects.json"
            registry.write_text(json.dumps({"原图尺寸": [100, 80], "原图摘要": hashlib.sha256(b"another-image").hexdigest(), "对象": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "其他原图版本"):
                module.compare(source, actual, deck, root / "evidence", registry)


if __name__ == "__main__":
    unittest.main()
