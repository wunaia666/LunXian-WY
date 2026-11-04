"""按原文完整保留人物信息，依门序和支序生成原生可编辑系谱图。"""

from __future__ import annotations

import argparse
import copy
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import ImageFont

from build_genealogy_charts import line_atom, text_atom
from build_genealogy_presentation import write_presentation
from build_standalone_genealogy import chinese_number, load_model


W, H = 2383.94, 1683.78
LEFT, RIGHT, TOP, FLOOR = 122, 52, 185, 1515
CELL, STEP, GAP = 210, 221, 38
NAME_SIZE, BODY_SIZE = 26, 17
FONTS = {}
PROTECTED = []


def compact(value):
    return re.sub(r"\s+", "", value).replace("※", "")


def content_key(value):
    return "".join(c for c in compact(value) if not unicodedata.category(c).startswith("P"))


def wrap(value, width, size, bold=False):
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype("C:/Windows/Fonts/simhei.ttf" if bold else "C:/Windows/Fonts/simsun.ttc", round(size*4))
    font = FONTS[key]
    names="|".join(re.escape(v) for v in PROTECTED)
    pieces = re.findall(r"(?:1[6-9]|20)\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?)?|"+("(?:"+names+")|" if names else "")+r"[A-Za-z\u00c0-\u024f]+|.",value)
    tokens = []
    for piece in pieces:
        if piece in "，。；：、）】》！？" and tokens:
            tokens[-1] += piece
        else:
            tokens.append(piece)
    lines, current = [], ""
    for token in tokens:
        if current and font.getlength(current+token)/4 > width-5:
            lines.append(current)
            current = ""
        current += token
    if current:
        lines.append(current)
    return lines


def source_material(paragraphs, records, plan):
    pieces = defaultdict(list)
    ledger = []
    primary = defaultdict(list)
    for rid, person in records.items():
        if not rid.startswith("补"):
            primary[person["para"]].append(rid)
    for rid, value in plan.get("verbatim_overrides",{}).items():
        for para in value.get("primary_paragraphs",[]):
            primary[para].append(rid)
    names = defaultdict(list)
    for rid, person in records.items():
        if not person.get("owner") and not person.get("related_to") and "失考" not in person["name"]:
            names[person["name"]].append(rid)
    active, anchor = None, None
    explicit = {int(k):v for k,v in plan.get("paragraph_owners",{}).items()}
    pending = []
    for index, original in enumerate(paragraphs,1):
        if index < plan.get("verbatim_start",57) or not original.strip():
            continue
        text = compact(original)
        if not text:
            continue
        if text.startswith("【"):
            active = None
            found = [(text.rfind(name),rid) for name,ids in names.items() if name in text for rid in ids if records[rid]["para"]<index]
            anchor = max(found,key=lambda x:(x[0],records[x[1]]["para"]))[1] if found else None
            tail = text.split("】",1)[1] if "】" in text else ""
            if tail:
                owner = explicit.get(index,anchor)
                if owner:
                    pieces[owner].append({"para":index,"text":tail,"whole":False})
                    ledger.append({"para":index,"original":original,"fragments":[tail],"records":[owner]})
                else:
                    pending.append((index,original))
            continue
        generation = re.match(r"^第[一二三四五六七八九十百]+[代世](?:[：:]?〖.*?〗)?",text)
        if generation:
            tail = text[generation.end():].strip("：:")
            if tail:
                owner = explicit.get(index,active or anchor)
                if owner:
                    pieces[owner].append({"para":index,"text":tail,"whole":False})
                    ledger.append({"para":index,"original":original,"fragments":[tail],"records":[owner]})
                else:
                    pending.append((index,original))
            continue
        if text.startswith(("（从第六代开始", "(从第六代开始")):
            continue
        if primary[index]:
            targets = primary[index]
            fragments = []
            for rid in targets:
                person = records[rid]
                raw = compact(person["raw"])
                if rid.startswith("补"):
                    raw = text
                pieces[rid].append({"para":index,"text":raw,"whole":True})
                fragments.append(raw)
                if not person.get("owner"):
                    active = rid
            ledger.append({"para":index,"original":original,"fragments":fragments,"records":targets})
            # 同段内的主体和配偶被拆成两条记录时，必须能完整还原原段。
            assert content_key("".join(fragments))==content_key(text), ("原段拆分不完整",index,fragments,text)
        else:
            owner = explicit.get(index,active or anchor)
            if owner:
                pieces[owner].append({"para":index,"text":text,"whole":False})
                ledger.append({"para":index,"original":original,"fragments":[text],"records":[owner]})
            else:
                pending.append((index,original))
    assert not pending, ("原文尚未定位",pending)
    return pieces,ledger


def profiles(records,pieces,plan):
    result = {}
    for rid,person in records.items():
        override = plan.get("verbatim_overrides",{}).get(rid,{})
        title = override.get("caption", person.get("display_name",person["name"]))
        body, fragments = [], []
        if override.get("body") is not None:
            body = list(override["body"])
            fragments = list(body)
        else:
            for item in pieces[rid]:
                text = item["text"]
                name = person["name"]
                position = text.find(name)
                if item["whole"] and 0<=position<20:
                    prefix = text[:position].strip("：:，,；;")
                    suffix = text[position+len(name):].lstrip("：:，,；;")
                    if person.get("owner"):
                        title = (prefix or person.get("role") or "配")+"："+name
                    elif "失考" in name:
                        title = (prefix+"（"+name+"）") if prefix else name
                    else:
                        title = name
                        if prefix:
                            body.append(prefix)
                    if suffix:
                        body.append(suffix)
                    fragments.extend(v for v in [name,prefix,suffix] if v)
                else:
                    body.append(text)
                    fragments.append(text)
        if person.get("related_to"):
            title = person["name"]
        notes=person.get("chart_notes",[])
        has_pending=person.get("uncertain") or any(re.search(r"待核|原列第|两支重载|不符|差六年",v) for v in notes)
        for note in notes:
            if has_pending and not re.search(r"详支|续见|承上见|同号|另支详载|另处详载",note):
                value = "核对注："+note
                if not any(content_key(note) in content_key(v) for v in body):
                    body.append(value)
        paragraphs = []
        title_parts=[title]
        if "（" in title and len(wrap(title,CELL,NAME_SIZE,True))>1:
            title_parts=re.split(r"(?=（)",title)
        for text in [line for part in title_parts for line in wrap(part,CELL,NAME_SIZE,True)]:
            paragraphs.append({"text":text,"size":NAME_SIZE,"bold":True,"leading":34,"align":"center"})
        for text in body:
            for part in wrap(text,CELL,BODY_SIZE):
                paragraphs.append({"text":part,"size":BODY_SIZE,"bold":False,"leading":23,"align":"left"})
        assert paragraphs, rid
        visible = content_key("".join(v["text"] for v in paragraphs))
        for fragment in fragments:
            assert content_key(fragment) in visible, ("正文片段缺失",rid,fragment)
        result[rid]={"paragraphs":paragraphs,"height":sum(v["leading"] for v in paragraphs)+4,"fragments":fragments,"source_paras":sorted({v["para"] for v in pieces[rid]}|set(override.get("source_paras",[])))}
    return result


def main():
    parser=argparse.ArgumentParser(description="按门序逐支排完并完整保留原文")
    for key in ["source","data","plan","registry","out"]:
        parser.add_argument("--"+key,required=True,type=Path)
    args=parser.parse_args()
    read=lambda path:json.loads(path.read_text(encoding="utf-8"))
    plan=read(args.plan)
    families,records,people,spouses,ids,initial=load_model(read(args.data),plan,read(args.registry)["record_to_person"])
    paragraphs=[p.text for p in Document(args.source).paragraphs]
    pieces,ledger=source_material(paragraphs,records,plan)
    global PROTECTED
    protected={r["name"] for r in records.values() if 1<len(r["name"])<12}
    surname=people[plan["gates"][0]["root"]]["name"][0]
    protected|={r["name"][1:] for r in records.values() if r["name"].startswith(surname) and 3<=len(r["name"])<=5}
    protected|={"名讳失考","氏名不详","后裔无考","待核"}
    for paragraph in paragraphs:
        protected.update(re.findall(r"(?:合葬于|合葬|葬于|移到)([\u3400-\u9fff]{2,10})",compact(paragraph)))
    PROTECTED=sorted(protected,key=lambda v:(-len(v),v))
    info=profiles(records,pieces,plan)
    parent={rid:plan.get("plot_parent_overrides",{}).get(rid,p.get("layout_parent")) for rid,p in people.items()}
    for rid,target in plan.get("plot_parent_overrides",{}).items():
        assert ids[people[rid]["layout_parent"]]==ids[target],"展示接续不得换成另一人物"
    kids=defaultdict(list)
    for rid,par in parent.items():
        if par in people:
            kids[par].append(rid)
    for rid in people:
        kids[rid].sort(key=lambda r:(people[r].get("order",people[r]["para"]),r))
    for rid,values in plan.get("child_order_overrides",{}).items():
        assert set(values)==set(kids[rid]),"明确子女次序不得增删成员"
        kids[rid]=values
    def subtree(root):
        output={root}
        for child in kids[root]:output |= subtree(child)
        return output
    def total_height(rid):
        return sum(info[s]["height"]+10 for s in [rid]+people[rid]["spouses"])
    def fit(members):
        leaves=[r for r in members if not any(c in members for c in kids[r])]
        if (len(leaves)-1)*STEP+CELL>W-LEFT-RIGHT:
            return False
        bands=sorted({people[r]["generation"] for r in members})
        height=sum(max(total_height(r) for r in members if people[r]["generation"]==g) for g in bands)+GAP*(len(bands)-1)
        return height<=FLOOR-TOP
    pages=[]
    def emit(root,members,gate,overview=False):
        assert fit(members), ("整组仍放不下",root,len(members))
        pages.append({"root":root,"members":members,"gate":gate,"overview":overview})
    def branch(root,gate):
        all_members=subtree(root)
        if fit(all_members):
            emit(root,all_members,gate)
            return
        cursor,frontier=root,{root}
        choice=None
        while True:
            proposed=frontier|set(kids[cursor])
            if not fit(proposed):break
            choice=(cursor,proposed)
            expanding=[c for c in kids[cursor] if kids[c]]
            if len(expanding)!=1:break
            frontier=proposed
            cursor=expanding[0]
        assert choice,("家庭成员不能同时列齐",root)
        cursor,members=choice
        completed=set()
        # 只把按原文顺序在前且能完整放下的支系纳入本页，不能截半支插入后代。
        for child in kids[cursor]:
            if not kids[child]:continue
            proposed=members|subtree(child)
            if not fit(proposed):break
            members=proposed
            completed.add(child)
        emit(root,members,gate,True)
        for child in kids[cursor]:
            if kids[child] and child not in completed:branch(child,gate)
    common=set(plan["common_records"])
    emit(plan["common_root"],common,{"number":0,"title":"共同祖先"},False)
    for gate in plan["gates"]:
        branch(gate["root"],gate)
    gate_numbers=[p["gate"]["number"] for p in pages]
    assert gate_numbers==sorted(gate_numbers),"门序交错"
    labels={s["id"]:s.get("generation_labels",plan.get("generation_labels",{})) for s in plan["sections"]}
    global_labels=plan.get("generation_labels",{})
    def ancestry(root):
        path=[]
        current=root
        while parent.get(current) in people:
            current=parent[current]
            path.append(people[current].get("display_name",people[current]["name"]))
        return "—".join(reversed(path))
    output=[]
    for number,page in enumerate(pages,1):
        members=page["members"]
        root,gate=page["root"],page["gate"]
        bands=sorted({people[r]["generation"] for r in members})
        roots=[r for r in members if parent.get(r) not in members]
        xs,cursor={},[0]
        def place(r):
            positions=[place(c) for c in kids[r] if c in members]
            if positions:
                xs[r]=(min(positions)+max(positions))/2
            else:
                xs[r]=cursor[0]*STEP
                cursor[0]+=1
            return xs[r]
        for r in sorted(roots,key=lambda r:people[r]["para"]):place(r)
        width=(cursor[0]-1)*STEP+CELL
        shift=LEFT+(W-LEFT-RIGHT-width)/2
        ys,y={},TOP
        for g in bands:
            ys[g]=y
            y+=max(total_height(r) for r in members if people[r]["generation"]==g)+GAP
        title=gate["title"]
        if gate["number"]:
            title+=" · "+people[root].get("display_name",people[root]["name"])+("本房成员" if page["overview"] else "支")
        atoms=[text_atom(title,70,30,W-140,36,True,height=48)]
        path=ancestry(root)
        if path:atoms.append(text_atom("世系："+path,80,92,W-160,17,False,height=30))
        bounds={}
        visible=sorted(members,key=lambda r:(people[r]["generation"],xs[r]))
        record_ids=[]
        for g in bands:
            family_values={labels.get(people[r]["family"],global_labels).get(str(g),"") for r in members if people[r]["generation"]==g}
            character=next(iter(family_values)) if len(family_values)==1 else global_labels.get(str(g),"")
            text="第"+chinese_number(g)+"代"+("\n【"+character+"】" if character else "")
            paragraphs2=[{"text":text.split("\n")[0],"size":19,"bold":True,"leading":28}]
            if character:
                for part in wrap("【"+character+"】",112,13):paragraphs2.append({"text":part,"size":13,"bold":False,"leading":19})
            a=text_atom(text,6,ys[g]+2,112,19,True,height=sum(v["leading"] for v in paragraphs2)+2)
            a["paragraphs"]=paragraphs2
            a["generation_label"]=g
            atoms.append(a)
        line_offset=len(atoms)
        for rid in visible:
            x,yy=shift+xs[rid],ys[people[rid]["generation"]]
            top=yy
            for record in [rid]+people[rid]["spouses"]:
                v=info[record]
                # 保留中文标点的悬挂余量，姓名中心仍与接线中心一致。
                a=text_atom("\n".join(p["text"] for p in v["paragraphs"]),x-4,yy,CELL+8,v["paragraphs"][0]["size"],True,height=v["height"])
                a.update(paragraphs=copy.deepcopy(v["paragraphs"]),person_record=record,source_paras=v["source_paras"])
                atoms.append(a)
                record_ids.append(record)
                yy+=v["height"]+10
            bounds[rid]={"center":x+CELL/2,"top":top,"bottom":yy-10}
        edges,connections=[],[]
        for par in visible:
            groups=defaultdict(list)
            for child in kids[par]:
                if child in members:groups[people[child]["generation"]].append(child)
            for generation,children in groups.items():
                px,sy=bounds[par]["center"],bounds[par]["bottom"]+5
                joint=min(bounds[c]["top"] for c in children)-23
                assert sy<joint,("接线空间不足",par,children)
                centers=[px]+[bounds[c]["center"] for c in children]
                edges += [line_atom(px,sy,px,joint,False,1.2),line_atom(min(centers),joint,max(centers),joint,False,1.2)]
                for child in children:
                    cx,ey=bounds[child]["center"],bounds[child]["top"]-5
                    edges.append(line_atom(cx,joint,cx,ey,False,1.2))
                    p=people[child]
                    tag="待核" if p.get("uncertain") else "嗣" if re.search("承嗣|收养",p.get("edge_kind","")) else "继" if "继女" in p.get("edge_kind","") else "女系" if "女系" in p.get("edge_kind","") else ""
                    if tag:edges.append(text_atom(tag,cx+5,joint+1,48,13,True,"left",height=20))
                    connections.append({"parent":par,"child":child,"parent_center":px,"child_center":cx,"start_y":sy,"joint_y":joint,"end_y":ey})
        for relation in plan.get("additional_relations",[]):
            par,child=relation["from_record"],relation["to_record"]
            if par in bounds and child in bounds:
                px,sy=bounds[par]["center"],bounds[par]["bottom"]+5
                cx,ey=bounds[child]["center"],bounds[child]["top"]-5
                joint=bounds[child]["top"]-30
                assert sy<joint
                edges += [line_atom(px,sy,px,joint,False,1.2),line_atom(px,joint,cx,joint,False,1.2),line_atom(cx,joint,cx,ey,False,1.2)]
                edges.append(text_atom(relation["label"],min(px,cx)+8,joint+2,max(230,abs(px-cx)-16),13,False,"left",height=20))
                connections.append({"parent":par,"child":child,"additional":True,"kind":relation["kind"]})
        atoms[line_offset:line_offset]=edges
        for related in plan.get("related_people",[]):
            if related["related_to"] not in members:continue
            v=info[related["id"]]
            x,y=W-RIGHT-CELL,FLOOR-v["height"]
            assert all(a["kind"]!="text" or x+CELL<a["x"] or a["x"]+a["w"]<x or y+v["height"]<a["y"] or a["y"]+a["h"]+8<y for a in atoms),"关联人物区域被占用"
            a=text_atom("\n".join(p["text"] for p in v["paragraphs"]),x-4,y,CELL+8,NAME_SIZE,True,height=v["height"])
            a.update(paragraphs=copy.deepcopy(v["paragraphs"]),person_record=related["id"],non_genealogical=True,source_paras=v["source_paras"])
            atoms.append(a)
            record_ids.append(related["id"])
        # 内容较少的房图按实际占用空间同比放大，正文至少保持基础字号。
        person_atoms=[a for a in atoms if a.get("person_record")]
        left=min(a["x"] for a in person_atoms)
        top=min(a["y"] for a in person_atoms)
        right=max(a["x"]+a["w"] for a in person_atoms)
        bottom=max(a["y"]+a["h"] for a in person_atoms)
        scale=min(1.5,(W-LEFT-RIGHT)/(right-left),(FLOOR-TOP)/(bottom-top))
        if scale<1.05:scale=1.0
        target_left=LEFT+(W-LEFT-RIGHT-(right-left)*scale)/2
        def tx(value):return target_left+(value-left)*scale
        def ty(value):return TOP+(value-top)*scale
        if scale>1:
            for a in atoms:
                if a["kind"]=="line":
                    for k in ["x1","x2"]:a[k]=tx(a[k])
                    for k in ["y1","y2"]:a[k]=ty(a[k])
                    a["width"]*=scale
                elif a.get("generation_label"):
                    a["y"]=ty(a["y"])
                elif a.get("person_record") or a["y"]>=TOP-40:
                    a["x"],a["y"]=tx(a["x"]),ty(a["y"])
                    for k in ["w","h","size"]:a[k]*=scale
                    for v in a.get("paragraphs",[]):
                        v["size"]*=scale
                        v["leading"]*=scale
            for e in connections:
                for k in ["parent_center","child_center"]:
                    if k in e:e[k]=tx(e[k])
                for k in ["start_y","joint_y","end_y"]:
                    if k in e:e[k]=ty(e[k])
            atoms[0]["size"]=42
        atoms.append(text_atom("标有“待核”的接续尚未确认；收养、出继、继亲和抚养等按原文另注。",70,H-58,W-180,13,False,"left",height=24))
        atoms.append(text_atom(str(number),W-100,H-58,40,15,False,"right",height=24))
        for a in atoms:
            if a["kind"]=="text":
                assert 0<=a["x"] and a["x"]+a["w"]<=W+0.1
                assert 0<=a["y"] and a["y"]+a["h"]<=H+0.1
                assert not re.search(r"(?:详支|续见|承上见)[\d、]+页",a["text"])
        output.append({"house_id":str(gate["number"]),"house_title":title,"global_page":number,"local_page":number,"local_total":len(pages),"atoms":atoms,"record_ids":record_ids,"connections":connections,"scope_root":root,"gate_number":gate["number"],"overview":page["overview"],"diagram_scale":scale})
    assert {rid for p in output for rid in p["record_ids"]}==set(records),"原有人物记录未覆盖"
    # 分房总述必须把同一家庭的全部直接子女同时列齐。
    for page in pages:
        if page["overview"]:
            frontier=[r for r in page["members"] if any(c in page["members"] for c in kids[r])]
            for r in frontier:assert set(kids[r])<=page["members"] or len(kids[r])==1
    args.out.mkdir(parents=True,exist_ok=True)
    payload={"width":W,"height":H,"pages":output,"page_count":len(output),"record_count":len(records),"source_ledger":ledger,"profiles":info,"plot_parents":parent,"original_records":records}
    (args.out/"全文门序版面.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    write_presentation(output,W,H,args.out/(plan["title"]+"_原文完整_按门逐支可编辑.pptx"))
    split=args.out/"各门可编辑文稿"
    split.mkdir(exist_ok=True)
    for gate in [{"number":0,"title":"共同祖先"}]+plan["gates"]:
        selected=[p for p in output if p["gate_number"]==gate["number"]]
        write_presentation(selected,W,H,split/(gate["title"]+".pptx"))
    write_index(payload,plan,args.out)
    print(f"全文门序版共{len(output)}张，保留{len(records)}条人物记录，逐段定位原文{len(ledger)}段。")
    for gate in [{"number":0,"title":"共同祖先"}]+plan["gates"]:
        selected=[p["global_page"] for p in output if p["gate_number"]==gate["number"]]
        print(gate["title"],min(selected),max(selected))


def write_index(payload,plan,out):
    doc=Document()
    section=doc.sections[0]
    section.page_width,section.page_height=Cm(21),Cm(29.7)
    section.top_margin=section.bottom_margin=Cm(1.7)
    section.left_margin=section.right_margin=Cm(1.8)
    normal=doc.styles["Normal"]
    normal.font.name="宋体"
    normal.font.size=Pt(10)
    normal.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"),"宋体")
    doc.add_heading(plan["title"]+"原文与系谱图逐段对照",0)
    doc.add_paragraph("按原稿门序逐门排完，各门内部按支序连续展开。人物原文信息保留在各自文本框内；配偶单独列框。图上不使用跳页提示，不使用虚线；未确认的接续直接标“待核”。")
    mapping=defaultdict(set)
    for page in payload["pages"]:
        for rid in page["record_ids"]:mapping[rid].add(page["global_page"])
    doc.add_heading("门序目录",1)
    table=doc.add_table(rows=1,cols=2)
    table.style="Table Grid"
    table.rows[0].cells[0].text="门别"
    table.rows[0].cells[1].text="图页"
    for number in sorted({p["gate_number"] for p in payload["pages"]}):
        pages=[p for p in payload["pages"] if p["gate_number"]==number]
        row=table.add_row().cells
        row[0].text="共同祖先" if number==0 else next(g["title"] for g in plan["gates"] if g["number"]==number)
        row[1].text=str(pages[0]["global_page"])+("—"+str(pages[-1]["global_page"]) if len(pages)>1 else "")
    doc.add_heading("原文逐段对应",1)
    table=doc.add_table(rows=1,cols=4)
    table.style="Table Grid"
    table.autofit=False
    widths=[1.3,10.0,3.1,3.0]
    for column,width in zip(table.columns,widths):column.width=Cm(width)
    for cell,width in zip(table.rows[0].cells,widths):cell.width=Cm(width)
    for c,t in zip(table.rows[0].cells,["原稿段","原文","人物框","图页"]):c.text=t
    header=OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(header)
    for item in payload["source_ledger"]:
        row=table.add_row().cells
        values=[str(item["para"]),item["original"],"、".join(payload["original_records"][r]["name"] for r in item["records"]),"、".join(map(str,sorted({n for r in item["records"] for n in mapping[r]})))]
        for c,t in zip(row,values):c.text=t
        for c,width in zip(row,widths):c.width=Cm(width)
        keep=OxmlElement("w:cantSplit")
        row[0]._tc.getparent().get_or_add_trPr().append(keep)
    zoom=doc.settings.element.find(qn("w:zoom"))
    if zoom is not None:zoom.set(qn("w:percent"),"100")
    doc.core_properties.author=""
    doc.core_properties.last_modified_by=""
    doc.save(out/(plan["title"]+"_原文逐段对照表.docx"))


if __name__=="__main__":
    main()
