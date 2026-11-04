"""建立人物与原文记录分离的关系核对台账，保留候选关系和人工答复。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.views import Selection

from export_review import create_sheet, export_report
from review_genealogy import read_rows


ORDER_BASES = {"原文称谓与分支顺序", "原文世次与分支顺序"}


def joined(values):
    return "；".join(dict.fromkeys(str(v) for v in values if v is not None and str(v).strip()))


def build(data, original_rows, registry):
    families = data["families"]
    people = {p["id"]: p for f in families for p in f["people"]}
    records = {}
    groups = defaultdict(list)
    for f in families:
        for kind, key in [("正文人物", "people"), ("配偶", "spouses")]:
            for p in f[key]:
                assert p["id"] not in records, "原始条目标识重复"
                record = dict(p, record_kind=kind, family=f["id"], family_name=f["title"])
                records[p["id"]] = record
                group = "同人：" + p["identity"] if p.get("identity") else "记录：" + p["id"]
                groups[group].append(record)

    assignments = registry.setdefault("record_to_person", {})
    redirects = registry.setdefault("redirects", {})
    next_number = registry.get("next_number", 1)
    entities = []
    for group, rows in groups.items():
        previous = sorted({assignments[p["id"]] for p in rows if p["id"] in assignments})
        if previous:
            identifier = previous[0]
            for other in previous[1:]:
                redirects[other] = identifier
        else:
            identifier = f"人{next_number:06d}"
            next_number += 1
        for record in rows:
            assignments[record["id"]] = identifier
        entities.append({"id": identifier, "names": joined(p["name"] for p in rows),
                         "aliases": joined(p.get("alias") for p in rows),
                         "dates": joined(p.get("dates") for p in rows),
                         "record_ids": [p["id"] for p in rows], "identity_group": group,
                         "identity_status": "按既有同人证据合并；待复核" if len(rows) > 1 else "暂编人物，跨稿同人尚未核定"})
    registry["next_number"] = next_number
    entity_by_id = {p["id"]: p for p in entities}

    def label(record_id):
        record = records[record_id]
        return f"{assignments[record_id]} {record['name']}"

    relations = []
    counter = 0

    def add_relation(source, target, kind, basis, record, category, status, note=""):
        nonlocal counter
        counter += 1
        relations.append({"id": f"关{counter:06d}", "from_id": assignments[source],
                          "to_id": assignments[target], "from_name": records[source]["name"],
                          "to_name": records[target]["name"], "kind": kind,
                          "basis": basis, "category": category, "status": status,
                          "source": record["source"], "para": record["para"],
                          "record_id": record["id"], "from_record": source,
                          "to_record": target, "note": note, "raw": record["raw"]})

    for p in people.values():
        parent = p.get("parent")
        if parent:
            assert parent in records, "上辈条目不存在"
            if p["parent_basis"] in ORDER_BASES:
                category = "存在疑问的关系"
                status = "待核实"
            elif p.get("issues"):
                category = "需要人工确认的关系"
                status = "待核实"
            else:
                category = "原文明示关系"
                status = "原文明示，尚未人工核定"
            add_relation(parent, p["id"], p["edge_kind"], p["parent_basis"], p,
                         category, status, joined(p.get("issues", [])))
        for candidate in p.get("candidate_parents", []):
            found = [r for r in people.values() if r["source"] == candidate["source"]
                     and r["para"] == candidate["para"] and r["name"] == candidate["name"]]
            assert len(found) == 1, "候选上辈定位不唯一或不存在"
            add_relation(found[0]["id"], p["id"], p["edge_kind"], p["parent_basis"], p,
                         "需要人工确认的关系", "待核实", joined([candidate.get("option"), p.get("confirmation_note")]))
    for r in records.values():
        if r["record_kind"] == "配偶" and r.get("owner"):
            assert r["owner"] in records, "配偶另一方条目不存在"
            add_relation(r["owner"], r["id"], "配偶（" + r["role"] + "）",
                         "原文婚配称谓及记载位置", r, "原文明示关系",
                         "原文明示，尚未人工核定", "不据此自动认定任何子女的生母或生父")

    children = defaultdict(list)
    for p in people.values():
        if p.get("parent"):
            children[p["parent"]].append(p["id"])
    unsettled = set()
    decision_notes = defaultdict(list)
    for decision in data.get("user_decisions", []):
        if decision.get("status") != "待核实":
            continue
        starts = [p["id"] for p in people.values()
                  if p.get("identity") == decision.get("affected_identity")]
        queue = list(starts)
        seen = set()
        while queue:
            record_id = queue.pop()
            if record_id in seen:
                continue
            seen.add(record_id)
            unsettled.add(assignments[record_id])
            decision_notes[assignments[record_id]].append(decision["id"])
            queue.extend(children[record_id])
            for spouse in people[record_id].get("spouses", []):
                unsettled.add(assignments[spouse])
                decision_notes[assignments[spouse]].append(decision["id"])

    for p in entities:
        rows = [records[r] for r in p["record_ids"]]
        generations = []
        for r in rows:
            if r.get("declared_gen"):
                generations.append(f"《{r['source']}》段{r['para']}：第{r['declared_gen']}世")
        p["original_generations"] = joined(generations) or "原文未标，待核实"
        p["family_notes"] = joined(r["family"] + " " + r["family_name"] for r in rows)
        p["upstream_pending"] = p["id"] in unsettled
        p["decision_ids"] = joined(decision_notes[p["id"]])
    for relation in relations:
        assert relation["from_id"] in entity_by_id and relation["to_id"] in entity_by_id
        assert relation["from_id"] != relation["to_id"], "出现人物自指关系"
    assert len(assignments.keys() & records.keys()) == len(records)
    assert len(entity_by_id) == len(entities)
    return {"entities": entities, "records": list(records.values()), "relations": relations,
            "original_rows": original_rows, "decisions": data.get("user_decisions", []),
            "issues": data["issues"], "findings": data["manual_findings"],
            "manual_edges": data["manual_edges"], "families": families}, assignments


def export_workbook(result, assignments, destination):
    wb = Workbook()
    wb.remove(wb.active)
    rows_by_id = {r["id"]: r for r in result["records"]}
    relation_columns = ["关系编号", "上辈或婚配一方编号", "姓名", "下辈或婚配另一方编号", "姓名", "关系原记", "核查分类", "状态", "依据", "材料", "段落", "原文条目", "说明", "原文"]

    def relation_row(r):
        return [r[k] for k in ["id", "from_id", "from_name", "to_id", "to_name", "kind", "category", "status", "basis", "source", "para", "record_id", "note", "raw"]]

    intro = create_sheet(wb, "阅读说明", ["项目", "说明"], [
        ["当前阶段", "关系核对阶段；未定稿，未制作系谱图。后续仍按一户一张完整图执行。"],
        ["人物编号", "人物编号与原文记录编号分开；仅已有明确同人证据的条目合并。其余跨稿疑似重复暂不合并，编号数量不等于实际人口。"],
        ["正式关系", "未经人工核定，不将候选关系写入已确认父母及子女字段。"],
        ["原文明示", "原文明示与人工核定是不同状态；前者保留原记，后者等待逐项确认。"],
        ["顺序关系", "仅凭世次栏目、称谓层级或排列顺序建立的连接归为候选，统一标为待核实。"],
        ["世代", "原标世次与暂排相对代次分别保存；正式世次、长幼排行和房支核定尚未完成。"],
        ["女性与特殊关系", "保留配偶及女性成员；生身、承嗣、继亲、女系分别留证，不自动把配偶当作生母或生父。"],
        ["最新人工答复", "见人工核定记录；无法确认仍为待核实，不因收到了答复就变成已确认关系。"],
        ["上游影响", "已记录的上游归属冲突会提示下游人物的房支和绝对世次待核实；不因此否定下游明确的局部亲属记载。"],
        ["完整性范围", "原文段落全文随表保留；叙述、名单、未识别段落作为待补录线索，尚未宣称全部人物已完成身份去重与关系核定。"],
        ["已确认关系", "当前没有家属确认具体归属的关系，本表相应工作表为空。后续每项确认均须关联依据与答复。"],
        ["查看顺序", "先看人工核定记录、重点核查、需要人工确认，再按人物编号回查人物主表及原文记录映射。"],
    ], [28, 115])
    intro.freeze_panes = "A2"
    intro.sheet_view.selection = [Selection(pane="bottomLeft", activeCell="A2", sqref="A2")]
    entity_rows = []
    incoming, outgoing, marriages = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in result["relations"]:
        if r["kind"].startswith("配偶"):
            marriages[r["from_id"]].append(f"{r['to_id']} {r['to_name']}〔{r['status']}〕")
            marriages[r["to_id"]].append(f"{r['from_id']} {r['from_name']}〔{r['status']}〕")
        else:
            incoming[r["to_id"]].append(f"{r['from_id']} {r['from_name']}〔{r['kind']}；{r['status']}〕")
            outgoing[r["from_id"]].append(f"{r['to_id']} {r['to_name']}〔{r['status']}〕")
    for p in result["entities"]:
        records = [rows_by_id[r] for r in p["record_ids"]]
        entity_rows.append([p["id"], p["names"], p["aliases"], p["dates"], p["original_generations"],
                            "待核实", "待核实", "待核实", joined(marriages[p["id"]]), "待核实",
                            joined(incoming[p["id"]]) or "原文未记上辈，待核实", joined(outgoing[p["id"]]),
                            joined(r.get("role") for r in records), "待核实", p["family_notes"], "待核实",
                            "待核实：上游承嗣归属尚未确认" if p["upstream_pending"] else "待逐户核定",
                            p["decision_ids"], joined(p["record_ids"]), p["identity_status"]])
    create_sheet(wb, "人物主表_核对稿", ["暂编人物编号", "姓名原记", "曾用名等原记", "生卒原记", "原标世代及出处", "核定世代", "已确认父亲", "已确认母亲", "婚配原记与状态", "已确认子女", "原记或候选上辈", "原记或候选下代", "原称谓及排行", "核定长幼顺序", "原文房支", "核定房支", "上游影响", "关联核定事项", "原始记录编号", "身份整理状态"], entity_rows,
                 [18, 25, 35, 40, 65, 18, 20, 20, 85, 25, 100, 110, 40, 20, 100, 20, 60, 20, 70, 65])
    create_sheet(wb, "原文记录映射", ["人物编号", "原文记录编号", "类别", "姓名", "别名原记", "材料", "段落", "原文分组", "原文房支", "原称谓", "原标世代", "暂排相对代次", "关系依据", "待核事项", "原文"],
                 [[assignments[r["id"]], r["id"], r["record_kind"], r["name"], r.get("alias", ""), r["source"], r["para"], r["family"], r["family_name"], r["role"], r.get("declared_gen") or "未标", r.get("relative_gen", "未暂排"), r.get("parent_basis", "婚配称谓及记载位置"), joined(r.get("issues", [])), r["raw"]] for r in result["records"]],
                 [18, 25, 18, 22, 30, 18, 12, 16, 65, 25, 18, 20, 75, 100, 130])
    for title in ["原文明示关系", "存在疑问的关系", "需要人工确认的关系"]:
        create_sheet(wb, title, relation_columns, [relation_row(r) for r in result["relations"] if r["category"] == title], [18, 22, 22, 22, 22, 35, 30, 40, 85, 15, 12, 25, 100, 130])
    create_sheet(wb, "已确认关系", relation_columns, [], [18, 22, 22, 22, 22, 35, 30, 40, 85, 15, 12, 25, 100, 130])
    missing = [r for r in result["records"] if (r["record_kind"] == "正文人物" and not r.get("parent") and not r.get("candidate_parents")) or (r["record_kind"] == "配偶" and not r.get("owner"))]
    create_sheet(wb, "资料缺失的关系", ["人物编号", "原文记录", "姓名", "材料", "段落", "缺口", "状态", "原文"],
                 [[assignments[r["id"]], r["id"], r["name"], r["source"], r["para"], "原文未记上辈或未能定位；不等于证实无父母" if r["record_kind"] == "正文人物" else "配偶另一方未定位", "待核实", r["raw"]] for r in missing], [18, 25, 22, 18, 12, 100, 18, 130])
    create_sheet(wb, "可能存在错误的关系", ["人物编号", "原文记录", "姓名", "材料", "段落", "核查提示", "状态", "原文"],
                 [[assignments[r["id"]], r["id"], r["name"], r["source"], r["para"], r["message"], "待核实", r["raw"]] for r in result["issues"]], [18, 25, 22, 18, 12, 110, 18, 130])
    create_sheet(wb, "世代排序_候选", ["人物编号", "原文记录", "姓名", "材料", "原文房支", "原标世代", "暂排相对代次", "正式世次", "状态", "说明"],
                 [[assignments[r["id"]], r["id"], r["name"], r["source"], r["family_name"], r.get("declared_gen") or "未标", r.get("relative_gen", "未暂排"), "待核实", "待核实", "相对代次可能以断链起点计数，不可直接作为入村世次；配偶不凭婚配自动确定世代"] for r in sorted(result["records"], key=lambda r: (r["source"], r.get("declared_gen") or 999, r["para"]))], [18, 25, 22, 18, 70, 18, 20, 18, 18, 110])
    create_sheet(wb, "房支归属_原记", ["原文分组", "原文房支", "材料", "起止段落", "入村第一世依据", "整理说明", "核定房支", "核定户边界"],
                 [[f["id"], f["title"], f["source"], f"{f['start']}—{f['end']}", f["migration"], joined(f["notes"]), "待核实", "待核实：原文分隔段不等于一户"] for f in result["families"]], [18, 75, 18, 22, 100, 100, 20, 70])
    family_units = defaultdict(list)
    for r in result["records"]:
        if r.get("parent"):
            family_units[r["parent"]].append(r)
    unit_rows = []
    for parent_record, children in family_units.items():
        parent = rows_by_id[parent_record]
        unit_rows.append([parent_record, assignments[parent_record], parent["name"], parent["source"],
                          parent["family_name"],
                          joined(assignments[c["id"]] + " " + c["name"] + "（原称" + c["role"] + "）" for c in children),
                          "待核实：共享原记上辈不自动证明同父同母，收养与亲生须区分",
                          "待核实：不按配偶位置自动分配生母或生父", "保留原文顺序，不等同已确认长幼"])
    create_sheet(wb, "家庭单元_候选", ["上辈原文条目", "上辈人物编号", "上辈姓名", "材料", "原文房支", "原记或候选子女及称谓", "同胞关系", "另一生亲", "排序依据"], unit_rows,
                 [25, 20, 22, 18, 75, 140, 110, 100, 65])
    create_sheet(wb, "重点核查", ["编号", "优先程度", "事项", "矛盾或缺口", "出处", "处理与依据", "状态"],
                 [[r[k] for k in ["id", "priority", "title", "detail", "evidence", "action"]] + ["待核实"] for r in result["findings"]], [15, 18, 55, 130, 75, 130, 18])
    create_sheet(wb, "人工核定记录", ["事项编号", "记录日期", "问题", "用户原答复", "当前状态", "影响范围"],
                 [[r.get(k, "") for k in ["id", "date", "question", "answer", "status", "scope"]] for r in result["decisions"]], [18, 25, 60, 110, 18, 130])
    create_sheet(wb, "叙述名单补充线索", ["材料", "段落", "人物或夫妇", "相关人物", "关系原记", "补录说明", "状态"],
                 [[r[k] for k in ["source", "para", "person", "relative", "kind", "note"]] + ["待核实：须与已建人物核对后补录"] for r in result["manual_edges"]], [18, 12, 50, 85, 65, 130, 70])
    create_sheet(wb, "未识别段落_待排查", ["材料", "分组", "原文房支", "段落", "原文", "处理"],
                 [[f["source"], f["id"], f["title"], r["para"], r["text"], "待核实：保留全部未识别段落，含标题、叙事及可能未补录的人物"] for f in result["families"] for r in f["unparsed"]], [18, 18, 70, 12, 140, 100])
    create_sheet(wb, "原始资料全文", ["材料", "原段落号", "原文"], [[r["source"], r["para"], r["text"]] for r in result["original_rows"]], [18, 18, 150])
    wb.save(destination)
    check = load_workbook(destination)
    assert check["人物主表_核对稿"].max_row - 1 == len(result["entities"])
    assert check["原文记录映射"].max_row - 1 == len(result["records"])
    assert check["已确认关系"].max_row == 1


def export_database(result, destination):
    with sqlite3.connect(destination) as connection:
        for table, rows in [("人物", result["entities"]), ("原文条目", result["records"]),
                            ("关系证据", result["relations"]), ("人工核定", result["decisions"])]:
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
            connection.execute(f'CREATE TABLE "{table}" (编号 TEXT PRIMARY KEY, 内容 TEXT NOT NULL)')
            connection.executemany(f'INSERT INTO "{table}" VALUES (?, ?)',
                                   [(r["id"], json.dumps(r, ensure_ascii=False)) for r in rows])
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def main():
    parser = argparse.ArgumentParser(description="建立严格区分原文、候选与人工确认的人物关系台账")
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--latest", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8")) if args.registry.exists() else {}
    original_rows = read_rows(args.source, "总") + read_rows(args.latest, "张氏新版")
    result, assignments = build(data, original_rows, registry)
    args.out.mkdir(parents=True, exist_ok=True)
    export_workbook(result, assignments, args.out / "人物关系与人工核定台账_第二轮.xlsx")
    people = {p["id"]: p for f in data["families"] for p in f["people"]}
    children = defaultdict(list)
    for p in people.values():
        if p.get("parent"):
            children[p["parent"]].append(p)
    export_report(data, args.out / "人物关系核查报告_第二轮.docx", people, children)
    export_database(result, args.out / "人物关系核对数据库.sqlite")
    (args.out / "人物关系核对数据库.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.registry.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print("原始记录数：", len(result["records"]))
    print("暂编人物编号数：", len(result["entities"]), "；不等于去重人口数")
    print("关系证据数：", len(result["relations"]))
    print("保留原文段落：", len(original_rows))
    print("人工核定记录：", len(result["decisions"]))


if __name__ == "__main__":
    main()
