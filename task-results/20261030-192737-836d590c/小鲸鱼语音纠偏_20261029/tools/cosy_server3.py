#!/usr/bin/env python3
"""CosyVoice3 本地语音服务（WSL 内运行）。

只提供日常语音需要的功能：健康检查、分段语气合成、参考音热切换、声纹诊断。
与二代服务（cosy_server.py）保持同一套 HTTP 约定，便于日常链路无缝切换与回退。

接口：
  GET  /health          -> {"ok","ready","phase","engine","prompt",...}
  POST /tts             -> {"text","instruct","speed","seed"} 返回 wav 二进制
                           响应头带 X-Synth-Ms / X-Chunks / X-Ref / X-Engine / X-Mode
  POST /admin/reload    -> {"wav"}  热换参考音
  POST /admin/analyze   -> {"files":[...]}  返回声纹与基频诊断
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("OMP_NUM_THREADS", "6")

HOME = os.path.expanduser("~")
REPO = os.environ.get("COSY_REPO", os.path.join(HOME, "CosyVoice"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "third_party", "Matcha-TTS"))

MODEL_DIR = os.environ.get("COSY_MODEL", os.path.join(HOME, "models", "Fun-CosyVoice3-0.5B-2512"))
CONFIG_PATH = "/mnt/e/sss_test/dafeiyu_assets/voice_config.json"
PROMPT_WAV = os.environ.get(
    "COSY_PROMPT", "/mnt/e/sss_test/dafeiyu_assets/audio/_cosy_ref/ref_douyin_link_7689724715246372473.wav"
)
PORT = int(os.environ.get("COSY_PORT", "9880"))
DEFAULT_SPEED = float(os.environ.get("COSY_SPEED", "1.0"))
WARMUP = os.environ.get("COSY_WARMUP", "1") == "1"
CHUNK_TIMEOUT = float(os.environ.get("COSY_CHUNK_TIMEOUT", "120"))
TOTAL_TIMEOUT = float(os.environ.get("COSY_TOTAL_TIMEOUT", "240"))
CHUNK_MAX_CHARS = int(os.environ.get("COSY_CHUNK_MAX", "22"))
CHUNK_MIN_CHARS = int(os.environ.get("COSY_CHUNK_MIN", "6"))
TORCH_THREADS = int(os.environ.get("COSY_THREADS", "6"))
POISON_EXIT_SEC = float(os.environ.get("COSY_POISON_EXIT", "0"))

SPK_ID = "dafeiyu"
GAP_BY_PUNCT = {"。": 0.30, "！": 0.24, "？": 0.26, "；": 0.24, "，": 0.16, "、": 0.12, "：": 0.17}
INSTRUCT_PREFIX = "You are a helpful assistant. "

STATE = {
    "phase": "loading",
    "ready": False,
    "t0": time.time(),
    "load_s": 0.0,
    "warmup_s": 0.0,
    "prompt": PROMPT_WAV,
    "inflight": 0,
    "last_synth_ms": 0,
    "total": 0,
    "errors": 0,
    "warning": "",
    "poisoned_at": 0.0,
    "engine": "cosyvoice3",
    "model": MODEL_DIR,
}
STATE_LOCK = threading.Lock()
_lock = threading.Lock()


def log(*a):
    print(*a, flush=True)


import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from cosyvoice.cli.cosyvoice import CosyVoice3  # noqa: E402

torch.set_num_threads(TORCH_THREADS)
try:
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.set_float32_matmul_precision("high")
except Exception:  # noqa: BLE001
    pass


def vram() -> tuple[int, int]:
    try:
        free, total = torch.cuda.mem_get_info()
        return int((total - free) / 1048576), int(free / 1048576)
    except Exception:  # noqa: BLE001
        return 0, 0


log(f"[cosy3] loading {MODEL_DIR} ...")
_t_load = time.time()
try:
    cosy = CosyVoice3(MODEL_DIR, fp16=True)
except TypeError:
    cosy = CosyVoice3(MODEL_DIR)
if torch.cuda.is_available():
    cosy.model.llm.half()
    cosy.model.flow.half()
    torch.cuda.empty_cache()
SR = cosy.sample_rate
_t_weights = time.time() - _t_load
_used, _free = vram()
log(f"[cosy3] weights loaded in {_t_weights:.1f}s sr={SR} vram={_used}MB free={_free}MB")


def split_chunks(text: str, max_chars: int = CHUNK_MAX_CHARS, min_chars: int = CHUNK_MIN_CHARS):
    """按语气标点切块，块长 [min_chars, max_chars]。"""
    text = re.sub(r"[…\.]{2,}", "，", text)
    text = re.sub(r"[，,]{2,}", "，", text).strip("，。 ")
    if not text:
        return []
    parts = re.findall(r"[^。！？；!?;\n]+[。！？；!?;]?", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        while len(p) > max_chars:
            cut = -1
            for i in range(max_chars, min_chars, -1):
                if p[i - 1] in "，、：,:":
                    cut = i
                    break
            if cut < 0:
                cut = max_chars
            out.append(p[:cut].strip("，、：,:"))
            p = p[cut:].strip("，、：,:")
        if p:
            out.append(p)
    merged: list[str] = []
    for p in out:
        if merged and len(p) < min_chars and len(merged[-1]) + len(p) <= max_chars:
            merged[-1] += p
        else:
            merged.append(p)
    if len(merged) > 1 and len(merged[0]) < min_chars and len(merged[0]) + len(merged[1]) <= max_chars:
        merged[1] = merged[0] + merged[1]
        merged.pop(0)
    return merged


def gap_for(chunk: str) -> float:
    tail = chunk[-1] if chunk else "。"
    return GAP_BY_PUNCT.get(tail, 0.18)


def _synth_one(chunk: str, instruct: str, speed: float) -> tuple[np.ndarray, float]:
    box: dict = {}

    def _run():
        try:
            prompt = instruct if instruct.startswith(INSTRUCT_PREFIX) else INSTRUCT_PREFIX + instruct
            if not prompt.endswith("<|endofprompt|>"):
                if prompt.endswith("。"):
                    prompt += "<|endofprompt|>"
                else:
                    prompt += "。<|endofprompt|>"
            pieces = []
            for out in cosy.inference_instruct2(chunk, prompt, PROMPT_WAV, stream=False, speed=speed):
                pieces.append(out["tts_speech"])
            if not pieces:
                raise RuntimeError("no audio chunks")
            box["wav"] = torch.cat(pieces, dim=1).squeeze(0).detach().float().cpu().numpy()
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=_run, daemon=True)
    t0 = time.time()
    th.start()
    th.join(CHUNK_TIMEOUT)
    if th.is_alive():
        with STATE_LOCK:
            STATE["poisoned_at"] = STATE["poisoned_at"] or time.time()
        raise TimeoutError(f"chunk 超 {CHUNK_TIMEOUT:.0f}s 未结束（text={chunk[:16]}）")
    if "err" in box:
        raise box["err"]
    return box["wav"], time.time() - t0


def synth(text: str, instruct: str, speed: float | None = None, seed=None) -> tuple[bytes, dict]:
    speed = DEFAULT_SPEED if speed is None else max(0.9, min(1.1, float(speed)))
    instruct = (instruct or "用平常聊天一样自然的语气说这句话").strip()
    chunks = split_chunks(text)
    if not chunks:
        raise ValueError("empty text after split")

    t0 = time.time()
    pieces, fails = [], []
    with _lock:
        if seed is not None:
            seed = int(seed) % 2147483647
            random.seed(seed)
            torch.manual_seed(seed)
            np.random.seed(seed)
        with STATE_LOCK:
            STATE["inflight"] = 1
        for i, c in enumerate(chunks):
            if time.time() - t0 > TOTAL_TIMEOUT:
                fails.append(f"total_timeout@{i}")
                break
            try:
                wav, cost = _synth_one(c, instruct, speed)
                pieces.append(wav)
                log(f"[cosy3] chunk {i+1}/{len(chunks)} {len(c)}ch {cost:.1f}s")
            except TimeoutError as e:
                fails.append(f"{i}:timeout")
                log(f"[cosy3] chunk {i+1}/{len(chunks)} TIMEOUT: {e}")
                break
            except Exception as e:  # noqa: BLE001
                fails.append(f"{i}:{type(e).__name__}")
                log(f"[cosy3] chunk {i+1}/{len(chunks)} FAIL {type(e).__name__}: {e}")
        with STATE_LOCK:
            STATE["inflight"] = 0
            STATE["last_synth_ms"] = int((time.time() - t0) * 1000)
            STATE["total"] += 1
            STATE["errors"] += len(fails)

    if not pieces:
        raise RuntimeError("全部块合成失败：" + ",".join(fails))

    seq = []
    for i, w in enumerate(pieces):
        seq.append(w)
        if i < len(pieces) - 1:
            seq.append(np.zeros(int(SR * gap_for(chunks[i])), dtype=w.dtype))
    final = np.concatenate(seq) if len(seq) > 1 else pieces[0]
    peak = float(np.max(np.abs(final)) + 1e-9)
    if peak > 0.99:
        final = final / peak * 0.97
    buf = io.BytesIO()
    sf.write(buf, final, SR, format="WAV", subtype="PCM_16")
    meta = {"chunks": len(pieces), "synth_ms": int((time.time() - t0) * 1000),
            "dur_s": round(float(len(final)) / SR, 2), "ref": os.path.basename(PROMPT_WAV),
            "fails": fails, "mode": "instruct2", "seed": seed}
    return buf.getvalue(), meta


def _warmup():
    with STATE_LOCK:
        STATE["phase"] = "warming"
    t = time.time()
    try:
        synth("我在呢，叫我干嘛呀？", "用自然轻松的语气说")
        with STATE_LOCK:
            STATE["warmup_s"] = round(time.time() - t, 1)
            STATE["phase"] = "ready"
            STATE["ready"] = True
        log(f"[cosy3] warmup done in {time.time() - t:.1f}s")
    except Exception as e:  # noqa: BLE001
        with STATE_LOCK:
            STATE["phase"] = "degraded"
            STATE["ready"] = False
            STATE["warning"] = f"warmup 失败：{type(e).__name__}"
        log(f"[cosy3] warmup 失败: {type(e).__name__}: {e}")


def _watchdog():
    while True:
        time.sleep(10)
        with STATE_LOCK:
            pa = STATE["poisoned_at"]
        if pa and POISON_EXIT_SEC > 0 and time.time() - pa > POISON_EXIT_SEC:
            log("[cosy3] 推理卡死，退出交给 supervisor 重拉")
            sys.stdout.flush()
            os._exit(11)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            sv = str(v).encode("ascii", "replace").decode("ascii")
            self.send_header(k, sv)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict, extra: dict | None = None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def do_GET(self):
        if not self.path.startswith("/health"):
            self._send(404, b"not found", "text/plain")
            return
        used, free = vram()
        with STATE_LOCK:
            s = dict(STATE)
        s["worker_stuck"] = bool(s.get("poisoned_at"))
        s.update({"ok": True, "sr": SR, "model": MODEL_DIR, "vram_alloc_mb": used,
                  "vram_free_mb": free, "elapsed_s": round(time.time() - s["t0"], 1),
                  "load_s": round(_t_weights, 1)})
        s.pop("t0", None)
        s.pop("poisoned_at", None)
        self._json(200, s)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            self._json(400, {"ok": False, "error": "bad json"})
            return

        if self.path.startswith("/admin/reload"):
            global PROMPT_WAV
            wav = data.get("wav") or PROMPT_WAV
            try:
                if not os.path.exists(wav):
                    raise FileNotFoundError("参考音不存在")
                with _lock:
                    PROMPT_WAV = wav
                with STATE_LOCK:
                    STATE["prompt"] = wav
                log(f"[cosy3] prompt switched to {wav}")
                self._json(200, {"ok": True, "ref": wav})
            except Exception as e:  # noqa: BLE001
                self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            return

        if self.path.startswith("/admin/analyze"):
            try:
                records = []
                root = Path("/mnt/e/sss_test/dafeiyu_assets/audio").resolve()
                for name in (data.get("files") or [])[:12]:
                    path = Path(name).resolve()
                    if root not in path.parents or path.suffix.lower() != ".wav":
                        raise ValueError("只允许分析本程序音频目录中的波形文件")
                    with _lock:
                        embedding = cosy.frontend._extract_spk_embedding(str(path)).detach().float().cpu().numpy().reshape(-1)
                    signal, rate = sf.read(str(path), dtype="float32")
                    if signal.ndim > 1:
                        signal = signal.mean(axis=1)
                    stride = max(1, rate // 16000)
                    signal, rate = signal[::stride], rate // stride
                    pitches = []
                    for offset in range(0, max(0, len(signal) - 1024), 320):
                        frame = signal[offset:offset + 1024]
                        frame = (frame - frame.mean()) * np.hanning(len(frame))
                        if np.sqrt(np.mean(frame * frame)) < 0.003:
                            continue
                        spectrum = np.fft.rfft(frame, 2048)
                        corr = np.fft.irfft(spectrum * np.conj(spectrum))[:1024]
                        lo, hi = max(1, int(rate / 600)), min(1023, int(rate / 70))
                        lag = lo + int(np.argmax(corr[lo:hi]))
                        if corr[lag] / (corr[0] + 1e-12) > 0.55:
                            pitches.append(rate / lag)
                    records.append({"file": path.name, "duration_s": round(len(signal) / rate, 3),
                                    "f0_median_hz": round(float(np.median(pitches)), 1) if pitches else None,
                                    "embedding": [round(float(v), 7) for v in embedding]})
                self._json(200, {"ok": True, "records": records})
            except Exception as error:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(error)})
            return

        if not self.path.startswith("/tts"):
            self._send(404, b"not found", "text/plain")
            return

        with STATE_LOCK:
            ready = STATE["ready"]
            phase = STATE["phase"]
            poisoned = bool(STATE["poisoned_at"])
        if poisoned:
            self._json(503, {"ok": False, "error": "worker_stuck"}, {"Retry-After": "45"})
            return
        if not ready:
            self._json(503, {"ok": False, "error": f"not ready ({phase})"}, {"Retry-After": "15"})
            return

        text = (data.get("text") or "").strip()
        if not text:
            self._json(400, {"ok": False, "error": "empty text"})
            return
        instruct = (data.get("instruct") or "用平常聊天一样自然的语气说这句话").strip()
        try:
            wav, meta = synth(text, instruct, data.get("speed"), seed=data.get("seed"))
            log(f"[cosy3] ok {meta['chunks']}chunk {meta['dur_s']}s {meta['synth_ms']}ms text={len(text)}ch")
            self._send(200, wav, "audio/wav", {
                "X-Synth-Ms": meta["synth_ms"], "X-Chunks": meta["chunks"], "X-Ref": meta["ref"],
                "X-Engine": "cosyvoice3", "X-Dur-S": meta["dur_s"],
                "X-Fails": ",".join(meta["fails"]) or "-", "X-Mode": meta["mode"],
                "X-Seed": "random" if meta["seed"] is None else str(meta["seed"]),
            })
        except TimeoutError as e:
            log(f"[cosy3] 504 {e}")
            self._json(504, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"[cosy3] listening 0.0.0.0:{PORT} phase={STATE['phase']}")
    threading.Thread(target=_watchdog, daemon=True).start()
    if WARMUP:
        threading.Thread(target=_warmup, daemon=True).start()
    else:
        with STATE_LOCK:
            STATE["ready"] = True
            STATE["phase"] = "ready"
    srv.serve_forever()