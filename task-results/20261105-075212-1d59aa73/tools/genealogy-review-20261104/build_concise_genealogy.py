"""以核对后的完整图册另制省略重复生育数量和名单的版本。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from docx import Document
from pptx import Presentation

import build_fulltext_genealogy as model
from build_genealogy_presentation import write_presentation


COUNTS = r"[一二两三四五六七八九十百零\d]+"
SUMMARY = re.compile(r"(?:夫妇|夫妻)?(?<![收未无])(?:育|生)(?:"+COUNTS+r"[子女])+(?:[：:][^。；;）)]*)?")


def omit_summary(text, record, changes):
    # 待核资料说明和特殊关系必须保留，不能把原稿矛盾一起删去。
    if text.startswith(("原记", "待核", "核对注")):
        return text
    def replace(match):
        original = match.group()
        kept = ""
        # 名单后若另有居住地说明，保留该说明，而非随名单删除。
        if "：" in original or ":" in original:
            suffix = re.split(r"[：:]", original, 1)[1]
            for piece in re.split(r"[，,]", suffix)[1:]:
                if piece.startswith(("居", "现居", "定居", "迁", "嫁", "葬", "信息")):
                    kept += piece+"。"
        changes.append({"记录": record, "删除": original, "另保留": kept})
        return kept
    result = SUMMARY.sub(replace, text)
    result = re.sub(r"[，,；;]+([。；;）)])", r"\1", result)
    result = re.sub(r"。{2,}", "。", result)
    result = re.sub(r"；[）)]", "）", result)
    result = result.strip("，,；;。 ")
    if result and text.endswith("。"):
        result += "。"
    return result


def check_variant(source, variant, layout):
    before, after = Presentation(source), Presentation(variant)
    assert len(before.slides) == len(after.slides) == len(layout["pages"]), "页数变化"
    for old, new, page in zip(before.slides, after.slides, layout["pages"]):
        assert len(old.shapes) == len(new.shapes), "图形对象增减"
        actual = []
        for a, b in zip(old.shapes, new.shapes):
            assert a.shape_type == b.shape_type, "对象类型变化"
            assert (a.left, a.top, a.width, a.height) == (b.left, b.top, b.width, b.height), "对象位置变化"
            if not b.has_text_frame:
                assert a._element.xml == b._element.xml, "关系线变化"
                continue
            nodes = b._element.xpath(".//p:cNvPr")
            description = nodes[0].get("descr", "") if nodes else ""
            if description.startswith("原文记录："):
                actual.append(description.split("：", 1)[1])
                old_title = "".join(p.text for p in a.text_frame.paragraphs if p.runs and p.runs[0].font.bold)
                new_title = "".join(p.text for p in b.text_frame.paragraphs if p.runs and p.runs[0].font.bold)
                assert old_title == new_title, "人物姓名或称谓变化"
            else:
                assert a.text == b.text, "其他标注变化"
        assert len(actual) == len(set(actual)), "同页人物记录分成多个框"
        assert set(actual) == set(page["record_ids"]), "人物记录遗漏"


def main():
    parser = argparse.ArgumentParser(description="另制省略重复子女数量与名单的简洁版")
    for name in ["layout", "source", "plan", "presentation", "out"]:
        parser.add_argument("--"+name, required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    original = read(args.layout)
    output = copy.deepcopy(original)
    plan = read(args.plan)
    records = output["original_records"]
    paragraphs = [p.text for p in Document(args.source).paragraphs]
    pieces, ledger = model.source_material(paragraphs, records, plan)
    changes = []
    for rid, items in pieces.items():
        for item in items:
            item["text"] = omit_summary(item["text"], rid, changes)
    for rid, value in plan.get("verbatim_overrides", {}).items():
        if "body" in value:
            value["body"] = [omit_summary(v, rid, changes) for v in value["body"]]
    for rid, person in records.items():
        notes = []
        for note in person.get("chart_notes", []):
            if re.fullmatch(r"(?:原记)?(?:育|生)(?:"+COUNTS+r"[子女])+(?:，未具名)?", note):
                changes.append({"记录": rid, "删除": note, "另保留": "", "类别": "重复数量附注"})
            else:
                notes.append(note)
        if "chart_notes" in person:
            person["chart_notes"] = notes
    # 被省略的旧名单含有异名时，把必要的待核差异单独保留。
    for entry in plan.get("source_name_equivalents", []):
        rid = entry["record_id"]
        note = "原稿名单作“"+entry["source_name"]+"”，与本框人物的对应待核。"
        if not any(entry["source_name"] in n for n in records[rid].get("chart_notes", [])):
            owner = next(v["records"][0] for v in ledger if v["para"] == entry["paragraph"])
            candidate = records[rid]["name"]
            candidate = candidate[1:] if candidate.startswith("张") else candidate
            note = "名单“"+entry["source_name"]+"”／“"+candidate+"”同人待核。"
            notes = records[owner].setdefault("chart_notes", [])
            replace = next((i for i, v in enumerate(notes) if candidate in v and "待核" in v), None)
            if replace is None:
                notes.append(note)
            else:
                notes[replace] = note
    protected = {p["name"] for p in records.values() if 1 < len(p["name"]) < 12}
    protected |= {p["name"][1:] for p in records.values() if p["name"].startswith("张") and 3 <= len(p["name"]) <= 5}
    protected |= {"名讳失考", "氏名不详", "后裔无考", "待核"}
    for paragraph in paragraphs:
        protected.update(re.findall(r"(?:合葬于|合葬|葬于|移到)([\u3400-\u9fff]{2,10})", model.compact(paragraph)))
    model.PROTECTED = sorted(protected, key=lambda v: (-len(v), v))
    info = model.profiles(records, pieces, plan)
    replaced = 0
    for page in output["pages"]:
        scale = page["diagram_scale"]
        for atom in page["atoms"]:
            rid = atom.get("person_record")
            if not rid:
                continue
            value = copy.deepcopy(info[rid]["paragraphs"])
            for paragraph in value:
                paragraph["size"] *= scale
                paragraph["leading"] *= scale
            assert sum(p["leading"] for p in value)+4*scale <= atom["h"]+0.1, ("简洁版信息超出原框", rid)
            if atom["paragraphs"] != value:
                replaced += 1
            atom["paragraphs"] = value
            atom["text"] = "\n".join(p["text"] for p in value)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / (plan["title"]+"_简洁版_不重复列子女名单_可编辑.pptx")
    write_presentation(output["pages"], output["width"], output["height"], target)
    check_variant(args.presentation, target, output)
    split = args.out / "各门可编辑文稿"
    split.mkdir(exist_ok=True)
    for number in sorted({page["gate_number"] for page in output["pages"]}):
        selected = [p for p in output["pages"] if p["gate_number"] == number]
        title = "共同祖先" if number == 0 else next(g["title"] for g in plan["gates"] if g["number"] == number)
        write_presentation(selected, output["width"], output["height"], split / (title+"_简洁版.pptx"))
    output["variant"] = "省略普通生育数量和名单；人物与特殊关系保留"
    output["profiles"] = info
    output["omitted_summaries"] = changes
    output["full_version_hash"] = hashlib.sha256(args.presentation.read_bytes()).hexdigest()
    (args.out / "简洁版版面.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("简洁版", len(output["pages"]), "页；", len(records), "条人物及资料记录；省略", len(changes), "处重复叙述；修改", replaced, "个人物框。")
    print("与完整版对照通过：人物记录、姓名、页序、各门归属、全部对象位置及连线一致。")


if __name__ == "__main__":
    main()
