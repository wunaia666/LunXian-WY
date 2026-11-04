"""独立从原稿和成品逐项检查人物框、原文、子女名单与数量。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from docx import Document
from pptx import Presentation


def key(value):
    return "".join(c for c in value if not c.isspace() and not unicodedata.category(c).startswith("P"))


def sex(person):
    if person.get("sex") in ["男", "女"]:
        return person["sex"]
    if "女" in person.get("role", ""):
        return "女"
    if "子" in person.get("role", ""):
        return "男"
    return "未注"


def audit(source, presentation, layout, plan, pdf=None):
    original = [p.text for p in Document(source).paragraphs]
    records = layout["original_records"]
    people = {r: p for r, p in records.items() if not p.get("owner") and not p.get("related_to")}
    source_ledger = {v["para"]: v for v in layout["source_ledger"]}
    problems, pending = [], []
    deck = Presentation(presentation)
    boxes, actual_pages, page_texts = defaultdict(list), [], []
    shape_count = Counter()
    for number, slide in enumerate(deck.slides, 1):
        local, all_text = [], []
        planned = layout["pages"][number-1]["atoms"]
        if len(slide.shapes) != len(planned):
            problems.append(["实际页面对象数与排图不符", number])
        for shape, atom in zip(slide.shapes, planned):
            if atom["kind"] == "line":
                coordinates = [shape.begin_x.pt, shape.begin_y.pt, shape.end_x.pt, shape.end_y.pt]
                expected = [atom[k] for k in ["x1", "y1", "x2", "y2"]]
            else:
                coordinates = [shape.left.pt, shape.top.pt, shape.width.pt, shape.height.pt]
                expected = [atom["x"], atom["y"], atom["w"], atom["h"]+2]
            if any(abs(a-b) > 0.01 for a, b in zip(coordinates, expected)):
                problems.append(["实际文字框或接线位置与排图不符", number, coordinates, expected])
        person_atoms = [a for a in planned if a.get("person_record")]
        for atom in planned:
            if atom["kind"] != "line":
                continue
            x1, x2 = sorted([atom["x1"], atom["x2"]])
            y1, y2 = sorted([atom["y1"], atom["y2"]])
            for box in person_atoms:
                vertical = abs(x1-x2)<0.1 and box["x"]+1<x1<box["x"]+box["w"]-1 and max(y1, box["y"]+1)<min(y2, box["y"]+box["h"]-1)
                horizontal = abs(y1-y2)<0.1 and box["y"]+1<y1<box["y"]+box["h"]-1 and max(x1, box["x"]+1)<min(x2, box["x"]+box["w"]-1)
                if vertical or horizontal:
                    problems.append(["连线穿过人物文字框", number, box["person_record"]])
        for connection in layout["pages"][number-1]["connections"]:
            if connection.get("additional"):
                continue
            for role in ["parent", "child"]:
                rid = connection[role]
                box = next(a for a in person_atoms if a["person_record"] == rid)
                if abs(box["x"]+box["w"]/2-connection[role+"_center"]) > 0.01:
                    problems.append(["接线未对准人物中心", number, rid])
        for shape in slide.shapes:
            shape_count["总对象"] += 1
            if shape.shape_type == 13:
                problems.append(["图片替代原生对象", number])
            if shape._element.xpath(".//a:prstDash[@val!='solid']"):
                problems.append(["发现虚线", number])
            if shape.has_text_frame:
                text = "\n".join(p.text for p in shape.text_frame.paragraphs)
                all_text.append(text)
                nodes = shape._element.xpath(".//p:cNvPr")
                description = nodes[0].get("descr", "") if nodes else ""
                if description.startswith("原文记录："):
                    rid = description.split("：", 1)[1]
                    boxes[rid].append({"页": number, "文字": text})
                    local.append(rid)
                    shape_count["人物文本框"] += 1
                if re.search(r"(?:详支|续见|承上见)\s*\d+[、，\d\s]*页", text):
                    problems.append(["发现跳页提示", number, text])
        if len(local) != len(set(local)):
            problems.append(["同页一个人物记录使用多个文本框", number])
        actual_pages.append(set(local))
        page_texts.append("\n".join(all_text))
    if set(boxes) != set(records):
        problems.append(["成品人物框与记录不一致", sorted(set(records)-set(boxes)), sorted(set(boxes)-set(records))])
    # 直接以原始人物行检查自己的文本框，不以生成器已分好的正文片段代替原文。
    personal_checks = []
    for rid, person in records.items():
        if rid.startswith("补"):
            continue
        para = person["para"]
        raw = key(person["raw"])
        if raw not in key(original[para-1]):
            problems.append(["人物原始行不在来源段落", rid, para])
        name = key(person["name"])
        position = raw.find(name)
        if position < 0:
            problems.append(["原始行未找到人物姓名", rid, para])
            continue
        prefix, suffix = raw[:position], raw[position+len(name):]
        for box in boxes[rid]:
            displayed = key(box["文字"])
            for part, value in [("姓名", name), ("称谓", prefix), ("全部原文详情", suffix)]:
                if value and value not in displayed:
                    problems.append(["人物原文信息缺失", rid, para, box["页"], part, value])
        personal_checks.append({"记录": rid, "原稿段": para, "姓名": person["name"], "图页": sorted({b["页"] for b in boxes[rid]})})
    # 整段覆盖另行从原稿枚举；标题只核实实质尾文，不能漏过未展开的独立说明。
    primary = defaultdict(list)
    for rid, person in records.items():
        if not rid.startswith("补"):
            primary[person["para"]].append(rid)
    paragraph_checks = []
    for para, raw in enumerate(original, 1):
        compact = re.sub(r"\s+", "", raw).replace("※", "")
        if para < plan.get("verbatim_start", 57) or not compact:
            continue
        if compact.startswith(("（从第六代开始", "(从第六代开始")):
            continue
        substantive = compact
        if compact.startswith("【") and "】" in compact:
            substantive = compact.split("】", 1)[1]
        else:
            title = re.match(r"^第[一二三四五六七八九十百]+[代世](?:[：:]?〖.*?〗)?", compact)
            if title:
                substantive = compact[title.end():].strip("：:")
        if not substantive:
            continue
        if para not in source_ledger:
            problems.append(["实质原文段落未进入对照表", para, raw])
            continue
        entry = source_ledger[para]
        if entry["original"] != raw:
            problems.append(["对照表篡改原文", para])
        if primary[para]:
            if key("".join(records[r]["raw"] for r in primary[para])) != key(substantive):
                problems.append(["拆分人物行遗漏来源内容", para])
        else:
            expected = key(substantive)
            if expected.startswith("妻室"):
                expected = expected[2:]
            if not any(expected in key(b["文字"]) for rid in entry["records"] for b in boxes[rid]):
                problems.append(["独立说明没有完整写入人物框", para, substantive])
        paragraph_checks.append({"原稿段": para, "人物记录": entry["records"]})
    # 子女名单从原稿重新解析，必须对应直接子女的独立框，父母框里出现姓名不算通过。
    parent = layout["plot_parents"]
    canonical = {r: r for r in people}
    for source_id, target_id in plan.get("same_person", []):
        canonical[source_id] = target_id
    children = defaultdict(set)
    for rid, par in parent.items():
        if par:
            children[par].add(rid)
    for relation in plan.get("additional_relations", []):
        children[relation["from_record"]].add(relation["to_record"])
    equivalents = {(x["paragraph"], x["source_name"]): x for x in plan.get("source_name_equivalents", [])}
    quantities, names = [], []
    numeral = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    expression = r"(?P<verb>收养|育|生|养)(?P<quantity>[一二两三四五六七八九十]+[子女](?:[一二两三四五六七八九十]+[子女])?)"
    for para, raw in enumerate(original, 1):
        if para < 57 or para not in source_ledger:
            continue
        compact = re.sub(r"\s+", "", raw)
        owners = {records[r].get("owner", r) for r in source_ledger[para]["records"]}
        pool = set()
        for owner in owners:
            local = children[owner]
            if not local:
                local = {c for r in people if canonical.get(r, r) == canonical.get(owner, owner) for c in children[r]}
            pool.update(local)
        if str(para) in plan.get("paragraph_child_scope", {}):
            specified = set(plan["paragraph_child_scope"][str(para)]["records"])
            allowed = {c for owner in owners for r in people if canonical.get(r, r) == canonical.get(owner, owner) for c in children[r]}
            if not specified <= allowed:
                problems.append(["跨处接续核对范围超出同一父辈", para, sorted(specified-allowed)])
            pool = specified
        for match in re.finditer(expression, compact):
            counts = {"男" if s == "子" else "女": numeral[n] for n, s in re.findall(r"([一二两三四五六七八九十]+)([子女])", match["quantity"])}
            after = compact[match.end():]
            listed = []
            if after.startswith(("：", ":")):
                tail = re.split(r"[。；;，,）]", after[1:], 1)[0]
                listed = tail.split("、")
                total = sum(counts.values())
                if len(listed) == 1 and total > 1 and len(tail) == total*2:
                    listed = [tail[i:i+2] for i in range(0, len(tail), 2)]
            selected = set()
            usable_names = 0
            for token in listed:
                token = re.sub(r"^(?:长|次|三|四|五|六|七|八|九|十)[子女]", "", token)
                token = re.split(r"[（(]", token, 1)[0]
                if token.startswith("名") and not token.startswith("名讳"):
                    token = token[1:]
                if not token or token in ["成人", "幼年夭折", "名讳失考", "名讳失考）", "长女", "次女", "三女"]:
                    continue
                hits = []
                for rid in pool:
                    p = records[rid]
                    choices = {p["name"], p["name"][1:] if p["name"].startswith("张") else p["name"]}
                    choices.update(re.findall(r"(?:乳名|又名)([\u3400-\u9fff]{1,4})(?=[）)，,；;]|$)", re.sub(r"\s+", "", p.get("raw", ""))))
                    if token in choices:
                        hits.append(rid)
                special = equivalents.get((para, token))
                status = "独立人物框已对应"
                if not hits and special:
                    hits = [special["record_id"]]
                    status = "异名对应待核"
                    pending.append(["名单异名", para, token, hits[0], special["basis"]])
                    located = owners | set(source_ledger[para]["records"])
                    if token not in key("".join(b["文字"] for owner in located for b in boxes[owner])):
                        problems.append(["异名原字未保留", para, token])
                if not hits:
                    problems.append(["子女名单没有对应独立人物框", para, token, sorted(pool)])
                for rid in hits:
                    if rid not in boxes:
                        problems.append(["子女独立框缺失", para, token, rid])
                selected.update(hits)
                usable_names += 1
                names.append({"原稿段": para, "原文姓名": token, "对应记录": hits, "状态": status})
            available = set(pool)
            if usable_names == sum(counts.values()) and len(selected) == sum(counts.values()):
                available = selected
            elif match["verb"] in ["收养", "养"]:
                available = {r for r in available if re.search("收养|承嗣", records[r].get("edge_kind", ""))}
            elif any(re.search("收养|承嗣", records[r].get("edge_kind", "")) for r in available):
                available = {r for r in available if not re.search("收养|承嗣", records[r].get("edge_kind", ""))}
            scope = plan.get("quantity_scope", {}).get(str(para)+":"+match.group())
            if scope:
                if not set(scope["records"]) <= pool:
                    problems.append(["人工注明的数量范围不属于本房子女", para, scope])
                available = set(scope["records"])
            actual = Counter(sex(records[r]) for r in available)
            mismatch = {s: [n, actual[s]] for s, n in counts.items() if actual[s] != n}
            item = {"原稿段": para, "原文数量": match.group(), "原记": counts, "图内对应": dict(actual), "记录": sorted(available), "数量差异": mismatch}
            quantities.append(item)
            if mismatch:
                pending.append(["数量对应需要复查", item])
    # 对照图中接续和资料层的父子关系；每条接续必须在某页实际画出。
    drawn = {(e["parent"], e["child"]) for page in layout["pages"] for e in page["connections"]}
    for rid, par in parent.items():
        if par and (par, rid) not in drawn:
            problems.append(["关系未画入成品", par, rid])
        if par and people[rid]["generation"] <= people[par]["generation"]:
            problems.append(["子辈代次未低于上辈", par, rid])
    for page, actual in zip(layout["pages"], actual_pages):
        if actual != set(page["record_ids"]):
            problems.append(["实际幻灯片与版面记录不一致", page["global_page"]])
    gates = [p["gate_number"] for p in layout["pages"]]
    if gates != sorted(gates):
        problems.append(["门序交错", gates])
    pdf_failures = []
    if pdf:
        import pymupdf as fitz
        with fitz.open(pdf) as rendered:
            if len(rendered) != len(page_texts):
                problems.append(["打印稿页数不一致", len(rendered), len(page_texts)])
            for number, page in enumerate(rendered, 1):
                displayed = key(page.get_text())
                for atom in layout["pages"][number-1]["atoms"]:
                    if atom["kind"] == "text" and key(atom["text"]) not in displayed:
                        pdf_failures.append([number, atom.get("person_record"), atom["text"]])
        problems.extend(["打印稿文字缺失", x] for x in pdf_failures)
    return {"原稿摘要": hashlib.sha256(Path(source).read_bytes()).hexdigest(), "原稿总段数": len(original), "实质段落检查数": len(paragraph_checks), "原始人物记录检查数": len(personal_checks), "全部人物及资料记录数": len(records), "成品页数": len(deck.slides), "对象统计": dict(shape_count), "名单人名检查数": len(names), "数量表达检查数": len(quantities), "硬错误": problems, "需说明的待核项目": pending, "逐人原文检查": personal_checks, "逐段检查": paragraph_checks, "名单检查": names, "数量检查": quantities}


def main():
    parser = argparse.ArgumentParser(description="独立核验原稿与最终可编辑成品")
    for name in ["source", "presentation", "layout", "plan", "out"]:
        parser.add_argument("--"+name, required=True, type=Path)
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    result = audit(args.source, args.presentation, read(args.layout), read(args.plan), args.pdf)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("成品页数", result["成品页数"], "实质段落", result["实质段落检查数"], "名单人名", result["名单人名检查数"], "数量表达", result["数量表达检查数"], "硬错误", len(result["硬错误"]), "待核项目", len(result["需说明的待核项目"]))
    for item in result["硬错误"][:12]:
        print(item)
    if result["硬错误"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
