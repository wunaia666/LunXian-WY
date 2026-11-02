"""在真实浏览器检查星图、检索、节点来源、键盘操作及移动端，不发送聊天或生成语音。"""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    folder = Path(__file__).resolve().parent
    output = folder / "界面验证"
    output.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        page = browser.new_page(
            viewport={"width": 1500, "height": 1200}, reduced_motion="reduce"
        )
        errors, posts = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                posts.append(request.url) if request.method == "POST" else None
            ),
        )
        page.goto(
            "http://127.0.0.1:8765/", wait_until="domcontentloaded", timeout=30000
        )
        page.locator('nav button[data-page="memory"]').click()
        page.wait_for_selector('.star-node[data-type="memory"]', timeout=15000)
        graph_data = page.request.get("http://127.0.0.1:8765/api/memory-map").json()[
            "data"
        ]
        shown = page.locator('.star-node[data-type="memory"]').count()
        if shown != graph_data["shown"]:
            raise RuntimeError("星图显示条数与真实接口不一致")
        memory = next(
            row
            for row in graph_data["nodes"]
            if row["type"] == "memory" and row.get("pinned")
        )
        page.locator('.star-node[data-id="' + memory["id"] + '"]').focus()
        page.keyboard.press("Enter")
        if memory["content"] not in page.locator("#star-detail").inner_text():
            raise RuntimeError("键盘选择记忆没有显示真实正文")
        page.get_by_role("button", name="查看原始来源与修订", exact=True).click()
        page.wait_for_selector("#memory-detail:not([hidden])")
        if memory["content"] not in page.locator("#memory-detail").inner_text():
            raise RuntimeError("来源面板与选中记忆不一致")
        page.locator("#memory-detail button").last.click()
        page.locator("#star-zoom-in").click()
        scale_before = page.locator("#memory-star-svg > g").last.get_attribute(
            "transform"
        )
        page.locator("#star-right").click()
        scale_after = page.locator("#memory-star-svg > g").last.get_attribute(
            "transform"
        )
        if scale_before == scale_after:
            raise RuntimeError("移动按钮没有生效")
        page.locator("#star-reset").click()
        page.locator("#memory-state").select_option("locked")
        expected_locked = page.request.get(
            "http://127.0.0.1:8765/api/memory-map?state=locked"
        ).json()["data"]["shown"]
        page.wait_for_function(
            "expected => document.querySelectorAll('.star-node[data-type=memory]').length === expected",
            arg=expected_locked,
        )
        locked_count = page.locator('.star-node[data-type="memory"]').count()
        if locked_count != expected_locked:
            raise RuntimeError("锁定筛选与数据库查询不一致")
        page.locator("#memory-search").fill("这是一段不存在的记忆检索词987654")
        page.wait_for_selector("#star-empty:not([hidden])", timeout=10000)
        empty_count = page.locator('.star-node[data-type="memory"]').count()
        if empty_count:
            raise RuntimeError("空检索仍展示了虚构记忆")
        page.locator("#memory-search").fill("")
        page.locator("#memory-state").select_option("all")
        page.wait_for_function(
            "() => document.querySelectorAll('.star-node[data-type=memory]').length > 4"
        )
        page.locator("#memory-mode-list").click()
        page.wait_for_selector("#memory-list-view:not([hidden])")
        list_count = page.locator("#memory-list .memory-card").count()
        page.locator("#memory-mode-map").click()
        page.locator("#star-reset").click()
        page.locator("#page-memory").screenshot(
            path=str(output / "记忆星图_桌面_完成版.png")
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth > innerWidth + 1"
        )
        page.screenshot(path=str(output / "记忆星图_手机_完成版.png"))
        if overflow:
            raise RuntimeError("移动端页面出现横向溢出")
        result = {
            "星图实际记忆数": shown,
            "接口总记忆数": graph_data["total"],
            "已锁定过滤条数": locked_count,
            "空查询记忆数": empty_count,
            "列表记录数": list_count,
            "节点与来源核对": True,
            "键盘选择及缩放移动": True,
            "移动端无横向溢出": not overflow,
            "网页脚本错误": errors,
            "自动写入请求数": len(posts),
        }
        if errors or posts:
            raise RuntimeError("只读界面验证出现脚本错误或自动写入请求")
        browser.close()
    (folder / "星图界面验证结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
