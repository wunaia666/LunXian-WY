"""仅删除族谱房支统括曲线，保留人物、连接线及其他原生对象。"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from zipfile import ZipFile

from lxml import etree


NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
FOOTNOTE = "大括号统括同支子女；"


def is_brace(shape):
    name = shape.find("p:nvSpPr/p:cNvPr", NS)
    return name is not None and name.get("name") == "房支统括大括号"


def update_footer(shape):
    changes = 0
    for text in shape.findall(".//a:t", NS):
        if text.text and FOOTNOTE in text.text:
            text.text = text.text.replace(FOOTNOTE, "")
            changes += 1
    return changes


def edit_presentation(source, target):
    removed, footer_changes, checked = 0, 0, 0
    with ZipFile(source) as original:
        with ZipFile(target, "w") as result:
            for entry in original.infolist():
                data = original.read(entry.filename)
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", entry.filename):
                    root = etree.fromstring(data)
                    tree = root.find("p:cSld/p:spTree", NS)
                    for shape in list(tree):
                        if is_brace(shape):
                            tree.remove(shape)
                            removed += 1
                        else:
                            footer_changes += update_footer(shape)
                    data = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
                result.writestr(entry, data)
    with ZipFile(source) as original, ZipFile(target) as result:
        assert original.namelist() == result.namelist(), "文件部件有增减"
        assert result.testzip() is None, "输出封装损坏"
        for name in original.namelist():
            if not re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
                assert original.read(name) == result.read(name), ("非图页部件变化", name)
                continue
            old = etree.fromstring(original.read(name))
            new = etree.fromstring(result.read(name))
            old_tree, new_tree = old.find("p:cSld/p:spTree", NS), new.find("p:cSld/p:spTree", NS)
            expected = [s for s in old_tree if not is_brace(s)]
            assert len(expected) == len(new_tree), ("误删其他对象", name)
            for before, after in zip(expected, new_tree):
                before = copy.deepcopy(before)
                update_footer(before)
                assert etree.tostring(before, method="c14n") == etree.tostring(copy.deepcopy(after), method="c14n"), ("保留对象发生变化", name)
                assert not is_brace(after), "大括号残留"
            checked += 1
    return {"文件": str(target), "图页": checked, "删除大括号": removed, "更新页脚": footer_changes, "其他对象逐项不变": True}


def main():
    parser = argparse.ArgumentParser(description="删除统括大括号并保持其余对象原样")
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    layouts = list(args.source_dir.glob("*版面.json"))
    assert len(layouts) == 1, "应有唯一的版面依据"
    layout = json.loads(layouts[0].read_text(encoding="utf-8"))
    total = 0
    for page in layout["pages"]:
        total += sum(a["kind"] == "brace" for a in page["atoms"])
        page["atoms"] = [a for a in page["atoms"] if a["kind"] != "brace"]
        for atom in page["atoms"]:
            if atom["kind"] == "text":
                atom["text"] = atom["text"].replace(FOOTNOTE, "")
                for value in atom.get("paragraphs", []):
                    value["text"] = value["text"].replace(FOOTNOTE, "")
    layout["display_options"] = {"family_braces": False, "basis": "用户明确要求去掉大型统括大括号"}
    (args.out / "去大括号版面.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    results = []
    for source in sorted(args.source_dir.rglob("*.pptx")):
        relative = source.relative_to(args.source_dir)
        if relative.parent == Path(".") and "夫妻横向" in source.stem:
            name = source.stem.replace("夫妻横向", "去大括号")+source.suffix
        else:
            name = source.stem+"_去大括号"+source.suffix
        target = args.out / relative.parent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        results.append(edit_presentation(source, target))
    main = next(r for r in results if r["图页"] == len(layout["pages"]))
    assert main["删除大括号"] == total, "实际删除与版面数量不一致"
    (args.out / "删除与保留核验.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("处理", len(results), "份文稿；整册", main["图页"], "页，删除", total, "个统括大括号；人物、关系连线、字号及位置逐项保持一致。")


if __name__ == "__main__":
    main()
