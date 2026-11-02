"""用现有真实浏览器验证状态提示，拦截所有写入请求，不操作聊天客户端。"""

import argparse
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).parent
URL = "http://127.0.0.1:8765"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    opener = build_opener(ProxyHandler({}))
    with opener.open(URL + "/api/status", timeout=15) as response:
        actual = json.load(response)["data"]
    cases = [("bridge_failed", "组件初始化失败", "查看连接故障"),
             ("waiting_bridge", "通道待就绪", "登录或连接小鲸鱼"),
             ("client_ready", "客户端已识别", "连接已登录账号")]
    if args.production:
        assert not actual["qq"]
        current = actual["connection"]["phase"]
        cases = [row for row in cases if row[0] == current]
        if current in {"client_missing", "client_unknown", "account_mismatch", "manager_unavailable"}:
            cases = [(current,"等待连接","登录或连接小鲸鱼")]
        if not cases:
            raise RuntimeError("当前页面状态变化，需要继续核对：" + current)
    result = []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"])
        for phase, label, button in cases:
            status = dict(actual)
            if not args.production:
                status.update(qq=False, connection={"phase":phase,
                    "account":"3768021466", "message":"已登录；组件初始化失败，无需重复扫码。" if phase == "bridge_failed" else "状态核对中"},
                    chat_start={"phase":phase, "message":"状态核对中"})
            page = browser.new_page(viewport={"width":1500,"height":1000}, reduced_motion="reduce")
            errors, writes = [], []

            def route(request_route):
                request = request_route.request
                pathname = request.url.split("?")[0].removeprefix(URL)
                if request.method != "GET":
                    writes.append(pathname)
                    request_route.fulfill(json={"ok":True,"data":{"phase":"idle","message":"已拦截写入"}})
                elif pathname == "/api/status":
                    request_route.fulfill(json={"ok":True,"data":status})
                elif pathname == "/" and not args.production:
                    request_route.fulfill(path=ROOT/"修复代码/dashboard.html", content_type="text/html; charset=utf-8")
                else:
                    request_route.continue_()

            page.route("**/*", route)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(URL, wait_until="networkidle")
            page.wait_for_function("label => document.querySelector('#account-status').textContent === label", arg=label)
            assert page.locator(".login-trigger").first.inner_text() == button
            assert not errors
            assert not writes
            if phase == "bridge_failed":
                page.locator(".login-trigger").first.click()
                assert page.locator("#login-dialog").is_visible()
                assert page.locator("#login-state").get_attribute("role") == "alert"
                assert page.locator("#login-state").inner_text() == status["connection"]["message"]
                assert not writes, "查看故障不应重新发起连接"
                assert page.locator("#login-start").inner_text() == "重新核对连接"
            result.append({"状态":phase,"显示":label,"脚本错误":len(errors),"写入请求":len(writes)})
            page.close()
        browser.close()
    output = {"验证对象":"正式页面" if args.production else "候选页面", "结果":result,
              "实际机器人已连接":actual["qq"],"发送聊天消息":False}
    (ROOT/("页面正式验证.json" if args.production else "页面回归验证.json")).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(output,ensure_ascii=False))


if __name__ == "__main__":
    main()
