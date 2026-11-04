"""用本机演示程序检查文字边界、编辑保存及实际打印结果。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import win32com.client


def main():
    parser = argparse.ArgumentParser(description="在核对副本中检查全部页面")
    parser.add_argument("--presentation", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--previews", default="1")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    source = args.work / "native_check.pptx"
    shutil.copy2(args.presentation, source)
    app = win32com.client.GetActiveObject("PowerPoint.Application")
    document = app.Presentations.Open(str(source), ReadOnly=True, Untitled=False, WithWindow=False)
    result = {"页数": document.Slides.Count, "检查文本框": 0, "文字溢出": [], "编辑保存重开": False}
    try:
        for number in range(1, document.Slides.Count+1):
            slide = document.Slides.Item(number)
            for index in range(1, slide.Shapes.Count+1):
                shape = slide.Shapes.Item(index)
                if not (shape.HasTextFrame and shape.TextFrame.HasText):
                    continue
                result["检查文本框"] += 1
                text = shape.TextFrame2.TextRange
                if text.BoundWidth > shape.Width+1 or text.BoundHeight > shape.Height+1:
                    result["文字溢出"].append({"页": number, "对象": index, "文字": text.Text, "框": [shape.Width, shape.Height], "实际": [text.BoundWidth, text.BoundHeight]})
        print("已检查", result["页数"], "页、", result["检查文本框"], "个文本框；溢出", len(result["文字溢出"]), flush=True)
        document.SaveAs(str(args.work / "native_check.pdf"), 32)
        for number in [int(v) for v in args.previews.split(",") if v]:
            document.Slides.Item(number).Export(str(args.work / f"核对第{number}张.png"), "PNG", 1920, 1356)
        # 改动仅发生在本次副本，并在保存前恢复原文字和位置。
        first = document.Slides.Item(1)
        text = next(first.Shapes.Item(j) for j in range(1, first.Shapes.Count+1) if first.Shapes.Item(j).HasTextFrame and first.Shapes.Item(j).TextFrame.HasText)
        value = text.TextFrame.TextRange.Text
        text.TextFrame.TextRange.Text = value + "编辑检查"
        text.TextFrame.TextRange.Text = value
        line = next(first.Shapes.Item(j) for j in range(1, first.Shapes.Count+1) if first.Shapes.Item(j).Type == 9)
        value = line.Left
        line.Left = value+1
        line.Left = value
        document.SaveCopyAs(str(args.work / "editable_check.pptx"))
    finally:
        document.Close()
    reopened = app.Presentations.Open(str(args.work / "editable_check.pptx"), ReadOnly=True, Untitled=False, WithWindow=False)
    try:
        result["编辑保存重开"] = reopened.Slides.Count == result["页数"]
    finally:
        reopened.Close()
    (args.work / "本机显示检查.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("打印稿已导出，编辑保存重开", "通过" if result["编辑保存重开"] else "未通过", flush=True)
    if result["文字溢出"] or not result["编辑保存重开"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
