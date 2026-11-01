"""只读检查监控的已确认声音、音频播放器与参数控件，不发送聊天或触发登录。"""

import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    folder = Path(__file__).resolve().parent
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe",
            args=["--mute-audio"],
        )
        page = browser.new_page()
        posted = []
        page.on(
            "request",
            lambda request: (
                posted.append(request.url) if request.method == "POST" else None
            ),
        )
        page.goto(
            "http://127.0.0.1:8765/", wait_until="domcontentloaded", timeout=30000
        )
        page.wait_for_function("typeof voice === 'function'", timeout=15000)
        page.evaluate("voice()")
        page.wait_for_timeout(500)
        result = page.evaluate(
            "() => ({message:document.getElementById('voice-engine').textContent,controls:['voice-profile','voice-mood','voice-tempo'].map(id=>({id,disabled:document.getElementById(id).disabled,value:document.getElementById(id).value})),note:document.getElementById('voice-profile-note').textContent})"
        )
        api = page.request.get("http://127.0.0.1:8765/api/voice").json()["data"]
        studio = page.request.get("http://127.0.0.1:8765/api/voice/studio").json()[
            "data"
        ]
        response = page.request.get("http://127.0.0.1:8765" + api["reference"]["url"])
        result.update(
            声音名称=api["reference"]["name"],
            已选音频摘要=hashlib.sha256(response.body()).hexdigest(),
            已选音频可播放=response.status == 200,
            已确认状态=studio.get("evaluation"),
            日常配置已生效=studio.get("production_changed"),
            自动写入请求数=len(posted),
        )
        if (
            not all(row["disabled"] for row in result["controls"])
            or result["controls"][1]["value"] != "normal"
            or result["controls"][2]["value"] != "1.0"
            or result["已选音频摘要"]
            != "20c311aec5c0a2649b7b88574d1afda52829c53c3fe2d6a7e149bdc8765dc074"
            or result["已确认状态"] != "accepted"
            or not result["日常配置已生效"]
            or posted
        ):
            raise RuntimeError("监控已选声音、控件状态或只读检查未通过")
        browser.close()
    (folder / "监控界面验证结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
