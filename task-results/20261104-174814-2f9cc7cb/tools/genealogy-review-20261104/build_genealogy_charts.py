"""以主稿人物和分户规则生成可追溯的系谱图版面及人物页码对照。"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook

from export_review import create_sheet


W, H = 1190.55, 841.89
LEFT, RIGHT, TOP, BOTTOM = 85, 36, 101, 763
CELL, STEP = 60, 68
ORDER_BASES = {"原文称谓与分支顺序", "原文世次与分支顺序"}


def join(values):
    return "；".join(dict.fromkeys(str(v) for v in values if v is not None and str(v).strip()))


def chunks(text, limit):
    lines, current, width = [], "", 0
    for char in str(text):
        char_width = 0.52 if ord(char) < 128 else 1
        if current and width + char_width > limit:
            lines.append(current)
            current, width = "", 0
        current += char
        width += char_width
    if current:
        lines.append(current)
    return lines


def short_dates(text):
    years = re.findall(r"(?:1[6789]|20)\d{2}", text or "")
    if len(years) >= 2:
        return years[0] + "—" + years[1]
    if years:
        suffix = "卒" if re.search(r"终|卒|去世|逝世", text) else "生" if "生" in text else "年"
        return years[0] + suffix
    return (text or "").replace("；", " ")


def node_lines(person, spouses, identifiers):
    lines = [(person["name"], 11.5, True)]
    alias = person.get("alias", "")
    if alias:
        lines.extend((line, 8, False) for line in chunks("（" + alias + "）", 7))
    date = short_dates(person.get("dates", ""))
    if date:
        lines.extend((line, 8.2, False) for line in chunks(date, 7))
    role = person.get("role", "")
    identity_line = (role + " " if role and role != "本段起首人物" else "") + identifiers[person["id"]]
    lines.extend((line, 7.1, False) for line in chunks(identity_line, 8.2))
    if person.get("display_parent"):
        lines.append(("父母归属待核实", 8, True))
    for spouse_id in person.get("spouses", []):
        spouse = spouses[spouse_id]
        role = spouse["role"]
        prefix = "继配" if "继" in role or "续" in role else "原配" if "原" in role else "婿" if "婿" in role else "配"
        lines.extend((line, 9.2, False) for line in chunks(prefix + "：" + spouse["name"], 6.2))
        lines.append((identifiers[spouse_id], 7.1, False))
    return lines


def tree_depths(node_ids, people):
    depths = {}

    def depth(identifier, trail):
        if identifier in depths:
            return depths[identifier]
        assert identifier not in trail, "关系循环"
        parent = people[identifier].get("parent")
        value = depth(parent, trail | {identifier}) + 1 if parent in node_ids else 0
        depths[identifier] = value
        return value

    for identifier in node_ids:
        depth(identifier, set())
    return depths


def build_house(house, families, identifiers):
    selected = [f for f in families if f["id"] in house["sources"]]
    lo, hi = house.get("range", [0, 10**8])
    people = {p["id"]: p for f in selected for p in f["people"] if lo <= p["para"] <= hi}
    spouses = {p["id"]: p for f in selected for p in f["spouses"] if p.get("owner") in people}
    assert people, "分户没有人物"
    owned = {sid for p in people.values() for sid in p["spouses"]}
    assert owned == set(spouses), "分户配偶归属遗漏"
    kids = defaultdict(list)
    for p in people.values():
        if p.get("parent") in people:
            kids[p["parent"]].append(p["id"])
    for values in kids.values():
        values.sort(key=lambda identifier: people[identifier]["para"])
    roots = sorted((p["id"] for p in people.values() if p.get("parent") not in people), key=lambda k: people[k]["para"])
    depths = tree_depths(set(people), people)
    floating = set()
    def mark_floating(identifier):
        floating.add(identifier)
        for child in kids[identifier]:
            mark_floating(child)
    for root in roots:
        if people[root].get("display_parent") and people[root].get("local_level", 1) > 1:
            mark_floating(root)
    if floating:
        offset = max((depths[k] for k in people if k not in floating), default=-1) + 1
        for k in floating:
            depths[k] += offset
    lines = {k: node_lines(p, spouses, identifiers) for k, p in people.items()}
    heights = {k: sum(size * 1.1 + 0.5 for _, size, _ in values) + 13 for k, values in lines.items()}
    leaves = []

    def collect(identifier):
        if kids[identifier]:
            for child in kids[identifier]:
                collect(child)
        else:
            leaves.append(identifier)

    for root in roots:
        collect(root)
    limit = max(1, int((W - LEFT - RIGHT) // STEP))
    pages = []
    for offset in range(0, len(leaves), limit):
        subset = set(leaves[offset:offset + limit])
        for leaf in list(subset):
            current = people[leaf].get("parent")
            while current in people:
                subset.add(current)
                current = people[current].get("parent")
        row_heights = {}
        for k in subset:
            row_heights[depths[k]] = max(row_heights.get(depths[k], 0), heights[k])
        levels = sorted(row_heights)
        bands, band, used = [], [], 0
        for level in levels:
            needed = row_heights[level] + 18
            if band and used + needed > BOTTOM - TOP:
                bands.append(band)
                band = [band[-1]]
                used = row_heights[band[0]] + 18
            band.append(level)
            used += needed
        if band:
            bands.append(band)
        for band in bands:
            visible = {k for k in subset if depths[k] in band}
            cursor = [0]
            xmap = {}

            def place(identifier):
                descendants = [k for k in kids[identifier] if k in subset]
                if descendants:
                    child_x = [place(k) for k in descendants]
                    xmap[identifier] = (min(child_x) + max(child_x)) / 2
                else:
                    xmap[identifier] = cursor[0] * STEP
                    cursor[0] += 1
                return xmap[identifier]

            for root in roots:
                if root in subset:
                    place(root)
            graph_width = max(CELL, (cursor[0] - 1) * STEP + CELL)
            shift = LEFT + max(0, (W - LEFT - RIGHT - graph_width) / 2)
            ymap, y = {}, TOP
            for level in band:
                ymap[level] = y
                y += row_heights[level] + 18
            positions = {k: {"x": shift + xmap[k], "y": ymap[depths[k]], "h": heights[k]} for k in visible}
            pages.append({"visible": sorted(visible, key=lambda k: (depths[k], positions[k]["x"])),
                          "positions": positions, "levels": band, "depths": depths,
                          "height": y, "horizontal_group": offset // limit + 1})
    page_map = defaultdict(list)
    for page_number, page in enumerate(pages, 1):
        for k in page["visible"]:
            page_map[k].append(page_number)
    migration = house.get("migration") or join(f["migration"] for f in selected)
    absolute = ("原文明示入村一代" in migration and "是否" not in migration and "始迁祖未证实" not in migration)
    return {"house": house, "people": people, "spouses": spouses, "children": kids,
            "pages": pages, "page_map": page_map, "lines": lines, "absolute": absolute,
            "migration": migration, "floating": floating}


def text_atom(text, x, y, width, size=9, bold=False, align="center", height=None):
    return {"kind": "text", "text": str(text), "x": x, "y": y, "w": width,
            "h": height or size * 1.4, "size": size, "bold": bold, "align": align}


def line_atom(x1, y1, x2, y2, dashed=False, width=0.7):
    return {"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "dashed": dashed, "width": width}


def render_page(built, index, global_page):
    house, page = built["house"], built["pages"][index]
    people, kids, positions = built["people"], built["children"], page["positions"]
    count = len(built["pages"])
    title = house["title"] + "系谱图"
    if count > 1:
        title += f"（本户第{index + 1}/{count}页）"
    atoms = [text_atom(title, 36, 25, W - 72, 21, True),
             text_atom("以《总》为准　·　" + house["id"] + "　·　核对稿", 36, 57, W - 72, 9),
             text_atom("入村世次按原文列示" if built["absolute"] else "入村第一世尚待核定；图中代序为从起列人物接续的相对代次", 36, 76, W - 72, 9)]
    for level in page["levels"]:
        y = min(positions[k]["y"] for k in page["visible"] if page["depths"][k] == level)
        pending_level = all(k in built["floating"] for k in page["visible"] if page["depths"][k] == level)
        label = "归属待核区" if pending_level else f"第{level + 1}世" if built["absolute"] else ("起列代" if level == 0 else f"相对第{level + 1}代")
        label_atom = text_atom(label, 5, y + 1, 72, 9, True)
        label_atom["fixed_left"] = True
        atoms.append(label_atom)
    for child_id in page["visible"]:
        p = people[child_id]
        parent_id = p.get("parent")
        if parent_id not in positions:
            continue
        parent, child = positions[parent_id], positions[child_id]
        px, cx = parent["x"] + CELL / 2, child["x"] + CELL / 2
        start_y, end_y = parent["y"] + parent["h"] + 1, child["y"] - 4
        joint = end_y - 5
        dashed = p["parent_basis"] in ORDER_BASES or "待核" in p["edge_kind"]
        atoms += [line_atom(px, start_y, px, joint, dashed), line_atom(px, joint, cx, joint, dashed), line_atom(cx, joint, cx, end_y, dashed)]
        kind = p["edge_kind"]
        tag = "嗣" if "承嗣" in kind or "收养" in kind else "继" if "继亲" in kind else "女系" if "女系" in kind else ""
        if tag:
            atoms.append(text_atom(tag, cx + 2, joint - 1, 24, 7.2, True, "left"))
    for k in page["visible"]:
        p, pos = people[k], positions[k]
        y = pos["y"]
        for value, size, bold in built["lines"][k]:
            atoms.append(text_atom(value, pos["x"], y, CELL, size, bold))
            y += size * 1.1 + 0.5
        other = sorted({number for child in kids[k] for number in built["page_map"][child] if child not in positions and number != index + 1})
        if other:
            value = "另支见" + "、".join(str(v) for v in other) + "页"
            atoms.append(text_atom(value, pos["x"] - 5, y, CELL + 10, 7.1, True))
        if p.get("parent") not in positions and p.get("parent") in people:
            parent_id = p["parent"]
            value = "承上：" + people[parent_id]["name"] + "，见" + "、".join(str(v) for v in built["page_map"][parent_id]) + "页"
            atoms.append(text_atom(value, pos["x"] - 10, y, CELL + 20, 7.1, True))
    # 小家族放大正文，改善单页打印时的可读性；较密页面保持原字号。
    x0 = min(p["x"] for p in positions.values())
    x1 = max(p["x"] + CELL for p in positions.values())
    bottom = max(p["y"] + p["h"] + 3 for p in positions.values())
    scale = min(1.6, (W - LEFT - RIGHT) / (x1 - x0 + 20), (BOTTOM - TOP) / (bottom - TOP))
    scale = max(1, scale)
    center = (x0 + x1) / 2
    target_center = (LEFT + W - RIGHT) / 2
    for atom in atoms[3:]:
        if atom["kind"] == "line":
            for axis in ["x1", "x2"]:
                atom[axis] = target_center + (atom[axis] - center) * scale
            for axis in ["y1", "y2"]:
                atom[axis] = TOP + (atom[axis] - TOP) * scale
            atom["width"] *= min(scale, 1.4)
        else:
            atom["y"] = TOP + (atom["y"] - TOP) * scale
            if atom.get("fixed_left"):
                atom["size"] *= min(scale, 1.2)
                atom["h"] *= min(scale, 1.2)
            else:
                atom["x"] = target_center + (atom["x"] - center) * scale
                atom["w"] *= scale
                atom["h"] *= scale
                atom["size"] *= scale
    notes = join([house.get("note", ""), built["migration"]])
    note_lines = chunks("图注：" + notes, 125)[:3]
    for i, value in enumerate(note_lines):
        atoms.append(text_atom(value, 36, 775 + i * 10, W - 72, 8, False, "left"))
    legend = "实线：主稿明确记述　虚线：据顺序整理或关系待核实　嗣：承嗣　继：继亲　配偶不自动认作全部子女生母／生父"
    atoms.append(text_atom(legend, 36, 809, W - 72, 7.7, False, "left"))
    atoms.append(text_atom("同户续页重复上代仅供接续，不重复计人。" if count > 1 else "姓名、原文及待核事项见配套人物表。", 36, 823, W - 150, 7.5, False, "left"))
    atoms.append(text_atom(str(global_page), W - 95, 820, 55, 9, False, "right"))
    for atom in atoms:
        if atom["kind"] == "text":
            assert atom["x"] >= 0 and atom["x"] + atom["w"] <= W + 0.1
            assert atom["y"] >= 0 and atom["y"] + atom["h"] <= H + 0.1, (house["id"], atom)
    return {"house_id": house["id"], "house_title": house["title"], "local_page": index + 1,
            "local_total": count, "global_page": global_page, "atoms": atoms,
            "record_ids": [rid for k in page["visible"] for rid in [k] + people[k]["spouses"]]}


def write_svg(page, destination):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}pt" height="{H}pt" viewBox="0 0 {W} {H}">',
             '<rect width="100%" height="100%" fill="white"/>']
    for atom in page["atoms"]:
        if atom["kind"] == "line":
            dash = ' stroke-dasharray="3 2"' if atom["dashed"] else ""
            parts.append(f'<line x1="{atom["x1"]}" y1="{atom["y1"]}" x2="{atom["x2"]}" y2="{atom["y2"]}" stroke="#111827" stroke-width="{atom["width"]}"{dash}/>')
        else:
            align = atom["align"]
            anchor = {"center": "middle", "left": "start", "right": "end"}[align]
            x = atom["x"] + (atom["w"] / 2 if align == "center" else atom["w"] if align == "right" else 0)
            weight = "bold" if atom["bold"] else "normal"
            parts.append(f'<text x="{x}" y="{atom["y"] + atom["size"]}" font-family="SimSun,宋体,serif" font-size="{atom["size"]}" font-weight="{weight}" text-anchor="{anchor}" fill="#111827">{html.escape(atom["text"])}</text>')
    parts.append("</svg>")
    destination.write_text("\n".join(parts), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="按主稿关系生成分户系谱图与分页索引")
    for key in ["data", "plan", "registry", "out"]:
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    ids = json.loads(args.registry.read_text(encoding="utf-8"))["record_to_person"]
    families = [f for f in data["families"] if f["source"] == "总"]
    args.out.mkdir(parents=True, exist_ok=True)
    vectors = args.out / "分户矢量图"
    vectors.mkdir(exist_ok=True)
    all_records = {p["id"]: p for f in families for key in ["people", "spouses"] for p in f[key]}
    house_membership = Counter()
    pages, house_rows, mapping = [], [], defaultdict(list)
    expected_vectors = set()
    for house in plan:
        built = build_house(house, families, ids)
        members = set(built["people"]) | set(built["spouses"])
        house_membership.update(members)
        first = len(pages) + 1
        for index in range(len(built["pages"])):
            page = render_page(built, index, len(pages) + 1)
            pages.append(page)
            filename = f'{house["id"]}_{index + 1:02d}.svg'
            expected_vectors.add(filename)
            write_svg(page, vectors / filename)
            for rid in page["record_ids"]:
                mapping[rid].append((house["id"], house["title"], page["global_page"], page["local_page"]))
        house_rows.append([house["id"], house["title"], len(built["pages"]), first, len(pages),
                           join(house["sources"]), house.get("note", ""), built["migration"]])
    assert set(house_membership) == set(all_records), "图中人物与主稿人物集合不同"
    assert all(v == 1 for v in house_membership.values()), "同一原文条目被误分入多户"
    assert set(mapping) == set(all_records), "分页导致人物漏图"
    # 仅清理本工具本轮输出目录中已失效的分页文件，避免交付旧页。
    for old in vectors.glob("户*_*.svg"):
        if old.name not in expected_vectors:
            assert old.resolve().parent == vectors.resolve()
            old.unlink()
    wb = Workbook()
    wb.remove(wb.active)
    create_sheet(wb, "分户页码目录", ["图户编号", "家族", "本户页数", "总册起页", "总册止页", "原文分组", "分户说明", "入村世次依据"], house_rows, [18, 70, 18, 18, 18, 30, 100, 110])
    create_sheet(wb, "图表人物逐条对应", ["人物编号", "原文条目", "姓名", "图户编号", "家族", "总册页码", "本户页码", "原文出处", "原文"],
                 [[ids[rid], rid, p["name"], join(v[0] for v in mapping[rid]), join(v[1] for v in mapping[rid]), join(v[2] for v in mapping[rid]), join(v[3] for v in mapping[rid]), f"《总》第{p['para']}段", p["raw"]] for rid, p in all_records.items()], [18, 24, 22, 25, 70, 35, 35, 30, 140])
    entities = defaultdict(list)
    for rid in all_records:
        entities[ids[rid]].append(rid)
    create_sheet(wb, "一人一条人物索引", ["人物编号", "姓名原记", "原文条目", "所在图户", "总册页码", "同人多处说明"],
                 [[identifier, join(all_records[r]["name"] for r in values), join(values), join(v[1] for r in values for v in mapping[r]), join(sorted({v[2] for r in values for v in mapping[r]})), "生身、承嗣两处同人分记，非重复人口" if len(values) > 1 else ""] for identifier, values in entities.items()], [18, 25, 55, 100, 60, 80])
    create_sheet(wb, "补充关系与未具名线索", ["材料", "段落", "人物或夫妇", "相关人物", "关系原记", "说明"], [[r[k] for k in ["source", "para", "person", "relative", "kind", "note"]] for r in data["manual_edges"] if r["source"] == "总"], [18, 15, 55, 90, 65, 140])
    wb.save(args.out / "系谱图人物与页码对照.xlsx")
    result = {"width": W, "height": H, "pages": pages, "houses": house_rows,
              "record_count": len(all_records), "entity_count": len(entities), "house_count": len(plan), "page_count": len(pages)}
    (args.out / "系谱图版面数据.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    check = load_workbook(args.out / "系谱图人物与页码对照.xlsx")
    assert check["图表人物逐条对应"].max_row - 1 == len(all_records)
    print("图户数：", len(plan), "；打印页数：", len(pages))
    print("主稿原文条目：", len(all_records), "；暂编人物编号：", len(entities))
    print("单页图户：", sum(r[2] == 1 for r in house_rows), "；分页图户：", sum(r[2] > 1 for r in house_rows))
    print("检查通过：主稿全部人物及配偶均有图中位置，原文条目没有跨户误分。")


if __name__ == "__main__":
    main()
