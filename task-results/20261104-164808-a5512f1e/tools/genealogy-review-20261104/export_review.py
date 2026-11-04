"""把关系核对底稿导出为可编辑表格与中文核对报告。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.views import Selection


INK = "111827"
LIGHT = "E7E8EA"
UNKNOWN = {"氏", "某氏", "姓氏不详", "姓名不详", "氏名不详", "名讳失考", "讳失考", "名字不详", "情况不详", "无从考证", "生卒姓氏不详"}


def reference(p):
    return f"《{p['source']}》第{p['para']}段"


def display(p):
    return p["name"] + (f"〔段{p['para']}〕" if p["name"] in UNKNOWN else "")


def create_sheet(wb, title, headers, rows, widths=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append([str(v) if isinstance(v, (list, dict)) else v for v in row])
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(name="黑体", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=INK)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="宋体", size=10, color=INK)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if cell.row % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F5F5F5")
        max_len = max((len(str(c.value or "")) for c in row), default=0)
        ws.row_dimensions[row[0].row].height = min(110, max(30, 15 * ((max_len + 39) // 40)))
    for i, width in enumerate(widths or [20] * len(headers), 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:1"
    ws.oddFooter.center.text = "第 &P 页 / 共 &N 页"
    return ws


def alias_keys(p):
    keys = {p["name"]}
    for item in p.get("alias", "").split("；"):
        item = re.sub(r"^(?:乳名|小名|又名|字|号)[，,:：]?", "", item)
        item = re.sub(r"\s+", "", item)
        if re.fullmatch(r"[\u3400-\u9fff]{1,5}", item) and not any(s in item for s in ["失考", "不详", "未婚", "早亡"]):
            keys.add(item if item.startswith(p["name"][0]) else p["name"][0] + item)
    return keys


def compare_records(data, people, spouses):
    # 对照限制在人工已定位的房支，避免把别户同名人物视为同一人。
    scopes = {"总21": [], "总27": ["张前五世", "张01"], "总30": ["张19", "张20"], "总31": [],
              "总47": ["张10"], "总48": ["张11"], "总49": ["张03", "张05"], "总50": ["张12"],
              "总51": ["张15", "张16"], "总52": ["张14"], "总53": ["张04"], "总54": ["张02", "张04", "张08"],
              "总55": ["张17", "张18"]}
    result, matches = [], {}
    for f in data["families"]:
        if f["id"] not in scopes:
            continue
        allowed = scopes[f["id"]]
        candidates = [q for q in people.values() if q["family"] in allowed]
        for p in f["people"]:
            options = [q for q in candidates if p["name"] not in UNKNOWN and alias_keys(p) & alias_keys(q)]
            # 同名而生年不同者，优先按生年识别；不会把无生年强行当作冲突。
            year = re.search(r"(?:1[6789]|20)\d{2}", p["dates"])
            if year and len(options) > 1:
                exact = [q for q in options if year.group() in q["dates"]]
                if exact:
                    options = exact
            matches[p["id"]] = options
            status = "同支姓名对应，关系须结合出处复核" if options else "新版未找到本支对应条目，保留待核"
            differences = []
            if options:
                if p["name"] not in {q["name"] for q in options}:
                    differences.append("通过别名对应，原姓名均保留")
                if p["sex"] in {"男", "女"} and any(q["sex"] in {"男", "女"} and p["sex"] != q["sex"] for q in options):
                    differences.append("两稿性别称谓不同")
                    status = "同支人物对应；性别待核"
                if len(options) > 1:
                    differences.append("新版同名多处出现，须核生身、承嗣或重复归属")
            parent = people.get(p["parent"])
            result.append([f["id"], f["title"], "人物", p["name"], p["para"], display(parent) if parent else p.get("display_parent", "未列或待核"),
                           "；".join(f"{q['name']}〔段{q['para']}〕" for q in options), status, "；".join(differences), p["raw"], "\n".join(q["raw"] for q in options)])
        for s in f["spouses"]:
            owner = people.get(s["owner"])
            targets = [spouses[sid] for q in matches.get(s["owner"], []) for sid in q["spouses"]]
            exact = [q for q in targets if q["name"] == s["name"] and s["name"] not in UNKNOWN]
            same_surname = [q for q in targets if q["name"][0] == s["name"][0] and s["name"] not in UNKNOWN]
            options = exact or same_surname
            status = "配偶姓名对应" if exact else ("同一人物配偶同姓；姓名、婚次须核" if options else "配偶未找到同名对应，保留原记待核")
            result.append([f["id"], f["title"], "配偶", s["name"], s["para"], display(owner) if owner else "归属待核",
                           "；".join(f"{q['name']}〔段{q['para']}〕" for q in options), status, "配偶关系不用于反推所有子女的生母", s["raw"], "\n".join(q["raw"] for q in options)])
    return result


def export_workbook(data, dest):
    people = {p["id"]: p for f in data["families"] for p in f["people"]}
    spouses = {s["id"]: s for f in data["families"] for s in f["spouses"]}
    children = defaultdict(list)
    for p in people.values():
        if p["parent"]:
            children[p["parent"]].append(p)
    wb = Workbook()
    wb.remove(wb.active)
    overview = create_sheet(wb, "阅读说明", ["项目", "说明"], [
        ["本轮范围", "先核人物关系，暂不制图。后续一户一张完整图；原文分隔段不直接等于户数。"],
        ["材料条目", "本底表分别保留两份材料的记载；跨稿、过继及重复人物没有合并成最终人口数。"],
        ["总稿正文人物条目", "=COUNTA('总稿人物'!A:A)-1"],
        ["新版正文人物条目", "=COUNTA('新版张氏人物'!A:A)-1"],
        ["两稿配偶记载条目", "=COUNTA('婚配关系'!A:A)-1"],
        ["关系证据", "明确名单、明确亲属记述优先；只按世次栏目和排列顺序整理的关系，仍需逐户确认。"],
        ["上辈称谓", "上辈可能为生父、生母、嗣父或继亲，须结合关系性质列；不得把上辈列一律理解为生父。"],
        ["母亲信息", "父亲配偶不自动认定为全部子女生母；多次婚配及带入子女单独标记。"],
        ["世次", "原文世次和候选接续代次分列；始迁祖未证实的户，不正式重编第一世。"],
        ["身份识别", "同名人物不全局合并；明确的生身、出继重复记载使用同一身份标记。"],
        ["查看顺序", "先看重点待核与张氏覆盖，再看逐户目录；按家族编号筛选人物、婚配和逐人对照。"],
        ["如何修改", "所有表格单元格均可编辑；可在重点待核的核定结果列填写家属确认内容。空白不等于已确认。"],
        ["举例", "在总稿人物筛选某一原文段编号，即可同时查看人名、上辈、婚配、子女、证据与原文。"],
        ["出处定位", "段落号为原始文档正文从头计数的段落序号，包括原件空段；不是页码，排版变化不影响编号。"],
        ["数量单位", "本文的数量均为条目、段或组；未给出未经去重确认的实际人数、户数。"],
    ], [30, 105])
    overview.freeze_panes = "A2"
    # 修改冻结位置后重设选区，避免残留分栏选区影响办公软件打开。
    overview.sheet_view.selection = [Selection(pane="bottomLeft", activeCell="A2", sqref="A2")]
    cov = {r["family"]: r for r in data["coverage"]}
    family_rows = []
    for f in data["families"]:
        roots = [display(p) for p in f["people"] if not p["parent"] and not p.get("display_parent")]
        family_rows.append([f["id"], f["title"], f["source"], f"第{f['start']}—{f['end']}段", len(f["people"]), len(f["spouses"]),
                            "；".join(roots), f["migration"], cov.get(f["id"], {}).get("status", "不属于本次张氏覆盖对照范围"), "；".join(f["notes"])])
    create_sheet(wb, "逐户目录", ["原文段编号", "原文家族或支系", "材料", "段落范围", "正文人物条目数", "配偶条目数", "起首人物或未接先祖", "入村第一世依据", "张氏覆盖情况", "户与支系处理说明"], family_rows, [15, 40, 14, 22, 15, 15, 45, 60, 36, 80])
    headers = ["人物条目标识", "原文段编号", "家族或支系", "姓名原记", "别名原记", "原文称谓", "性别原注", "原标世次", "按关系接续的相对代次", "上辈条目或候选", "关系性质", "生身父母另记", "承嗣或继亲另记", "配偶", "下代人物", "关系依据", "核对状态", "待核说明", "出处", "原文", "同人身份标记"]
    main_rows = {"总": [], "张氏新版": []}
    edge_rows = []
    for p in people.values():
        parent = people.get(p["parent"])
        parent_text = display(parent) if parent else p.get("display_parent", "本段起首；上辈未具名或未记")
        warning = "；".join(dict.fromkeys(p["issues"]))
        state = "有待核事项" if warning or p.get("display_parent") else ("原文明示关系" if p["parent_basis"] not in ["原文称谓与分支顺序", "原文世次与分支顺序", "未建立"] else "按原文顺序整理，待逐户确认")
        spouse_text = "；".join(f"{spouses[s]['name']}（原称{spouses[s]['role']}）" for s in p["spouses"])
        child_text = "；".join(f"{q['name']}〔段{q['para']}〕" for q in children[p["id"]])
        main_rows[p["source"]].append([p["id"], p["family"], p["family_name"], p["name"], p["alias"], p["role"], p["sex"],
                                       p["declared_gen"] or "未标", p["relative_gen"], parent_text, p["edge_kind"], p.get("biological", "未另注"),
                                       p.get("adoptive", "未另注"), spouse_text, child_text, p["parent_basis"], state, warning, reference(p), p["raw"], p.get("identity", p["id"])])
        if parent:
            edge_rows.append([p["family"], p["family_name"], display(parent), p["name"], p["edge_kind"], p["parent_basis"], reference(parent), reference(p), warning])
    widths = [20, 15, 40, 18, 25, 20, 12, 15, 18, 40, 24, 38, 40, 45, 70, 40, 32, 75, 24, 80, 25]
    create_sheet(wb, "总稿人物", headers, main_rows["总"], widths)
    create_sheet(wb, "新版张氏人物", headers, main_rows["张氏新版"], widths)
    marriage_rows = []
    for f in data["families"]:
        for s in f["spouses"]:
            owner = people.get(s["owner"])
            marriage_rows.append([s["id"], f["id"], f["title"], display(owner) if owner else "配偶归属待核", s["name"], s["role"], s["dates"], reference(s), s["raw"], "配偶；不自动认定为所有子女生母或生父"])
    create_sheet(wb, "婚配关系", ["条目标识", "原文段编号", "家族或支系", "配偶另一方", "配偶姓名原记", "婚次或称谓原记", "年代摘录", "出处", "原文", "说明"], marriage_rows, [20, 15, 42, 28, 22, 22, 36, 25, 100, 55])
    create_sheet(wb, "上下辈关系", ["原文段编号", "家族或支系", "上辈", "下辈", "关系性质", "依据", "上辈出处", "下辈出处", "待核说明"], edge_rows, [15, 45, 24, 24, 26, 48, 25, 25, 85])
    create_sheet(wb, "张氏覆盖", ["原文段编号", "家族或支系", "覆盖判断", "对照依据", "处理建议"], [[r[k] for k in ["family", "title", "status", "evidence", "action"]] for r in data["coverage"]], [15, 38, 40, 100, 75])
    compare = compare_records(data, people, spouses)
    create_sheet(wb, "张氏逐人对照", ["原文段编号", "家族或支系", "条目类型", "旧稿姓名", "旧稿段落", "旧稿上辈或配偶", "新版同支对应条目", "对照状态", "差异或限制", "旧稿原文", "新版原文"], compare, [15, 40, 15, 22, 16, 35, 60, 55, 70, 100, 100])
    create_sheet(wb, "重点待核", ["编号", "优先程度", "事项", "矛盾或缺口", "原文出处", "核对处理", "核定结果（待填写）"], [[r[k] for k in ["id", "priority", "title", "detail", "evidence", "action"]] + [""] for r in data["manual_findings"]], [12, 15, 40, 110, 60, 85, 75])
    create_sheet(wb, "逐条提示", ["家族或支系", "人物条目标识", "姓名", "材料", "段落", "核对提示", "原文"], [[r[k] for k in ["family", "id", "name", "source", "para", "message", "raw"]] for r in data["issues"]], [45, 22, 20, 15, 15, 100, 100])
    create_sheet(wb, "叙述名单补充关系", ["材料", "段落", "人物或夫妇", "相关人物", "关系原记", "补录说明"], [[r[k] for k in ["source", "para", "person", "relative", "kind", "note"]] for r in data["manual_edges"]], [18, 15, 45, 65, 40, 110])
    absent = []
    for f in data["families"]:
        names = {p["name"] for p in f["people"]}
        for p in f["people"]:
            for name in p["children_declared"]:
                if name not in names:
                    absent.append([f["id"], f["title"], p["name"], name, reference(p), "仅名单出现，或正文异名、另段展开；不能直接新增为独立人物", p["context"]])
    create_sheet(wb, "名单未展开线索", ["原文段编号", "家族或支系", "名单所属人物", "名单姓名原记", "所属人物出处", "解释", "原文及相邻婚配"], absent, [15, 42, 25, 25, 25, 85, 120])
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.save(dest)
    check = load_workbook(dest)
    assert check["总稿人物"].max_row - 1 == len(main_rows["总"])
    assert check["新版张氏人物"].max_row - 1 == len(main_rows["张氏新版"])
    assert check["婚配关系"].max_row - 1 == len(spouses)
    return people, children, len(compare)


def font_style(style, size=10.5, bold=False):
    style.font.name = "宋体"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor.from_string(INK)
    style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "黑体" if bold else "宋体")


def word_table(doc, headers, rows, widths):
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    for column, width in zip(table.columns, widths):
        column.width = Cm(width)
    for cell, name, width in zip(table.rows[0].cells, headers, widths):
        cell.text = name
        cell.width = Cm(width)
        pr = cell._tc.get_or_add_tcPr()
        shade = OxmlElement("w:shd")
        shade.set(qn("w:fill"), LIGHT)
        pr.append(shade)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    repeat = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for values in rows:
        cells = table.add_row().cells
        for cell, text, width in zip(cells, values, widths):
            cell.width = Cm(width)
            cell.text = str(text)
        keep = OxmlElement("w:cantSplit")
        table.rows[-1]._tr.get_or_add_trPr().append(keep)
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.space_before = Pt(3)
                for run in p.runs:
                    run.font.size = Pt(9)
    doc.add_paragraph()
    return table


def export_report(data, dest, people, children):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(1.8)
    sec.left_margin, sec.right_margin = Cm(1.8), Cm(1.8)
    for name, size, bold in [("Normal", 10.5, False), ("Title", 23, True), ("Heading 1", 15, True), ("Heading 2", 12, True), ("Heading 3", 10.5, True)]:
        font_style(doc.styles[name], size, bold)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.2
    doc.styles["Normal"].paragraph_format.space_after = Pt(6)
    foot = sec.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    foot.add_run("人物关系核对稿  ·  第 ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    foot._p.append(field)
    foot.add_run(" 页")
    report_text = data.get("report_text", {})
    doc.core_properties.title = report_text.get("title", "村志人物关系梳理与张氏对照核对稿")
    doc.core_properties.author = ""
    doc.core_properties.subject = "关系核对阶段；不作出版定稿"
    doc.add_heading("人物关系梳理与张氏对照", 0)
    doc.add_paragraph(report_text.get("subtitle", "村志人物关系  ·  首轮核对稿"))
    doc.add_paragraph("本轮只整理人物及亲属关系，不制作系谱图。后续按一户一张完整图处理；在入村第一代及房支归属核定前，不把暂排的代次当作正式世次。")
    doc.add_heading("一、两份材料的整理范围", 1)
    total = [f for f in data["families"] if f["source"] == "总"]
    newer = [f for f in data["families"] if f["source"] != "总"]
    counts = [("《总》", len(total), sum(len(f["people"]) for f in total), sum(len(f["spouses"]) for f in total)),
              ("张氏新版", len(newer), sum(len(f["people"]) for f in newer), sum(len(f["spouses"]) for f in newer))]
    word_table(doc, ["材料", "本稿整理分组", "正文人物条目", "配偶条目"], counts, [4.2, 4.2, 4.4, 4.4])
    doc.add_paragraph("上表按原件记载条目统计，包含两稿重复、同人出继重复及同姓氏失考配偶，不是去重后的实际人数。原文分组也不是核定户数：《总》有一段写两户，也有同一先祖后裔分三段展开。")
    doc.add_paragraph("核对顺序：明确的子女名单与亲属表述优先，再参考世次栏目和上下文。同名不跨户合并；不凭年龄差、字辈或相邻位置补造亲子关系。配偶并不自动等同全部子女的生母或生父。")
    doc.add_heading("二、张氏覆盖判断", 1)
    doc.add_paragraph("《总》中有13个分隔段涉及本次张氏对照：10段主体支系可在新版定位，1段为张、刘混合记述且仅部分覆盖，另2段未找到对应支系。“主体支系已覆盖”只表示支系已收录，不表示姓名、性别、世次与婚配细节已全部一致。")
    for r in data["coverage"]:
        doc.add_heading(r["family"] + "  " + r["title"], 2)
        doc.add_paragraph(r["status"] + "。" + r["evidence"] + " " + r["action"])
    doc.add_heading("三、张氏共同先祖与主要房支", 1)
    doc.add_paragraph(report_text.get("common_ancestors", "共同先祖与主要房支以原文和人工核对记录为准。"))
    root = next(f for f in data["families"] if f["id"] == "张前五世")
    first_rows = []
    for p in root["people"]:
        parent = people.get(p["parent"])
        first_rows.append([p["declared_gen"] or "未注", display(p), display(parent) if parent else "始迁一代", p["edge_kind"] + ("；" + p["adoptive"] if p.get("adoptive") else ""), f"新版第{p['para']}段"])
    word_table(doc, ["原世次", "人物", "上辈", "特殊关系", "出处"], first_rows, [1.6, 4.3, 4.0, 4.8, 2.5])
    if report_text.get("identity_note"):
        doc.add_paragraph(report_text["identity_note"])
    doc.add_heading("四、必须先核实的关系与资料问题", 1)
    for r in data["manual_findings"]:
        doc.add_heading(r["id"] + "  " + r["title"], 2)
        doc.add_paragraph(r["detail"])
        doc.add_paragraph("出处：" + r["evidence"] + "。处理：" + r["action"])
    if data.get("user_decisions"):
        doc.add_heading("本轮人工核对答复", 2)
        for r in data["user_decisions"]:
            doc.add_paragraph(r["id"] + "：" + r["question"] + "。" + r["date"] + "答复：“" + r["answer"] + "”。当前状态：" + r["status"] + "。")
            doc.add_paragraph("影响范围：" + r.get("scope", "按相关人物及其上下游复查"))
    doc.add_heading("五、《总》逐户关系提要", 1)
    doc.add_paragraph("以下按原件55个分隔段排列，用于核对户的边界和上辈关系；不把这55段直接作为最终55户。完整到人的父母、婚配、下代、证据和待核信息见配套关系底表。")
    for f in total:
        doc.add_heading(f["id"] + "  " + f["title"], 2)
        roots = [p for p in f["people"] if not p["parent"] and not p.get("display_parent")]
        # 子房另段展开时，正文起首者仍列出，便于对照原件边界。
        if not roots and f["people"]:
            roots = f["people"][:1]
        chains = []
        for p in roots:
            names = list(dict.fromkeys(q["name"] for q in children[p["id"]]))
            parent = people.get(p["parent"])
            start = ((display(parent) + "之子／下一代") if parent else "本段起首") + display(p)
            chains.append(start + ("；下代：" + "、".join(names) if names else "；原段未展开具名下代"))
        doc.add_paragraph("。".join(chains) + "。")
        doc.add_paragraph("第一世依据：" + f["migration"] + "。" + (" ".join(f["notes"]) if f["notes"] else ""))
    doc.add_heading("六、后续制图前的核定内容", 1)
    doc.add_paragraph("先确认入村第一代及每户边界，再处理重点待核表中的归属、世次和同人问题。对已经明确的生身与承嗣关系分别留线；资料确实失考的地方保留失考标记。核定后每户制作一张完整图，配套系谱表；本稿没有开始制作图形。")
    doc.add_paragraph("附表阅读：先看“重点待核”和“张氏覆盖”，再按原文段编号筛选“总稿人物”“新版张氏人物”“婚配关系”“上下辈关系”。“叙述名单补充关系”保留正文未单列但影响亲属关系的人物与未具名亲属，不因删去故事文字而删去关系。")
    doc.save(dest)


def main():
    parser = argparse.ArgumentParser(description="导出关系核对底表与中文核对报告")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    people, children, compared = export_workbook(data, args.out / "人物关系底表与张氏逐人对照.xlsx")
    export_report(data, args.out / "人物关系梳理与张氏对照_核对稿.docx", people, children)
    print("导出人物条目：", len(people))
    print("张氏逐人对照条目：", compared)
    print("已导出表格与文档，待办公软件复算和渲染检查。")


if __name__ == "__main__":
    main()
