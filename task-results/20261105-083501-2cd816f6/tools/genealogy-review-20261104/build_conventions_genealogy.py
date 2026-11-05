"""按原稿凡例重排代系、分门房支及原生可编辑婚配关系。"""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import defaultdict
from pathlib import Path

from docx import Document

import build_fulltext_genealogy as text_model
from build_genealogy_charts import line_atom, text_atom
from build_genealogy_presentation import write_presentation
from build_standalone_genealogy import chinese_number


W, H = 2383.94, 1683.78
LEFT, RIGHT, TOP, FLOOR = 136, 48, 205, 1515
CELL, SPOUSE_GAP, FAMILY_GAP, GENERATION_GAP = 210, 36, 48, 70


def content_key(text):
    return re.sub(r"[\s，,：:。；;（）()【】†△—－-]", "", text)


def edge_style(person):
    kind = person.get("edge_kind", "亲子")
    if person.get("uncertain") or "待核" in kind:
        return False, "待核"
    if kind.startswith(("收养", "承嗣", "跨代承嗣")):
        return True, "*** ** 养" if kind.startswith("收养") else "*** ** 嗣"
    if kind == "继女":
        return True, "继女"
    if kind.startswith("生身"):
        return False, "生身／出继" if "出继" in kind else "生身"
    if kind == "女系":
        return False, "女系"
    return False, ""


def format_profiles(source, records, gates):
    protected = {p["name"] for p in records.values() if 1 < len(p["name"]) < 12}
    protected |= {p["name"][1:] for p in records.values() if p["name"].startswith("张") and 3 <= len(p["name"]) <= 5}
    protected |= {"公，讳失考", "名讳失考", "氏名不详", "后裔无考", "待核"}
    for profile in source.values():
        value = "".join(p["text"] for p in profile["paragraphs"])
        protected.update(re.findall(r"约(?:1[6789]|20)\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?)?", value))
        protected.update(re.findall(r"(?:合葬于|合葬|葬于|移到)([\u3400-\u9fff]{2,10})", value))
    text_model.PROTECTED = sorted(protected, key=lambda value: (-len(value), value))
    result, changes = {}, []
    for rid, old in source.items():
        person = records[rid]
        title = "".join(p["text"] for p in old["paragraphs"] if p["bold"])
        old_body = [p["text"] for p in old["paragraphs"] if not p["bold"]]
        body, pending = [], ""
        for value in old_body:
            role_line = re.fullmatch(r"(?:始祖公|[长次三四五六七八九十]?[子女]|嗣子)(?:（[^）]+）)?", value)
            if role_line or value.startswith(("核对注：", "待核：", "原记")):
                if pending:
                    body.append(pending)
                    pending = ""
                if role_line:
                    body.append(value)
                    continue
            pending += value
            if pending.endswith("。"):
                body.append(pending)
                pending = ""
        if pending:
            body.append(pending)
        original_title = title
        if not person.get("owner") and person["name"] in ["讳失考", "名讳失考", "次子（失考）"]:
            role = person.get("role", "")
            if "子" in role or person.get("sex") == "男" or "公" in title:
                title = "公，讳失考"
                if role and role not in body and role != "本段起首人物":
                    body.insert(0, role)
        if rid in gates:
            title = "【"+person["name"]+"】"
        if person.get("owner"):
            role = person.get("role", "配")
            prefix = "原配" if "原" in role else "继配" if "继" in role else "配"
            title = prefix+"："+person["name"]
        if person.get("related_to"):
            title = person["name"]+"（抚养人）"
        own_raw = re.sub(r"\s+", "", person.get("raw", ""))
        early = bool(re.search(r"幼年夭折|早殇|早夭|夭折", own_raw)) and not person.get("record_kind")
        date_range = re.search(r"(?:1[6789]|20)\d{2}年?[—－-]+(?:1[6789]|20)\d{2}", own_raw)
        death_range = bool(date_range) and not re.search(r"年间生|之间生", own_raw)
        joint_burial = any("夫妇合葬" in re.sub(r"\s+", "", records[s].get("raw", "")) for s in person.get("spouses", []))
        deceased = death_range or early or joint_burial or bool(re.search(r"卒于|去世|辞世|亡故|早亡|早逝|享寿|享年|合葬|葬于|葬[\u3400-\u9fff]", own_raw))
        if early:
            title += "△"
        new_body = []
        for value in body:
            value = value.replace("（乳名", "（").replace("(乳名", "（")
            value = re.sub(r"(?<=[年日月\d])[—－-]+(?=(?:1[6789]|20)\d{2})", "——", value)
            new_body.append(value)
        if deceased:
            # 凡例规定已故符号放在生卒信息之后，不能直接缀在姓名后。
            combined = "".join(new_body)
            date = r"(?:1[6789]|20)\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?)?"
            patterns = [date+r"[—－-]+"+date+r"(?:间生|年间生)?", r"卒于"+date, r"(?:享寿|享年)[零〇一二两三四五六七八九十百\d]+岁", r"生卒(?:不详|失考)", date+r"生"]
            found = next((m for pattern in patterns if (m := re.search(pattern, combined))), None)
            if found:
                offset = found.end()
                for index, value in enumerate(new_body):
                    if offset <= len(value):
                        new_body[index] = value[:offset]+"†"+value[offset:]
                        break
                    offset -= len(value)
            else:
                new_body.append("生卒失考†")
        paragraphs = []
        title_parts = [title]
        title_lines = text_model.wrap(title, CELL, 26, True)
        title_width = text_model.FONTS[(26, True)].getlength(title)/4
        if "（" in title and (len(title_lines) > 1 or title_width > CELL-8):
            title_parts = re.split(r"(?=（)", title)
        for part in title_parts:
            for line in text_model.wrap(part, CELL, 26, True):
                paragraphs.append({"text": line, "size": 26, "bold": True, "leading": 35, "align": "center"})
        for part in new_body:
            for line in text_model.wrap(part, CELL, 17):
                paragraphs.append({"text": line, "size": 17, "bold": False, "leading": 24, "align": "left"})
        result[rid] = {"paragraphs": paragraphs, "height": sum(p["leading"] for p in paragraphs)+6, "source_paras": old["source_paras"]}
        # 仅规范凡例明确指定的字面形式；其他详细资料须逐字保留。
        before = content_key("".join(p["text"] for p in old["paragraphs"] if not p["bold"]).replace("乳名", ""))
        after = content_key("".join(new_body))
        assert before in after, ("详细信息发生非格式变化", rid)
        changes.append({"record": rid, "old_title": original_title, "title": title, "deceased": deceased, "early_death": early})
    return result, changes


class Diagram:
    def __init__(self, source, plan):
        self.source, self.plan = source, plan
        self.records = copy.deepcopy(source["original_records"])
        self.people = {r: p for r, p in self.records.items() if not p.get("owner") and not p.get("related_to")}
        self.parent = source["plot_parents"]
        self.gates = {g["root"]: g for g in plan["gates"]}
        self.info, self.display_changes = format_profiles(source["profiles"], self.records, self.gates)
        self.kids = defaultdict(list)
        self.related = defaultdict(list)
        for rid, person in self.records.items():
            if person.get("related_to"):
                self.related[person["related_to"]].append(rid)
        for rid, parent in self.parent.items():
            if parent:
                self.kids[parent].append(rid)
        for root in self.people:
            self.kids[root].sort(key=lambda rid: (self.people[rid].get("order", self.people[rid]["para"]), rid))
        for root, order in plan.get("child_order_overrides", {}).items():
            assert set(order) == set(self.kids[root]), "明确的子女排序与资料不一致"
            self.kids[root] = order
        self.pages = []

    def companions(self, rid):
        return self.people[rid]["spouses"]+self.related[rid]

    def unit_width(self, rid):
        return CELL*2+SPOUSE_GAP if self.companions(rid) else CELL

    def unit_height(self, rid):
        values = self.companions(rid)
        companion_height = sum(self.info[r]["height"] for r in values)+24*max(0, len(values)-1)
        return max(self.info[rid]["height"], companion_height)

    def subtree(self, root):
        result = {root}
        for child in self.kids[root]:
            result |= self.subtree(child)
        return result

    def gate_number(self, rid):
        current = rid
        while current not in self.gates and self.parent.get(current):
            current = self.parent[current]
        return self.gates[current]["number"] if current in self.gates else 0

    def dimensions(self, members):
        widths = {}
        def measure(rid):
            values = [measure(c) for c in self.kids[rid] if c in members]
            descendants = sum(values)+FAMILY_GAP*max(0, len(values)-1)
            widths[rid] = max(self.unit_width(rid), descendants)
            return widths[rid]
        roots = [r for r in members if self.parent.get(r) not in members]
        width = sum(measure(r) for r in roots)+FAMILY_GAP*max(0, len(roots)-1)
        generations = sorted({self.people[r]["generation"] for r in members})
        height = sum(max(self.unit_height(r) for r in members if self.people[r]["generation"] == g) for g in generations)+GENERATION_GAP*max(0, len(generations)-1)
        return width, height, widths

    def fits(self, members):
        width, height, _ = self.dimensions(members)
        return width <= W-LEFT-RIGHT and height <= FLOOR-TOP

    def emit(self, root, members, gate, phase, title, part=None):
        assert self.fits(members), ("分页后仍不能容纳", title, self.dimensions(members)[:2])
        self.pages.append({"root": root, "members": members, "gate_number": gate, "phase": phase, "title": title, "part": part})

    def branch(self, root, gate):
        title = self.gates[next(r for r, g in self.gates.items() if g["number"] == gate)]["title"]+"卷 · "+self.people[root]["name"]+"支"
        entire = self.subtree(root)
        if self.fits(entire):
            self.emit(root, entire, gate, "分支", title)
            return
        direct = self.kids[root]
        assert direct, ("单个人物信息不能容纳", root)
        groups, group = [], []
        for child in direct:
            if group and not self.fits({root, child, *group}):
                groups.append(group)
                group = []
            assert self.fits({root, child}), ("父子两个家庭单元不能同时容纳", root, child)
            group.append(child)
        if group:
            groups.append(group)
        for index, group in enumerate(groups, 1):
            members, cursor = {root, *group}, root
            frontier = list(group)
            while True:
                expanding = [r for r in frontier if self.kids[r]]
                if len(expanding) != 1:
                    break
                child = expanding[0]
                proposed = members | set(self.kids[child])
                if not self.fits(proposed):
                    break
                members, cursor, frontier = proposed, child, list(self.kids[child])
            complete = set()
            for child in frontier:
                if not self.kids[child]:
                    continue
                proposed = members | self.subtree(child)
                if not self.fits(proposed):
                    break
                members = proposed
                complete.add(child)
            part = (index, len(groups)) if len(groups) > 1 else None
            self.emit(root, members, gate, "分支", title+(" · 本房成员" if len(groups) == 1 else " · 本房子女分列"), part)
            for child in frontier:
                if self.kids[child] and child not in complete:
                    self.branch(child, gate)

    def plan_pages(self):
        generations = lambda members: {r for r in members if self.people[r]["generation"] <= 5}
        first = self.plan["common_root"]
        first_two = {r for r, p in self.people.items() if p["generation"] <= 2}
        self.emit(first, first_two, 0, "代系", "前五代代系 · 第一、第二代")
        second = next(r for r in first_two if self.people[r]["generation"] == 2 and self.kids[r])
        roots = [g["root"] for g in self.plan["gates"]]
        for group, label in [(roots[:3], "长门、二门、三门"), (roots[3:], "四门、五门")]:
            self.emit(second, {second, *group}, 0, "代系", "前五代代系 · 第三代（"+label+"）")
        for gate in self.plan["gates"]:
            root = gate["root"]
            members = generations(self.subtree(root))
            if len(members) == 1:
                continue
            if self.fits(members):
                self.emit(root, members, gate["number"], "代系", "前五代代系 · "+gate["title"])
            else:
                for child in self.kids[root]:
                    subgroup = {root} | generations(self.subtree(child))
                    if len(subgroup) > 1:
                        self.emit(root, subgroup, gate["number"], "代系", "前五代代系 · "+gate["title"]+" · "+self.people[child]["name"]+"房")
        for gate in self.plan["gates"]:
            number = gate["number"]
            ancestors = [r for r, p in self.people.items() if p["generation"] == 5 and self.gate_number(r) == number and self.kids[r]]
            ancestors.sort(key=lambda rid: self.people[rid]["para"])
            if not ancestors:
                self.emit(gate["root"], {gate["root"]}, number, "分支", gate["title"]+"卷 · 后裔无考")
            else:
                for root in ancestors:
                    self.branch(root, number)
        stages = [0 if p["phase"] == "代系" else p["gate_number"] for p in self.pages]
        assert stages == sorted(stages), "前五代与分门部分交错"

    def render(self, page, number):
        members = page["members"]
        width, height, widths = self.dimensions(members)
        roots = [r for r in members if self.parent.get(r) not in members]
        roots.sort(key=lambda rid: self.people[rid]["para"])
        xs = {}
        def place(rid, x):
            xs[rid] = x+widths[rid]/2
            children = [c for c in self.kids[rid] if c in members]
            total = sum(widths[c] for c in children)+FAMILY_GAP*max(0, len(children)-1)
            offset = x+(widths[rid]-total)/2
            for child in children:
                place(child, offset)
                offset += widths[child]+FAMILY_GAP
        offset = LEFT+(W-LEFT-RIGHT-width)/2
        for root in roots:
            place(root, offset)
            offset += widths[root]+FAMILY_GAP
        bands = sorted({self.people[r]["generation"] for r in members})
        ys, y = {}, TOP
        for generation in bands:
            ys[generation] = y
            y += max(self.unit_height(r) for r in members if self.people[r]["generation"] == generation)+GENERATION_GAP
        title = page["title"]
        if page["part"]:
            title += "（"+str(page["part"][0])+"／"+str(page["part"][1])+"）"
        atoms = [text_atom(title, 70, 28, W-140, 37, True, height=49)]
        subtitle = "第一至第五代依代续列；后续各卷自第六代起按房支顺序展开。" if page["phase"] == "代系" else "第六代起按原稿房支展开；本页保留必要的上代接续。"
        atoms.append(text_atom(subtitle, 80, 94, W-160, 17, False, height=28))
        for generation in bands:
            family_labels = {next((s.get("generation_labels", self.plan.get("generation_labels", {})) for s in self.plan["sections"] if s["id"] == self.people[r]["family"]), self.plan.get("generation_labels", {})).get(str(generation), "") for r in members if self.people[r]["generation"] == generation}
            character = next(iter(family_labels)) if len(family_labels) == 1 else self.plan.get("generation_labels", {}).get(str(generation), "")
            value = "第"+chinese_number(generation)+"代"+("\n【"+character+"】" if character else "")
            paragraphs = [{"text": value.split("\n")[0], "size": 19, "bold": True, "leading": 28}]
            if character:
                paragraphs += [{"text": v, "size": 13, "bold": False, "leading": 19} for v in text_model.wrap("【"+character+"】", 115, 13)]
            atom = text_atom(value, 5, ys[generation]+2, 122, 19, True, height=sum(p["leading"] for p in paragraphs)+2)
            atom.update(paragraphs=paragraphs, generation_label=generation)
            atoms.append(atom)
        lines, boxes, ids, marriages = [], {}, [], []
        visible = sorted(members, key=lambda r: (self.people[r]["generation"], xs[r]))
        for rid in visible:
            unit_width = self.unit_width(rid)
            x, yy = xs[rid]-unit_width/2, ys[self.people[rid]["generation"]]
            def draw_record(record, xx, yyy):
                info = self.info[record]
                atom = text_atom("\n".join(p["text"] for p in info["paragraphs"]), xx-4, yyy, CELL+8, 26, True, height=info["height"])
                atom.update(paragraphs=copy.deepcopy(info["paragraphs"]), person_record=record, source_paras=info["source_paras"])
                atoms.append(atom)
                ids.append(record)
                boxes[record] = {"x": xx, "y": yyy, "w": CELL, "h": info["height"], "center": xx+CELL/2}
            draw_record(rid, x, yy)
            side_y = yy
            spouse_ids = self.people[rid]["spouses"]
            if spouse_ids:
                spine = x+CELL+SPOUSE_GAP/2
                lines.append(line_atom(x+CELL+6, yy+17, spine, yy+17, False, 1.1))
                end_y = yy
                for spouse in spouse_ids:
                    draw_record(spouse, x+CELL+SPOUSE_GAP, side_y)
                    lines.append(line_atom(spine, side_y+17, x+CELL+SPOUSE_GAP-6, side_y+17, False, 1.1))
                    marriages.append({"person": rid, "spouse": spouse, "kind": "婚配", "horizontal_y": side_y+17})
                    end_y = side_y+17
                    side_y += self.info[spouse]["height"]+24
                if end_y > yy+17:
                    lines.append(line_atom(spine, yy+17, spine, end_y, False, 1.1))
            for related in self.related[rid]:
                draw_record(related, x+CELL+SPOUSE_GAP, side_y)
                sy = side_y+17
                if sy > yy+17:
                    lines.append(line_atom(x+CELL+SPOUSE_GAP/2, yy+17, x+CELL+SPOUSE_GAP/2, sy, False, 1.1))
                lines.append(line_atom(x+CELL+6, sy, x+CELL+SPOUSE_GAP-6, sy, False, 1.1))
                atoms.append(text_atom("抚养", x+CELL+1, sy-18, SPOUSE_GAP-2, 10, False, height=17))
                side_y += self.info[related]["height"]+24
        connections = []
        for parent in visible:
            groups = defaultdict(list)
            for child in self.kids[parent]:
                if child in members:
                    groups[self.people[child]["generation"]].append(child)
            for generation, children in groups.items():
                px = boxes[parent]["center"]
                sy = boxes[parent]["y"]+boxes[parent]["h"]+5
                joint = ys[generation]-35
                assert sy < joint, ("代际接线空间不足", parent, generation)
                # 同父母家庭的子女用共享横支线统括，竖线分别落到人物姓名中心。
                centers = [boxes[c]["center"] for c in children]
                lines.append(line_atom(px, sy, px, joint, False, 1.2))
                lines.append(line_atom(min([px]+centers), joint, max([px]+centers), joint, False, 1.2))
                if len(centers) > 1:
                    lines.append({"kind": "brace", "x": min(centers), "y": joint-19, "w": max(centers)-min(centers), "h": 13, "width": 0.9})
                for child in children:
                    cx, ey = boxes[child]["center"], boxes[child]["y"]-5
                    dashed, tag = edge_style(self.people[child])
                    lines.append(line_atom(cx, joint, cx, ey, dashed, 1.2))
                    if tag:
                        atoms.append(text_atom(tag, cx+5, joint+2, 115, 12, False, "left", height=20))
                    connections.append({"parent": parent, "child": child, "parent_center": px, "child_center": cx, "start_y": sy, "joint_y": joint, "end_y": ey, "dashed": dashed, "label": tag})
        for relation in self.plan.get("additional_relations", []):
            parent, child = relation["from_record"], relation["to_record"]
            if parent not in boxes or child not in boxes:
                continue
            px, sy = boxes[parent]["center"], boxes[parent]["y"]+boxes[parent]["h"]+5
            cx, ey = boxes[child]["center"], boxes[child]["y"]-5
            joint = boxes[child]["y"]-43
            assert sy < joint
            lines += [line_atom(px, sy, px, joint, False, 1.1), line_atom(px, joint, cx, joint, False, 1.1), line_atom(cx, joint, cx, ey, False, 1.1)]
            atoms.append(text_atom("共同收养候选，待核", min(px, cx)+8, joint-23, max(260, abs(px-cx)-16), 12, False, "left", height=20))
            connections.append({"parent": parent, "child": child, "additional": True, "dashed": False, "label": "待核"})
        # 连线置于文本框之前，所有对象仍可独立编辑。
        first_person = next(i for i, a in enumerate(atoms) if a.get("person_record"))
        atoms[first_person:first_person] = lines
        # 稀疏页面同比放大，保持基础字号并利用较空的版心。
        person_atoms = [a for a in atoms if a.get("person_record")]
        left = min(a["x"] for a in person_atoms)
        top = min(a["y"] for a in person_atoms)
        right = max(a["x"]+a["w"] for a in person_atoms)
        bottom = max(a["y"]+a["h"] for a in person_atoms)
        scale = min(1.5, (W-LEFT-RIGHT)/(right-left), (FLOOR-TOP)/(bottom-top))
        if scale < 1.05:
            scale = 1.0
        target_left = LEFT+(W-LEFT-RIGHT-(right-left)*scale)/2
        tx = lambda value: target_left+(value-left)*scale
        ty = lambda value: TOP+(value-top)*scale
        if scale > 1:
            for atom in atoms:
                if atom["kind"] == "line":
                    for key in ["x1", "x2"]:
                        atom[key] = tx(atom[key])
                    for key in ["y1", "y2"]:
                        atom[key] = ty(atom[key])
                    atom["width"] *= scale
                elif atom["kind"] == "brace":
                    atom["x"], atom["y"] = tx(atom["x"]), ty(atom["y"])
                    for key in ["w", "h", "width"]:
                        atom[key] *= scale
                elif atom.get("generation_label"):
                    atom["y"] = ty(atom["y"])
                elif atom.get("person_record") or atom["y"] >= TOP-50:
                    atom["x"], atom["y"] = tx(atom["x"]), ty(atom["y"])
                    for key in ["w", "h", "size"]:
                        atom[key] *= scale
                    for value in atom.get("paragraphs", []):
                        value["size"] *= scale
                        value["leading"] *= scale
            for edge in connections:
                for key in ["parent_center", "child_center"]:
                    if key in edge:
                        edge[key] = tx(edge[key])
                for key in ["start_y", "joint_y", "end_y"]:
                    if key in edge:
                        edge[key] = ty(edge[key])
            for marriage in marriages:
                marriage["horizontal_y"] = ty(marriage["horizontal_y"])
            atoms[0]["size"] = 42
        legend = "† 已故　△ 早夭　*** ** 嗣继　虚线：明确收养、承嗣、继亲；实线“待核”：关系未确认。"
        atoms.append(text_atom(legend, 65, H-78, W-180, 13, False, "left", height=23))
        atoms.append(text_atom("大括号统括同支子女；婚配横线仅示夫妻，生母归属以原文为准。", 65, H-49, W-180, 12, False, "left", height=21))
        atoms.append(text_atom(str(number), W-105, H-50, 45, 15, False, "right", height=23))
        for atom in atoms:
            if atom["kind"] == "text":
                assert atom["x"] >= 0 and atom["x"]+atom["w"] <= W+0.1, ("文字超出版宽", atom)
                assert atom["y"] >= 0 and atom["y"]+atom["h"] <= H+0.1, ("文字超出页高", atom)
        assert len(ids) == len(set(ids)), "同页人物重复列框"
        return {"global_page": number, "house_id": str(page["gate_number"]), "house_title": title, "gate_number": page["gate_number"], "phase": page["phase"], "record_ids": ids, "scope_root": page["root"], "atoms": atoms, "connections": connections, "marriages": marriages, "diagram_scale": scale}


def main():
    parser = argparse.ArgumentParser(description="按原稿凡例重排可编辑系谱图")
    for name in ["layout", "plan", "source", "out"]:
        parser.add_argument("--"+name, required=True, type=Path)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    source, plan = read(args.layout), read(args.plan)
    source_rules = [p.text for p in Document(args.source).paragraphs[:47]]
    diagram = Diagram(source, plan)
    diagram.plan_pages()
    pages = [diagram.render(p, number) for number, p in enumerate(diagram.pages, 1)]
    assert {r for p in pages for r in p["record_ids"]} == set(diagram.records), "人物或资料记录遗漏"
    drawn = {(e["parent"], e["child"]) for p in pages for e in p["connections"]}
    assert all(not parent or (parent, child) in drawn for child, parent in diagram.parent.items()), "原接续未绘出"
    for p in pages:
        if p["phase"] == "代系":
            assert all(diagram.people[r]["generation"] <= 5 for r in p["record_ids"] if r in diagram.people), "前五代混入后代"
        for edge in p["connections"]:
            if edge["label"] == "待核":
                assert not edge["dashed"], "待核关系不得用虚线"
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / (plan["title"]+"_按凡例重排_夫妻横向_可编辑.pptx")
    write_presentation(pages, W, H, target)
    split = args.out / "五门独立卷"
    split.mkdir(exist_ok=True)
    for gate in plan["gates"]:
        selected = [p for p in pages if p["gate_number"] == gate["number"]]
        write_presentation(selected, W, H, split / (gate["title"]+"_独立卷.pptx"))
    ancestors = [p for p in pages if p["phase"] == "代系"]
    write_presentation(ancestors, W, H, args.out / "第一至第五代_代系总览.pptx")
    payload = {"width": W, "height": H, "pages": pages, "page_count": len(pages), "record_count": len(diagram.records), "original_records": diagram.records, "plot_parents": diagram.parent, "profiles": diagram.info, "display_changes": diagram.display_changes, "source_rules": source_rules, "source_ledger": source["source_ledger"]}
    (args.out / "按凡例重排版面.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("按凡例重排完成：", len(pages), "页；前五代", len(ancestors), "页；", len(diagram.records), "条人物及资料记录。")
    for gate in plan["gates"]:
        selected = [p["global_page"] for p in pages if p["gate_number"] == gate["number"] and p["phase"] == "分支"]
        print(gate["title"], min(selected), "—", max(selected))


if __name__ == "__main__":
    main()
