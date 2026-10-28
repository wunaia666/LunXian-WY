"""仅在本机提供语音识别和图片生成，不调用付费媒体接口。"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import subprocess
import tempfile
import threading
import time
import uuid
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(r"E:\sss_test")
CONFIG = json.loads(
    (BASE / "dafeiyu_assets/local_media_config.json").read_text(encoding="utf-8")
)
ASR_LOCK = threading.Lock()
IMAGE_LOCK = threading.Lock()
ASR_MODEL = None
LOGGER = logging.getLogger(__name__)
FFMPEG = Path(
    r"E:\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin"
)
os.environ["PATH"] = str(FFMPEG) + os.pathsep + os.environ.get("PATH", "")


class Handler(BaseHTTPRequestHandler):
    """只接受持有本机令牌的媒体请求。"""

    def log_message(self, *args):
        # 不将上传内容、访问令牌或完整请求写入日志。
        pass

    def reply(self, status: int, data: dict):
        """返回一个有长度限制的结构化结果。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """健康检查只报告模型是否就绪。"""
        if self.path != "/health":
            return self.reply(404, {"error": "接口不存在"})
        self.reply(
            200,
            {
                "service": "dafeiyu-local-media",
                "ok": True,
                "asr_ready": (BASE / "models/whisper/base.pt").exists(),
                "image_ready": all(
                    (BASE / "models/sd-turbo" / name).is_file()
                    for name in (
                        "unet/diffusion_pytorch_model.fp16.safetensors",
                        "text_encoder/model.fp16.safetensors",
                        "vae/diffusion_pytorch_model.fp16.safetensors",
                    )
                ),
                "image_busy": IMAGE_LOCK.locked(),
                "asr_busy": ASR_LOCK.locked(),
            },
        )

    def do_POST(self):
        """识别上传音频，或启动一个受限的绘图任务。"""
        global ASR_MODEL
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + CONFIG["token"]):
            return self.reply(401, {"error": "本机访问凭据无效"})
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 128 * 1024 * 1024:
            return self.reply(413, {"error": "上传大小不符合限制"})
        body = self.rfile.read(size)
        if self.path == "/v1/audio/transcriptions":
            # 本地模型串行推理；短时间排队，避免视频转写和语音条同时到达时直接失败。
            if not ASR_LOCK.acquire(timeout=45):
                return self.reply(429, {"error": "本地识别正在处理另一段音频"})
            audio_path = None
            try:
                import torch
                import whisper

                message = BytesParser(policy=policy.default).parsebytes(
                    (
                        "Content-Type: "
                        + self.headers.get("Content-Type", "")
                        + "\r\nMIME-Version: 1.0\r\n\r\n"
                    ).encode()
                    + body
                )
                upload = next(
                    (
                        x.get_payload(decode=True)
                        for x in message.iter_parts()
                        if x.get_param("name", header="content-disposition") == "file"
                    ),
                    None,
                )
                if not upload:
                    return self.reply(400, {"error": "未收到音频文件"})
                with tempfile.NamedTemporaryFile(
                    suffix=".audio", delete=False, dir=BASE / "tmp"
                ) as temp:
                    temp.write(upload)
                    audio_path = Path(temp.name)
                if ASR_MODEL is None:
                    torch.set_num_threads(4)
                    ASR_MODEL = whisper.load_model(
                        str(BASE / "models/whisper/base.pt"), device="cpu"
                    )
                result = ASR_MODEL.transcribe(
                    str(audio_path),
                    language="zh",
                    fp16=False,
                    condition_on_previous_text=False,
                    initial_prompt="以下是简体中文日常聊天。",
                    verbose=False,
                )
                text = str(result.get("text", "")).strip()
                self.reply(200, {"text": text, "language": "zh"})
            except Exception as exc:
                LOGGER.exception("本地语音识别未完成")
                self.reply(
                    500, {"error": "本地语音识别未完成", "kind": type(exc).__name__}
                )
            finally:
                if audio_path is not None:
                    audio_path.unlink(missing_ok=True)
                ASR_LOCK.release()
            return
        if self.path == "/generate":
            if not IMAGE_LOCK.acquire(blocking=False):
                return self.reply(429, {"error": "本地绘图正在处理另一张图片"})
            try:
                task = json.loads(body)
                prompt = str(task.get("prompt", "")).strip()
                if not prompt or len(prompt) > 1200:
                    return self.reply(400, {"error": "绘画描述为空或太长"})
                image = (
                    BASE
                    / "dafeiyu_assets/generated"
                    / f"fish_{uuid.uuid4().hex[:16]}.png"
                )
                payload = {
                    "prompt": prompt,
                    "output": str(image),
                    "seed": secrets.randbelow(2**31),
                }
                if task.get("reference_path"):
                    reference = Path(task["reference_path"]).resolve()
                    if (
                        not reference.is_relative_to(
                            (BASE / "dafeiyu_assets/generated/references").resolve()
                        )
                        or not reference.is_file()
                        or reference.stat().st_size > 12 * 1024 * 1024
                    ):
                        return self.reply(400, {"error": "参考图不在已接收图片目录"})
                    strength = float(task.get("strength", 0.45))
                    if not 0.25 <= strength <= 0.8:
                        return self.reply(400, {"error": "参考图变化程度超出范围"})
                    payload.update(reference_path=str(reference), strength=strength)
                started = time.time()
                with (BASE / "tmp/local_image_worker.log").open(
                    "a", encoding="utf-8"
                ) as log:
                    result = subprocess.run(
                        [
                            r"E:\ComfyUI\python_embeded\python.exe",
                            "-X",
                            "utf8",
                            str(BASE / "tools/local_image_worker.py"),
                        ],
                        check=False,
                        input=json.dumps(payload, ensure_ascii=False),
                        text=True,
                        encoding="utf-8",
                        stdout=log,
                        stderr=log,
                        timeout=300,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                if (
                    result.returncode != 0
                    or not image.exists()
                    or image.stat().st_size < 1000
                ):
                    raise RuntimeError("绘图进程未生成有效图片")
                self.reply(
                    200,
                    {
                        "ok": True,
                        "mode": "image_to_image"
                        if payload.get("reference_path")
                        else "text_to_image",
                        "path": str(image),
                        "seconds": round(time.time() - started, 1),
                    },
                )
            except Exception as exc:
                LOGGER.exception("本地绘图未完成")
                self.reply(500, {"error": "本地绘图未完成", "kind": type(exc).__name__})
            finally:
                IMAGE_LOCK.release()
            return
        self.reply(404, {"error": "接口不存在"})


if __name__ == "__main__":
    (BASE / "tmp").mkdir(parents=True, exist_ok=True)
    print("本地媒体服务已启动，仅监听本机。", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 9890), Handler).serve_forever()
