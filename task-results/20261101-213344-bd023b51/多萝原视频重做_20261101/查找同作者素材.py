"""只读收集同作者公开可见作品清单，筛选可能包含正常说话的素材。"""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    folder = Path(__file__).resolve().parent
    identifier = "7500493303280946470"
    author = {}
    posts = {}
    pagination = []

    def absorb(value):
        if isinstance(value, dict):
            current_id = str(value.get("aweme_id", ""))
            speaker = value.get("author") or {}
            if current_id == identifier and speaker.get("sec_uid"):
                author.update(
                    {
                        "公开编号": speaker["sec_uid"],
                        "名称": speaker.get("nickname"),
                        "简介": speaker.get("signature", ""),
                    }
                )
            if current_id and (
                speaker.get("nickname") == "卖唱的doro"
                or (author and speaker.get("sec_uid") == author["公开编号"])
            ):
                duration = (value.get("video") or {}).get("duration") or value.get(
                    "duration"
                )
                music = value.get("music") or {}
                posts[current_id] = {
                    "作品编号": current_id,
                    "描述": value.get("desc", ""),
                    "秒数": round(duration / 1000, 3)
                    if isinstance(duration, (int, float))
                    else None,
                    "音乐名称": music.get("title"),
                    "音乐作者": music.get("author"),
                    "发布时间": value.get("create_time"),
                    "地址": "https://www.douyin.com/video/" + current_id,
                }
            for item in value.values():
                absorb(item)
        elif isinstance(value, list):
            for item in value:
                absorb(item)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        def receive(response):
            path = urlsplit(response.url).path
            if "/aweme/v1/web/" not in path:
                return
            try:
                body = response.json()
            except Exception:
                return
            if "aweme/post" in path:
                pagination.append(
                    {
                        "还有更多": body.get("has_more"),
                        "本页数量": len(body.get("aweme_list") or []),
                    }
                )
            absorb(body)

        page.on("response", receive)
        page.goto(
            "https://www.douyin.com/video/" + identifier,
            wait_until="domcontentloaded",
            timeout=45000,
        )
        deadline = time.monotonic() + 55
        while not author and time.monotonic() < deadline:
            page.wait_for_timeout(1500)
        if not author:
            raise RuntimeError("未取得指定作品作者的公开编号，不猜测其他账号")
        print(
            json.dumps(
                {"指定作者": author["名称"], "状态": "正在读取同作者公开主页"},
                ensure_ascii=False,
            ),
            flush=True,
        )
        profile_url = "https://www.douyin.com/user/" + author["公开编号"]
        page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
        previous = len(posts)
        stalled = 0
        for index in range(32):
            page.wait_for_timeout(1800)
            links = page.locator('[data-e2e="user-post-list"] a[href*="/video/"]')
            if links.count() == 0:
                links = page.locator('a[href*="/video/"]')
            if links.count():
                try:
                    links.last.scroll_into_view_if_needed(timeout=1500)
                except Exception:
                    pass
            page.mouse.move(900, 650)
            page.mouse.wheel(0, 2600)
            if index == 7 and not pagination:
                text = page.locator("body").inner_text(timeout=10000)
                if "服务异常" in text:
                    print(
                        "公开作品列表返回服务异常，正在正常刷新重试一次。", flush=True
                    )
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                    stalled = 0
            if index % 4 == 3:
                print(
                    json.dumps(
                        {"公开作品已读取": len(posts), "滚动次数": index + 1},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if len(posts) == previous:
                stalled += 1
            else:
                stalled = 0
            previous = len(posts)
            if pagination and pagination[-1]["还有更多"] == 0:
                break
            if stalled >= 10:
                break
        page_text = page.locator("body").inner_text(timeout=10000)
        (folder / "同作者主页文字.local.txt").write_text(
            page_text[:50000], encoding="utf-8"
        )
        browser.close()
    for row in posts.values():
        description = row["描述"]
        score = 0
        if row["秒数"] and 2.5 < row["秒数"] < 16:
            score += 4
        score += sum(
            3
            for word in (
                "说话",
                "台词",
                "不唱",
                "聊天",
                "配音",
                "晚安",
                "早安",
                "你好",
                "对话",
                "念",
                "人，",
            )
            if word in description
        )
        score -= sum(
            2
            for word in ("cover", "翻唱", "唱歌", "点歌", "音乐", "bgm", "完整版")
            if word in description
        )
        row["说话候选排序分"] = score
    ordered = sorted(
        posts.values(), key=lambda row: (-row["说话候选排序分"], row.get("秒数") or 999)
    )
    result = {
        "作者": author,
        "公开主页": profile_url,
        "公开可见作品数": len(ordered),
        "作品列表分页": pagination,
        "采集边界": "只读取未登录公开页面实际返回的作品；标题排序不能证明含有真实说话，仍需逐条核对音轨",
        "主页列表服务异常": "服务异常" in page_text,
        "作品": ordered,
    }
    (folder / "同作者公开作品清单.local.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"作者": author, "公开可见作品数": len(ordered), "优先核对": ordered[:15]},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
