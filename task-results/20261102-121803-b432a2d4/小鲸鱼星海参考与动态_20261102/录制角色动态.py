"""录制独立角色展示页面，不包含任何聊天、记忆或账号数据。"""

import json
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parent
    folder = root / "动态录制"
    folder.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(folder),
            record_video_size={"width": 1280, "height": 720},
            reduced_motion="no-preference",
        )
        page = context.new_page()
        page.goto((root / "小鲸鱼动态展示.html").as_uri(), wait_until="load")
        page.wait_for_function(
            "() => [...document.images].every(image => image.complete && image.naturalWidth > 0)"
        )
        page.wait_for_timeout(1000)
        page.wait_for_timeout(9000)
        recording = page.video
        context.close()
        source = Path(recording.path())
        browser.close()
    output = root / "小鲸鱼_动态展示.mp4"
    command = [
        r"E:\sss_test\apps\ShareX\ffmpeg.exe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "1",
        "-i",
        str(source),
        "-t",
        "8",
        "-an",
        "-r",
        "25",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-y",
        str(output),
    ]
    subprocess.run(command, check=True, timeout=90, capture_output=True)
    if not output.is_file() or output.stat().st_size < 50000:
        raise RuntimeError("动态短片未成功导出")
    result = {
        "动态文件": output.name,
        "时长秒数": 8,
        "画面尺寸": "1280×720",
        "包含眨眼漂浮及呼吸效果": True,
        "包含聊天或记忆内容": False,
        "字节数": output.stat().st_size,
    }
    (root / "动态导出记录.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
