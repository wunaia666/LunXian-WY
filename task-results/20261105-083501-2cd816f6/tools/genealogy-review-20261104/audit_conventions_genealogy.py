"""独立核验凡例版人物、代系、婚配、线型及实际打印文字。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from pptx import Presentation


def normalized(value):
    return re.sub(r"\s+", "", value)


def main():
    parser = argparse.ArgumentParser(description="核验凡例版的原生对象与资料一致性")
    for name in ["layout", "baseline", "presentation", "out"]:
        parser.add_argument("--"+name, required=True, type=Path)
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    layout, baseline = read(args.layout), read(args.baseline)
    records = layout["original_records"]
    problems, seen = [], set()
    count = Counter()
    if records != baseline["original_records"]:
        problems.append(["原始人物或关系资料发生变化"])
    if layout["plot_parents"] != baseline["plot_parents"]:
        problems.append(["世系接续发生变化"])
    deck = Presentation(args.presentation)
    if len(deck.slides) != len(layout["pages"]):
        problems.append(["图页数不一致"])
    for slide, page in zip(deck.slides, layout["pages"]):
        number = page["global_page"]
        if len(slide.shapes) != len(page["atoms"]):
            problems.append(["原生对象数量不一致", number])
        local = []
        for shape, atom in zip(slide.shapes, page["atoms"]):
            count[atom["kind"]] += 1
            if atom["kind"] == "text":
                if normalized(shape.text) != normalized(atom["text"]):
                    problems.append(["文本框文字不一致", number, atom.get("person_record")])
                if atom.get("person_record"):
                    nodes = shape._element.xpath(".//p:cNvPr")
                    if not nodes or nodes[0].get("descr", "") != "原文记录："+atom["person_record"]:
                        problems.append(["人物框编号不一致", number, atom["person_record"]])
                    local.append(atom["person_record"])
                if abs(shape.left.pt-atom["x"]) > 0.01 or abs(shape.top.pt-atom["y"]) > 0.01:
                    problems.append(["文字框坐标不一致", number])
            elif atom["kind"] == "line":
                expected = [atom[k] for k in ["x1", "y1", "x2", "y2"]]
                actual = [shape.begin_x.pt, shape.begin_y.pt, shape.end_x.pt, shape.end_y.pt]
                if any(abs(a-b) > 0.01 for a, b in zip(actual, expected)):
                    problems.append(["实际连线位置不一致", number])
                dashed = bool(shape._element.xpath(".//a:prstDash[@val!='solid']"))
                if dashed != bool(atom.get("dashed")):
                    problems.append(["实际虚实线不一致", number])
            elif atom["kind"] == "brace":
                if not shape._element.xpath(".//a:custGeom/a:pathLst/a:path/a:cubicBezTo"):
                    problems.append(["统括大括号不是原生曲线", number])
            if shape.shape_type == 13:
                problems.append(["存在图片替代原生内容", number])
        if len(local) != len(set(local)) or set(local) != set(page["record_ids"]):
            problems.append(["同页一人一框或覆盖异常", number])
        seen.update(local)
        if page["phase"] == "代系":
            for rid in local:
                if not records[rid].get("owner") and not records[rid].get("related_to") and records[rid]["generation"] > 5:
                    problems.append(["前五代部分混入后代", number, rid])
        people_boxes = [a for a in page["atoms"] if a.get("person_record")]
        for index, a in enumerate(people_boxes):
            for b in people_boxes[index+1:]:
                if max(a["x"], b["x"]) < min(a["x"]+a["w"], b["x"]+b["w"])-0.1 and max(a["y"], b["y"]) < min(a["y"]+a["h"], b["y"]+b["h"])-0.1:
                    problems.append(["人物框重叠", number, a["person_record"], b["person_record"]])
        for atom in page["atoms"]:
            if atom["kind"] != "line":
                continue
            x1, x2 = sorted([atom["x1"], atom["x2"]])
            y1, y2 = sorted([atom["y1"], atom["y2"]])
            for b in people_boxes:
                vertical = abs(x1-x2)<0.1 and b["x"]+1<x1<b["x"]+b["w"]-1 and max(y1, b["y"]+1)<min(y2, b["y"]+b["h"]-1)
                horizontal = abs(y1-y2)<0.1 and b["y"]+1<y1<b["y"]+b["h"]-1 and max(x1, b["x"]+1)<min(x2, b["x"]+b["w"]-1)
                if vertical or horizontal:
                    problems.append(["连线穿过人物框", number, b["person_record"]])
        for marriage in page["marriages"]:
            spouse = records[marriage["spouse"]]
            if spouse.get("owner") != marriage["person"]:
                problems.append(["婚配对象错误", number, marriage])
            a = next(v for v in people_boxes if v["person_record"] == marriage["person"])
            b = next(v for v in people_boxes if v["person_record"] == marriage["spouse"])
            if b["x"] <= a["x"]+a["w"]:
                problems.append(["夫妻未横向分列", number, marriage])
        for edge in page["connections"]:
            if "待核" in edge["label"] and edge["dashed"]:
                problems.append(["待核关系使用了虚线", number, edge])
    if seen != set(records):
        problems.append(["原有人物或资料未覆盖", sorted(set(records)-seen)])
    for rid, profile in baseline["profiles"].items():
        before = "".join(p["text"] for p in profile["paragraphs"] if not p["bold"])
        after = "".join(p["text"] for p in layout["profiles"][rid]["paragraphs"] if not p["bold"])
        if re.findall(r"\d+", before) != re.findall(r"\d+", after):
            problems.append(["日期或其他数字变化", rid])
        old = re.sub(r"[\s，,：:。；;（）()【】†△—－-]", "", before.replace("乳名", ""))
        new = re.sub(r"[\s，,：:。；;（）()【】†△—－-]", "", after)
        if old not in new:
            problems.append(["详细资料内容丢失", rid])
    expected_spouses = {(p["owner"], r) for r, p in records.items() if p.get("owner")}
    actual_spouses = {(m["person"], m["spouse"]) for p in layout["pages"] for m in p["marriages"]}
    if expected_spouses != actual_spouses:
        problems.append(["配偶横线未全部覆盖", sorted(expected_spouses-actual_spouses)])
    edges = {(e["parent"], e["child"]) for p in layout["pages"] for e in p["connections"]}
    for child, parent in layout["plot_parents"].items():
        if parent and (parent, child) not in edges:
            problems.append(["世系连线遗漏", parent, child])
    if args.pdf:
        import pymupdf
        with pymupdf.open(args.pdf) as rendered:
            if len(rendered) != len(layout["pages"]):
                problems.append(["打印稿页数不一致"])
            for number, page in enumerate(rendered, 1):
                visible = normalized(page.get_text())
                for atom in layout["pages"][number-1]["atoms"]:
                    if atom["kind"] == "text" and normalized(atom["text"]) not in visible:
                        problems.append(["打印稿文字缺失", number, atom.get("person_record"), atom["text"]])
    result = {"图页数": len(deck.slides), "人物及资料记录": len(records), "婚配对数": len(expected_spouses), "原生对象": dict(count), "硬错误": problems}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("检查", len(deck.slides), "页、", len(records), "条人物及资料、", len(expected_spouses), "对婚配；硬错误", len(problems))
    for value in problems[:12]:
        print(value)
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
