"""使用公开主页的作品搜索，不登录、不读取用户资料、不猜造接口签名。"""

import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    folder = Path(__file__).resolve().parent
    listing = json.loads(
        (folder / "同作者公开作品清单.local.json").read_text(encoding="utf-8")
    )
    author_id = listing["作者"]["公开编号"]
    found = {}
    attempts = []
    current_word = ""

    def absorb(value):
        if isinstance(value, dict):
            author = value.get("author") or {}
            identifier = str(value.get("aweme_id", ""))
            if identifier and author.get("sec_uid") == author_id:
                found[identifier] = {
                    "作品编号": identifier,
                    "描述": value.get("desc", ""),
                    "秒数": (value.get("video") or {}).get("duration", 0) / 1000,
                    "命中词": current_word,
                }
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

        def receive(response):
            if "/aweme/v1/web/" not in urlsplit(response.url).path:
                return
            try:
                absorb(response.json())
            except Exception:
                return

        page.on("response", receive)
        page.goto(listing["公开主页"], wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        for word in ("说话", "台词", "晚安", "聊天"):
            current_word = word
            before = set(found)
            try:
                field = page.get_by_placeholder("搜索 Ta 的作品", exact=True)
                field.fill(word, timeout=4000)
                field.press("Enter", timeout=4000)
                page.wait_for_timeout(4500)
                text = page.locator("body").inner_text(timeout=5000)
                row = {
                    "搜索词": word,
                    "新增同作者作品": len(set(found) - before),
                    "服务异常": "服务异常" in text,
                    "要求登录": "登录后搜索" in text or "登录后查看" in text,
                    "无结果": "暂无搜索结果" in text or "没有找到" in text,
                }
            except Exception as error:
                row = {"搜索词": word, "入口操作受阻": type(error).__name__}
            attempts.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if row.get("要求登录") or row.get("入口操作受阻"):
                break
        browser.close()
    result = {
        "作者": listing["作者"]["名称"],
        "公开主页": listing["公开主页"],
        "已知主页作品总数": 210,
        "此前公开清单数量": listing["公开可见作品数"],
        "公开搜索尝试": attempts,
        "本次返回同作者作品": list(found.values()),
        "边界": "仅核对公开页面实际返回的数据，分页异常或未登录限制不能解释为作者没有说话作品",
    }
    (folder / "同作者作品搜索记录.local.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps({"本次返回同作者作品数": len(found)}, ensure_ascii=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
