"""按单份材料与本地核对配置生成独立的可编辑系谱图册。"""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from build_genealogy_charts import chunks, line_atom, text_atom
from export_genealogy_word import write_document


W, H = 1190.55, 841.89
LEFT, RIGHT, TOP, FLOOR = 94, 42, 125, 746
CELL, STEP = 82, 92


def load_model(data, plan, registry):
    families = copy.deepcopy([f for f in data["families"] if f["source"] == plan["source"]])
    records = {p["id"]: p for f in families for key in ["people", "spouses"] for p in f[key]}
    initial = set(records)
    for rid, change in plan.get("overrides", {}).items():
        assert rid in records, rid
        records[rid].update(change)
    for item in plan.get("additions", []):
        assert item["id"] not in records
        item = copy.deepcopy(item)
        family = next(f for f in families if f["id"] == item["family"])
        key = "spouses" if "owner" in item else "people"
        defaults = {"alias": "", "dates": "", "spouses": [], "issues": [], "role": "", "sex": "未注", "parent": "", "edge_kind": "亲子", "parent_basis": "原文明示", "source": plan["source"], "declared_gen": None, "context": item["raw"]}
        defaults.update(item)
        family[key].append(defaults)
        records[item["id"]] = defaults
        if key == "spouses":
            records[item["owner"]]["spouses"].append(item["id"])
    people = {p["id"]: p for f in families for p in f["people"]}
    spouses = {p["id"]: p for f in families for p in f["spouses"]}
    identifiers = {rid: registry.get(rid, rid) for rid in records}
    for source, target in plan.get("same_person", []):
        assert source in records and target in records
        identifiers[source] = identifiers[target]
    # 布局关系与正式核定关系分开保存；待核关系不能冒充已确认父母。
    for p in people.values():
        p["layout_parent"] = p.get("layout_parent", p.get("parent", ""))
        if p.get("layout_parent"):
            assert p["layout_parent"] in people, p
        p["generation"] = p.get("generation") or p.get("declared_gen") or p.get("relative_gen") or 1
    assert initial <= set(records), "不得删除原文记录"
    assert all(p["owner"] in people for p in spouses.values())
    assert {s for p in people.values() for s in p["spouses"]} == set(spouses)
    for rid in people:
        seen, current = set(), rid
        while current in people:
            assert current not in seen, ("关系循环", rid)
            seen.add(current)
            current = people[current].get("layout_parent")
    return families, records, people, spouses, identifiers, initial


def date_lines(p):
    value = p.get("display_dates", p.get("dates", ""))
    value = value.replace("年—", "—").replace("年——", "—")
    return [line for part in value.split("；") for line in chunks(part, 9.5)]


def node_blocks(p, spouses, ids):
    values = [(p.get("display_name", p["name"]), 12, True)]
    if p.get("alias"):
        alias = p["alias"].replace("乳名", "").replace("又名", "")
        values += [(v, 8.5, False) for v in chunks("（" + alias + "）", 8.8)]
    values += [(v, 8.7, False) for v in date_lines(p)]
    role = p.get("role", "")
    if role and role not in ["本段起首人物", p.get("display_name", p["name"])]:
        values += [(v, 8, False) for v in chunks(role, 10.5)]
    for note in p.get("chart_notes", []):
        values += [(v, 8, True) for v in chunks(note, 9.5)]
    blocks = [{"record_id": p["id"], "lines": values}]
    for sid in p["spouses"]:
        s = spouses[sid]
        prefix = s.get("role") or "配"
        if prefix not in ["原配", "继配", "婿", "夫"]:
            prefix = "配"
        spouse_lines = [(v, 9.3, False) for v in chunks(prefix + "：" + s["name"], 8.3)]
        spouse_lines += [(v, 8, False) for v in date_lines(s)]
        blocks.append({"record_id": sid, "lines": spouse_lines})
    return blocks


def node_lines(p, spouses, ids):
    return [line for block in node_blocks(p, spouses, ids) for line in block["lines"]]


def layout_section(section, people, spouses, identifiers):
    members = set(section["records"])
    assert members and members <= set(people)
    kids = defaultdict(list)
    for rid in members:
        par = people[rid].get("layout_parent")
        if par in members:
            assert people[par]["generation"] < people[rid]["generation"], ("代际层级未分开", par, rid)
            kids[par].append(rid)
    order = lambda rid: (people[rid].get("order", people[rid]["para"]), rid)
    for values in kids.values():
        values.sort(key=order)
    roots = sorted([r for r in members if people[r].get("layout_parent") not in members], key=order)
    leaves = []
    def collect(r):
        if kids[r]:
            for c in kids[r]: collect(c)
        else: leaves.append(r)
    for r in roots: collect(r)
    lines = {r: node_lines(people[r], spouses, identifiers) for r in members}
    heights = {r: sum(s * 1.16 + 0.8 for _, s, _ in lines[r]) + 24 for r in members}
    capacity = int((W - LEFT - RIGHT - CELL) // STEP) + 1
    pages = []
    for start in range(0, len(leaves), capacity):
        subset = set(leaves[start:start + capacity])
        for rid in list(subset):
            par = people[rid].get("layout_parent")
            while par in members:
                subset.add(par)
                par = people[par].get("layout_parent")
        generations = sorted({people[r]["generation"] for r in subset})
        row_h = {g: max(heights[r] for r in subset if people[r]["generation"] == g) for g in generations}
        bands, band, used = [], [], 0
        for g in generations:
            needed = row_h[g] + 27
            if band and used + needed > FLOOR - TOP:
                bands.append(band)
                band = [band[-1]]
                used = row_h[band[0]] + 27
            band.append(g)
            used += needed
        if band: bands.append(band)
        cursor, xs = [0], {}
        def place(r):
            children = [c for c in kids[r] if c in subset]
            if children:
                positions = [place(c) for c in children]
                xs[r] = (min(positions) + max(positions)) / 2
            else:
                xs[r] = cursor[0] * STEP
                cursor[0] += 1
            return xs[r]
        for root in roots:
            if root in subset: place(root)
        width = (cursor[0] - 1) * STEP + CELL
        shift = LEFT + (W - LEFT - RIGHT - width) / 2
        for band in bands:
            visible = sorted([r for r in subset if people[r]["generation"] in band], key=lambda r: (people[r]["generation"], xs[r]))
            ys, y = {}, TOP
            for g in band:
                ys[g] = y
                y += row_h[g] + 27
            positions = {r: {"x": shift + xs[r], "y": ys[people[r]["generation"]], "h": heights[r]} for r in visible}
            pages.append({"visible": visible, "positions": positions, "bands": band, "ys": ys})
    return {"definition": section, "members": members, "kids": kids, "pages": pages, "lines": lines}


def render(built, index, people, spouses, ids, mapping, offset, all_sections):
    section, page = built["definition"], built["pages"][index]
    local_total = len(built["pages"])
    title = section["title"] + (f"（第{index + 1}/{local_total}页）" if local_total > 1 else "")
    atoms = [text_atom(title, 36, 25, W - 72, 20, True),
             text_atom(section.get("ancestry", ""), 36, 58, W - 72, 10),
             text_atom("据张氏专稿独立编排　·　世代按亲属链接续；原标不一致处加注待核", 36, 79, W - 72, 9)]
    pos = page["positions"]
    for g in page["bands"]:
        atoms.append(text_atom("第" + str(g) + "世", 12, page["ys"][g] + 2, 68, 10, True))
    for rid in page["visible"]:
        p = people[rid]
        par = p.get("layout_parent")
        if par not in pos: continue
        a, b = pos[par], pos[rid]
        px, cx = a["x"] + CELL / 2, b["x"] + CELL / 2
        sy, ey = a["y"] + a["h"] - 1, b["y"] - 5
        joint = ey - 8
        uncertain = p.get("uncertain", False)
        atoms.extend([line_atom(px, sy, px, joint, uncertain), line_atom(px, joint, cx, joint, uncertain), line_atom(cx, joint, cx, ey, uncertain)])
        tag = "待核" if uncertain else "嗣" if re.search("承嗣|收养", p.get("edge_kind", "")) else "继" if "继女" in p.get("edge_kind", "") else "女系" if "女系" in p.get("edge_kind", "") else ""
        if tag: atoms.append(text_atom(tag, cx + 3, joint - 2, 28, 8, True, "left"))
    for rid in page["visible"]:
        p, point = people[rid], pos[rid]
        par = p.get("layout_parent")
        footer = []
        if par and par not in pos:
            refs = mapping.get(par, [])
            if refs:
                value = "承上见" + "、".join(str(n) for n in refs[:4]) + "页"
                footer.append(value)
        others = sorted({n for child in built["kids"][rid] for n in mapping[child] if child not in pos and n != offset + index + 1})
        if others:
            footer.append("续见" + "、".join(str(n) for n in others[:5]) + "页")
        external = sorted({mapping[c][0] for c,q in people.items() if q.get("layout_parent")==rid and c not in built["members"] and mapping.get(c)})
        if external:
            footer.append("详支" + "、".join(str(n) for n in external[:5]) + "页")
        blocks = node_blocks(p, spouses, ids)
        blocks[0]["lines"].extend((value, 7.5, True) for value in footer[:2])
        y = point["y"]
        for block in blocks:
            paragraphs = [{"text": value, "size": size, "bold": bold, "leading": size*1.16+0.8} for value,size,bold in block["lines"]]
            height = sum(v["leading"] for v in paragraphs)
            atom = text_atom("\n".join(v["text"] for v in paragraphs), point["x"]-4, y, CELL+8, paragraphs[0]["size"], paragraphs[0]["bold"], height=height+1)
            atom["paragraphs"] = paragraphs
            atom["person_record"] = block["record_id"]
            atoms.append(atom)
            y += height
    notes = section.get("notes", [])
    for n, line in enumerate([v for note in notes for v in chunks(note, 123)][:4]):
        atoms.append(text_atom(line, 36, 756 + n * 11, W - 72, 8.5, False, "left"))
    atoms.append(text_atom("实线：原文关系按支系接续　虚线：候选关系待核　嗣：承嗣／收养　继：继亲；配偶不自动视为全部子女生母／生父", 36, 809, W - 72, 8, False, "left"))
    atoms.append(text_atom("同人出继、承嗣两处保留原记；续页重复上代供接续。核对编号仅留在配套索引中，图上不显示。", 36, 824, W - 140, 7.8, False, "left"))
    atoms.append(text_atom(str(offset + index + 1), W - 82, 820, 40, 10, False, "right"))
    for a in atoms:
        if a["kind"] == "text":
            assert 0 <= a["x"] and a["x"] + a["w"] <= W + 0.1
            assert 0 <= a["y"] and a["y"] + a["h"] <= H + 0.1, a
    return {"house_id": section["id"], "house_title": section["title"], "local_page": index + 1, "local_total": local_total,
            "global_page": offset + index + 1, "atoms": atoms,
            "record_ids": [s for r in page["visible"] for s in [r] + people[r]["spouses"]]}


def report(plan, families, records, people, spouses, ids, pages, groups, destination):
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = Inches(0.65)
    sec.left_margin = sec.right_margin = Inches(0.65)
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    doc.add_heading(plan["title"] + "编排与核对说明", 0)
    doc.add_paragraph("本册仅依据所附张氏专稿制作，保留原文人物及配偶记录，不以其他稿件覆盖。第一世为原文约1783年迁居高家圪台的始祖；名讳失考者按原记保留。图册为关系核对稿，有争议的关系不作事实定稿。")
    doc.add_paragraph(f"共{len(pages)}页图，按始祖总览及房支分段。原抽取人物、配偶记录与补充记录全部有图中位置。暂编人物编号用于交叉核对，不代表核定人口数。")
    doc.add_heading("编辑与打印", 1)
    doc.add_paragraph("每个人的姓名、生卒、称谓和注记合并在一个原生文本框内；配偶各用一个文本框，关系线保持独立可编辑。图上不显示核对编号，编号仅在索引中保留。选中页内图组后可编辑组内文字；需要单独移动时，右键选择“组合→取消组合”。页面使用横向纸张（420×297毫米），打印选实际大小；较小纸张可适配缩印，但字号随之缩小。")
    doc.add_heading("图页目录", 1)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    for c, t in zip(table.rows[0].cells, ["编号", "内容", "图册页码"]): c.text = t
    for g in groups:
        cells = table.add_row().cells
        for c,t in zip(cells,[g[0],g[1],str(g[3]) if g[3]==g[4] else f"{g[3]}—{g[4]}"]): c.text = t
    doc.add_heading("待核事项与编排依据", 1)
    for issue in plan["findings"]:
        doc.add_heading(issue["title"], 2)
        doc.add_paragraph(issue["detail"])
        doc.add_paragraph("原文出处：" + issue["evidence"])
        doc.add_paragraph("图中处理：" + issue["action"])
    doc.add_page_break()
    doc.add_heading("人物与原文逐条索引", 1)
    doc.add_paragraph("每一行对应一条原文记载。出继、生身或重复记载可沿用同一人物编号；原文不确定的同人、姓名差异不擅自合并。补充者为原文名单或内嵌配偶，不补造姓名。段落从原文件第一段起计，包含空段。")
    mapping = defaultdict(set)
    for page in pages:
        for rid in page["record_ids"]: mapping[rid].add(page["global_page"])
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for c,t in zip(table.rows[0].cells,["人物编号", "姓名／原称", "图页", "原文段", "关系与原标"]): c.text=t
    header = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(header)
    for rid,p in sorted(records.items(),key=lambda item:(item[1]["para"],item[0])):
        parent=people.get(p.get("parent", ""),{}).get("name", "")
        owner=people.get(p.get("owner", ""),{}).get("name", "")
        rel=("配偶："+owner) if owner else (("上辈："+parent) if parent else "上辈未核定／始祖")
        if p.get("declared_gen"): rel += "；原列第"+str(p["declared_gen"])+"代"
        if p.get("uncertain"): rel += "；关系待核"
        if p.get("chart_notes"): rel += "；"+"；".join(p["chart_notes"])
        cells=table.add_row().cells
        for c,t in zip(cells,[ids[rid],p["name"],"、".join(map(str,sorted(mapping[rid]))),str(p["para"]),rel]): c.text=t
    doc.core_properties.author=""
    doc.core_properties.last_modified_by=""
    doc.core_properties.title=plan["title"]+"核对说明"
    doc.save(destination)


def main():
    parser=argparse.ArgumentParser(description="按单份材料生成独立可编辑系谱图册")
    for key in ["data","plan","registry","out"]: parser.add_argument("--"+key,required=True,type=Path)
    args=parser.parse_args()
    data=json.loads(args.data.read_text(encoding="utf-8"))
    plan=json.loads(args.plan.read_text(encoding="utf-8"))
    registry=json.loads(args.registry.read_text(encoding="utf-8"))["record_to_person"]
    families, records, people, spouses, ids, initial=load_model(data,plan,registry)
    sections=copy.deepcopy(plan["sections"])
    for section in sections:
        if "families" in section:
            section["records"]=[p["id"] for f in families if f["id"] in section["families"] for p in f["people"]]
    built=[layout_section(s,people,spouses,ids) for s in sections]
    mapping=defaultdict(list)
    number=0
    for b in built:
        for page in b["pages"]:
            number+=1
            for rid in page["visible"]: mapping[rid].append(number)
    pages,groups=[],[]
    for b in built:
        first=len(pages)+1
        offset=len(pages)
        for i in range(len(b["pages"])): pages.append(render(b,i,people,spouses,ids,mapping,offset,built))
        groups.append([b["definition"]["id"],b["definition"]["title"],len(b["pages"]),first,len(pages)])
    covered={rid for page in pages for rid in page["record_ids"]}
    assert covered==set(records), ("人物漏图",set(records)-covered)
    args.out.mkdir(parents=True,exist_ok=True)
    payload={"width":W,"height":H,"pages":pages,"houses":groups,"record_count":len(records),"source_records":len(initial),"entity_count":len(set(ids.values())),"page_count":len(pages)}
    (args.out/"独立系谱图版面.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    (args.out/"独立关系与原文记录.json").write_text(json.dumps({"records":records,"identifiers":ids,"findings":plan["findings"]},ensure_ascii=False,indent=2),encoding="utf-8")
    write_document(pages,W,H,args.out/(plan["title"]+"_逐项可编辑系谱图.docx"))
    folder=args.out/"分房支可编辑文档"
    folder.mkdir(exist_ok=True)
    for group in groups:
        selected=[p for p in pages if p["house_id"]==group[0]]
        name=re.sub(r'[<>:"/\\|?*]',"",group[1])
        write_document(selected,W,H,folder/(group[0]+"_"+name+".docx"))
    report(plan,families,records,people,spouses,ids,pages,groups,args.out/(plan["title"]+"_人物索引与待核说明.docx"))
    print(f"原文人物与配偶记录{len(initial)}条；补充原文名单与内嵌信息{len(records)-len(initial)}条；图册{len(pages)}页，{len(groups)}个分段。")
    print("全部人物及配偶均有图中位置；原文条目完整保留。")


if __name__=="__main__": main()
