"""持久保存电脑留言，复用一个便签窗口，不重复弹出窗口。"""

from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import psutil

ROOT = Path(r"E:\sss_test")


def leave_note(text: str, title: str = "小鲸鱼的留言", root: Path = ROOT) -> dict:
    """保存留言并启动或更新专用便签，仅在窗口回报后标记已显示。"""
    text, title = text.strip(), title.strip()
    if not 1 <= len(text) <= 1000 or not 1 <= len(title) <= 40:
        raise ValueError("留言须为一至一千字，标题须为一至四十字")
    folder = root / "dafeiyu_assets/desktop_note"
    folder.mkdir(parents=True, exist_ok=True)
    state = folder / "note.json"
    revision = time.time_ns()
    if state.exists():
        backups = folder / "history"
        backups.mkdir(exist_ok=True)
        (backups / (str(revision) + ".json")).write_bytes(state.read_bytes())
    temporary = folder / "note.tmp"
    temporary.write_text(
        json.dumps({"标题": title, "正文": text, "版本": revision}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(state)
    desktop = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, desktop) != 0:
        raise RuntimeError("无法取得当前用户桌面路径，留言已保存在项目目录")
    link = Path(desktop.value) / "小鲸鱼留言.txt"
    if link.exists():
        backups = folder / "history"
        backups.mkdir(exist_ok=True)
        (backups / (str(revision) + "_桌面原文.txt")).write_bytes(link.read_bytes())
    link.write_text(title + "\n\n" + text + "\n", encoding="utf-8-sig")
    script = root / "tools/xiaojingyu_note_window.py"
    status_path = folder / "window.json"
    status = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.exists()
        else {}
    )
    running = False
    try:
        process = psutil.Process(int(status.get("进程", 0)))
        running = (
            str(script).casefold() in " ".join(process.cmdline()).casefold()
            and time.time() - status.get("时间", 0) < 10
        )
    except (psutil.Error, ValueError):
        pass
    if not running:
        interpreter = root / "venvs/astrbot/Scripts/pythonw.exe"
        if importlib.util.find_spec("tkinter") is None:
            candidates = sorted(
                (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python").glob(
                    "Python*/pythonw.exe"
                ),
                reverse=True,
            )
            interpreter = next(
                (path for path in candidates if (path.parent / "Lib/tkinter").is_dir()),
                None,
            )
            if interpreter is None:
                return {
                    "已保存": True,
                    "窗口已显示": False,
                    "桌面文件": str(link),
                    "说明": "未找到现有的电脑图形界面解释器，留言已保存",
                }
        with (folder / "window.log").open("ab") as output:
            subprocess.Popen(
                [str(interpreter), str(script)],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    for _ in range(30):
        time.sleep(0.1)
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if (
                status.get("版本") == revision
                and time.time() - status.get("时间", 0) < 5
            ):
                return {
                    "已保存": True,
                    "窗口已显示": True,
                    "桌面文件": str(link),
                    "标题": title,
                }
        except (OSError, ValueError):
            pass
    return {
        "已保存": True,
        "窗口已显示": False,
        "桌面文件": str(link),
        "说明": "留言文件已落地，但尚未收到便签窗口显示回报",
    }
