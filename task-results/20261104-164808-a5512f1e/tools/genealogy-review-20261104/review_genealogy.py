"""提取家族人物条目，建立可追溯的关系核对底表，不把推测当作定论。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
CN = r"\u3400-\u4dbf\u4e00-\u9fff"
ROLE = re.compile(r"^([长次二三四五六七八九十独续继外玄曾来昆云侄仍晜耳孙儿子男女媳婿妻室配嗣原公祖始兄弟]{1,10})(?:[（(][^）)]*[）)])?[：:]")
STOP = re.compile(r"[（(：:，,。；;、\d？?]|生卒|生年|情况|无从|信息|姓氏|名字|名讳|讳失|终年|享年|享寿|早逝|英年|后裔|务农|农民|嫁|系|本人|青年|从小|参加|部队|收养|过嗣|过继|本镇|定居|曾在|迁居|现住|后随|一生|成年|随军|太原|山西|临县|学校|地质|大学|煤矿|自办|自由|终生|住石|现居")
UNKNOWN = {"氏", "某氏", "情况不详", "无从考证", "生卒姓氏不详", "姓氏不详", "姓名不详", "氏名不详", "名讳失考", "讳失考", "名字不详", "信息不详"}


def read_rows(path: Path, source: str):
    with ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    return [{"source": source, "para": i, "text": "".join(p.xpath(".//w:t/text()", namespaces=NS)).strip()}
            for i, p in enumerate(root.xpath("//w:body//w:p", namespaces=NS), 1)
            if "".join(p.xpath(".//w:t/text()", namespaces=NS)).strip()]


def split_blocks(rows):
    blocks, current = [], []
    for row in rows:
        if "※" in row["text"]:
            prefix = row["text"].split("※", 1)[0].strip()
            if prefix:
                current.append(dict(row, text=prefix))
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks


def get_name(content):
    text = content.strip().lstrip("：:")
    if any(text.startswith(s) for s in UNKNOWN):
        for s in sorted(UNKNOWN, key=len, reverse=True):
            if text.startswith(s):
                return s
    tokens = text.split()
    if len(tokens) > 1:
        head = tokens[0]
        if re.fullmatch(f"[{CN}]{{2,5}}", head):
            return head
        if re.fullmatch(f"[{CN}]", head):
            tail = tokens[1]
            m = STOP.search(tail)
            tail = tail[:m.start()] if m else tail
            if re.fullmatch(f"[{CN}]{{1,3}}", tail):
                return head + tail
    m = STOP.search(text)
    part = text[:m.start()] if m else text
    part = re.sub(r"\s+", "", part).strip("：:，。")
    if re.fullmatch(f"[{CN}]{{1,5}}", part):
        return part
    return None


def get_dates(text):
    normalized = re.sub(r"\s+", "", text)
    spans = re.findall(r"(?:约)?(?:1[6789]|20)\d{2}(?:年\d{1,2}月\d{1,2}日|年\d{1,2}月|年)?(?:[—－一-]+(?:约)?(?:1[6789]|20)\d{2}年?|年[生终卒]|年去世|年辞世|年逝世)?", normalized)
    ages = re.findall(r"(?:享年|享寿|终年)?\d{1,3}岁(?:寿终|终)?|生卒不详|生年不详|生卒失考|生卒姓氏不详|早逝|幼年夭折|英年早逝", normalized)
    return "；".join(dict.fromkeys(spans[:2] + ages[:1]))


def role_level(role):
    if "侄曾" in role:
        return 4
    if "侄孙" in role:
        return 3
    if "侄" in role:
        return 2
    for word, level in [("云", 8), ("昆", 7), ("晜", 7), ("来", 6), ("玄", 5), ("曾", 4), ("孙", 3)]:
        if word in role:
            return level
    return 2


def cn_num(s):
    digits = {c: i for i, c in enumerate("零一二三四五六七八九")}
    if "十" in s:
        a, b = s.split("十", 1)
        return digits.get(a, 1) * 10 + digits.get(b, 0)
    return digits.get(s)


def normalize_alias(text):
    aliases = re.findall(r"[（(]([^）)]*)[）)]", text)
    return "；".join(a for a in aliases if len(a) <= 22 and not re.search(r"夫妇|夫妻|育|配|嗣|养|本镇|年月|名字|名讳", a))


def person_line(row):
    text = row["text"]
    compact = re.sub(r"\s+", "", text)
    if "家族" in text or compact.startswith(("注：", "注:", "本部分", "以下是", "从以下", "育", "无亲生", "（", "(", "【", "第", "※")):
        return None
    if re.match(r"^[二三四五]门[：:]", compact):
        content = re.split(r"[：:]", text, maxsplit=1)[1].strip()
        name = get_name(content)
        return ("本段起首人物", name, content) if name else None
    match = ROLE.match(compact)
    role = match.group(1) if match else "本段起首人物"
    content = re.split(r"[：:]", text, maxsplit=1)[1].strip() if match else text
    if not match:
        content = re.sub(r"^[二三四五]门[：:]", "", content)
    name = get_name(content)
    if not name:
        return None
    if name in {"妻", "本支", "合葬", "家", "娘家", "村娘家", "行工作", "府工作", "现役", "党员", "役二级上士", "家坡村娘家"}:
        return None
    if not match and name[0] not in "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁杜阮席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程裴陆荣翁荀羊惠甄曲封储靳段富巫乌焦巴弓牧隗山谷车侯全秋仲宫宁仇甘祖武符刘詹龙叶幸司黎薄印白怀蒲邰从索赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎闫充慕连茹习艾鱼容向古易廖耿满匡文寇广阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公问渠":
        return None
    return role, name, content


def expand_rows(rows):
    expanded = []
    for row in rows:
        text = row["text"]
        # 原件有把配偶、子女条目粘在同一段的情况，拆开但保留原段落号。
        parts = re.split(r"(?<=娘家)(?=曾\s*孙\s*[男女]\s*[：:])|(?<=\S)\s+(?=配[：:])", text)
        for part in parts:
            expanded.append(dict(row, text=part))
    return expanded


def child_names(text, surname):
    text = re.sub(r"\s+", " ", text)
    output = []
    for m in re.finditer(r"(?:生育|养育|夫妇育|夫妻育|育|生|收养|养)([一二两三四五六七八九十\d子男女儿长次、共名即？?]{1,20})[：:]([^。；;）)]+)", text):
        prefix, values = m.groups()
        if not re.search(r"子|男|女|儿", prefix):
            continue
        values = values.split("其中")[0]
        for item in re.split(r"[、，,\s]+", values):
            item = re.sub(r"[（(].*", "", item).strip("：:即")
            item = re.sub(r"^(?:长子|次子|三子|长女|次女|名)", "", item)
            if re.fullmatch(f"[{CN}]{{1,5}}", item) and not re.search(r"子|女|名字|不详|失考|分别|嫁于|情况", item):
                output.append(item if item.startswith(surname) else surname + item)
    return list(dict.fromkeys(output))


def extract_family(rows, fid, title, source, explicit=False):
    people, spouses, unparsed = [], [], []
    active, base, latest = None, None, {}
    declared_gen = None
    for index, row in enumerate(expand_rows(rows)):
        text = row["text"]
        compact = re.sub(r"\s+", "", text)
        gm = re.match(r"第([一二三四五六七八九十]+)[代世]", compact)
        if gm:
            declared_gen = cn_num(gm.group(1))
            continue
        parsed = person_line(row)
        if not parsed:
            if active and not ("家族" in text or compact.startswith(("【", "※", "第", "以下", "本部分"))):
                active["context"] += "\n" + text
            unparsed.append(row)
            continue
        role, name, content = parsed
        spouse = "配" in role or "妻" in role or "媳" in role or "婿" in role
        if spouse:
            owner = active
            # 妻室紧随起首人物；后裔媳妇按同代最近人物匹配，避免跨代误挂。
            if not explicit and "妻" not in role and "婿" not in role:
                level = role_level(role)
                candidate = latest.get(level)
                if candidate:
                    owner = candidate
            record = {"id": f"{fid}-配{len(spouses)+1:03d}", "name": name,
                      "role": role, "owner": owner["id"] if owner else "", "source": source,
                      "para": row["para"], "raw": text, "dates": get_dates(content), "alias": normalize_alias(content)}
            spouses.append(record)
            if owner:
                owner["spouses"].append(record["id"])
                owner["context"] += "\n" + text
            continue
        level = role_level(role) if role != "本段起首人物" else 1
        person = {"id": f"{fid}-人{len(people)+1:03d}", "family": fid, "family_name": title,
                  "name": name, "alias": normalize_alias(content), "role": role, "source": source,
                  "para": row["para"], "raw": text, "context": text, "spouses": [],
                  "dates": get_dates(content), "sex": "女" if "女" in role else ("男" if any(s in role for s in ("男", "子")) else "未注"),
                  "local_level": level, "declared_gen": declared_gen if explicit else None,
                  "parent": "", "parent_basis": "未建立", "edge_kind": "亲子", "issues": [], "children_declared": []}
        if explicit:
            parent = latest.get((declared_gen or 1) - 1)
            if parent:
                person["parent"] = parent["id"]
                person["parent_basis"] = "原文世次与分支顺序"
            if declared_gen and person["sex"] != "女":
                latest[declared_gen] = person
        elif role == "本段起首人物":
            base = person
            latest = {1: person}
        elif not explicit:
            parent = latest.get(level - 1)
            if parent:
                person["parent"] = parent["id"]
                person["parent_basis"] = "原文称谓与分支顺序"
            if person["sex"] != "女":
                latest[level] = person
        people.append(person)
        active = person
    family = {"id": fid, "title": title, "source": source, "start": rows[0]["para"], "end": rows[-1]["para"],
              "people": people, "spouses": spouses, "unparsed": unparsed, "migration": "始迁祖未证实；仅保留相对代次", "notes": []}
    return family


def link_declarations(family):
    people = family["people"]
    by_name = defaultdict(list)
    for p in people:
        by_name[p["name"]].append(p)
    default_surname = next((p["name"][0] for p in people if p["name"] not in UNKNOWN), "")
    for p in people:
        surname = p["name"][0] if p["name"] not in UNKNOWN else default_surname
        p["children_declared"] = child_names(p["context"], surname)
    for p in people:
        candidates = [q for q in people if q["id"] != p["id"] and p["name"] in q["children_declared"]]
        if len(candidates) == 1:
            q = candidates[0]
            p["parent"] = q["id"]
            p["parent_basis"] = "原文明确子女名单"
        elif len(candidates) > 1:
            p["issues"].append("同名人物出现多个子女名单，须按房支核对")
    # 顺序不能解决的无上辈人物保留为空，不跨户自动寻找父亲。


def apply_overrides(families, config):
    by_key = {(f["source"], p["para"], p["name"]): p for f in families for p in f["people"]}
    for fix in config.get("person_overrides", []):
        key = (fix["source"], fix["para"], fix["name"])
        p = by_key.get(key)
        if not p:
            raise ValueError("人工核对条目不存在：" + str(key))
        if "parent_para" in fix:
            parent = by_key.get((fix["source"], fix["parent_para"], fix["parent_name"])) if fix["parent_para"] else None
            p["parent"] = parent["id"] if parent else ""
            p["parent_basis"] = fix.get("basis", "人工复核原文")
        for field in ["edge_kind", "declared_gen", "sex", "biological", "adoptive", "identity", "display_parent", "generation_note", "candidate_parents", "confirmation_note"]:
            if field in fix:
                p[field] = fix[field]
        if fix.get("issue"):
            p["issues"].append(fix["issue"])
    for f in families:
        if f["id"] in config.get("family_notes", {}):
            entry = config["family_notes"][f["id"]]
            f["migration"] = entry.get("migration", f["migration"])
            f["notes"] = entry.get("notes", [])


def validate_people(families):
    all_people = {p["id"]: p for f in families for p in f["people"]}
    issues = []
    for f in families:
        for p in f["people"]:
            seen = {p["id"]}
            current = p
            while current["parent"]:
                parent = all_people.get(current["parent"])
                if not parent:
                    p["issues"].append("上辈条目不存在")
                    break
                if parent["id"] in seen:
                    raise ValueError("发现关系循环：" + p["id"])
                seen.add(parent["id"])
                current = parent
            parent = all_people.get(p["parent"])
            if parent:
                p["relative_gen"] = len(seen)
                if p["declared_gen"] and parent["declared_gen"] and p["declared_gen"] != parent["declared_gen"] + 1:
                    p["issues"].append(f"原标第{p['declared_gen']}世与上辈原标第{parent['declared_gen']}世不相邻")
                for a, b in [(parent, p)]:
                    by = re.search(r"(?:1[6789]|20)\d{2}", re.sub(r"\s+", "", a["raw"]))
                    cy = re.search(r"(?:1[6789]|20)\d{2}", re.sub(r"\s+", "", b["raw"]))
                    if by and cy and re.search(r"年生|[—－-]", a["raw"]) and re.search(r"年生|[—－-]", b["raw"]):
                        gap = int(cy.group()) - int(by.group())
                        if gap < 12 or gap > 75:
                            p["issues"].append(f"上辈与本人生年相差{gap}年，须核对年份或关系")
            else:
                p["relative_gen"] = 1
            if p["source"] != "总" and p["declared_gen"] and p["declared_gen"] != p["relative_gen"] and len(seen) > 1:
                p["issues"].append(f"原标第{p['declared_gen']}世；按已列上辈关系接续为第{p['relative_gen']}世，须核世次栏目")
            compact = re.sub(r"\s+", "", p["raw"])
            years = re.search(r"((?:1[6789]|20)\d{2})年?[—－-]+((?:1[6789]|20)\d{2})", compact)
            if years and int(years.group(2)) < int(years.group(1)):
                p["issues"].append("原文卒年早于生年")
            if re.search(r"过继|过嗣|承嗣|养子|嗣子|继子|立嗣|入赘|收养|领养|抚养|继父", p["context"]):
                p["issues"].append("涉及收养、过继、继亲或入赘，须区分生身与承嗣关系")
            for message in dict.fromkeys(p["issues"]):
                issues.append({"family": f["title"], "id": p["id"], "name": p["name"], "source": p["source"], "para": p["para"], "message": message, "raw": p["raw"]})
        for spouse in f["spouses"]:
            compact = re.sub(r"\s+", "", spouse["raw"])
            years = re.search(r"((?:1[6789]|20)\d{2})年?[—－-]+((?:1[6789]|20)\d{2})", compact)
            if years and int(years.group(2)) < int(years.group(1)):
                issues.append({"family": f["title"], "id": spouse["id"], "name": spouse["name"], "source": spouse["source"], "para": spouse["para"], "message": "配偶条目原文卒年早于生年", "raw": spouse["raw"]})
    return issues


def build(source, latest, out, config_path=None):
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path else {}
    total_rows, latest_rows = read_rows(source, "总"), read_rows(latest, "张氏新版")
    families = []
    for i, block in enumerate(split_blocks(total_rows[2:]), 1):
        first = block[0]["text"]
        if "家族" in first:
            first = first.split("各分支概况：")[-1]
            title = first[:first.index("家族") + 2]
            title = title.split("各分支概况：")[-1]
        else:
            parsed = next((person_line(r) for r in block if person_line(r)), None)
            title = (parsed[1] if parsed else "未定名") + "支"
        families.append(extract_family(block, f"总{i:02d}", title, "总"))
    section = []
    current_title = "张氏共同先祖"
    number = 0
    for row in [r for r in latest_rows if r["para"] >= 57]:
        if row["text"].startswith("【"):
            # 前五世按原件的世代栏目整理，避免把同一先祖重复制造成新人。
            if row["para"] < 153:
                section.append(row)
                continue
            if section:
                fid = "张前五世" if number == 0 else f"张{number:02d}"
                families.append(extract_family(section, fid, current_title, "张氏新版", True))
            number += 1
            section = []
            current_title = row["text"].strip("【】")
        else:
            section.append(row)
    if section:
        families.append(extract_family(section, f"张{number:02d}", current_title, "张氏新版", True))
    for family in families:
        link_declarations(family)
        if family["source"] != "总":
            family["migration"] = "以新版第58段记载的始迁祖为第一世；原世次栏目与关系接续分别保留"
    apply_overrides(families, config)
    issues = validate_people(families)
    output = {"families": families, "issues": issues, "manual_findings": config.get("findings", []), "coverage": config.get("coverage", []), "manual_edges": config.get("manual_edges", []), "report_text": config.get("report_text", {}), "user_decisions": config.get("user_decisions", [])}
    (out / "人物关系底稿.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("原总分隔段数：", sum(f["source"] == "总" for f in families))
    print("人物正文条目：", sum(len(f["people"]) for f in families))
    print("配偶条目：", sum(len(f["spouses"]) for f in families))
    print("待核提示数：", len(issues))
    print("数据保存：", out / "人物关系底稿.json")
    return output


def main():
    parser = argparse.ArgumentParser(description="整理家族资料的人物及关系，保留出处和待核事项")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--latest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    build(args.source, args.latest, args.out, args.config)


if __name__ == "__main__":
    main()
