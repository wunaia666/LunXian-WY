"""读取真实本机数据验证三维视角、可追溯星团、新图片与角色动态。"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    errors, writes = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        context = browser.new_context(
            viewport={"width": 1600, "height": 1120}, reduced_motion="reduce"
        )
        page = context.new_page()
        page.add_init_script(
            "window.whaleCanvasStrokes=0;const original=CanvasRenderingContext2D.prototype.stroke;CanvasRenderingContext2D.prototype.stroke=function(...args){if(this.canvas.id==='memory-space-canvas')window.whaleCanvasStrokes++;return original.apply(this,args)}"
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
                "/memory-map.js",
                "/memory-map.css",
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
            elif not args.production and path in (
                "/assets/whale-blink.png",
                "/assets/whale-hug.png",
                "/assets/whale-starry.png",
            ):
                route.fulfill(path=ROOT / path[1:], content_type="image/png")
            else:
                route.continue_()

        page.route("**/*", route_request)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(URL, wait_until="networkidle")
        assert page.locator("#whale-gallery .whale-art-card").count() == 3, (
            "三组新素材没有接入"
        )
        for name in ("whale-blink.png", "whale-hug.png", "whale-starry.png"):
            if args.production:
                response = page.request.get(URL + "/assets/" + name)
                assert response.status == 200 and response.headers[
                    "content-type"
                ].startswith("image/png"), "正式素材无法读取"
        page.locator('[data-open-page="memory"]').click()
        page.wait_for_function(
            "() => Number(document.querySelector('#memory-star-svg').dataset.memoryCount)>0 && Number(document.querySelector('#memory-star-svg').dataset.draws)>0"
        )
        original = page.request.get(URL + "/api/memory-map").json()["data"]
        count = page.locator('.star-node[data-type="memory"]').count()
        assert count == original["shown"], "星团制造或遗漏了真实记忆"
        info = page.evaluate("whaleMemoryMap.inspect()")
        assert info["clusters"] > 1 and info["links"] >= count, (
            "真实记忆没有形成星团和关联"
        )
        assert page.evaluate("whaleCanvasStrokes") >= info["links"], (
            "关联数据没有真正绘制到画布"
        )
        assert not info["animationRunning"], "未遵循减少动态效果设置"
        before = page.locator("#memory-star-svg").get_attribute("data-camera")
        point = page.locator('.star-node[data-type="memory"]').first.get_attribute(
            "transform"
        )
        page.locator("#star-right").click()
        page.wait_for_function(
            'before => document.querySelector("#memory-star-svg").dataset.camera !== before',
            arg=before,
        )
        assert point != page.locator(
            '.star-node[data-type="memory"]'
        ).first.get_attribute("transform"), "节点未随三维视角旋转"
        page.locator("#star-reset").click()
        pinned = next(
            n for n in original["nodes"] if n["type"] == "memory" and n.get("pinned")
        )
        page.locator('.star-node[data-id="' + pinned["id"] + '"]').focus()
        page.keyboard.press("Enter")
        assert pinned["content"] in page.locator("#star-detail").inner_text(), (
            "记忆详情未对应真实正文"
        )
        assert "归组依据" in page.locator(".inspector-path").inner_text(), (
            "缺少关键词或主题归组依据"
        )
        page.get_by_role("button", name="查看原始来源与修订", exact=True).click()
        page.wait_for_selector("#memory-detail:not([hidden])")
        assert pinned["content"] in page.locator("#memory-detail").inner_text(), (
            "来源与记忆不一致"
        )
        page.locator("#memory-detail button").last.click()
        page.locator("#star-reset").click()
        bounds = page.locator("#memory-star-svg").bounding_box()
        before = page.locator("#memory-star-svg").get_attribute("data-camera")
        page.mouse.move(bounds["x"] + 25, bounds["y"] + 70)
        page.mouse.down()
        page.mouse.move(bounds["x"] + 85, bounds["y"] + 100, steps=4)
        page.mouse.up()
        page.wait_for_function(
            'before => document.querySelector("#memory-star-svg").dataset.camera !== before',
            arg=before,
        )
        previous_zoom = page.evaluate("whaleMemoryMap.inspect().camera.k")
        page.locator("#star-zoom-in").click()
        page.wait_for_function(
            "previous => whaleMemoryMap.inspect().camera.k>previous", arg=previous_zoom
        )
        page.locator("#star-labels").click()
        assert page.locator("#star-labels").get_attribute("aria-pressed") == "true"
        page.locator("#star-labels").click()
        page.locator("#star-fullscreen").click()
        page.wait_for_function("() => document.fullscreenElement !== null")
        page.locator("#star-fullscreen").click()
        page.wait_for_function("() => document.fullscreenElement === null")
        page.locator("#memory-state").select_option("locked")
        locked = page.request.get(URL + "/api/memory-map?state=locked").json()["data"][
            "shown"
        ]
        page.wait_for_function(
            'count => document.querySelectorAll(".star-node[data-type=memory]").length===count',
            arg=locked,
        )
        page.locator("#memory-search").fill("不存在的星团词987651")
        page.wait_for_selector("#star-empty:not([hidden])")
        assert page.locator('.star-node[data-type="memory"]').count() == 0
        page.locator("#memory-search").fill("")
        page.locator("#memory-state").select_option("all")
        page.wait_for_function(
            'count => document.querySelectorAll(".star-node[data-type=memory]").length===count',
            arg=count,
        )
        page.locator("#memory-mode-list").click()
        page.wait_for_selector("#memory-list-view:not([hidden])")
        assert page.locator(".memory-card").count() > 0
        page.locator("#memory-mode-map").click()
        page.locator("#star-reset").click()
        page.wait_for_timeout(100)
        contained = page.locator("#memory-star-svg").evaluate(
            "svg => {const box=svg.getBoundingClientRect();return [...svg.querySelectorAll('.star-node .star-orb')].every(node=>{const point=node.getBoundingClientRect();return point.left>=box.left-1&&point.right<=box.right+1&&point.top>=box.top-1&&point.bottom<=box.bottom+1})}"
        )
        assert contained, "归航后仍有星团或记忆被画布边缘裁切"
        output = ROOT / "界面验证"
        output.mkdir(exist_ok=True)
        page.locator(".memory-star-panel").screenshot(
            path=str(output / "三维主题星团.png")
        )
        for section in ("voice", "computer", "chats", "context", "logs", "home"):
            page.locator('nav button[data-page="' + section + '"]').click()
            assert page.locator("#page-" + section).is_visible()
        page.emulate_media(reduced_motion="no-preference")
        if page.locator("#whale-animations").get_attribute("aria-pressed") == "true":
            page.locator("#whale-animations").click()
        page.locator("#whale-animations").click()
        state = page.locator(".whale-sprite").first.evaluate(
            "node => getComputedStyle(node).animationPlayState"
        )
        assert state == "running", "眨眼动画没有启动"
        blink_positions = page.locator(".whale-sprite").first.evaluate(
            "node => {const animation=node.getAnimations()[0];animation.pause();animation.currentTime=0;const opened=getComputedStyle(node).backgroundPosition;animation.currentTime=6000;const closed=getComputedStyle(node).backgroundPosition;animation.play();return [opened,closed]}"
        )
        assert blink_positions[0] != blink_positions[1], "眨眼素材的实际帧位置没有变化"
        page.locator("#whale-animations").click()
        assert (
            page.locator(".whale-sprite").first.evaluate(
                "node => getComputedStyle(node).animationPlayState"
            )
            == "paused"
        ), "角色动画不能暂停"
        page.locator("#whale-gallery").screenshot(path=str(output / "三组角色素材.png"))
        overflows = []
        for section in ("home", "memory"):
            page.locator('nav button[data-page="' + section + '"]').click()
            for width, height in (
                (1366, 900),
                (1024, 900),
                (768, 1024),
                (390, 844),
                (375, 812),
                (844, 390),
            ):
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(100)
                if page.evaluate(
                    "document.documentElement.scrollWidth > innerWidth + 1"
                ):
                    overflows.append([section, width, height])
        assert not overflows, "页面发生横向溢出：" + str(overflows)
        if page.locator("#star-motion").get_attribute("aria-pressed") == "false":
            page.locator("#star-motion").click()
        old_angle = page.evaluate("whaleMemoryMap.inspect().camera.yaw")
        page.wait_for_timeout(450)
        assert page.evaluate("whaleMemoryMap.inspect().camera.yaw") != old_angle, (
            "自动巡游没有实际改变三维视角"
        )
        page.locator('nav button[data-page="home"]').click()
        page.wait_for_timeout(100)
        assert not page.evaluate("whaleMemoryMap.inspect().animationRunning"), (
            "离开星图后仍持续巡游绘制"
        )
        page.locator('nav button[data-page="memory"]').click()
        page.emulate_media(reduced_motion="reduce")
        page.wait_for_timeout(150)
        assert not page.evaluate("whaleMemoryMap.inspect().animationRunning")
        assert not errors and not writes, "界面发生脚本错误或自动写入"
        result = {
            "验证对象": "正式页面" if args.production else "独立预览",
            "真实记忆数": count,
            "主题星团数": info["clusters"],
            "真实归组关联数": info["links"],
            "连线已绘制": True,
            "三维旋转与缩放": True,
            "节点来源与归组依据": True,
            "搜索锁定列表全屏": True,
            "角色图片及动效开关": True,
            "两页六种尺寸": "无横向溢出",
            "减少动态效果": True,
            "网页脚本错误": errors,
            "自动写入请求": writes,
        }
        context.close()
        browser.close()
    (ROOT / ("正式验证.json" if args.production else "预览验证.json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
