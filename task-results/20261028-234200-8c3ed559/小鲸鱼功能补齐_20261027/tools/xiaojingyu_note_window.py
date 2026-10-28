"""小鲸鱼独立便签窗口；更新时不抢焦点，关闭后保留桌面文本。"""

import ctypes
import json
import os
import time
import tkinter as tk
from pathlib import Path


def main():
    """使用互斥量保证每个桌面会话只有一个便签窗口。"""
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, "Local\\XiaojingyuDesktopNote")
    if kernel.GetLastError() == 183:
        return
    folder = Path(r"E:\sss_test\dafeiyu_assets\desktop_note")
    root = tk.Tk()
    root.title("小鲸鱼便签")
    root.geometry("330x260+80+100")
    root.configure(bg="#FFF4CF")
    root.attributes("-topmost", False)
    heading = tk.Label(
        root,
        bg="#FFF4CF",
        fg="#342E23",
        font=("Microsoft YaHei UI", 14, "bold"),
        anchor="w",
        wraplength=295,
    )
    heading.pack(fill="x", padx=16, pady=(16, 8))
    body = tk.Label(
        root,
        bg="#FFF4CF",
        fg="#342E23",
        font=("Microsoft YaHei UI", 12),
        anchor="nw",
        justify="left",
        wraplength=295,
    )
    body.pack(fill="both", expand=True, padx=16, pady=8)
    tk.Label(
        root,
        text="小鲸鱼 · 留言已保存到桌面",
        bg="#FFF4CF",
        fg="#706855",
        font=("Microsoft YaHei UI", 9),
    ).pack(pady=8)
    revision = None

    def refresh():
        nonlocal revision
        try:
            note = json.loads((folder / "note.json").read_text(encoding="utf-8"))
            if note["版本"] != revision:
                heading.config(text=note["标题"])
                body.config(text=note["正文"])
                revision = note["版本"]
                root.update_idletasks()
            status = {"进程": os.getpid(), "版本": revision, "时间": time.time()}
            temp = folder / "window.tmp"
            temp.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
            temp.replace(folder / "window.json")
        except (OSError, ValueError, KeyError):
            pass
        root.after(1000, refresh)

    refresh()
    root.mainloop()
    kernel.CloseHandle(ctypes.c_void_p(handle))


if __name__ == "__main__":
    main()
