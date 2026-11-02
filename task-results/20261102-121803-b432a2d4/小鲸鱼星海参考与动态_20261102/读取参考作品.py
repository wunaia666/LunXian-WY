"""读取用户指定的公开作品，仅保存参考视频和作品核对摘要，不登录或发送消息。"""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parent
    folder = root / "参考视频"
    folder.mkdir(parents=True, exist_ok=True)
    identifier = "7702103501119307496"
    url = "https://www.douyin.com/video/" + identifier
    details, caught = [], []

    def absorb(value):
        if isinstance(value, dict):
            if str(value.get("aweme_id")) == identifier and isinstance(
                value.get("video"), dict
            ):
                details.append(value)
            for child in value.values():
                absorb(child)
        elif isinstance(value, list):
            for child in value:
                absorb(child)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        context = browser.new_context(
            locale="zh-CN", viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        def received(response):
            parsed = urlsplit(response.url)
            if parsed.hostname and (
                parsed.hostname.endswith("douyinvod.com")
                or "/aweme/v1/play" in parsed.path
            ):
                if response.url not in caught:
                    caught.append(response.url)
            if "/aweme/v1/web/" in parsed.path or "aweme/detail" in parsed.path:
                try:
                    absorb(response.json())
                except Exception:
                    pass

        page.on("response", received)
        print("正在核对指定作品的作者、标题和可公开播放的视频。", flush=True)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        deadline = time.monotonic() + 45
        videos = []
        while time.monotonic() < deadline:
            videos = page.evaluate(
                "() => [...document.querySelectorAll('video')].map(v=>({duration:Number.isFinite(v.duration)?v.duration:0,src:v.currentSrc||v.src})).sort((a,b)=>b.duration-a.duration)"
            )
            if details or (videos and videos[0]["duration"] > 3 and caught):
                break
            page.wait_for_timeout(1500)
        text = page.locator("body").inner_text(timeout=10000)
        (folder / "页面核对.local.txt").write_text(text[:12000], encoding="utf-8")
        target = details[-1] if details else None
        nickname = (target.get("author") or {}).get("nickname", "") if target else ""
        description = target.get("desc", "") if target else page.title()
        duration = (
            target["video"].get("duration", 0) / 1000
            if target
            else (videos[0]["duration"] if videos else 0)
        )
        if nickname and nickname != "东方鹤白":
            raise RuntimeError("取得的作品作者与用户指定作者不符")
        if not target and not ("东方鹤白" in text and "鲸宝" in text):
            raise RuntimeError("页面尚不能确认是指定作品，未将验证页当成参考视频")
        candidates = []
        if target:
            video = target["video"]
            for address in [
                row.get("play_addr", {}) for row in video.get("bit_rate", [])
            ] + [video.get("play_addr", {})]:
                candidates.extend(address.get("url_list", []))
        candidates.extend(caught)
        if videos and videos[0]["src"].startswith("https://"):
            candidates.insert(0, videos[0]["src"])
        saved = None
        for address in dict.fromkeys(candidates):
            try:
                response = context.request.get(
                    address,
                    headers={"Referer": url, "Range": "bytes=0-"},
                    timeout=45000,
                )
                content = response.body()
                if response.ok and len(content) > 200000 and b"ftyp" in content[:64]:
                    saved = folder / "鲸宝养成日记第十三天.mp4"
                    saved.write_bytes(content)
                    break
            except Exception:
                continue
        browser.close()
    result = {
        "原始链接": "https://v.douyin.com/cJEI01mGYXU/",
        "作品地址": url,
        "作品编号": identifier,
        "作者": nickname,
        "描述": description,
        "秒数": duration,
        "视频已取得": bool(saved),
    }
    (folder / "参考核对.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not saved:
        raise RuntimeError("公开视频暂未取得，未声称已看过具体画面")


if __name__ == "__main__":
    main()
