"""小鲸鱼语音合成：固定柔和女声，整句朗读与轻量后处理。

音色和语速从配置读取，保留原始声线，不再用共振峰上移和随机变调。
本地情感模型仍可按配置启用；实际使用的引擎由调用结果记录。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path

AUDIO_DIR = Path(r"E:\sss_test\dafeiyu_assets\audio")
WORK_DIR = AUDIO_DIR / "_work"
FFMPEG_CANDIDATES = [
    r"E:\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe",
    r"E:\sss_test\tmp\bin\ffmpeg.exe",
    r"E:\sss_test\apps\ShareX\ffmpeg.exe",
    r"D:\AI\ffmpeg\bin\ffmpeg.exe",
]

VOICE_DEFAULT = "zh-CN-XiaoxuanNeural"  # 默认保留晓萱的原始声线
FORMANT_BASE = 1.0  # 保留原始音色，不再叠加变调

# 情绪 → 每句参数 + 句间停顿(ms) + 后处理共振峰倍率 + 提亮(dB)
# rate 一律 0：用户要求正常倍速，情绪只靠音高、停顿和指令表达，不靠加速。
# pitch 单位是 **Hz**（edge-tts 的 pitch 参数就是 Hz）。旧版填 0~3 却拼成 "3Hz"，
# 在 250Hz 基频上不到 0.2 个半音，等于没升调——这是"七档情绪听起来一样"的头号原因。
MOODS: dict[str, dict] = {
    "normal": {"rate": 0, "pitch": 0, "gap": 180, "formant": 1.0, "bright": -1},
    "cheerful": {"rate": 0, "pitch": 30, "gap": 150, "formant": 1.0, "bright": 0},
    "smug": {"rate": -1, "pitch": 12, "gap": 175, "formant": 1.0, "bright": -1},
    "angry": {"rate": 1, "pitch": 18, "gap": 140, "formant": 1.0, "bright": 0},
    "lazy": {"rate": -2, "pitch": -12, "gap": 240, "formant": 1.0, "bright": -2},
    "serious": {"rate": 0, "pitch": -4, "gap": 200, "formant": 1.0, "bright": -1},
    "sad": {"rate": -2, "pitch": -20, "gap": 220, "formant": 1.0, "bright": -2},
    # 2026-10-25 新增三档：用户点名的撒娇/疑惑/安慰。旧的 7 个 key 全部保留。
    "coquettish": {"rate": -1, "pitch": 24, "gap": 210, "formant": 1.0, "bright": 0},
    "puzzled": {"rate": 0, "pitch": 16, "gap": 230, "formant": 1.0, "bright": -1},
    "comfort": {"rate": -3, "pitch": -6, "gap": 250, "formant": 1.0, "bright": -2},
}
# 旧名兼容
MOODS["sleepy"] = MOODS["lazy"]

# 句间抖动幅度：旧版 rate ±3 / pitch -2~+4 听着"飘"，定稿收到 rate ±2 / pitch ±2
JITTER_RATE = 0
JITTER_PITCH = 0

# 情绪中文名，面板与工具说明共用
MOOD_LABELS = {
    "normal": "日常",
    "cheerful": "开心",
    "smug": "得意",
    "angry": "生气",
    "lazy": "懒散",
    "serious": "认真",
    "sad": "委屈",
    "coquettish": "撒娇",
    "puzzled": "疑惑",
    "comfort": "安慰",
}

# ---------------- CosyVoice2 后端 ----------------
# edge-tts 只有 rate/pitch/volume，没有情感通道。CosyVoice2 支持自然语言指令
# （instruct2），所以"感情"交给它；失败自动回退 edge-tts。
VOICE_CONFIG_PATH = Path(r"E:\sss_test\dafeiyu_assets\voice_config.json")

COSY_INSTRUCT: dict[str, str] = {
    # 指令必须短。实测：30~40 字的韵律描述会让模型把指令后半段当正文念出来
    # （撒娇那版把"像拉着人衣角小声说话"整句读了出来）。音色不靠这里描述，
    # 靠参考音；这里只负责语气。
    "normal": "用自然轻松的语气说",
    "cheerful": "用开心带笑的语气说",
    "smug": "用得意欠揍的语气说",
    "angry": "用生气质问的语气说",
    "lazy": "用懒懒的语气说",
    "serious": "用认真的语气说",
    "sad": "用委屈低落的语气说",
    "coquettish": "用撒娇的语气说",
    "puzzled": "用疑惑的语气说",
    "comfort": "用温柔安慰的语气说",
}

_cosy_state: dict[str, float] = {"ok": 0.0, "fail": 0.0}
_cosy_reason = ""
LAST_SYNTH_BACKEND = ""

# 本次合成实际发生了什么——写进 voice_latest.json，面板据此显示"真实引擎"。
# 旧版只有 LAST_SYNTH_BACKEND，且回退只 print 到 stdout，事后无法解释"为什么声音变了"。
LAST_SYNTH_META: dict[str, object] = {
    "backend_actual": "",
    "voice_id": "",
    "mood": "",
    "synth_ms": 0,
    "chunks": 0,
    "ref": "",
    "fallback": "",
    "fallback_reason": "",
}


def reset_meta() -> None:
    for k, v in list(LAST_SYNTH_META.items()):
        LAST_SYNTH_META[k] = "" if isinstance(v, str) else 0


# 句末标点 → 停顿毫秒。固定 120ms 会让每句间隔一模一样，听着就是念稿。
GAP_BY_PUNCT = {
    "！": 190,
    "？": 205,
    "。": 255,
    "；": 230,
    "，": 145,
    "、": 115,
    "：": 165,
}
GAP_MOOD_SCALE = {
    "cheerful": 0.85,
    "angry": 0.8,
    "lazy": 1.35,
    "sad": 1.25,
    "serious": 1.05,
}


def _gaps_for(clauses: list[str], mood: str) -> list[int]:
    """按句末标点分配停顿并加抖动，避免句与句之间像等间距拼接。"""
    scale = GAP_MOOD_SCALE.get(mood, 1.0)
    gaps = []
    for clause in clauses[:-1]:
        tail = clause.rstrip()[-1:] if clause.strip() else ""
        base = GAP_BY_PUNCT.get(tail, 170)
        gaps.append(max(60, int(base * scale + random.randint(-25, 25))))
    return gaps


def load_voice_config() -> dict:
    try:
        import json

        return json.loads(VOICE_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def cosy_available(cfg: dict) -> bool:
    """3 秒探测 CosyVoice 服务；失败结果缓存，避免每次多等。

    必须 `ready=true` 才算可用：服务端加载完权重后还要后台预热，
    预热期间打进来只会排队，反而比直接走 edge 更慢。
    """
    global _cosy_reason
    import time as _t

    url = str(cfg.get("cosy_url", "http://127.0.0.1:9880")).rstrip("/")
    cache = float(cfg.get("cosy_health_cache_sec", 60))
    now = _t.time()
    if _cosy_state["ok"] and now - _cosy_state["ok"] < cache:
        return True
    if _cosy_state["fail"] and now - _cosy_state["fail"] < cache:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{url}/health")
        if r.status_code == 200:
            data = r.json() if r.content else {}
            if data.get("ready"):
                _cosy_state["ok"] = now
                _cosy_state["fail"] = 0.0
                _cosy_reason = ""
                return True
            _cosy_reason = f"health_not_ready:{data.get('phase', '?')}"
        else:
            _cosy_reason = f"health_http_{r.status_code}"
    except Exception as e:
        _cosy_reason = f"health_exception:{type(e).__name__}"
    _cosy_state["fail"] = now
    return False


async def _cosy_clause(
    clause: str, mood: str, cfg: dict, timeout: float
) -> dict | None:
    """合成分句，返回 {"data": wav字节, "ms": 服务端耗时, "chunks": 块数}。失败返回 None。"""
    import httpx

    url = str(cfg.get("cosy_url", "http://127.0.0.1:9880")).rstrip("/")
    payload = {
        "text": clause,
        "mood": mood,
        "instruct": COSY_INSTRUCT.get(mood, COSY_INSTRUCT["normal"]),
        # 显式传 1.0：服务端默认曾是 1.4（加速 40%），听起来像赶时间、没有呼吸感
        "speed": 1.0,
    }
    # 试听参数显式进入请求，避免服务端默认值和随机种子让各段不可复现。
    if cfg.get("cosy_mode"):
        payload["mode"] = str(cfg["cosy_mode"])
    if cfg.get("cosy_seed") is not None:
        payload["seed"] = int(cfg["cosy_seed"]) % 2147483647
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{url}/tts", json=payload)
        if r.status_code != 200 or len(r.content) < 2000:
            print(
                f"[tts] cosy 分句失败 HTTP {r.status_code} len={len(r.content)}: {clause[:20]}"
            )
            return None
        if r.headers.get("X-Fails", "-") not in ("", "-"):
            return None
        ref = r.headers.get("X-Ref") or ""
        expected = Path(cfg.get("_模型", {}).get("ref_wav_wsl", "")).name
        if cfg.get("reference_only") and (not expected or ref != expected):
            return None
        actual_mode = r.headers.get("X-Mode") or ""
        if cfg.get("cosy_mode") and actual_mode != cfg["cosy_mode"]:
            return None
        return {
            "data": r.content,
            "ms": int(r.headers.get("X-Synth-Ms") or 0),
            "chunks": int(r.headers.get("X-Chunks") or 1),
            "ref": ref,
            "mode": actual_mode,
        }
    except Exception as e:
        print(f"[tts] cosy 分句超时/异常 {type(e).__name__}: {clause[:20]}")
        return None


def _split_strong(text: str, min_chars: int = 8, max_chars: int = 60) -> list[str]:
    """只按强标点断句，短句并回上一句。

    旧版在这里按 `，` 也切，还加了「≤34 字整条合成」的捷径——结果正好落进
    CosyVoice frontend 对 ≤80 字不切的区间，长句一旦不吐终止符就跑满上限。
    现在细切成 22 字的活交给服务端，这里只保证「一句 = 一个语义单位」。
    """
    parts = re.findall(r"[^。！？；\n]+[。！？；]?", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and len(p) < min_chars and len(out[-1]) + len(p) <= max_chars:
            out[-1] += p
        else:
            out.append(p)
    if (
        len(out) > 1
        and len(out[0]) < min_chars
        and len(out[0]) + len(out[1]) <= max_chars
    ):
        out[1] = out[0] + out[1]
        out.pop(0)
    return out


async def cosy_synth(text: str, mood: str, cfg: dict) -> Path | None:
    """调本地 CosyVoice2 合成，返回 wav 路径。任何异常都返回 None 交给回退。

    服务端已按 22 字分块并限制 token 上限，这里只按语义断句 + 拼静音。
    """
    cfg = dict(cfg)
    cfg.setdefault("cosy_seed", 20261029)
    timeout = float(cfg.get("cosy_timeout_sec", 150))
    # 省略号会让 CosyVoice 陷入超长生成，本地先压掉再发
    safe_text = re.sub(r"[…\.]{2,}", "，", text)
    safe_text = re.sub(r"[，,]{2,}", "，", safe_text).strip("，")
    safe_text = safe_text or text

    clauses = _split_strong(safe_text)
    if not clauses:
        return None

    clause_timeout = max(60.0, min(timeout, 180.0))
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(text, f"cosy_{mood}")

    def _finish(path: Path) -> Path:
        """统一过后处理；失败就交回原始文件，不因为润色失败而丢语音。"""
        ff = ffmpeg_path()
        if not ff:
            return path
        tmp = path.with_name(path.stem + "._post.wav")
        if _cosy_post(ff, path, tmp, MOODS.get(mood, MOODS["normal"]), cfg):
            tmp.replace(path)
        return path

    ms_total = 0
    ref_name = ""
    if len(clauses) == 1:
        got = await _cosy_clause(clauses[0], mood, cfg, clause_timeout)
        if got is None:
            got = await _cosy_clause(clauses[0], mood, cfg, clause_timeout)  # 重试一次
        if got is None:
            _cosy_state["fail"] = time.time()
            return None
        p = AUDIO_DIR / f"{stem}.wav"
        p.write_bytes(got["data"])
        matched = _pitch_match(ffmpeg_path(), [p], cfg, AUDIO_DIR)
        if matched and matched[0] != p and matched[0].is_file():
            matched[0].replace(p)
        _cosy_state["ok"] = time.time()
        LAST_SYNTH_META.update(
            synth_ms=got["ms"],
            chunks=got["chunks"],
            ref=got.get("ref") or "",
            mode=got.get("mode") or "",
        )
        return _finish(p)

    ff = ffmpeg_path()
    work = AUDIO_DIR / f"_cosy_parts_{stem}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        wavs: list[Path] = []
        kept: list[str] = []
        for i, clause in enumerate(clauses):
            got = await _cosy_clause(clause, mood, cfg, clause_timeout)
            if got is None:
                got = await _cosy_clause(clause, mood, cfg, clause_timeout)  # 重试一次
            if got is None:
                # 分句缺失时整条失败，禁止把残缺内容当作成功语音。
                _cosy_state["fail"] = time.time()
                return None
            ms_total += got["ms"]
            ref_name = got.get("ref") or ref_name
            w = work / f"{i:02d}.wav"
            w.write_bytes(got["data"])
            wavs.append(w)
            kept.append(clause)

        if not wavs:
            _cosy_state["fail"] = time.time()
            return None
        LAST_SYNTH_META.update(
            synth_ms=ms_total,
            chunks=len(wavs),
            ref=ref_name,
            mode=got.get("mode") or "",
        )
        if len(wavs) == 1:
            p = AUDIO_DIR / f"{stem}.wav"
            p.write_bytes(wavs[0].read_bytes())
            _cosy_state["ok"] = time.time()
            return _finish(p)
        if not ff:
            return None

        wavs = _pitch_match(ff, wavs, cfg, work)
        gaps = _gaps_for(kept, mood)
        joined = work / "joined.wav"
        if not _concat_wavs(wavs, gaps, joined):
            return None
        p = AUDIO_DIR / f"{stem}.wav"
        p.write_bytes(joined.read_bytes())
        _cosy_state["ok"] = time.time()
        return _finish(p)
    finally:
        shutil.rmtree(work, ignore_errors=True)


MAX_CHARS = 900
SENT_END = "。！？!?；;…\n"
CLAUSE_END = "，,、：:"


def ffmpeg_path() -> str | None:
    p = shutil.which("ffmpeg")
    if p and os.path.isfile(p):
        return p
    for c in FFMPEG_CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def clean_text(text: str) -> str:
    t = text or ""
    t = re.sub(r"\[emo:[a-zA-Z_]+\]", "", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_`#>|~]+", "", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    if len(t) > MAX_CHARS:
        raise ValueError(f"语音正文超过{MAX_CHARS}字，请分成多条发送，未截短正文")
    return t


def split_sentences(text: str, max_len: int = 14) -> list[tuple[str, int]]:
    """切短句。返回 [(句子, 句后停顿毫秒)]。逗号处短停，句号处长停。"""
    text = text.strip()
    if not text:
        return []
    parts: list[tuple[str, int]] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in SENT_END:
            seg = buf.strip()
            if seg:
                parts.append((seg, 0))
            buf = ""
        elif ch in CLAUSE_END and len(buf) >= 8:
            seg = buf.strip()
            if seg:
                parts.append((seg, 1))
            buf = ""
    if buf.strip():
        parts.append((buf.strip(), 0))

    # 过长的句子再硬切
    out: list[tuple[str, int]] = []
    for seg, kind in parts:
        while len(seg) > max_len * 2:
            out.append((seg[:max_len], 1))
            seg = seg[max_len:]
        if seg:
            out.append((seg, kind))
    # 太短的跟前一句合并，避免"嗯。"这种碎片
    merged: list[tuple[str, int]] = []
    for seg, kind in out:
        if merged and len(seg) <= 3 and len(merged[-1][0]) < max_len:
            merged[-1] = (merged[-1][0] + seg, kind)
        else:
            merged.append((seg, kind))
    return merged


# ---------------- 韵律层 ----------------
# edge-tts 只有 rate/pitch/volume 三个旋钮，没有 style/emotion 参数。
# 所以"感情"只能靠**一句话内部**的韵律曲线挤出来：
#   · 越往后越慢（收尾感），越靠前稍快（急切开口）
#   · 感叹句整体提音高、加速；问句末段上扬
#   · 省略号/破折号处拖长、压低
# 让每个"气息单元"带自己的参数，而不是整句一刀切——这是旧版听着像念稿的主因。

UNIT_MARKS = {
    "。": "period",
    "．": "period",
    ".": "period",
    "！": "excl",
    "!": "excl",
    "？": "quest",
    "?": "quest",
    "…": "ellipsis",
    "—": "dash",
    "~": "wave",
    "～": "wave",
    "，": "comma",
    ",": "comma",
    "、": "comma",
    "：": "colon",
    ":": "colon",
    "；": "colon",
    ";": "colon",
}
STRONG_MARKS = {"period", "excl", "quest", "ellipsis", "dash"}
SOFT_MARKS = {"comma", "colon", "wave"}


def split_units(text: str, max_len: int = 12) -> list[dict]:
    """切成"气息单元"，每单元带标点类型。比 split_sentences 更细。"""
    text = (text or "").strip()
    if not text:
        return []
    units: list[dict] = []
    buf = ""
    for ch in text:
        if ch in UNIT_MARKS:
            seg = buf.strip()
            buf = ""
            if seg:
                units.append({"text": seg, "punc": UNIT_MARKS[ch]})
            elif units:
                # 连续标点（如"？！"）合并到前一个单元，取更强的那个
                prev = units[-1]
                if UNIT_MARKS[ch] in STRONG_MARKS and prev["punc"] not in STRONG_MARKS:
                    prev["punc"] = UNIT_MARKS[ch]
            continue
        buf += ch
    if buf.strip():
        units.append({"text": buf.strip(), "punc": "none"})

    # 过长单元硬切
    out: list[dict] = []
    for u in units:
        t, p = u["text"], u["punc"]
        while len(t) > max_len:
            out.append({"text": t[:max_len], "punc": "comma"})
            t = t[max_len:]
        if t:
            out.append({"text": t, "punc": p})
    # 极短碎片（"嗯""啊"）并入前一个，避免单字孤岛
    merged: list[dict] = []
    for u in out:
        if merged and len(u["text"]) <= 2 and merged[-1]["punc"] not in STRONG_MARKS:
            merged[-1]["text"] += u["text"]
            merged[-1]["punc"] = u["punc"]
        else:
            merged.append(u)
    return merged


def build_plan(units: list[dict], preset: dict, mood_key: str) -> list[dict]:
    """给每个单元算 rate/pitch 增量与停顿，构成一句话内部的起伏曲线。"""
    n = len(units)
    if not n:
        return []
    base_rate = preset["rate"]
    base_pitch = preset["pitch"]

    # 情绪决定"起伏幅度"：生气/开心起伏大，认真/犯懒平稳
    swing = {
        "cheerful": 1.15,
        "angry": 1.25,
        "smug": 0.95,
        "sad": 1.0,
        "serious": 0.6,
        "lazy": 0.55,
    }.get(mood_key, 0.85)

    plan: list[dict] = []
    for i, u in enumerate(units):
        punc = u["punc"]
        rate = base_rate
        pitch = base_pitch

        # pitch 现在以 Hz 计，增幅同步放大（原来 +2/+3/+4 是"半音感"的误用）
        if punc == "excl":
            pitch += round(8 * swing)
        elif punc == "quest":
            pitch += round(12 * swing)
        elif punc == "ellipsis":
            rate -= round(2 * swing)
            pitch -= round(6 * swing)
        elif punc == "dash":
            rate -= round(4 * swing)
            pitch -= round(14 * swing)
        elif punc == "wave":
            rate -= 3
            pitch += 14
        elif punc == "comma":
            pitch += 5

        # 停顿统一走 GAP_BY_PUNCT + GAP_MOOD_SCALE，避免 build_plan 和 _gaps_for
        # 两套毫秒表并存（改一处不生效，是旧版排查最久的一个坑）。
        tail = u["text"].rstrip()[-1:] if u["text"].strip() else ""
        base = GAP_BY_PUNCT.get(tail) or GAP_BY_PUNCT.get(
            {"period": "。", "excl": "！", "quest": "？", "colon": "；"}.get(punc, "，")
        )
        gap = max(50, int(base * GAP_MOOD_SCALE.get(mood_key, 1.0)))

        plan.append(
            {"text": u["text"], "punc": punc, "rate": rate, "pitch": pitch, "gap": gap}
        )
    return plan


def _safe_name(text: str, mood: str) -> str:
    h = hashlib.sha1(f"{text}|{mood}".encode()).hexdigest()[:10]
    return f"fish_{time.strftime('%Y%m%d_%H%M%S')}_{mood}_{h}"


async def _synth_one(
    text: str, rate: int, pitch: int, idx: int, workdir: Path
) -> Path | None:
    """使用固定音色和语速合成整句，避免随机变调。"""
    import edge_tts

    cfg = load_voice_config()
    rate += int(cfg.get("edge_rate_percent", -6))
    pitch += int(cfg.get("edge_pitch_hz", 0))
    rate = max(-50, min(50, rate))
    pitch = max(-80, min(80, pitch))  # edge-tts 的 pitch 是 Hz，超范围会被拒
    out = workdir / f"{idx:03d}.mp3"
    try:
        comm = edge_tts.Communicate(
            text,
            str(cfg.get("edge_voice", VOICE_DEFAULT)),
            rate=f"{rate:+d}%",
            pitch=f"{pitch:+d}Hz",
            volume="+0%",
        )
        await comm.save(str(out))
        if out.exists() and out.stat().st_size > 500:
            return out
    except Exception:
        return None
    return None


def _to_wav(ff: str, src: Path, dst: Path) -> bool:
    try:
        subprocess.run(
            [
                ff,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(dst),
            ],
            check=True,
            timeout=60,
            capture_output=True,
        )
        return dst.exists()
    except Exception:
        return False


def _concat_wavs(wavs: list[Path], gaps: list[int], out: Path) -> bool:
    """纯 stdlib 拼接 wav，句间插静音。"""
    try:
        params = None
        frames: list[bytes] = []
        for i, w in enumerate(wavs):
            with wave.open(str(w), "rb") as f:
                if params is None:
                    params = f.getparams()
                frames.append(f.readframes(f.getnframes()))
            gap_ms = gaps[i] if i < len(gaps) else 150
            if gap_ms > 0 and params:
                silence = b"\x00" * int(
                    params.framerate
                    * params.sampwidth
                    * params.nchannels
                    * gap_ms
                    / 1000
                )
                frames.append(silence)
        if not params:
            return False
        with wave.open(str(out), "wb") as f:
            f.setnchannels(params.nchannels)
            f.setsampwidth(params.sampwidth)
            f.setframerate(params.framerate)
            for chunk in frames:
                f.writeframes(chunk)
        return out.exists()
    except Exception:
        return False


def _post_process(ff: str, src: Path, dst: Path, formant: float, bright: int) -> bool:
    """轻微去尖、限制峰值，保留自然响度与原始音色。"""
    filters = [
        "highpass=f=70",
        "lowpass=f=9500",
        f"equalizer=f=4200:width_type=q:width=1:g={min(0, bright)}",
        "acompressor=threshold=0.12:ratio=1.25:attack=15:release=160:knee=2.5",
        "alimiter=limit=0.93",
    ]
    try:
        subprocess.run(
            [
                ff,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-af",
                ",".join(filters),
                "-b:a",
                "96k",
                str(dst),
            ],
            check=True,
            timeout=90,
            capture_output=True,
        )
        return dst.exists() and dst.stat().st_size > 1000
    except Exception:
        return False


def _wav_f0_median(path: Path) -> float | None:
    """估计一段语音的基频中位数，只用于音高校准。

    采用与本地语音服务 /admin/analyze 完全一致的算法（FFT 自相关 + 0.55 周期性门槛），
    保证"参考音多高、合成音多高"两边用同一把尺子，避免口径不同把校准推过头。
    """
    try:
        import numpy as np

        with wave.open(str(path), "rb") as stream:
            rate = stream.getframerate()
            channels = stream.getnchannels()
            width = stream.getsampwidth()
            frames = stream.readframes(stream.getnframes())
        if width != 2 or not frames:
            return None
        signal = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            signal = signal.reshape(-1, channels).mean(axis=1)
        stride = max(1, rate // 16000)
        signal = signal[::stride]
        rate = rate // stride
        pitches = []
        for offset in range(0, max(0, len(signal) - 1024), 320):
            frame = signal[offset : offset + 1024]
            frame = (frame - frame.mean()) * np.hanning(len(frame))
            if float(np.sqrt(np.mean(frame * frame))) < 0.003:
                continue
            spectrum = np.fft.rfft(frame, 2048)
            corr = np.fft.irfft(spectrum * np.conj(spectrum))[:1024]
            low = max(1, int(rate / 600))
            high = min(1023, int(rate / 70))
            if high <= low:
                continue
            lag = low + int(np.argmax(corr[low:high]))
            if corr[lag] / (corr[0] + 1e-12) > 0.55:
                pitches.append(rate / lag)
        return float(np.median(pitches)) if pitches else None
    except Exception:
        return None


def _pitch_shift_wav(ff: str, src: Path, dst: Path, ratio: float, rate: int = 24000) -> bool:
    """整体变调且时长不变：音高与共振峰一起移动，等同原素材被变调的效果。"""
    try:
        subprocess.run(
            [
                ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                "-af",
                f"asetrate={int(round(rate * ratio))},aresample={rate},atempo={1 / ratio:.6f}",
                "-c:a", "pcm_s16le", str(dst),
            ],
            check=True, timeout=60, capture_output=True,
        )
        return dst.exists() and dst.stat().st_size > 1000
    except Exception:
        return False


def _pitch_match(ff: str | None, wavs: list[Path], cfg: dict, work: Path) -> list[Path]:
    """把每句的基频对齐到参考音，避免长句越说越低。

    只移动整体音高，句内的起伏保留；参考音本身是被调高的可爱音，
    所以这里用"共振峰同步"的变调方式，而不是只抬基频。
    单句最多调整 ±4 个半音，超过就不动，避免把正常句子改坏。
    """
    target = float(cfg.get("cosy_target_f0", 0) or 0)
    if not ff or not cfg.get("cosy_pitch_match") or target <= 0:
        return wavs
    result: list[Path] = []
    for index, wav in enumerate(wavs):
        measured = _wav_f0_median(wav)
        if not measured:
            result.append(wav)
            continue
        ratio = max(0.79, min(1.26, target / measured))
        if abs(ratio - 1.0) < 0.03:
            result.append(wav)
            continue
        shifted = work / f"{index:02d}_pitch.wav"
        result.append(shifted if _pitch_shift_wav(ff, wav, shifted, ratio) else wav)
    return result


def _cosy_post(
    ff: str, src: Path, dst: Path, preset: dict, cfg: dict | None = None
) -> bool:
    """本地情感模型仅做轻微舒缓和去尖，不叠加混响。

    `cosy_air_db`：参考音如果本身偏闷（抖音鱼眼效果会把 3kHz 以上砍掉一大截），
    克隆出来的声音也会闷。给一个可选的高频补偿，默认 0 = 完全照搬参考音。
    """
    cfg = cfg or {}
    air = float(cfg.get("cosy_air_db", 0) or 0)
    tempo = max(0.85, min(1.0, float(cfg.get("cosy_tempo", 0.98))))
    if cfg.get("cosy_preserve_dynamics") and tempo == 1.0:
        shutil.copyfile(src, dst)
        return dst.exists() and dst.stat().st_size > 1000
    filters = ["highpass=f=80", f"atempo={tempo:.3f}"]
    if air:
        filters.append(f"highshelf=f=3200:g={air:.1f}:width_type=q:width=0.7")
    filters += [
        f"equalizer=f=4200:width_type=q:width=1:g={min(0, preset.get('bright', -1))}",
        "acompressor=threshold=0.12:ratio=1.25:attack=15:release=160:knee=2.5",
        "alimiter=limit=0.97",
    ]
    if cfg.get("cosy_preserve_dynamics"):
        # 试听保留模型本身的音色和音量起伏，只在用户选择时调整速度。
        filters = [f"atempo={tempo:.3f}"]
    try:
        subprocess.run(
            [
                ff,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-af",
                ",".join(filters),
                str(dst),
            ],
            check=True,
            timeout=90,
            capture_output=True,
        )
        return dst.exists() and dst.stat().st_size > 1000
    except Exception:
        return False


async def synth(
    text: str, mood: str = "normal", *, ext: str = "mp3", backend: str | None = None
) -> Path:
    """合成语音，返回音频路径。

    未指定后端时读取配置；仅限指定原声时，合成失败直接返回失败。
    指定原声保护同样约束显式指定的后端，禁止通过自检参数换成其他音色。
    """
    global LAST_SYNTH_BACKEND
    spoken = clean_text(text)
    if not spoken:
        raise ValueError("没有可朗读的内容（清理后为空）")

    mood_key = mood if mood in MOODS else "normal"
    reset_meta()
    LAST_SYNTH_BACKEND = ""
    LAST_SYNTH_META["mood"] = mood_key

    # 优先本地 CosyVoice2（有真情感），失败再走 edge-tts 流程
    cfg = load_voice_config()
    use = (backend or str(cfg.get("backend", ""))).lower()
    if cfg.get("reference_only") and use != "cosy":
        raise RuntimeError("仅允许用户指定视频原声，不能切换为其他音色")
    if use == "cosy":
        if await cosy_available(cfg):
            p = await cosy_synth(spoken, mood_key, cfg)
            if p:
                LAST_SYNTH_BACKEND = "cosy"
                LAST_SYNTH_META.update(
                    backend_actual="cosy",
                    voice_id=str(LAST_SYNTH_META.get("ref") or "cosy"),
                    fallback="",
                    fallback_reason="",
                )
                return p
            _cosy_reason_local = "synth_failed"
        else:
            _cosy_reason_local = _cosy_reason or "unavailable"
        if (
            backend == "cosy"
            or cfg.get("reference_only")
            or cfg.get("fallback") == "none"
        ):
            LAST_SYNTH_META.update(fallback="", fallback_reason=_cosy_reason_local)
            raise RuntimeError("指定原声合成失败，本次不切换其他音色")
        LAST_SYNTH_META.update(fallback="edge", fallback_reason=_cosy_reason_local)
        print(f"[tts] CosyVoice 不可用（{_cosy_reason_local}），回退 edge-tts")

    preset = MOODS[mood_key]
    ff = ffmpeg_path()

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(spoken, mood_key)
    final_mp3 = AUDIO_DIR / f"{stem}.mp3"

    # 复活气息单元切分：旧版把整段当一个 unit，导致 GAP 逻辑永远走不到
    # （`gap` 只在 len(wavs) > 1 时生效），七档情绪被压平成同一个语调。
    units = split_units(spoken, 14)
    if not units:
        raise ValueError("切句后为空")
    plan = build_plan(units, preset, mood_key)

    workdir = WORK_DIR / stem
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        mp3s = []
        for i, u in enumerate(plan):
            p = await _synth_one(u["text"], u["rate"], u["pitch"], i, workdir)
            if p:
                mp3s.append(p)
        if not mp3s:
            raise RuntimeError(
                "TTS 生成失败：所有句子都合成失败（网络或 edge-tts 异常）"
            )
        LAST_SYNTH_BACKEND = "edge"
        LAST_SYNTH_META.update(
            backend_actual="edge",
            voice_id=str(cfg.get("edge_voice", VOICE_DEFAULT)),
            chunks=len(mp3s),
        )

        # 没有音频转换器时保留合成器的原始音频
        if not ff:
            shutil.copy(mp3s[0], final_mp3)
            return (
                final_mp3
                if ext == "mp3"
                else _as_ext(ff, final_mp3, AUDIO_DIR / f"{stem}.wav", "wav")
            )

        wavs = []
        for i, p in enumerate(mp3s):
            w = workdir / f"{i:03d}.wav"
            if await asyncio.to_thread(_to_wav, ff, p, w):
                wavs.append(w)
        if not wavs:
            shutil.copy(mp3s[0], final_mp3)
            return final_mp3

        gaps = [plan[i]["gap"] for i in range(min(len(wavs), len(plan)))]

        if len(wavs) == 1:
            joined = wavs[0]  # 单单元也要过后处理，保持音色一致
        else:
            joined = workdir / "joined.wav"
            if not _concat_wavs(wavs, gaps, joined):
                shutil.copy(mp3s[0], final_mp3)
                return final_mp3

        processed = workdir / "post.wav"
        if not await asyncio.to_thread(
            _post_process, ff, joined, processed, preset["formant"], preset["bright"]
        ):
            processed = joined

        # 转换音频时让出事件循环，避免阻塞聊天消息。
        try:
            await asyncio.to_thread(
                subprocess.run,
                [
                    ff,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(processed),
                    "-b:a",
                    "96k",
                    str(final_mp3),
                ],
                check=True,
                timeout=90,
                capture_output=True,
            )
        except Exception:
            shutil.copy(mp3s[0], final_mp3)

        if not final_mp3.exists() or final_mp3.stat().st_size < 1000:
            raise RuntimeError("TTS 生成失败：最终音频为空")

        if ext == "wav":
            return _as_ext(ff, final_mp3, AUDIO_DIR / f"{stem}.wav", "wav")
        return final_mp3
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _as_ext(ff: str | None, mp3: Path, dst: Path, ext: str) -> Path:
    if not ff:
        return mp3
    try:
        subprocess.run(
            [
                ff,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(mp3),
                "-ar",
                "24000",
                "-ac",
                "1",
                str(dst),
            ],
            check=True,
            timeout=60,
            capture_output=True,
        )
        return dst if dst.exists() else mp3
    except Exception:
        return mp3


def gc(max_age_hours: int = 48, max_total_mb: int = 120) -> dict:
    if not AUDIO_DIR.exists():
        return {"removed": 0, "kept": 0}
    now = time.time()
    files = sorted(
        [
            p
            for p in AUDIO_DIR.iterdir()
            if p.is_file()
            and not p.name.startswith("试听_")
            and p.suffix.lower() in (".mp3", ".wav", ".silk")
        ],
        key=lambda p: p.stat().st_mtime,
    )
    removed = 0
    for p in list(files):
        if now - p.stat().st_mtime > max_age_hours * 3600:
            try:
                p.unlink()
                removed += 1
                files.remove(p)
            except Exception:
                pass
    total = sum(p.stat().st_size for p in files)
    limit = max_total_mb * 1024 * 1024
    while files and total > limit:
        p = files.pop(0)
        try:
            total -= p.stat().st_size
            p.unlink()
            removed += 1
        except Exception:
            pass
    # 清掉残留工作目录
    if WORK_DIR.exists():
        for d in WORK_DIR.iterdir():
            if d.is_dir() and now - d.stat().st_mtime > 3600:
                shutil.rmtree(d, ignore_errors=True)
    return {"removed": removed, "kept": len(files)}


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    text = args[0] if args else "老爸，你真是个人才！"
    mood = args[1] if len(args) > 1 else "normal"
    p = asyncio.run(synth(text, mood))
    with wave.open(str(p)) if False else open(os.devnull):
        pass
    print(f"OK {p} ({p.stat().st_size} bytes)")