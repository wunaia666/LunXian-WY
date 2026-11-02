"""使用真实本机数据验证新页面，预览时替换静态文件，不执行聊天或语音操作。"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    output = ROOT / "界面验证"
    output.mkdir(exist_ok=True)
    errors, writes = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        page = browser.new_page(
            viewport={"width": 1600, "height": 1200}, reduced_motion="reduce"
        )

        def route_request(route):
            request = route.request
            if request.method != "GET":
                writes.append(request.url.split("?")[0])
                route.abort()
                return
            path = request.url.split("?")[0].removeprefix(URL)
            if not args.production and path in (
                "/",
                "/memory-map.css",
                "/memory-map.js",
            ):
                name = "dashboard.html" if path == "/" else path[1:]
                content_type = (
                    "text/html"
                    if name.endswith(".html")
                    else "text/css"
                    if name.endswith(".css")
                    else "text/javascript"
                )
                route.fulfill(
                    path=ROOT / "monitor" / name,
                    content_type=content_type + "; charset=utf-8",
                )
            else:
                route.continue_()

        page.route("**/*", route_request)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(URL, wait_until="networkidle")
        page.wait_for_function(
            "() => document.querySelector('#memory-total').textContent.includes('条')"
        )
        page.screenshot(path=str(output / "深海首页_桌面.png"))
        page.locator('[data-open-page="memory"]').click()
        page.wait_for_selector('.star-node[data-type="memory"]')
        graph = page.request.get(URL + "/api/memory-map").json()["data"]
        count = page.locator('.star-node[data-type="memory"]').count()
        edges = page.locator(".star-link").count()
        assert count == graph["shown"], "星图记忆数与真实接口不一致"
        assert edges == len(graph["links"]) and edges > 0, "真实关系未全部绘制"
        visible_edges = page.locator(".star-link").evaluate_all(
            "nodes => nodes.filter(n => Number(getComputedStyle(n).opacity) >= .5 && n.getTotalLength() > 0 && getComputedStyle(n).stroke !== 'none').length"
        )
        assert visible_edges == edges, "默认视图存在不可见连线"
        assert page.locator("#star-count-links").inner_text() == str(edges), (
            "关联数与图中航线不一致"
        )
        memory = next(
            row
            for row in graph["nodes"]
            if row["type"] == "memory" and row.get("pinned")
        )
        page.locator('.star-node[data-id="' + memory["id"] + '"]').focus()
        page.keyboard.press("Enter")
        assert memory["content"] in page.locator("#star-detail").inner_text(), (
            "节点详情没有显示真实正文"
        )
        highlighted = page.locator(".star-link.highlight").count()
        assert highlighted >= 2, "记忆到中心的所属分类路径没有点亮"
        assert "小鲸鱼" in page.locator(".inspector-path").inner_text(), (
            "详情缺少关联路径"
        )
        page.get_by_role("button", name="查看原始来源与修订", exact=True).click()
        page.wait_for_selector("#memory-detail:not([hidden])")
        assert memory["content"] in page.locator("#memory-detail").inner_text(), (
            "来源与当前记忆不一致"
        )
        page.locator("#memory-detail button").last.click()
        page.locator("#star-labels").click()
        assert page.locator("#memory-star-svg").evaluate(
            "node => node.classList.contains('labels-expanded')"
        ), "标签展开按钮没有生效"
        page.locator("#star-labels").click()
        page.locator("#star-fullscreen").click()
        page.wait_for_function("() => document.fullscreenElement !== null")
        assert page.locator("#star-fullscreen").inner_text() == "退出沉浸", (
            "沉浸模式状态没有更新"
        )
        page.locator("#star-fullscreen").click()
        page.wait_for_function("() => document.fullscreenElement === null")
        assert page.locator("#star-motion").get_attribute("aria-pressed") == "false", (
            "未遵循减少动态效果设置"
        )
        page.locator("#star-reset").click()
        before = page.locator("[data-scene]").get_attribute("transform")
        page.locator("#star-zoom-in").click()
        page.locator("#star-right").click()
        assert page.locator("[data-scene]").get_attribute("transform") != before, (
            "缩放或移动无效"
        )
        page.locator("#star-reset").click()
        assert page.locator("[data-scene]").get_attribute("transform") == before, (
            "归航没有恢复视图"
        )
        page.locator("#memory-star-svg").focus()
        page.keyboard.press("ArrowUp")
        assert page.locator("[data-scene]").get_attribute("transform") != before, (
            "键盘方向移动没有生效"
        )
        page.locator("#star-reset").click()
        bounds = page.locator("#memory-star-svg").bounding_box()
        page.mouse.move(bounds["x"] + 35, bounds["y"] + 35)
        page.mouse.down()
        page.mouse.move(bounds["x"] + 95, bounds["y"] + 65, steps=4)
        page.mouse.up()
        assert page.locator("[data-scene]").get_attribute("transform") != before, (
            "画布拖动没有生效"
        )
        page.locator("#star-reset").click()
        page.locator("#memory-state").select_option("locked")
        locked = page.request.get(URL + "/api/memory-map?state=locked").json()["data"]
        page.wait_for_function(
            "count => document.querySelectorAll('.star-node[data-type=memory]').length === count",
            arg=locked["shown"],
        )
        assert page.locator(".star-link").count() == len(locked["links"]), (
            "锁定筛选后的连线不对应真实数据"
        )
        page.locator("#memory-search").fill("不存在的记忆测试词986213")
        page.wait_for_selector("#star-empty:not([hidden])")
        assert page.locator(".star-link").count() == 0, "空搜索仍显示关联线"
        page.locator("#memory-search").fill("")
        page.locator("#memory-state").select_option("all")
        page.wait_for_function(
            "count => document.querySelectorAll('.star-link').length === count",
            arg=edges,
        )
        page.locator("#memory-mode-list").click()
        page.wait_for_selector("#memory-list-view:not([hidden])")
        assert page.locator(".memory-card").count() > 0, "记忆列表不可用"
        page.locator("#memory-mode-map").click()
        page.locator("#star-reset").click()
        page.locator("#page-memory").screenshot(path=str(output / "深海星图_桌面.png"))
        for section in (
            "voice",
            "computer",
            "chats",
            "context",
            "logs",
            "home",
            "memory",
        ):
            page.locator('nav button[data-page="' + section + '"]').click()
            assert page.locator("#page-" + section).is_visible(), (
                "原栏目切换失败：" + section
            )
        page.wait_for_function(
            "() => document.querySelectorAll('.star-link').length > 0"
        )
        overflows = []
        for width, height in (
            (1366, 1000),
            (1024, 900),
            (768, 1024),
            (390, 844),
            (375, 812),
            (844, 390),
        ):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(100)
            overflow = page.evaluate(
                "document.documentElement.scrollWidth > innerWidth + 1"
            )
            if overflow:
                overflows.append([width, height])
            if width <= 480:
                canvas_bottom = page.locator("#memory-star-svg").bounding_box()
                tools_top = page.locator(".star-tools").bounding_box()
                assert (
                    canvas_bottom["y"] + canvas_bottom["height"] <= tools_top["y"] + 1
                ), "手机移动工具遮挡了星图"
                targets = page.locator(".star-tools button").evaluate_all(
                    "buttons => buttons.every(button => button.getBoundingClientRect().width >= 44 && button.getBoundingClientRect().height >= 44)"
                )
                assert targets, "手机星图工具触摸范围不足"
        assert not overflows, "页面存在横向溢出：" + str(overflows)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator(".memory-star-panel").screenshot(
            path=str(output / "深海星图_手机.png")
        )
        page.emulate_media(reduced_motion="no-preference")
        page.locator("#star-motion").click()
        assert page.locator("#star-motion").get_attribute("aria-pressed") == "true", (
            "手动开启动效失败"
        )
        assert not page.locator("#memory-star-svg").evaluate(
            "node => node.animationsPaused()"
        ), "动效开关没有恢复航线流光"
        page.locator("#star-motion").click()
        assert page.locator("#memory-star-svg").evaluate(
            "node => node.animationsPaused()"
        ), "动效开关没有暂停航线流光"
        result = {
            "验证对象": "正式页面" if args.production else "改版预览",
            "真实记忆数": count,
            "真实关联数": edges,
            "默认可见关联数": visible_edges,
            "节点选中后高亮路径数": highlighted,
            "锁定筛选记忆数": locked["shown"],
            "七个原栏目": "切换通过",
            "搜索来源与列表": "通过",
            "缩放移动归航": "通过",
            "标签与动效开关": "通过",
            "沉浸全屏与退出": "通过",
            "键盘与拖动": "通过",
            "减少动态效果": "通过",
            "六种窗口尺寸": "无横向溢出",
            "网页脚本错误": errors,
            "写入请求": writes,
        }
        assert not errors, "页面脚本出现错误"
        assert not writes, "页面自动发起写入请求"
        browser.close()
    filename = "正式界面验证.json" if args.production else "预览验证.json"
    (ROOT / filename).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
