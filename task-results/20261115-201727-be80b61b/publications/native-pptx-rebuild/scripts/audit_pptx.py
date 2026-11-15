"""清点原生对象、检查包关系，并按需用本机演示软件打开与导出小图。"""

from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import posixpath
import shutil
import tempfile
import time
from urllib.parse import unquote
from xml.etree import ElementTree as ET
import zipfile


def inspect_package(path):
    errors = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for name, count in Counter(archive.namelist()).items():
            if count > 1:
                errors.append(f"包内部件重名：{name}")
        for required in ("[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml"):
            if required not in names:
                errors.append(f"缺少必要部件：{required}")
        damaged = archive.testzip()
        if damaged:
            errors.append(f"压缩包校验失败：{damaged}")
        for name in names:
            if not name.endswith((".xml", ".rels")):
                continue
            try:
                root = ET.fromstring(archive.read(name))
            except ET.ParseError:
                errors.append(f"内部标记无法解析：{name}")
                continue
            if not name.endswith(".rels"):
                continue
            base = posixpath.dirname(posixpath.dirname(name))
            for relation in root:
                if relation.get("TargetMode") == "External":
                    continue
                target = unquote(relation.get("Target", "")).split("#", 1)[0]
                resolved = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(base, target))
                if resolved not in names:
                    errors.append(f"关系目标缺失：{name} → {resolved}")
    return {"状态": "未通过" if errors else "已验证", "检查范围": "压缩包完整性、必要部件、内部标记可解析及内部关系目标存在；不是完整格式规范校验", "问题": errors}


def inspect_objects(path):
    from PIL import Image
    from pptx import Presentation
    from lxml import etree

    deck = Presentation(path)
    pages = []
    for number, slide in enumerate(deck.slides, 1):
        rows = []

        def visit(shapes, parent=None):
            for shape in shapes:
                kind = int(shape.shape_type)
                row = {"对象标识": shape.shape_id, "名称": shape.name, "父对象标识": parent, "类型": kind,
                       "位置尺寸": [shape.left, shape.top, shape.width, shape.height],
                       "文字": shape.text if shape.has_text_frame else ""}
                if hasattr(shape, "fill"):
                    row["填充类型"] = int(shape.fill.type) if shape.fill.type is not None else None
                geometry = shape._element.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}custGeom")
                if geometry is not None:
                    row["自定义几何操作数"] = sum(etree.QName(node).localname in ("moveTo", "lnTo", "cubicBezTo", "quadBezTo", "arcTo") for node in geometry.iter())
                if kind == 13:
                    import io

                    try:
                        with Image.open(io.BytesIO(shape.image.blob)) as image:
                            alpha = image.convert("RGBA").getchannel("A")
                            row["图片存在透明像素"] = alpha.getextrema()[0] < 255
                    except Exception:
                        row["图片透明检查"] = "待确认：当前图片格式未能分析"
                rows.append(row)
                if kind == 6:
                    visit(shape.shapes, shape.shape_id)

        visit(slide.shapes)
        pages.append({"页码": number, "对象统计": dict(Counter(str(row["类型"]) for row in rows)), "对象": rows})
    return {"页数": len(deck.slides), "画布": [deck.slide_width, deck.slide_height], "页面": pages}


def inspect_office(path, preview_dir=None, reference_image=None, reference_page=1):
    import pythoncom
    import win32com.client
    from PIL import Image

    pythoncom.CoInitialize()
    app = deck = None
    result = {"状态": "待确认", "渲染状态": "待确认", "对象": [], "预览": [], "原尺寸对照": []}
    try:
        # 只打开输入的临时副本，避免办公软件对用户原件进行恢复或缓存写入。
        with tempfile.TemporaryDirectory(prefix="ppt_check_") as directory:
            local = Path(directory) / "input.pptx"
            shutil.copy2(path, local)
            for attempt in range(6):
                try:
                    app = win32com.client.Dispatch("PowerPoint.Application")
                    deck = app.Presentations.Open(str(local), True, False, False)
                    break
                except Exception:
                    if attempt == 5:
                        raise
                    pythoncom.PumpWaitingMessages()
                    time.sleep(1)

            def visit(shapes, page, parent=None):
                for index in range(1, shapes.Count + 1):
                    shape = shapes.Item(index)
                    row = {"页码": page, "对象标识": int(shape.Id), "父对象标识": parent, "名称": str(shape.Name)}
                    try:
                        row["顶点数"] = int(shape.Nodes.Count)
                    except Exception:
                        row["顶点查询"] = "不适用或当前对象接口未提供"
                    try:
                        row["具有文本框能力"] = bool(shape.HasTextFrame)
                        if shape.HasTextFrame and shape.TextFrame.HasText:
                            text = shape.TextFrame.TextRange
                            row["文字字界"] = [float(text.BoundLeft), float(text.BoundTop), float(text.BoundWidth), float(text.BoundHeight)]
                            row["对象外框"] = [float(shape.Left), float(shape.Top), float(shape.Width), float(shape.Height)]
                    except Exception:
                        row["文字字界检查"] = "待确认：当前对象未获得字界"
                    result["对象"].append(row)
                    if int(shape.Type) == 6:
                        visit(shape.GroupItems, page, int(shape.Id))

            try:
                if reference_image is not None and not 1 <= reference_page <= deck.Slides.Count:
                    raise ValueError("指定的原图对应页码不在文稿范围内。")
                for number in range(1, deck.Slides.Count + 1):
                    slide = deck.Slides.Item(number)
                    visit(slide.Shapes, number)
                    if preview_dir is not None:
                        small = Path(preview_dir) / "_ai小图"
                        small.mkdir(parents=True, exist_ok=True)
                        width, height = float(deck.PageSetup.SlideWidth), float(deck.PageSetup.SlideHeight)
                        scale = 1568 / max(width, height)
                        native = Path(directory) / f"page_{number:03d}.jpg"
                        slide.Export(str(native), "JPG", round(width * scale), round(height * scale))
                        output = small / f"第{number:03d}页.jpg"
                        with Image.open(native) as image:
                            image.convert("RGB").save(output, quality=82, optimize=True)
                        result["预览"].append(str(output.resolve()))
                        if reference_image is not None and number == reference_page:
                            with Image.open(reference_image) as source:
                                reference_size = source.size
                            if abs(reference_size[0] - reference_size[1] * width / height) > 1:
                                raise ValueError("画布比例与原图不同，不能通过拉伸导出来掩盖布局差异；回填主体需单独登记等比对照区域。")
                            full_dir = Path(preview_dir) / "原尺寸对照"
                            full_dir.mkdir(parents=True, exist_ok=True)
                            full = full_dir / f"page_{number:03d}.png"
                            slide.Export(str(full.resolve()), "PNG", *reference_size)
                            with Image.open(full) as image:
                                if image.size != reference_size:
                                    raise ValueError("原生导出的像素尺寸与原图不一致。")
                                image.thumbnail((1568, 1568))
                                image.convert("RGB").save(output, quality=82, optimize=True)
                            result["原尺寸对照"].append({"页码": number, "原图": str(Path(reference_image).resolve()), "原图摘要": hashlib.sha256(Path(reference_image).read_bytes()).hexdigest(), "尺寸": reference_size, "渲染图": str(full.resolve()), "渲染图摘要": hashlib.sha256(full.read_bytes()).hexdigest()})
                result["状态"] = "已验证"
                if preview_dir is not None:
                    result["渲染状态"] = "已验证"
            finally:
                slide = None
                deck.Close()
                deck = None
    except Exception as error:
        result["状态"] = "未通过"
        result["原因"] = str(error)
    finally:
        # 只释放本次引用，不退出用户正在使用的演示软件。
        deck = app = None
        gc.collect()
        pythoncom.CoUninitialize()
    return result


def audit(path, office=False, preview_dir=None, reference_image=None, reference_page=1):
    result = {"文件": str(Path(path).resolve()), "文件摘要": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "包结构检查": inspect_package(path),
              "实际打开与原生检查": {"状态": "待确认", "原因": "未执行本机演示软件检查"},
              "人工功能与视觉验收": {"状态": "待确认", "项目": ["文字内容与颜色及填充修改后保存重开", "背景改色后保存重开", "图片移动缩放替换后保存重开", "同一不规则文本框改字改色及实际编辑顶点后保存重开", "移开元素后无残字残片", "同尺寸叠加和差异图及局部放大检查与修正", "文字无意外溢出", "回填页序与导航", "恢复原图外观后重新检查最终文件"]}}
    if result["包结构检查"]["问题"]:
        return result
    result["对象清点"] = inspect_objects(path)
    if office:
        try:
            result["实际打开与原生检查"] = inspect_office(path, preview_dir, reference_image, reference_page)
        except ImportError as error:
            result["实际打开与原生检查"] = {"状态": "待确认", "原因": f"本机原生检查依赖不可用：{error}"}
    result["检查期间文件版本一致"] = result["文件摘要"] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if not result["检查期间文件版本一致"]:
        result["实际打开与原生检查"] = {"状态": "未通过", "原因": "检查期间最终文件发生变化，必须重新检查。"}
    return result


def main():
    parser = argparse.ArgumentParser(description="记录包关系、原生对象及本机实际打开证据，不自动宣称视觉达标。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助")
    parser.add_argument("input", type=Path, help="待检查的演示文件")
    parser.add_argument("--output", type=Path, required=True, help="检查记录路径（.json）")
    parser.add_argument("--office", action="store_true", help="实际用本机演示软件打开并查询对象")
    parser.add_argument("--preview-dir", type=Path, help="输出压缩预览的目录，需要同时指定原生检查选项")
    parser.add_argument("--reference-image", type=Path, help="用于原尺寸导出的当前原图")
    parser.add_argument("--reference-page", type=int, default=1, help="原图在最终文稿中的对应页码")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".json" or args.output.resolve() == args.input.resolve():
        parser.error("检查记录必须使用独立的 .json 路径，不能覆盖输入。")
    if args.preview_dir and not args.office:
        parser.error("生成原生预览需要同时指定 --office。")
    if args.reference_image and (not args.office or not args.preview_dir):
        parser.error("原尺寸导出需要同时指定 --office 和 --preview-dir。")
    try:
        result = audit(args.input.resolve(), args.office, args.preview_dir, args.reference_image, args.reference_page)
    except Exception as error:
        result = {"文件": str(args.input.resolve()), "包结构检查": {"状态": "未通过", "问题": [str(error)]}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"检查记录：{args.output.resolve()}")
    failed = result["包结构检查"]["状态"] == "未通过" or result.get("实际打开与原生检查", {}).get("状态") == "未通过"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
