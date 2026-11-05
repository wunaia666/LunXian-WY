"""独立核对主稿人物、原文段落、图册接线和可编辑对象的一致性。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree


def compact(value):
    return re.sub(r"\s+", "", str(value))


def overlaps(a, b):
    return min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])>1 and min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])>1


def main():
    parser=argparse.ArgumentParser(description="主稿、图册、文本框和关系线交叉核验")
    for key in ["source","data","layout","presentation","out"]:
        parser.add_argument("--"+key,required=True,type=Path)
    parser.add_argument("--pdf",type=Path)
    args=parser.parse_args()
    read=lambda p:json.loads(p.read_text(encoding="utf-8"))
    source=Document(args.source)
    data,layout=read(args.data),read(args.layout)
    records=layout["original_records"]
    original={p["id"]:p for f in data["families"] if f["source"]=="总" for p in f["people"]+f["spouses"]}
    expected={r for r,p in records.items() if not p.get("render_as")}
    result={"原稿人物及配偶记录":len(original),"补入原文资料记录":len(records)-len(original),"保留记录合计":len(records),"合框后资料框记录":len(expected),"家族户数":len(layout["households"]),"整户单页户数":sum(x["整户一页"] for x in layout["households"]),"图页数":len(layout["pages"]),"遗漏记录":[],"文字重叠":[],"连线穿字":[],"页面越界":[],"接线遗漏":[],"原文未归段":[],"章节标题与分隔段":[]}
    assert set(original)<=set(records), "遗漏原有记录"
    for r,p in original.items():
        master=records[records[r].get("render_as",r)]
        assert compact(p["raw"]) in compact("".join(x["text"] for x in master["fragments"])), ("原文记录片段缺失",r)
    ledger={x["para"] for x in layout["source_ledger"]}
    for i,p in enumerate(source.paragraphs,1):
        if p.text.strip() and i not in ledger:
            key="章节标题与分隔段" if i<=2 or not compact(p.text).replace("※", "") else "原文未归段"
            result[key].append({"段":i,"原文":p.text})
    namespaces={"p":"http://schemas.openxmlformats.org/presentationml/2006/main","a":"http://schemas.openxmlformats.org/drawingml/2006/main"}
    seen,edges,marriages=set(),set(),set()
    text_boxes=0
    with ZipFile(args.presentation) as archive:
        assert archive.testzip() is None
        assert not any(n.startswith("ppt/media/") for n in archive.namelist()), "人物图不得替换为整图图片"
        for number,page in enumerate(layout["pages"],1):
            root=etree.fromstring(archive.read(f"ppt/slides/slide{number}.xml"))
            actual=root.xpath('//p:cNvPr[starts-with(@descr,"原文记录：")]/@descr',namespaces=namespaces)
            actual=[v.split("：",1)[1] for v in actual]
            assert len(actual)==len(set(actual)), ("同一人物同页超过一个框",number)
            assert set(actual)==set(page["record_ids"])
            seen.update(actual)
            text_boxes+=len(actual)
            edges.update((e["parent"],e["child"]) for e in page["connections"])
            marriages.update((e["person"],e["spouse"]) for e in page["marriages"])
            text="".join(root.xpath('//a:t/text()',namespaces=namespaces))
            assert not re.search(r"人\s*00\d+|详支\d|续见\d|承上见\d",text)
            assert not any(a["kind"]=="brace" for a in page["atoms"])
            atoms=[a for a in page["atoms"] if a["kind"]=="text"]
            for i,a in enumerate(atoms):
                rectangle=(a["x"],a["y"],a["w"],a["h"])
                if a["x"] < -1 or a["y"] < -1 or a["x"]+a["w"]>layout["width"]+1 or a["y"]+a["h"]>layout["height"]+1:
                    result["页面越界"].append({"页":number,"记录":a.get("person_record"),"文字":a["text"][:60]})
                for b in atoms[i+1:]:
                    if overlaps(rectangle,(b["x"],b["y"],b["w"],b["h"])):
                        result["文字重叠"].append({"页":number,"甲":a.get("person_record",a["text"][:20]),"乙":b.get("person_record",b["text"][:20])})
            boxes=[a for a in atoms if a.get("person_record")]
            for line in [a for a in page["atoms"] if a["kind"]=="line"]:
                x1,x2=sorted([line["x1"],line["x2"]]);y1,y2=sorted([line["y1"],line["y2"]])
                if x2-x1<.01 and y2-y1<.01:
                    continue
                for b in boxes:
                    hit=False
                    if abs(y2-y1)<.01:
                        hit=b["y"]+.5<y1<b["y"]+b["h"]-.5 and min(x2,b["x"]+b["w"])-max(x1,b["x"])>.5
                    if abs(x2-x1)<.01:
                        hit=b["x"]+.5<x1<b["x"]+b["w"]-.5 and min(y2,b["y"]+b["h"])-max(y1,b["y"])>.5
                    if hit:
                        result["连线穿字"].append({"页":number,"人物":b["person_record"],"线":[x1,y1,x2,y2]})
    source_missing=[]
    household_text=defaultdict(str)
    record_text={}
    for page in layout["pages"]:
        for atom in page["atoms"]:
            if atom["kind"]!="text":
                continue
            value=compact("".join(p["text"] for p in atom.get("paragraphs",[{"text":atom["text"]}])))
            household_text[page["house_id"]]+=value
            if atom.get("person_record"):
                record_text[atom["person_record"]]=value
    for r,p in original.items():
        target=records[r].get("render_as",r)
        value=record_text[target]
        raw,name=compact(p["raw"]),p["name"]
        index=raw.find(name)
        parts=[raw] if not 0<=index<25 else [raw[:index].strip("：:，,；;"),name,raw[index+len(name):].lstrip("：:，,；;")]
        if not all(part in value for part in parts if part):
            source_missing.append({"记录":r,"段":p["para"]})
    for entry in layout["source_ledger"]:
        if entry["kind"]=="本户说明":
            value=household_text[entry["house"]]
        elif entry["kind"]=="正文续行":
            rid=entry["records"][0]
            value=record_text[records[rid].get("render_as",rid)]
        else:
            continue
        if compact(entry["text"]) not in value:
            source_missing.append({"段":entry["para"],"类别":entry["kind"]})
    result["原文片段回读缺项"]=source_missing
    result["遗漏记录"]=sorted(expected-seen)
    assert seen==expected, ("图册人物不全",expected-seen,seen-expected)
    expected_edges={(p["parent"],r) for r,p in records.items() if r in expected and not p.get("owner") and p.get("parent") in expected and layout["assigned"][r]==layout["assigned"][p["parent"]]}
    result["接线遗漏"]=[list(v) for v in sorted(expected_edges-edges)]
    assert edges<=expected_edges, ("无依据的新接线",edges-expected_edges)
    expected_marriages={(r,s) for r,p in records.items() if r in expected for s in p.get("spouses",[])}
    assert marriages==expected_marriages, ("婚配连线缺失",expected_marriages-marriages)
    result["文本框出现次数"]=text_boxes
    result["亲属接线数"]=len(edges)
    result["婚配接线数"]=len(marriages)
    result["待核记录数"]=sum(bool(p.get("issues")) or any("待核" in n for n in p.get("notes",[])) for p in records.values())
    if args.pdf:
        import fitz
        pdf=fitz.open(args.pdf)
        assert len(pdf)==len(layout["pages"]), "打印页数不一致"
        missing=[]
        for number,page in enumerate(layout["pages"]):
            actual=compact(pdf[number].get_text())
            for atom in page["atoms"]:
                if not atom.get("person_record"):
                    continue
                for paragraph in atom["paragraphs"]:
                    value=compact(paragraph["text"])
                    if value not in actual:
                        missing.append({"页":number+1,"记录":atom["person_record"],"片段":value})
        result["打印文字回读缺项"]=missing
        pdf.close()
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if not isinstance(v,list)},ensure_ascii=False))
    print("问题计数",json.dumps({k:len(v) for k,v in result.items() if isinstance(v,list)},ensure_ascii=False))
    errors=[k for k in ["遗漏记录","文字重叠","连线穿字","页面越界","接线遗漏","原文未归段","原文片段回读缺项","打印文字回读缺项"] if result.get(k)]
    if errors:
        raise SystemExit("尚未通过："+"、".join(errors))


if __name__=="__main__":
    main()
