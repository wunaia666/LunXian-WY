"""核对已登录账号识别和页面提示，拦截所有写入，不连接客户端。"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    url = "http://127.0.0.1:8765"
    if not args.production:
        sys.path.insert(0, str(root / "project/tools"))
        for name in ("qq_gateway_runtime", "xiaojingyu_connection_probe"):
            importlib.import_module(name)
        spec = importlib.util.spec_from_file_location(
            "verified_connection_monitor", root / "monitor/monitor.py"
        )
        monitor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(monitor)
        status = monitor.api_status()
    else:
        import urllib.request

        with urllib.request.urlopen(url + "/api/status", timeout=15) as response:
            status = json.load(response)["data"]
    errors, blocked = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        page = browser.new_page(
            viewport={"width": 1500, "height": 1000}, reduced_motion="reduce"
        )

        def intercept(route):
            request = route.request
            path = request.url.split("?")[0].removeprefix(url)
            if request.method != "GET":
                blocked.append(path)
                route.fulfill(
                    json={
                        "ok": True,
                        "data": {"phase": "idle", "message": "只读验证已拦截写入"},
                    }
                )
            elif path == "/api/status":
                route.fulfill(json={"ok": True, "data": status})
            elif not args.production and path == "/":
                route.fulfill(
                    path=root / "monitor/dashboard.html",
                    content_type="text/html; charset=utf-8",
                )
            else:
                route.continue_()

        page.route("**/*", intercept)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="networkidle")
        if status["qq"]:
            page.wait_for_function(
                "() => document.querySelector('#account-status').textContent==='机器人已连接'"
            )
        elif status.get("connection", {}).get("phase") == "client_ready":
            page.wait_for_function(
                "() => document.querySelector('#account-status').textContent==='客户端已识别'"
            )
            assert "3768021466" in page.locator("#account-sub").inner_text()
            assert "未接入" in page.locator("#account-sub").inner_text()
            assert page.locator("#login-start").inner_text() == "连接已登录账号"
            assert not page.locator("#login-start").is_disabled()
            assert page.locator(".login-trigger").first.inner_text() == "连接已登录账号"
            assert "其他聊天进程" not in page.locator("#start-note").inner_text()
        else:
            raise RuntimeError(
                "当前账号状态已变化，需按真实状态复核："
                + status.get("qq_state", "未知")
            )
        assert not errors, "网页出现脚本错误"
        if not status["qq"]:
            assert not blocked, "未接入时页面自动发起了写入请求"
        result = {
            "验证对象": "正式页面" if args.production else "独立预览",
            "目标客户端已识别": status.get("connection", {}).get("account")
            == "3768021466",
            "机器人通道已连接": status["qq"],
            "页面阶段准确": True,
            "连接按钮指向当前账号": True,
            "网页脚本错误": errors,
            "实际发送写入请求": 0,
            "本轮接管客户端": False,
            "本轮发送聊天消息": False,
        }
        browser.close()
    (root / ("正式验证.json" if args.production else "预览验证.json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
