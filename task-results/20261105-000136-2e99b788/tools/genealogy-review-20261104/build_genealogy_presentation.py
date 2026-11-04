"""把独立系谱图转为原生可编辑演示文稿，并合并起首总览。"""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import defaultdict
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Pt

import build_standalone_genealogy as model


def convert_references(text, remap):
    def replace(match):
        numbers = sorted({remap[int(n)] for n in re.findall(r"\d+", match[2])})
        return match[1] + "、".join(map(str, numbers)) + "页"
    return re.sub(r"(承上见|续见|详支)([\d、]+)页", replace, text)


def transform_page(page, scale, dx, dy):
    page = copy.deepcopy(page)
    for atom in page["atoms"]:
        if atom["kind"] == "line":
            for key in ["x1", "x2"]:
                atom[key] = atom[key] * scale + dx
            for key in ["y1", "y2"]:
                atom[key] = atom[key] * scale + dy
            atom["width"] *= scale
        else:
            atom["x"] = atom["x"] * scale + dx
            atom["y"] = atom["y"] * scale + dy
            for key in ["w", "h", "size"]:
                atom[key] *= scale
            for paragraph in atom.get("paragraphs", []):
                paragraph["size"] *= scale
                paragraph["leading"] *= scale
    for edge in page.get("connections", []):
        for key in ["parent_center", "child_center"]:
            edge[key] = edge[key] * scale + dx
        for key in ["start_y", "joint_y", "end_y"]:
            edge[key] = edge[key] * scale + dy
    return page


def write_presentation(pages, width, height, target):
    deck = Presentation()
    deck.slide_width, deck.slide_height = Pt(width), Pt(height)
    deck.core_properties.author = ""
    deck.core_properties.last_modified_by = ""
    deck.core_properties.title = "家族世系图"
    for page in pages:
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        for atom in page["atoms"]:
            if atom["kind"] == "line":
                shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Pt(atom["x1"]), Pt(atom["y1"]), Pt(atom["x2"]), Pt(atom["y2"]))
                shape.name = "亲属关系连线"
                shape.line.color.rgb = RGBColor.from_string("111827")
                shape.line.width = Pt(atom["width"])
                if atom.get("dashed"):
                    shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
                continue
            shape = slide.shapes.add_textbox(Pt(atom["x"]), Pt(atom["y"]), Pt(atom["w"]), Pt(atom["h"] + 2))
            shape.name = "人物信息" if atom.get("person_record") else "世系标注"
            frame = shape.text_frame
            frame.clear()
            frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
            frame.word_wrap = False
            frame.vertical_anchor = MSO_ANCHOR.TOP
            values = atom.get("paragraphs", [{**atom, "leading": atom["size"] * 1.16 + 0.8}])
            for i, value in enumerate(values):
                paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
                paragraph.alignment = {"center": PP_ALIGN.CENTER, "left": PP_ALIGN.LEFT, "right": PP_ALIGN.RIGHT}[value.get("align",atom["align"])]
                paragraph.space_before = paragraph.space_after = Pt(0)
                paragraph.line_spacing = Pt(value["leading"])
                run = paragraph.add_run()
                run.text = value["text"]
                run.font.name = "黑体" if value["bold"] else "宋体"
                run.font.size = Pt(value["size"])
                run.font.bold = value["bold"]
                run.font.color.rgb = RGBColor.from_string("111827")
                properties = run._r.get_or_add_rPr()
                east_asian = OxmlElement("a:ea")
                east_asian.set("typeface", run.font.name)
                properties.append(east_asian)
            shape._element.nvSpPr.cNvPr.set("descr", "原文记录：" + atom["person_record"] if atom.get("person_record") else "世系图标注")
        slide.notes_slide.notes_text_frame.text = "本页按原文关系编排。关系存在疑点的连线及注记继续保留待核实状态。"
    deck.save(target)


def main():
    parser = argparse.ArgumentParser(description="合并起首总览并导出可编辑演示文稿")
    for key in ["layout", "data", "plan", "registry", "out"]:
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.layout.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    data = json.loads(args.data.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8"))["record_to_person"]
    families, records, people, spouses, ids, initial = model.load_model(data, plan, registry)
    section = copy.deepcopy(plan["sections"][0])
    section.setdefault("generation_labels", plan.get("generation_labels", {}))
    if "records" not in section:
        section["records"] = [p["id"] for f in families if f["id"] in section["families"] for p in f["people"]]
    old_first = [p for p in source["pages"] if p["house_id"] == section["id"]]
    removed = len(old_first) - 1
    remap = {p["global_page"]: 1 if p in old_first else p["global_page"] - removed for p in source["pages"]}
    model.W, model.H = 2383.94, 1683.78
    model.LEFT, model.RIGHT, model.TOP, model.FLOOR = 72, 28, 170, 1480
    model.CELL, model.STEP = 104, 114
    original_blocks = model.node_blocks
    def larger_blocks(*values):
        blocks = original_blocks(*values)
        for block in blocks:
            lines = []
            for index, (text, size, bold) in enumerate(block["lines"]):
                new_size = 24 if index == 0 and bold else 15 if index == 0 else 14
                values = re.split(r"(?=（)", text) if index == 0 and bold else [text]
                for value in values:
                    lines.extend((part, new_size, bold) for part in model.chunks(value, (model.CELL + 3) / new_size))
            block["lines"] = lines
        return blocks
    model.node_blocks = larger_blocks
    built = model.layout_section(section, people, spouses, ids)
    assert len(built["pages"]) == 1, "起首总览仍需分页，不能强制压缩"
    mapping = defaultdict(list)
    for p in source["pages"]:
        for rid in p["record_ids"]:
            if rid in people and remap[p["global_page"]] not in mapping[rid]:
                mapping[rid].append(remap[p["global_page"]])
    for rid in section["records"]:
        mapping[rid] = [1]
    first = model.render(built, 0, people, spouses, ids, mapping, 0, [built])
    model.node_blocks = original_blocks
    for atom in first["atoms"]:
        if atom["kind"] != "text":
            continue
        is_marker = atom["text"] in ["嗣", "继", "待核", "女系"]
        if is_marker:
            atom["size"] = 12
            atom["h"] = 19
        if atom["y"] >= 809 and not atom.get("person_record") and not atom.get("generation_label") and not is_marker:
            atom["y"] += 810
            atom["size"] = 12
            atom["h"] = 20
        elif atom["y"] >= 756 and not atom.get("person_record") and not atom.get("generation_label") and not is_marker:
            atom["y"] = 1530 + (atom["y"] - 756) / 11 * 19
            atom["size"] = 12
            atom["h"] = 20
        if atom.get("generation_label"):
            atom["w"] = 90
            atom["paragraphs"][0].update(size=18, leading=24)
            for paragraph in atom["paragraphs"][1:]:
                paragraph.update(size=12, leading=18)
            atom["h"] = sum(p["leading"] for p in atom["paragraphs"]) + 2
    first["atoms"][0]["text"] = section["title"] + "（完整总览）"
    first["atoms"][0]["size"] = 36
    first["atoms"][0]["h"] = 48
    first["atoms"][1]["y"] = 83
    first["atoms"][1]["size"] = 15
    first["atoms"][1]["h"] = 24
    first["atoms"][2]["y"] = 114
    first["atoms"][2]["size"] = 14
    first["atoms"][2]["h"] = 23
    pages = [first]
    scale = min(model.W / source["width"], model.H / source["height"])
    dx = (model.W - source["width"] * scale) / 2
    dy = (model.H - source["height"] * scale) / 2
    for old in source["pages"]:
        if old in old_first:
            continue
        page = transform_page(old, scale, dx, dy)
        page["global_page"] = remap[old["global_page"]]
        for atom in page["atoms"]:
            if atom["kind"] == "text":
                atom["text"] = convert_references(atom["text"], remap)
                for paragraph in atom.get("paragraphs", []):
                    paragraph["text"] = convert_references(paragraph["text"], remap)
        page["atoms"][-1]["text"] = str(page["global_page"])
        pages.append(page)
    assert {r for p in pages for r in p["record_ids"]} == set(records), "存在人物遗漏"
    assert set(first["record_ids"]) == {r for p in old_first for r in p["record_ids"]}, "总览人物不一致"
    for page in pages:
        for atom in page["atoms"]:
            if atom["kind"] == "text":
                assert 0 <= atom["x"] <= model.W - atom["w"] + 0.1
                assert 0 <= atom["y"] <= model.H - atom["h"] + 0.1
    groups = []
    for house in source["houses"]:
        selected = [p for p in pages if p["house_id"] == house[0]]
        groups.append([house[0], house[1], len(selected), selected[0]["global_page"], selected[-1]["global_page"]])
    args.out.mkdir(parents=True, exist_ok=True)
    payload = {**source, "width": model.W, "height": model.H, "pages": pages, "houses": groups, "page_count": len(pages)}
    (args.out / "演示文稿版面.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_presentation(pages, model.W, model.H, args.out / (plan["title"] + "_全册可编辑.pptx"))
    write_presentation([first], model.W, model.H, args.out / "始祖与五门世系_单张总览.pptx")
    model.report(plan, families, records, people, spouses, ids, pages, groups, args.out / (plan["title"] + "_演示文稿人物索引.docx"))
    print(f"合并前{len(old_first)}页总览，合并后1张；全册{len(pages)}张。人物、配偶和连线均为独立可编辑对象。")


if __name__ == "__main__":
    main()
