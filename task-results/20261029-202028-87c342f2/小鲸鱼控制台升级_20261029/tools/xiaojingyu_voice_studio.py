"""指定原声的本地试听工作台，生成候选后由用户明确确认日常配置。"""

from __future__ import annotations

import importlib.util
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from xiaojingyu_checks import REFERENCE_SHA

ROOT = Path(r"E:\sss_test")
STATE = ROOT / "dafeiyu_assets/runtime/voice_studio.json"
LOCK = threading.Lock()
TASK = None


def save(value):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(STATE)
    return value


def status():
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "idle", "message": "填写文字，生成指定原声的本地试听。"}
    if (
        value.get("phase") == "running"
        and not (TASK and TASK.is_alive())
        and time.time() - value.get("at", 0) > 15
    ):
        value.update(phase="interrupted", message="上次试听已中断，可以重新生成。")
    return value


def checked_config():
    import hashlib

    assets = ROOT / "dafeiyu_assets"
    cfg = json.loads((assets / "voice_config.json").read_text(encoding="utf-8"))
    reference = assets / "audio/_cosy_ref/ref_douyin_link_7689724715246372473.wav"
    if (
        str(cfg.get("_模型", {}).get("source_video_id")) != "7689724715246372473"
        or hashlib.sha256(reference.read_bytes()).hexdigest() != REFERENCE_SHA
    ):
        raise ValueError("指定视频原声校验未通过，未生成或更换声音")
    if Path(cfg.get("_模型", {}).get("ref_wav_wsl", "")).name != reference.name:
        raise ValueError("当前参考音配置不符")
    cfg.update(backend="cosy", reference_only=True, fallback="none")
    return cfg


def generate(request):
    import asyncio
    import wave

    try:
        cfg = checked_config()
        profile = request["profile"]
        cfg.update(
            cosy_mode="cross_lingual" if profile == "stable" else "instruct2",
            cosy_seed=20261029,
            cosy_tempo=request["tempo"],
        )
        staged = (
            Path(__file__).resolve().parent.parent
            / "AstrBot/data/plugins/astrbot_plugin_dafeiyu_voice/tts.py"
        )
        source = (
            staged
            if staged.is_file()
            else ROOT / "AstrBot/data/plugins/astrbot_plugin_dafeiyu_voice/tts.py"
        )
        spec = importlib.util.spec_from_file_location(
            "whale_preview_tts_" + request["id"], source
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        folder = ROOT / "dafeiyu_assets/audio/previews"
        folder.mkdir(parents=True, exist_ok=True)
        module.AUDIO_DIR = folder

        async def synthesize():
            if not await module.cosy_available(cfg):
                raise RuntimeError("指定原声服务尚未就绪")
            return await module.cosy_synth(
                module.clean_text(request["text"]), request["mood"], cfg
            )

        path = asyncio.run(synthesize())
        if not path or not path.is_file():
            raise RuntimeError("本次原声合成未生成完整文件")
        target = folder / (request["id"] + ".wav")
        shutil.copy2(path, target)
        with wave.open(str(target), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        save(
            {
                **request,
                "phase": "ready",
                "message": "候选已生成，等待你试听确认。",
                "file": target.name,
                "duration": round(duration, 2),
                "meta": module.LAST_SYNTH_META,
                "reference_sha": REFERENCE_SHA,
                "sent_messages": False,
                "production_changed": False,
                "at": time.time(),
            }
        )
    except Exception as error:
        save(
            {
                **request,
                "phase": "failed",
                "message": "试听未完成：" + str(error)[:160],
                "at": time.time(),
            }
        )


def start(body):
    global TASK
    text = str(body.get("text", "")).strip()
    mood = str(body.get("mood", "normal"))
    profile = str(body.get("profile", "stable"))
    tempo = float(body.get("tempo", 0.94))
    if (
        not 1 <= len(text) <= 240
        or mood not in {"normal", "cheerful", "comfort", "coquettish", "puzzled"}
        or profile not in {"stable", "expressive"}
        or not 0.85 <= tempo <= 1.0
    ):
        raise ValueError("请提供一至二百四十字、有效语气和正常范围内的语速")
    with LOCK:
        if TASK and TASK.is_alive():
            return status()
        request = {
            "id": uuid.uuid4().hex,
            "text": text,
            "mood": mood,
            "profile": profile,
            "tempo": tempo,
            "phase": "running",
            "message": "正在本机生成原声试听，请稍候。",
            "at": time.time(),
        }
        save(request)
        TASK = threading.Thread(
            target=generate, args=(request,), name="小鲸鱼原声试听", daemon=True
        )
        TASK.start()
        return request


def accept(body):
    with LOCK:
        candidate = status()
        if (
            body.get("accepted") is not True
            or candidate.get("phase") != "ready"
            or body.get("id") != candidate.get("id")
            or candidate.get("reference_sha") != REFERENCE_SHA
        ):
            raise ValueError("请先试听本次生成的候选，再明确确认")
        audio = ROOT / "dafeiyu_assets/audio/previews" / (candidate["id"] + ".wav")
        if (
            candidate.get("file") != audio.name
            or not audio.is_file()
            or audio.stat().st_size < 1000
        ):
            raise ValueError("本次试听文件不可用，请重新生成候选")
        cfg = checked_config()
        path = ROOT / "dafeiyu_assets/voice_config.json"
        backup = ROOT / "backups/voice_profiles"
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup / (str(time.time_ns()) + ".json"))
        cfg.update(
            cosy_mode="cross_lingual"
            if candidate["profile"] == "stable"
            else "instruct2",
            cosy_seed=20261029,
            cosy_tempo=candidate["tempo"],
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
        candidate.update(
            production_changed=True,
            accepted_at=time.time(),
            message="你已确认此候选，日常语音参数已更新。",
        )
        return save(candidate)
