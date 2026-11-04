"""使用同一版面数据直接生成嵌入中文字库的矢量打印版及分户文件。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pymupdf


def main():
    parser = argparse.ArgumentParser(description="导出系谱图矢量打印总册和分户打印文件")
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--regular-font", required=True, type=Path)
    parser.add_argument("--bold-font", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    fonts = {False: pymupdf.Font(fontfile=str(args.regular_font)), True: pymupdf.Font(fontfile=str(args.bold_font))}
    files = {False: str(args.regular_font), True: str(args.bold_font)}
    document = pymupdf.open()
    for definition in data["pages"]:
        page = document.new_page(width=data["width"], height=data["height"])
        for bold, filename in files.items():
            page.insert_font(fontname="Fbold" if bold else "Fregular", fontfile=filename)
        for atom in definition["atoms"]:
            if atom["kind"] == "line":
                page.draw_line((atom["x1"], atom["y1"]), (atom["x2"], atom["y2"]), color=(0.067, 0.094, 0.153),
                               width=atom["width"], dashes="[3 2] 0" if atom["dashed"] else "[] 0", overlay=True)
            else:
                font = fonts[atom["bold"]]
                text_width = font.text_length(atom["text"], fontsize=atom["size"])
                assert text_width <= atom["w"] + 1, (definition["global_page"], atom["text"])
                x = atom["x"] + ((atom["w"] - text_width) / 2 if atom["align"] == "center" else atom["w"] - text_width if atom["align"] == "right" else 0)
                baseline = atom["y"] + font.ascender * atom["size"]
                page.insert_text((x, baseline), atom["text"], fontname="Fbold" if atom["bold"] else "Fregular",
                                 fontsize=atom["size"], color=(0.067, 0.094, 0.153), overlay=True)
    document.set_metadata({"title": "村志分户系谱图", "author": "", "subject": "按主稿制作的分户系谱核对图"})
    document.subset_fonts()
    target = args.out / "村志系谱图_打印.pdf"
    document.save(target, garbage=4, deflate=True)
    document.close()
    original = pymupdf.open(target)
    folder = args.out / "分户打印文件"
    folder.mkdir(exist_ok=True)
    for index, house in enumerate(data["houses"], 1):
        part = pymupdf.open()
        part.insert_pdf(original, from_page=house[3] - 1, to_page=house[4] - 1)
        part.set_metadata({"title": house[1] + "系谱图", "author": ""})
        part.subset_fonts()
        name = re.sub(r'[<>:"/\\|?*]', "", house[1])[:45]
        part.save(folder / f"{index:02d}_{house[0]}_{name}.pdf", garbage=4, deflate=True)
        part.close()
    print("矢量总册页数：", len(original), "；分户打印文件数：", len(data["houses"]))
    original.close()


if __name__ == "__main__":
    main()
