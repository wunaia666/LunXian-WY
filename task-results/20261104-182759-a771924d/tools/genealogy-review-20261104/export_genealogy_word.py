"""把系谱图版面转换为文字文档原生组合图形，姓名与连线可分别编辑。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from lxml import etree


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def element(tag, **attributes):
    prefix, local = tag.split(":")
    value = etree.Element("{" + NS[prefix] + "}" + local)
    for key, data in attributes.items():
        value.set(key, str(data))
    return value


def add(parent, tag, **attributes):
    child = element(tag, **attributes)
    parent.append(child)
    return child


def emu(points):
    return round(points * 12700)


def transform(parent, x, y, width, height, flip_h=False, flip_v=False):
    attributes = {}
    if flip_h:
        attributes["flipH"] = "1"
    if flip_v:
        attributes["flipV"] = "1"
    xf = add(parent, "a:xfrm", **attributes)
    add(xf, "a:off", x=emu(x), y=emu(y))
    add(xf, "a:ext", cx=emu(width), cy=emu(height))


def shape(atom):
    node = element("wps:wsp")
    add(node, "wps:cNvSpPr", **({"txBox": "1"} if atom["kind"] == "text" else {}))
    properties = add(node, "wps:spPr")
    if atom["kind"] == "frame":
        transform(properties, 0, 0, atom["w"], atom["h"])
        geometry = add(properties, "a:prstGeom", prst="rect")
        add(geometry, "a:avLst")
        fill = add(properties, "a:solidFill")
        add(fill, "a:srgbClr", val="FFFFFF")
        line = add(properties, "a:ln")
        add(line, "a:noFill")
        add(node, "wps:bodyPr")
        return node
    if atom["kind"] == "line":
        transform(properties, min(atom["x1"], atom["x2"]), min(atom["y1"], atom["y2"]),
                  abs(atom["x2"] - atom["x1"]), abs(atom["y2"] - atom["y1"]),
                  atom["x2"] < atom["x1"], atom["y2"] < atom["y1"])
        geometry = add(properties, "a:prstGeom", prst="line")
        add(geometry, "a:avLst")
        line = add(properties, "a:ln", w=emu(atom["width"]), cap="flat")
        fill = add(line, "a:solidFill")
        add(fill, "a:srgbClr", val="111827")
        add(line, "a:prstDash", val="dash" if atom["dashed"] else "solid")
        add(node, "wps:bodyPr")
        return node
    transform(properties, atom["x"], atom["y"], atom["w"], atom["h"])
    geometry = add(properties, "a:prstGeom", prst="rect")
    add(geometry, "a:avLst")
    add(properties, "a:noFill")
    line = add(properties, "a:ln")
    add(line, "a:noFill")
    text_box = add(node, "wps:txbx")
    content = add(text_box, "w:txbxContent")
    paragraph = add(content, "w:p")
    ppr = add(paragraph, "w:pPr")
    spacing = add(ppr, "w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    spacing.set(qn("w:line"), str(round(atom["size"] * 20)))
    spacing.set(qn("w:lineRule"), "exact")
    alignment = add(ppr, "w:jc")
    alignment.set(qn("w:val"), {"center": "center", "left": "left", "right": "right"}[atom["align"]])
    run = add(paragraph, "w:r")
    rpr = add(run, "w:rPr")
    fonts = add(rpr, "w:rFonts")
    for key in ["ascii", "hAnsi", "eastAsia", "cs"]:
        fonts.set(qn("w:" + key), "黑体" if atom["bold"] else "宋体")
    if atom["bold"]:
        add(rpr, "w:b")
    color = add(rpr, "w:color")
    color.set(qn("w:val"), "111827")
    for key in ["sz", "szCs"]:
        size = add(rpr, "w:" + key)
        size.set(qn("w:val"), str(round(atom["size"] * 2)))
    lang = add(rpr, "w:lang")
    lang.set(qn("w:eastAsia"), "zh-CN")
    text = add(run, "w:t")
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = atom["text"]
    body = add(node, "wps:bodyPr", rot="0", vertOverflow="overflow", horzOverflow="overflow",
               vert="horz", wrap="square", lIns="0", tIns="0", rIns="0", bIns="0",
               anchor="t", anchorCtr="0", compatLnSpc="1")
    add(body, "a:noAutofit")
    return node


def append_graph(paragraph, page, width, height, identifier):
    drawing = OxmlElement("w:drawing")
    anchor = element("wp:anchor", distT="0", distB="0", distL="0", distR="0", simplePos="0",
                     relativeHeight="251658240", behindDoc="0", locked="0", layoutInCell="1", allowOverlap="1")
    add(anchor, "wp:simplePos", x="0", y="0")
    for direction in ["H", "V"]:
        position = add(anchor, "wp:position" + direction, relativeFrom="page")
        add(position, "wp:posOffset").text = "0"
    add(anchor, "wp:extent", cx=emu(width), cy=emu(height))
    add(anchor, "wp:effectExtent", l="0", t="0", r="0", b="0")
    add(anchor, "wp:wrapNone")
    add(anchor, "wp:docPr", id=identifier, name="系谱图第" + str(identifier) + "页", descr=page["house_title"] + "，姓名和连线可编辑")
    add(anchor, "wp:cNvGraphicFramePr")
    graphic = add(anchor, "a:graphic")
    data = add(graphic, "a:graphicData", uri=NS["wpg"])
    group = etree.SubElement(data, "{" + NS["wpg"] + "}wgp", nsmap={"wpg": NS["wpg"], "wps": NS["wps"]})
    add(group, "wpg:cNvGrpSpPr")
    group_properties = add(group, "wpg:grpSpPr")
    xf = add(group_properties, "a:xfrm")
    add(xf, "a:off", x="0", y="0")
    add(xf, "a:ext", cx=emu(width), cy=emu(height))
    add(xf, "a:chOff", x="0", y="0")
    add(xf, "a:chExt", cx=emu(width), cy=emu(height))
    # 全页底框固定组合图边界，避免文档软件按可见文字重新裁切并移动图形。
    group.append(shape({"kind": "frame", "w": width, "h": height}))
    for atom in page["atoms"]:
        group.append(shape(atom))
    drawing.append(anchor)
    paragraph.add_run()._r.append(drawing)


def write_document(pages, width, height, destination):
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Pt(width)
    section.page_height = Pt(height)
    section.top_margin = section.bottom_margin = Inches(0.4)
    section.left_margin = section.right_margin = Inches(0.4)
    section.header_distance = section.footer_distance = Pt(0)
    normal = document.styles["Normal"]
    normal.font.size = Pt(1)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = Pt(1)
    for index, page in enumerate(pages):
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.page_break_before = index > 0
        paragraph.paragraph_format.keep_with_next = False
        append_graph(paragraph, page, width, height, index + 1)
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.core_properties.title = "村志分户系谱图（可编辑文字文档）"
    zoom = document.settings.element.find(qn("w:zoom"))
    if zoom is not None:
        zoom.set(qn("w:percent"), "100")
    destination.parent.mkdir(parents=True, exist_ok=True)
    document.save(destination)
    with ZipFile(destination) as archive:
        assert not any(name.startswith("word/media/") for name in archive.namelist()), "图形不能被转成图片"
        root = etree.fromstring(archive.read("word/document.xml"))
        assert len(root.xpath("//wpg:wgp", namespaces=NS)) == len(pages)
        assert root.xpath("//w:t/text()", namespaces=NS) == [atom["text"] for page in pages for atom in page["atoms"] if atom["kind"] == "text"]


def main():
    parser = argparse.ArgumentParser(description="导出系谱图原生可编辑文字文档")
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pages", help="仅导出指定总册页码，用于检查版面")
    parser.add_argument("--split", action="store_true")
    args = parser.parse_args()
    source = json.loads(args.data.read_text(encoding="utf-8"))
    pages = source["pages"]
    if args.pages:
        wanted = {int(value) for value in args.pages.split(",")}
        pages = [p for p in pages if p["global_page"] in wanted]
    args.out.mkdir(parents=True, exist_ok=True)
    write_document(pages, source["width"], source["height"], args.out / "村志系谱图_可编辑.docx")
    if args.split:
        folder = args.out / "分户可编辑文档"
        folder.mkdir(exist_ok=True)
        for index, house in enumerate(source["houses"], 1):
            title = re.sub(r'[<>:"/\\|?*]', "", house[1])[:45]
            selected = [p for p in pages if p["house_id"] == house[0]]
            if selected:
                write_document(selected, source["width"], source["height"], folder / f"{index:02d}_{house[0]}_{title}.docx")
    print("已生成原生可编辑文字文档，图页数：", len(pages))


if __name__ == "__main__":
    main()
