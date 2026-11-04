"""交叉检查原稿、人物底表和修订前后的系谱图，生成可追溯核对记录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree


def normalized(text):
    return re.sub(r"\s+", "", str(text))


def audit(source, before, after, records, plan, presentation=None):
    paragraphs = [p.text for p in Document(source).paragraphs]
    old_ids = {r for p in before["pages"] for r in p["record_ids"]}
    new_ids = {r for p in after["pages"] for r in p["record_ids"]}
    assert old_ids <= new_ids, "修订后漏掉原有人物记录"
    assert new_ids == set(records), "底表与图册人物不一致"
    old_edges = {(e["parent"], e["child"]) for p in before["pages"] for e in p["connections"]}
    new_edges = {(e["parent"], e["child"]) for p in after["pages"] for e in p["connections"]}
    added_edges = {(e["from_record"], e["to_record"]) for e in plan.get("additional_relations", [])}
    assert old_edges <= new_edges, "修订时丢失原有关联接线"
    assert new_edges-old_edges == added_edges, "出现无依据的新接线"
    mapping = defaultdict(set)
    by_paragraph = defaultdict(list)
    for p in after["pages"]:
        assert len(p["record_ids"]) == len(set(p["record_ids"])), "同一页重复建立人物框"
        boxes = [a["person_record"] for a in p["atoms"] if a.get("person_record")]
        assert len(boxes) == len(set(boxes)) == len(p["record_ids"]), "人物未保持一人一框"
        assert set(boxes) == set(p["record_ids"])
        for rid in boxes:
            mapping[rid].add(p["global_page"])
    for rid, person in records.items():
        paragraph = person["para"]
        assert 1 <= paragraph <= len(paragraphs), "原稿出处越界"
        by_paragraph[paragraph].append(rid)
        if person.get("related_to"):
            assert person["name"] in normalized(paragraphs[paragraph-1]), "关联人物没有原文姓名依据"
            assert person.get("generation") is None, "不得给外部关联人物硬排宗谱世次"
        current, seen = rid, set()
        while current in records:
            assert current not in seen, "关系发生循环"
            seen.add(current)
            value = records[current]
            current = value.get("layout_parent") or value.get("parent")
    if presentation:
        namespaces = {"p":"http://schemas.openxmlformats.org/presentationml/2006/main", "a":"http://schemas.openxmlformats.org/drawingml/2006/main"}
        with ZipFile(presentation) as package:
            assert package.testzip() is None
            assert not any(n.startswith("ppt/media/") for n in package.namelist()), "可编辑图册混入整图图片"
            for i, page in enumerate(after["pages"], 1):
                root = etree.fromstring(package.read(f"ppt/slides/slide{i}.xml"))
                rendered = root.xpath('//p:cNvPr[starts-with(@descr,"原文记录：")]/@descr', namespaces=namespaces)
                assert len(rendered) == len(set(rendered)) == len(page["record_ids"])
                assert {v.removeprefix("原文记录：") for v in rendered} == set(page["record_ids"])
                text = "".join(root.xpath("//a:t/text()",namespaces=namespaces))
                assert not re.search(r"人\s*00\d+|补张\s*\d+", text), "图上泄漏核对编号"
    ledger = []
    for index, text in enumerate(paragraphs, 1):
        if not text.strip():
            continue
        related = []
        for rid in by_paragraph[index]:
            person = records[rid]
            related.append({"记录编号":rid,"姓名":person["name"],"图页":sorted(mapping[rid]),
                            "上代":records.get(person.get("parent"),{}).get("name",""),
                            "版面接续上代":records.get(person.get("layout_parent"),{}).get("name",""),
                            "配偶所属":records.get(person.get("owner"),{}).get("name",""),
                            "待核":bool(person.get("uncertain"))})
        ledger.append({"原稿段":index,"原文":text,"关联记录":related,
                       "机器定位结果":"已定位关联人物记录" if related else "未单列人物记录，须结合原文人工核读"})
    return {"原稿文件":str(source),"原稿指纹":hashlib.sha256(source.read_bytes()).hexdigest(),
            "原稿段落":len(paragraphs),"原稿非空段":len(ledger),
            "修订前记录数":len(old_ids),"修订后记录数":len(new_ids),
            "新增关联记录":sorted(new_ids-old_ids),"新增候选接线":[list(e) for e in sorted(new_edges-old_edges)],
            "修订后图页数":len(after["pages"]),"原稿逐段台账":ledger,
            "说明":"上述数量为原文记录条数，包含出继和重复记载，不代表核定人口数；机器检查仅验证原稿出处、底表与图的一致，原稿是否漏人须另行人工阅读全文。"}


def main():
    parser = argparse.ArgumentParser(description="原稿、人物记录与图册交叉核对")
    for key in ["source","before","after","records","plan","out"]:
        parser.add_argument("--"+key,required=True,type=Path)
    parser.add_argument("--presentation",type=Path)
    args=parser.parse_args()
    read=lambda p:json.loads(p.read_text(encoding="utf-8"))
    result=audit(args.source,read(args.before),read(args.after),read(args.records)["records"],read(args.plan),args.presentation)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"交叉核对通过：原稿{result['原稿段落']}段，修订后{result['修订后记录数']}条记录、{result['修订后图页数']}张图。")


if __name__=="__main__":
    main()
