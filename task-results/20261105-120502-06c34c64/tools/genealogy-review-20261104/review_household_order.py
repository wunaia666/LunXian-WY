"""复核配偶下置、直线接续和房支顺序，另列带出处的待审核清单。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


def compact(value):
    return re.sub(r"\s+", "", value)


def main():
    parser = argparse.ArgumentParser(description="复查上下代、配偶下置、直线接续与分支先后")
    parser.add_argument("--layout", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.layout.read_text(encoding="utf-8"))
    records, pages = data["original_records"], data["pages"]
    houses = {h["户号"]: h["家族"] for h in data["households"]}
    page_map = defaultdict(list)
    problems = defaultdict(list)
    children = defaultdict(list)
    for rid, person in records.items():
        if not person.get("owner") and not person.get("render_as") and person.get("parent"):
            children[person["parent"]].append(rid)
    for values in children.values():
        values.sort(key=lambda rid: (records[rid].get("order", records[rid]["para"]), rid))

    def level(rid, trail=()):
        assert rid not in trail, "原始关系存在循环"
        person = records[rid]
        parent = person.get("parent")
        if parent in records and data["assigned"][rid] == data["assigned"][parent]:
            return level(parent, trail + (rid,)) + 1
        return person.get("generation", person.get("relative_gen", person.get("local_level", 1)))

    levels = {rid: level(rid) for rid, p in records.items() if not p.get("owner") and not p.get("render_as")}
    source_year_warnings=[]
    source_life_warnings=[]
    def source_year(person):
        if not person.get('original_record'):
            return None
        match=re.search(r'(?<!\d)((?:1[6-9]|20)\d{2})(?:年?生|年?[—－-]+)',compact(person['raw']))
        return int(match.group(1)) if match else None
    for rid,person in records.items():
        if person.get('original_record') and not person.get('render_as'):
            lifespan=re.search(r'(?<!\d)((?:1[6-9]|20)\d{2})年?[—－-]+((?:1[6-9]|20)\d{2})年?',compact(person['raw']))
            if lifespan and (int(lifespan[2])<int(lifespan[1]) or int(lifespan[2])-int(lifespan[1])>115):
                source_life_warnings.append(rid)
                if not person.get('issues') and not any('待核' in s for s in person.get('notes',[])):
                    problems['生卒异常尚未标待核'].append(rid)
        parent=records.get(person.get('parent'))
        if not parent or person.get('owner') or person.get('render_as') or any(word in person.get('edge_kind','') for word in ['承嗣','收养','继亲']):
            continue
        first,second=source_year(parent),source_year(person)
        if first and second and not 12<=second-first<=70:
            source_year_warnings.append({'人物':rid,'上代原记生年':first,'本人原记生年':second})
            if not person.get('issues') and not any('待核' in s for s in person.get('notes',[])):
                problems['生年异常尚未标待核'].append(rid)
    for page in pages:
        number, boxes, scale = page["global_page"], page["boxes"], page["scale"]
        assert page["vertical_partners"] and page["straight_family_stems"], "存在配偶右置页"
        for rid in page["record_ids"]:
            page_map[rid].append(number)
        lines = [a for a in page["atoms"] if a["kind"] == "line"]

        def has_line(x1, y1, x2, y2):
            return any(all(abs(a[k] - v) < .1 for k, v in zip(["x1", "y1", "x2", "y2"], [x1, y1, x2, y2])) for a in lines)

        grouped = defaultdict(list)
        for edge in page["connections"]:
            grouped[edge["parent"]].append(edge["child"])
        spans, expected_lines = [], 0
        for rid in page["members"]:
            box = boxes[rid]
            bottom = box["y"] + box["h"]
            for spouse in records[rid]["spouses"]:
                partner = boxes[spouse]
                if abs(partner["center"] - box["center"]) > .1 or partner["y"] < bottom + 30 * scale:
                    problems["配偶未按顺序下置"].append([number, rid, spouse])
                bottom = partner["y"] + partner["h"]
            same_generation = [other for other in page["members"] if levels[other] == levels[rid]]
            if any(abs(boxes[other]["y"] - box["y"]) > .1 for other in same_generation):
                problems["同代未对齐"].append([number, rid])
            local = [child for child in children[rid] if child in boxes]
            if local and [boxes[c]["center"] for c in local] != sorted(boxes[c]["center"] for c in local):
                problems["子女顺序不符原稿"].append([number, rid])
        for parent, kids in grouped.items():
            pb = boxes[parent]
            bottoms = [pb["y"] + pb["h"]] + [boxes[s]["y"] + boxes[s]["h"] for s in records[parent]["spouses"]]
            x, start = pb["center"], max(bottoms) + 7 * scale
            joint = boxes[kids[0]]["y"] - 46 * scale
            centers = [boxes[c]["center"] for c in kids]
            left, right = min([x] + centers), max([x] + centers)
            if not has_line(x, start, x, joint) or not has_line(left, joint, right, joint):
                problems["上代直线或横支线未对齐"].append([number, parent])
            expected_lines += 2 + len(kids)
            spans.append((parent, joint, left, right))
            for child in kids:
                cb = boxes[child]
                if levels[child] != levels[parent] + 1 or cb["y"] <= pb["y"]:
                    problems["上下代位置错误"].append([number, parent, child])
                if not has_line(cb["center"], joint, cb["center"], cb["y"] - 9 * scale):
                    problems["下代接线未对准"].append([number, child])
        if len(lines) != expected_lines:
            problems["多余或遗漏的折线"].append([number, len(lines), expected_lines])
        for a, b in combinations(spans, 2):
            if abs(a[1] - b[1]) < .1 and min(a[3], b[3]) - max(a[2], b[2]) >= -.1:
                problems["不同家庭横支线误接"].append([number, a[0], b[0]])

    def descendants(rid):
        return {rid}.union(*(descendants(child) for child in children[rid]))

    for parent, kids in list(children.items()):
        previous_last = -1
        for child in kids:
            all_pages = [n for desc in descendants(child) for n in page_map[desc]]
            if all_pages:
                if min(all_pages) < previous_last:
                    problems["跨页房支顺序交叉"].append([parent, child])
                previous_last = max(all_pages)

    # 对已标注的疑点、补录正文中的疑点和异常生年分别检查，避免只读取旧清单。
    pending = []
    house_order = {h['户号']: n for n, h in enumerate(data['households'])}
    ordered_records = sorted(records.items(), key=lambda item: (house_order[data['assigned'][item[0]]], item[1]['para'], item[0]))
    for rid, person in ordered_records:
        target = person.get("render_as", rid)
        reasons = []
        reasons.extend("待核：" + s for s in person.get("issues", []))
        reasons.extend(s for s in person.get("notes", []) if "待核" in s)
        reasons.extend(s for s in data["profiles"][target]["body"] if "待核" in s)
        if "待核" in person.get("edge_kind", ""):
            reasons.append("亲属接线性质待核：" + person["edge_kind"])
        if person.get("continuation_of"):
            continue
        if not reasons:
            continue
        reasons = list(dict.fromkeys(reasons))
        # 同一疑点已包含在长段落中时，避免重复列出短句。
        reasons = [s for s in reasons if not any(s != other and s in other for other in reasons)]
        parent = person.get("owner") or person.get("parent")
        source = "\n".join(f"第{x['para']}段：{x['text']}" for x in person["fragments"])
        pending.append({"序号": len(pending) + 1, "户号": data["assigned"][rid], "家族": houses[data["assigned"][rid]],
                        "姓名或原称谓": person["name"], "当前对应亲属": records.get(parent, {}).get("name", "上代未定"),
                        "所在图页": "、".join(map(str, sorted(set(page_map[target])))), "原稿段号": person["para"],
                        "待审核事项": "\n".join(reasons), "原文出处": source,
                        "核查建议": "请对照所列原文，确认对应人物、上代归属或记载差异；确认前保留原记。", "确认结果": "", "记录编号": rid})

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "待审核事项清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(pending[0]))
        writer.writeheader(); writer.writerows(pending)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "待审核事项"
    sheet.append(list(pending[0]))
    for row in pending:
        sheet.append(list(row.values()))
    sheet.freeze_panes = "D2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = [7, 10, 28, 18, 20, 18, 12, 62, 72, 46, 38, 22]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    for row in sheet:
        for cell in row:
            cell.font = Font(name="宋体", size=11, color="000000")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for cell in sheet[1]:
        cell.font = Font(name="黑体", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="333333")
    sheet.row_dimensions[1].height = 30
    for index, row in enumerate(pending, 2):
        sheet.row_dimensions[index].height = min(240, max(60, 18 * max(len(row['待审核事项']) // 28 + row['待审核事项'].count('\n') + 1, len(row['原文出处']) // 34 + 1)))
    intro = workbook.create_sheet("使用说明", 0)
    for line in ["待审核事项清单", "原稿为指定的《总》；图页为本次配偶下置直线版整册页码。", "请在“确认结果”列填写核查结论。未确认前，图中保留“待核”。", "本清单列关系、归属和记载差异等已发现疑点；原稿未载的普通生卒资料不逐项催补。", "记录编号仅为核对定位使用，不在系谱图中显示。", f"共{len(pending)}条人物记录涉及待审核事项。"]:
        intro.append([line])
    intro.column_dimensions['A'].width = 120
    for row in intro:
        row[0].font = Font(name="宋体", size=12)
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
        intro.row_dimensions[row[0].row].height = 38
    path = args.out / "待审核事项清单.xlsx"
    workbook.save(path)
    check = load_workbook(path, read_only=True, data_only=False)
    assert check["待审核事项"].max_row == len(pending) + 1
    check.close()
    readable = ["待审核事项清单", f"共{len(pending)}条人物记录涉及待审核事项。", "图页为本次配偶下置直线版整册页码。", ""]
    for row in pending:
        readable.extend([f"{row['序号']}．{row['家族']}／{row['姓名或原称谓']}（整册第{row['所在图页']}页，原稿第{row['原稿段号']}段）", row['待审核事项'], "原文：" + row['原文出处'], ""])
    (args.out / "待审核事项清单.txt").write_text("\n".join(readable), encoding="utf-8-sig")
    result = {"检查页数": len(pages), "检查户数": len(houses), "配偶下置": True, "关系图形检查": dict(problems), "原记生年异常且已标待核":source_year_warnings,"原记生卒异常且已标待核":source_life_warnings,"待审核记录数": len(pending), "待审核涉及户数": len({r['户号'] for r in pending})}
    (args.out / "房支顺序与直线复核结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if problems:
        raise SystemExit("尚有图形或排列问题，需修正后再交付")


if __name__ == "__main__":
    main()
