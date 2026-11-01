"""提取用户指定公开视频的完整音轨，核对作品和时长，保留未经处理的副本。"""

import argparse
import hashlib
import json
import subprocess
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description="完整提取指定作者的公开作品音轨")
    parser.add_argument("--id", default="7500493303280946470")
    args = parser.parse_args()
    identifier = args.id
    if not identifier.isdigit() or not 18 <= len(identifier) <= 20:
        raise ValueError("作品编号格式无效")
    root = Path(__file__).resolve().parent
    folder = (
        root
        if identifier == "7500493303280946470"
        else root / "同作者素材" / identifier
    )
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "原始素材"
    source.mkdir(exist_ok=True)
    record_path = folder / "原视频提取记录.json"
    if record_path.is_file():
        existing = json.loads(record_path.read_text(encoding="utf-8"))
        checks = (
            ("完整视频文件", "视频摘要"),
            ("完整音轨文件", "音轨摘要"),
            ("原编码音轨文件", "原编码音轨摘要"),
            ("双声道原音文件", "双声道原音摘要"),
        )
        if existing.get("作品编号") == identifier and all(
            (source / existing.get(file_key, "不存在")).is_file()
            and hashlib.sha256((source / existing[file_key]).read_bytes()).hexdigest()
            == existing.get(sha_key)
            for file_key, sha_key in checks
        ):
            print(
                json.dumps(
                    {
                        "作品编号": identifier,
                        "状态": "完整素材已存在且摘要一致，未重复下载",
                        "秒数": existing["完整音轨秒数"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return
    url = "https://www.douyin.com/video/" + identifier
    browser_path = r"C:\Users\14431\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe"
    ffmpeg = r"E:\sss_test\apps\ShareX\ffmpeg.exe"
    caught = []
    details = []

    def absorb(value):
        if isinstance(value, dict):
            if str(value.get("aweme_id")) == identifier and isinstance(
                value.get("video"), dict
            ):
                details.append(value)
            for item in value.values():
                absorb(item)
        elif isinstance(value, list):
            for item in value:
                absorb(item)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=browser_path, args=["--mute-audio"]
        )
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 800},
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
                    return

        page.on("response", received)
        print("正在读取用户指定作品的公开播放页。", flush=True)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        deadline = time.monotonic() + 65
        media = None
        while time.monotonic() < deadline:
            videos = page.evaluate(
                "() => [...document.querySelectorAll('video')].map(v=>({duration:Number.isFinite(v.duration)?v.duration:0,src:v.currentSrc || v.src})).sort((a,b)=>b.duration-a.duration)"
            )
            media = videos[0] if videos else None
            if details and details[-1]["video"].get("duration"):
                media = {"duration": details[-1]["video"]["duration"] / 1000, "src": ""}
                break
            if (
                media
                and media.get("duration")
                and media.get("duration") > 3
                and len(caught) > 1
            ):
                break
            page.wait_for_timeout(2000)
        title = page.title()
        page_text = page.locator("body").inner_text(timeout=10000)
        (folder / "播放页文字.local.txt").write_text(
            page_text[:30000], encoding="utf-8"
        )
        if not media or not media.get("duration"):
            browser.close()
            raise RuntimeError("公开播放页未取得有效视频，未把验证页或空页面当作素材")
        page.evaluate(
            "() => {const v=document.querySelector('video');if(v){v.muted=true;v.play().catch(()=>{});}}"
        )
        page.wait_for_timeout(5000)
        target = details[-1] if details else None
        if target and (target.get("author") or {}).get("nickname") != "卖唱的doro":
            raise RuntimeError("素材并非已确认作者，未纳入同声音参考")
        if target and target["video"].get("duration"):
            media["duration"] = target["video"]["duration"] / 1000
        elif media["duration"] <= 3:
            raise RuntimeError("只取得占位视频时长，未把短预览当成完整作品")
        (folder / "公开作品元数据.local.json").write_text(
            json.dumps(
                {
                    "作品编号": identifier,
                    "作者": (target.get("author") or {}).get("nickname")
                    if target
                    else None,
                    "描述": target.get("desc") if target else None,
                    "目标作品秒数": media["duration"],
                    "视频元素数": len(videos),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if target:
            candidates = []
            video = target["video"]
            for address in [
                row.get("play_addr", {})
                for row in sorted(
                    video.get("bit_rate", []),
                    key=lambda row: row.get("bit_rate", 0),
                    reverse=True,
                )
            ] + [video.get("play_addr", {})]:
                for address_url in address.get("url_list", []):
                    if address_url not in candidates:
                        candidates.append(address_url)
            candidates.extend(
                address for address in caught if address not in candidates
            )
        else:
            candidates = list(caught)
        current = media.get("src", "")
        if current.startswith("https://") and current not in candidates:
            candidates.insert(0, current)
        if not target and (
            identifier != "7500493303280946470" or "想你" not in title + page_text
        ):
            raise RuntimeError("页面内容尚不能确认是用户指定作品，停止提取")
        print(
            json.dumps(
                {
                    "页面标题": title,
                    "页面视频秒数": media["duration"],
                    "媒体候选数": len(candidates),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        good = []
        for index, address in enumerate(candidates[:3]):
            try:
                response = context.request.get(
                    address,
                    headers={"Referer": url, "Range": "bytes=0-"},
                    timeout=90000,
                )
                if response.status not in (200, 206):
                    continue
                body = response.body()
                if len(body) < 10000 or body[4:8] != b"ftyp":
                    continue
                candidate = source / ("媒体候选_" + str(index) + ".mp4")
                candidate.write_bytes(body)
                wav = source / ("完整音轨候选_" + str(index) + ".wav")
                subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(candidate),
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "32000",
                        "-c:a",
                        "pcm_s16le",
                        str(wav),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=90,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                with wave.open(str(wav), "rb") as stream:
                    duration = stream.getnframes() / stream.getframerate()
                if abs(duration - media["duration"]) > 0.2:
                    continue
                good.append(
                    {
                        "video": candidate,
                        "audio": wav,
                        "bytes": len(body),
                        "duration": duration,
                    }
                )
                print(
                    json.dumps(
                        {
                            "完整候选": index,
                            "字节": len(body),
                            "秒数": round(duration, 3),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as error:
                print(
                    json.dumps(
                        {"候选": index, "状态": "未采用", "原因": type(error).__name__},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        browser.close()
    if not good:
        raise RuntimeError("未取得与页面完整时长匹配的媒体文件")
    best = max(good, key=lambda row: row["bytes"])
    video_path = source / (identifier + "_完整视频.mp4")
    audio_path = source / (identifier + "_完整原音.wav")
    best["video"].replace(video_path)
    best["audio"].replace(audio_path)
    encoded_audio = source / (identifier + "_原编码音轨.m4a")
    stereo_audio = source / (identifier + "_双声道原音.wav")
    for arguments in (
        ["-c:a", "copy", str(encoded_audio)],
        ["-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(stereo_audio)],
    ):
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video_path),
                "-map",
                "0:a:0",
                "-vn",
            ]
            + arguments,
            check=True,
            capture_output=True,
            timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    metadata = {
        "用户短链": "https://v.douyin.com/AuhbcIinEJs/"
        if identifier == "7500493303280946470"
        else url,
        "作品地址": url,
        "作品编号": identifier,
        "标题": title,
        "作者": (target.get("author") or {}).get("nickname") if target else None,
        "作品描述": target.get("desc") if target else None,
        "页面秒数": media["duration"],
        "完整音轨秒数": round(best["duration"], 3),
        "完整视频文件": video_path.name,
        "完整音轨文件": audio_path.name,
        "视频摘要": hashlib.sha256(video_path.read_bytes()).hexdigest(),
        "音轨摘要": hashlib.sha256(audio_path.read_bytes()).hexdigest(),
        "原编码音轨文件": encoded_audio.name,
        "原编码音轨摘要": hashlib.sha256(encoded_audio.read_bytes()).hexdigest(),
        "双声道原音文件": stereo_audio.name,
        "双声道原音摘要": hashlib.sha256(stereo_audio.read_bytes()).hexdigest(),
        "处理": "完整解码音轨，单声道三万二千赫兹；未剪切、调速或变调",
    }
    (folder / "原视频提取记录.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
