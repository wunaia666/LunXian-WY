"""按核对后的图册页序移动原稿段落，不改动文字或段落格式。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def paragraph_text(element):
    return "".join(element.xpath(".//w:t/text()", namespaces=NS))


def canonical(element):
    return etree.tostring(element, method="c14n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_order(paragraphs, layout, start):
    records = layout["original_records"]
    ledger = {entry["para"]: entry for entry in layout["source_ledger"]}
    first_page = {}
    gate_start = {}
    for page in layout["pages"]:
        gate_start.setdefault(page["gate_number"], page["global_page"])
        for rid in page["record_ids"]:
            first_page.setdefault(rid, page["global_page"])
    boundaries = []
    for number in range(start, len(paragraphs)+1):
        text = re.sub(r"\s+", "", paragraph_text(paragraphs[number-1]))
        if not text.startswith("【"):
            continue
        beginning = number
        # 标题前的共用代次或阅读说明随第一个房支移动，不复制、不重写。
        previous = re.sub(r"\s+", "", paragraph_text(paragraphs[number-2])) if number > start else ""
        if re.match(r"^第[一二三四五六七八九十百]+[代世]", previous) or previous.startswith(("（从第六代开始", "(从第六代开始")):
            beginning -= 1
        gate = re.match(r"^【([长一二三四五])门", text)
        assert gate, ("原稿房支标题未识别", number, text)
        gate_number = {"长": 1, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5}[gate[1]]
        boundaries.append({"start": beginning, "heading": number, "title": paragraph_text(paragraphs[number-1]), "gate": gate_number})
    assert boundaries, "原稿没有可独立移动的房支标题"
    common_end = boundaries[0]["start"]
    units = []
    for index, boundary in enumerate(boundaries):
        end = boundaries[index+1]["start"] if index+1 < len(boundaries) else len(paragraphs)+1
        numbers = list(range(boundary["start"], end))
        related = list(dict.fromkeys(rid for n in numbers if n in ledger for rid in ledger[n]["records"]))
        candidates = [rid for rid in related if not records[rid].get("owner")]
        assert candidates and all(r in first_page for r in candidates), ("房支未对应图册人物", boundary)
        page_number = max(gate_start[boundary["gate"]], min(first_page[r] for r in candidates))
        units.append({"paragraphs": numbers, "records": related, "page": page_number, "first_source_paragraph": numbers[0], "gate": boundary["gate"], "title": boundary["title"]})
    # 按完整房支移动，房支内部的父母、配偶、子女、代次及其后代仍按原稿连续。
    ordered = sorted(units, key=lambda v: (v["gate"], v["page"], v["first_source_paragraph"]))
    order = list(range(1, common_end)) + [n for unit in ordered for n in unit["paragraphs"]]
    assert len(order) == len(paragraphs) and set(order) == set(range(1, len(paragraphs)+1)), "原段落漏排或重复"
    assert [u["page"] for u in ordered] == sorted(u["page"] for u in ordered), "图页顺序不一致"
    return order, ordered


def verify(source, target, order):
    with ZipFile(source) as original, ZipFile(target) as result:
        assert original.namelist() == result.namelist(), "文档部件增删"
        changed = [name for name in original.namelist() if original.read(name) != result.read(name)]
        assert changed == ["word/document.xml"], ("正文外的文档部件被改动", changed)
        old = etree.fromstring(original.read("word/document.xml"))
        new = etree.fromstring(result.read("word/document.xml"))
        old_paragraphs = old.findall("w:body/w:p", NS)
        new_paragraphs = new.findall("w:body/w:p", NS)
        assert len(old_paragraphs) == len(new_paragraphs) == len(order), "段落数变化"
        assert Counter(canonical(p) for p in old_paragraphs) == Counter(canonical(p) for p in new_paragraphs), "段落文字或格式有变化"
        for number, source_number in enumerate(order):
            assert canonical(new_paragraphs[number]) == canonical(old_paragraphs[source_number-1]), ("段落不是原样移动", number+1, source_number)
        assert canonical(old.find("w:body/w:sectPr", NS)) == canonical(new.find("w:body/w:sectPr", NS)), "页面设置变化"
        old_body, new_body = old.find("w:body", NS), new.find("w:body", NS)
        for p in list(old_paragraphs):
            old_body.remove(p)
        for p in list(new_paragraphs):
            new_body.remove(p)
        assert canonical(old) == canonical(new), "段落次序以外的正文结构有变化"
        assert result.testzip() is None, "文档封装损坏"
    return {"源段落数": len(order), "段落文字及格式逐项一致": True, "正文外全部部件逐字节一致": True, "页面设置一致": True, "新增或删除段落": 0}


def main():
    parser = argparse.ArgumentParser(description="按图册顺序重排原文，原段落及其他部件保持不变")
    for name in ["source", "layout", "presentation", "out", "audit"]:
        parser.add_argument("--"+name, required=True, type=Path)
    parser.add_argument("--start", type=int, default=57)
    args = parser.parse_args()
    original_hash = digest(args.source)
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    deck = Presentation(args.presentation)
    assert len(deck.slides) == len(layout["pages"]), "图册与页序依据不一致"
    for slide, page in zip(deck.slides, layout["pages"]):
        actual = []
        for shape in slide.shapes:
            nodes = shape._element.xpath(".//p:cNvPr")
            text = nodes[0].get("descr", "") if nodes else ""
            if text.startswith("原文记录："):
                actual.append(text.split("：", 1)[1])
        assert set(actual) == set(page["record_ids"]), "实际图页人物与页序依据不一致"
    with ZipFile(args.source) as package:
        root = etree.fromstring(package.read("word/document.xml"))
        body = root.find("w:body", NS)
        paragraphs = body.findall("w:p", NS)
        assert all(child.tag in [f"{{{W}}}p", f"{{{W}}}sectPr"] for child in body), "本工具不移动含表格等其他正文对象的文档"
        order, units = build_order(paragraphs, layout, args.start)
        for paragraph in paragraphs:
            body.remove(paragraph)
        for position, source_number in enumerate(order):
            body.insert(position, paragraphs[source_number-1])
        content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(args.out, "w") as output:
            for entry in package.infolist():
                output.writestr(entry, content if entry.filename == "word/document.xml" else package.read(entry.filename))
    checks = verify(args.source, args.out, order)
    assert digest(args.source) == original_hash, "原始文件被修改"
    inverse = {source_number: target_number for target_number, source_number in enumerate(order, 1)}
    audit = {"原稿摘要": original_hash, "重排稿摘要": digest(args.out), "保留前言段落数": args.start-1, "依据图册页数": len(deck.slides), "实际移动位置段落数": sum(number != old for number, old in enumerate(order, 1)), "核验": checks, "重排顺序": order, "排图单元": units, "原段对应新段": inverse}
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print("保留开头", args.start-1, "段；按图册顺序排列", len(units), "组；原稿与重排稿均", len(order), "段。")
    print("文字、标点、空格、字体及段落格式逐段完全一致；除正文段落顺序外，全部文档部件保持不变。")


if __name__ == "__main__":
    main()
