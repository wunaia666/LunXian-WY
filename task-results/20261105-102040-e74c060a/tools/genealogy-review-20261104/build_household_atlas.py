"""以指定主稿和分户规则生成逐户可编辑世系图，并逐段保留核对依据。"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from docx import Document

import build_fulltext_genealogy as typography
from build_genealogy_charts import line_atom, text_atom
from build_genealogy_presentation import write_presentation
from build_standalone_genealogy import chinese_number


W, H = 3370.39, 2383.94
LEFT, RIGHT, TOP = 160, 80, 245
CELL, PARTNER_GAP, FAMILY_GAP, ROW_GAP = 150, 32, 32, 80


def compact(value):
    return re.sub(r"\s+", "", str(value))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def source_model(source, data, rules, plan):
    rows = [p.text for p in Document(source).paragraphs]
    families = [copy.deepcopy(f) for f in data["families"] if f["source"] == "总"]
    records, owned_rows, assigned = {}, defaultdict(list), {}
    for f in families:
        for key in ["people", "spouses"]:
            for p in f[key]:
                p["family"] = f["id"]
                p["original_record"] = True
                p.setdefault("spouses", [])
                p.setdefault("parent", "")
                p.setdefault("issues", [])
                p["notes"] = []
                p["fragments"] = [{"para": p["para"], "text": compact(p["raw"])}]
                assert compact(p["raw"]) in compact(rows[p["para"]-1]), ("主稿记录不一致", p["id"])
                records[p["id"]] = p
                owned_rows[p["para"]].append(p["id"])
    for house in rules:
        lo, hi = house.get("range", [0, len(rows)])
        for r, p in records.items():
            if not p.get("owner") and p["family"] in house["sources"] and lo <= p["para"] <= hi:
                assert r not in assigned, ("人物被分入两户", r)
                assigned[r] = house["id"]
                for s in p["spouses"]:
                    assert s not in assigned
                    assigned[s] = house["id"]
    assert set(assigned) == set(records), "原有记录未全部分户"
    for r, value in plan.get("notes", {}).items():
        records[r]["notes"].extend(value)
    for r, values in plan.get("overrides", {}).items():
        records[r].update(values)
    for new in plan.get("additions", []):
        p = copy.deepcopy(new)
        assert p["id"] not in records
        assert compact(p["name"]) in compact(rows[p["para"]-1]) or p.get("unnamed"), ("补录姓名没有原文依据", p["id"])
        p.setdefault("spouses", [])
        p.setdefault("parent", "")
        p.setdefault("issues", [])
        p.setdefault("notes", [])
        p["original_record"] = False
        p["fragments"] = [{"para": p["para"], "text": compact(p["raw"])}]
        records[p["id"]] = p
        assigned[p["id"]] = p["house"]
        if p.get("owner"):
            records[p["owner"]]["spouses"].append(p["id"])
    house_notes = defaultdict(list)
    ledger = []
    f_by_id = {f["id"]: f for f in families}
    # 没有独立人物行的续行归还给上一条记录，家族开头说明归入本户原文说明。
    for house in rules:
        active = None
        lo, hi = house.get("range", [0, len(rows)])
        spans = [(max(f_by_id[f]["start"], lo), min(f_by_id[f]["end"], hi)) for f in house["sources"]]
        for start, end in spans:
            active = None
            for para in range(start, end+1):
                text = compact(rows[para-1])
                if not text:
                    continue
                targets = [r for r in owned_rows[para] if assigned[r] == house["id"]]
                if targets:
                    active = targets[-1]
                    remainder = text
                    for r in targets:
                        remainder = remainder.replace(compact(records[r]["raw"]), "", 1)
                    if remainder.strip("：:，。；;（）()"):
                        house_notes[house["id"]].append({"para": para, "text": remainder})
                    ledger.append({"para": para, "house": house["id"], "records": targets, "kind": "人物原文", "text": text})
                elif active and not text.startswith(("注：", "高克勤、高克俭家族")) and para != start:
                    records[active]["fragments"].append({"para": para, "text": text})
                    ledger.append({"para": para, "house": house["id"], "records": [active], "kind": "正文续行", "text": text})
                else:
                    house_notes[house["id"]].append({"para": para, "text": text})
                    ledger.append({"para": para, "house": house["id"], "records": [], "kind": "本户说明", "text": text})
    # 原稿段落归类和原文片段另存，图上不展示内部人物编号。
    assert len({x["para"] for x in ledger}) == len(ledger), "原文段落重复分户"
    for p in records.values():
        if p.get("owner"):
            continue
        if p.get("issues"):
            p["notes"].extend("待核："+v for v in p["issues"])
        if not p.get("parent") and p.get("local_level", 1) > 1 and p.get("original_record"):
            p["notes"].append("上代归属待核；按原文称谓暂列层次")
    for rid, p in records.items():
        if p.get("render_as"):
            master=records[p["render_as"]]
            assert master["name"]==p["name"], "同人归并必须保留同一姓名和明确原文依据"
            master["fragments"].extend(p["fragments"])
            master["notes"].extend(p["notes"])
    return rows, records, assigned, house_notes, ledger


def make_profiles(records):
    typography.PROTECTED = []
    result = {}
    for rid, p in records.items():
        name = p["name"]
        title = (("继配" if "继" in p.get("role", "") or "续" in p.get("role", "") else "配")+"："+name) if p.get("owner") else p.get("display_name",name)
        body = []
        if p.get("original_record"):
            original = "".join(x["text"] for x in p["fragments"])
            index = original.find(name)
            if 0 <= index < 25:
                prefix, suffix = original[:index].strip("：:，,；;"), original[index+len(name):].lstrip("：:，,；;")
                if prefix:
                    body.append(prefix)
                if suffix:
                    body.append(suffix)
            else:
                body.append(original)
        else:
            body.append(p.get("body", p["raw"]))
        body.extend(dict.fromkeys(p.get("notes", [])))
        paragraphs = []
        for line in typography.wrap(title, CELL, 26, True):
            paragraphs.append({"text": line, "size": 26, "bold": True, "leading": 35, "align": "center"})
        for value in body:
            for line in typography.wrap(value, CELL, 17):
                paragraphs.append({"text": line, "size": 17, "bold": False, "leading": 24, "align": "left"})
        result[rid] = {"paragraphs": paragraphs, "height": sum(x["leading"] for x in paragraphs)+10,
                       "source_paras": sorted({x["para"] for x in p["fragments"]}), "body": body}
        if p.get("original_record"):
            visible = compact("".join(x["text"] for x in paragraphs))
            original = compact("".join(x["text"] for x in p["fragments"]))
            # 姓名与原称谓在框内重新分行，但原文其余字符不得删除。
            assert all(compact(v) in visible for v in ([original] if index < 0 or index >= 25 else [prefix, name, suffix]) if v), ("人物详情缺失", rid)
    return result


class Household:
    def __init__(self, house, records, assigned, profiles, notes, vertical=False):
        self.vertical = vertical
        self.house, self.records, self.info = house, records, profiles
        self.people = {r: p for r, p in records.items() if assigned[r] == house["id"] and not p.get("owner") and not p.get("render_as")}
        self.parent = {r: p.get("parent", "") for r, p in self.people.items()}
        self.kids = defaultdict(list)
        for r, par in self.parent.items():
            if par in self.people:
                self.kids[par].append(r)
        for values in self.kids.values():
            values.sort(key=lambda r: (self.people[r].get("order", self.people[r]["para"]), r))
        self.generation = {}
        def generation(r, trail):
            assert r not in trail, ("存在亲属循环", r)
            if r not in self.generation:
                parent = self.parent[r]
                self.generation[r] = generation(parent, trail|{r})+1 if parent in self.people else self.people[r].get("generation", self.people[r].get("relative_gen", self.people[r].get("local_level", 1)))
            return self.generation[r]
        for r in self.people:
            generation(r, set())
        self.roots = sorted((r for r in self.people if self.parent[r] not in self.people), key=lambda r: (self.people[r].get("order", self.people[r]["para"]), r))
        self.notes = notes
        values = []
        if house.get("note"):
            values.append("分户说明："+house["note"])
        values.extend(x["text"] for x in notes)
        self.note_text = "　".join(dict.fromkeys(values))
        self.note_lines = typography.wrap(self.note_text, W-160, 19)
        self.floor = H-100-max(90, len(self.note_lines)*28+35)
        self.pages = []

    def unit_width(self, rid):
        if self.vertical:
            return CELL+80 if self.people[rid]["spouses"] else CELL
        return CELL*2+PARTNER_GAP if self.people[rid]["spouses"] else CELL

    def unit_height(self, rid):
        spouses = self.people[rid]["spouses"]
        if self.vertical:
            return self.info[rid]["height"]+sum(self.info[s]["height"]+34 for s in spouses)
        return max(self.info[rid]["height"], sum(self.info[s]["height"] for s in spouses)+32*max(0, len(spouses)-1))

    def subtree(self, r):
        return {r}.union(*(self.subtree(c) for c in self.kids[r]))

    def dimensions(self, members):
        def combine(groups):
            positions, contour = {}, {}
            for child_positions, child_contour in groups:
                shift=max((contour[g][1]+FAMILY_GAP-left for g,(left,right) in child_contour.items() if g in contour),default=0)
                positions.update({r:x+shift for r,x in child_positions.items()})
                for g,(left,right) in child_contour.items():
                    left,right=left+shift,right+shift
                    contour[g]=(min(contour[g][0],left),max(contour[g][1],right)) if g in contour else (left,right)
            return positions,contour
        def measure(r):
            kids=[c for c in self.kids[r] if c in members]
            positions,contour=combine([measure(c) for c in kids])
            center=(positions[kids[0]]+positions[kids[-1]])/2 if kids else self.unit_width(r)/2
            positions[r]=center
            contour[self.generation[r]]=(center-self.unit_width(r)/2,center+self.unit_width(r)/2)
            return positions,contour
        roots = [r for r in self.roots if r in members]
        roots += [r for r in members if self.parent[r] not in members and r not in roots]
        roots.sort(key=lambda r: (self.people[r].get("order", self.people[r]["para"]),r))
        positions,contour=combine([measure(r) for r in roots])
        left=min(v[0] for v in contour.values());right=max(v[1] for v in contour.values())
        positions={r:x-left for r,x in positions.items()}
        width=right-left
        bands = sorted({self.generation[r] for r in members})
        height = sum(max(self.unit_height(r) for r in members if self.generation[r]==g) for g in bands)+ROW_GAP*max(0,len(bands)-1)
        return width, height, positions, roots

    def fits(self, members):
        width, height, _, _ = self.dimensions(members)
        return width <= W-LEFT-RIGHT and height <= self.floor-TOP

    def plan(self):
        entire = set(self.people)
        if self.fits(entire):
            self.pages.append({"members": entire, "part_title": "全户世系"})
            return
        # 完整房支优先；需要拆分时，保留上代框，并依原稿先后逐支排到最末代。
        def branch(root, ancestors=()):
            all_members = self.subtree(root)|set(ancestors)
            if self.fits(all_members):
                self.pages.append({"members": all_members, "part_title": self.people[root]["name"]+"支"})
                return
            children = self.kids[root]
            if not children:
                raise ValueError("单个人物资料超过页面容量："+root)
            context = list(ancestors)+[root]
            if not self.fits(set(context)|{children[0]}):
                if self.fits(set(context)) and not any(set(context) <= page["members"] for page in self.pages):
                    self.pages.append({"members":set(context),"part_title":self.people[root]["name"]+"上代接续"})
                context = [root]
            # 连续的完整小支可共页；遇到大支立即递归，防止跳到下一房后才续前房。
            current = set(context)
            pending = False
            for child in children:
                group = self.subtree(child)
                if self.fits(current|group):
                    current |= group
                    pending = True
                else:
                    if not self.fits(set(context)|group):
                        first_new=len(self.pages)
                        branch(child,tuple(context))
                        if pending:
                            combined=self.pages[first_new]["members"]|current
                            if self.fits(combined):
                                self.pages[first_new]["members"]=combined
                            else:
                                self.pages.insert(first_new,{"members":current,"part_title":self.people[root]["name"]+"支"})
                        current,pending=set(context),False
                        continue
                    if pending:
                        self.pages.append({"members": current, "part_title": self.people[root]["name"]+"支"})
                    current, pending = set(context), False
                    if self.fits(current|group):
                        current |= group
                        pending = True
                    else:
                        branch(child, tuple(context))
            if pending:
                self.pages.append({"members": current, "part_title": self.people[root]["name"]+"支"})
        current = set()
        for root in self.roots:
            group = self.subtree(root)
            if self.fits(current|group):
                current |= group
            else:
                if not self.fits(group):
                    first_new=len(self.pages)
                    branch(root)
                    if current:
                        combined=self.pages[first_new]["members"]|current
                        if self.fits(combined):
                            self.pages[first_new]["members"]=combined
                        else:
                            self.pages.insert(first_new,{"members":current,"part_title":"本户分支"})
                    current=set()
                    continue
                if current:
                    self.pages.append({"members": current, "part_title": "本户分支"})
                current = set()
                if self.fits(group):
                    current = group
                else:
                    branch(root)
        if current:
            self.pages.append({"members": current, "part_title": "本户分支"})
        assert set().union(*(p["members"] for p in self.pages)) == set(self.people)

    def render(self, page, number):
        members = page["members"]
        width,height,xs,roots = self.dimensions(members)
        scale = min(1.65,(W-LEFT-RIGHT)/max(width,1),(self.floor-TOP)/max(height,1))
        assert scale >= .99999, ("分页失败", self.house["id"],width,height)
        offset = LEFT+(W-LEFT-RIGHT-width*scale)/2
        generations = sorted({self.generation[r] for r in members})
        ys, cursor = {}, 0
        for g in generations:
            ys[g] = cursor
            cursor += max(self.unit_height(r) for r in members if self.generation[r]==g)+ROW_GAP
        total = len(self.pages)
        title = self.house["title"]+"系谱图"+(f"（本户第{number}／{total}页）" if total>1 else "")
        atoms=[text_atom(title,70,35,W-140,48,True,height=68)]
        subtitle = "依据《总》逐户编排；一人一框，文字与关系线均可编辑。"
        if total>1:
            subtitle += "本页："+page["part_title"]+"。"
        atoms.append(text_atom(subtitle,80,122,W-160,22,False,height=35))
        atoms.append(text_atom("代次按本户所列关系衔接；始迁代或亲属归属未明确处保留待核。婚配线不直接认定子女的生母、生父。",80,162,W-160,19,False,height=31))
        boxes, ids, edges, marriages = {},[],[],[]
        for g in generations:
            atoms.append(text_atom("第"+chinese_number(g)+"代",12,TOP+ys[g]*scale+4,135,22,True,height=33))
        def record(r,x,y):
            info=self.info[r]
            a=text_atom("\n".join(p["text"] for p in info["paragraphs"]),offset+(x-4)*scale,TOP+y*scale,(CELL+8)*scale,26*scale,True,height=info["height"]*scale)
            a.update(paragraphs=[{**p,"size":p["size"]*scale,"leading":p["leading"]*scale} for p in info["paragraphs"]],person_record=r,source_paras=info["source_paras"])
            atoms.append(a)
            boxes[r]={"x":a["x"],"y":a["y"],"w":a["w"],"h":a["h"],"center":offset+(x+CELL/2)*scale}
            ids.append(r)
        def line(x1,y1,x2,y2,dashed=False):
            atoms.append(line_atom(offset+x1*scale,TOP+y1*scale,offset+x2*scale,TOP+y2*scale,dashed,1.25*scale))
        for r in sorted(members,key=lambda r:(self.generation[r],xs[r])):
            x,y=xs[r]-(CELL if self.vertical else self.unit_width(r))/2,ys[self.generation[r]]
            record(r,x,y)
            if self.vertical:
                sy=y+self.info[r]["height"]+34
                spouses=self.people[r]["spouses"]
                for s in spouses:
                    record(s,x,sy)
                    line(x-6,y+17,x-26,y+17)
                    line(x-26,y+17,x-26,sy+17)
                    line(x-26,sy+17,x-6,sy+17)
                    marriages.append({"person":r,"spouse":s})
                    sy+=self.info[s]["height"]+34
                continue
            sy=y
            partners=self.people[r]["spouses"]
            spine=x+CELL+PARTNER_GAP/2
            if partners:
                line(x+CELL+6,y+17,spine,y+17)
            for s in partners:
                record(s,x+CELL+PARTNER_GAP,sy)
                line(spine,sy+17,x+CELL+PARTNER_GAP-6,sy+17)
                marriages.append({"person":r,"spouse":s})
                sy += self.info[s]["height"]+32
            if len(partners)>1:
                line(spine,y+17,spine,sy-self.info[partners[-1]]["height"]-32+17)
        for p in members:
            children=[c for c in self.kids[p] if c in members]
            if not children:
                continue
            px=xs[p] if self.vertical else xs[p]-self.unit_width(p)/2+CELL/2
            start=ys[self.generation[p]]+self.info[p]["height"]+7
            # 家庭单元最高文字为下代共享横线预留足够间隔。
            joint=ys[self.generation[children[0]]]-46
            assert joint>start
            centers=[xs[c] if self.vertical else xs[c]-self.unit_width(c)/2+CELL/2 for c in children]
            spine=px+CELL/2+25 if self.vertical and self.people[p]["spouses"] else px
            line(px,start,spine,start)
            line(spine,start,spine,joint)
            line(min([spine]+centers),joint,max([spine]+centers),joint)
            for c,cx in zip(children,centers):
                kind=self.people[c].get("edge_kind", "亲子")
                pending="待核" in kind or bool(self.people[c].get("issues"))
                adoption=("承嗣" in kind or "收养" in kind or "继亲" in kind) and not pending
                line(cx,joint,cx,ys[self.generation[c]]-9,adoption)
                label="待核" if pending else ("继" if "继亲" in kind else "嗣") if adoption else "出养" if "出养" in kind else ""
                if label:
                    atoms.append(text_atom(label,offset+(cx+6)*scale,TOP+(joint+5)*scale,55*scale,12*scale,False,height=19*scale))
                edges.append({"parent":p,"child":c,"kind":kind,"pending":pending})
        if self.note_lines:
            yy=self.floor+34
            atom=text_atom("\n".join(self.note_lines),80,yy,W-160,19,False,height=len(self.note_lines)*28+10)
            atom["paragraphs"]=[{"text":s,"size":19,"bold":False,"leading":28,"align":"left"} for s in self.note_lines]
            atoms.append(atom)
        atoms.append(text_atom("图例：横向短线为婚配；下接支线为原稿亲属关系；承嗣另标“嗣”；有疑问处直接标“待核”。",80,H-64,W-260,17,False,height=27))
        atoms.append(text_atom(str(page["global_page"]),W-135,H-64,60,17,False,height=27))
        return {"house_id":self.house["id"],"title":title,"global_page":page["global_page"],"house_page":number,"house_pages":total,"record_ids":ids,"members":sorted(members),"connections":edges,"marriages":marriages,"boxes":boxes,"atoms":atoms,"scale":scale,"vertical_partners":self.vertical}


def main():
    parser=argparse.ArgumentParser(description="逐户合图、完整分支分页和原稿追溯核对")
    for key in ["source","data","rules","plan","out"]:
        parser.add_argument("--"+key,required=True,type=Path)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    data,rules,plan=read(args.data),read(args.rules),read(args.plan)
    rows,records,assigned,notes,ledger=source_model(args.source,data,rules,plan)
    profiles=make_profiles(records)
    pages,summary=[],[]
    for house in rules:
        candidates=[Household(house,records,assigned,profiles,notes[house["id"]],vertical=v) for v in [False,True]]
        for candidate in candidates:
            candidate.plan()
        diagram=min(candidates,key=lambda d:(len(d.pages),d.vertical))
        first=len(pages)+1
        for number,page in enumerate(diagram.pages,1):
            page["global_page"]=len(pages)+1
            pages.append(diagram.render(page,number))
        summary.append({"户号":house["id"],"家族":house["title"],"图页数":len(diagram.pages),"起页":first,"止页":len(pages),"资料记录数":sum(v==house["id"] for v in assigned.values()),"整户一页":len(diagram.pages)==1})
        print(house["id"],house["title"],len(diagram.pages),"页",flush=True)
    layout={"width":W,"height":H,"source":str(args.source),"source_sha256":hashlib.sha256(args.source.read_bytes()).hexdigest(),"original_records":records,"assigned":assigned,"profiles":profiles,"pages":pages,"households":summary,"source_ledger":ledger}
    dump(args.out/"逐户图册版面.json",layout)
    write_presentation(pages,W,H,args.out/"村志系谱图_以总为准_一户一图_可编辑.pptx")
    separate=args.out/"逐户可编辑文件"
    separate.mkdir(exist_ok=True)
    for item in summary:
        safe=re.sub(r'[<>:"/\\|?*]','',item["家族"])
        write_presentation([p for p in pages if p["house_id"]==item["户号"]],W,H,separate/(item["户号"]+"_"+safe+".pptx"))
    with (args.out/"逐户页数与原文记录清单.csv").open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    with (args.out/"人物与图页核对.csv").open("w",encoding="utf-8-sig",newline="") as handle:
        fields=["记录编号","户号","姓名","原稿段","图页","亲属归属","原文"]
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for r,p in records.items():
            writer.writerow({"记录编号":r,"户号":assigned[r],"姓名":p["name"],"原稿段":p["para"],"图页":"、".join(str(x["global_page"]) for x in pages if p.get("render_as",r) in x["record_ids"]),"亲属归属":records.get(p.get("owner") or p.get("parent"),{}).get("name",""),"原文":"".join(x["text"] for x in p["fragments"])})
    dump(args.out/"分户统计.json",summary)
    print("已生成",len(summary),"户",len(pages),"页；资料记录",len(records),flush=True)


if __name__=="__main__":
    main()
