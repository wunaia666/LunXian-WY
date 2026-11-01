"""以用户验收的原多萝训练配对和生日对白参数提供本机日常合成。"""

import array
import gc
import importlib.util
import io
import json
import os
import re
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xiaojingyu_voice_profile import approved_profile  # noqa: E402

STATE = {
    "phase": "loading",
    "ready": False,
    "engine": "gptsovits",
    "ok": False,
    "inflight": 0,
    "total": 0,
    "errors": 0,
}
LOCK = threading.Lock()
ENGINE = None
PROFILE = None


def split_text(text, maximum=80):
    """保持标点和全文，只有超过模型适用长度时才拆段。"""
    pieces = []
    buffer = ""
    for sentence in re.findall(
        r"[^。！？!?；;\n]+[。！？!?；;\n]*|[。！？!?；;\n]+", text
    ):
        if buffer and len(buffer) + len(sentence) > maximum:
            pieces.append(buffer)
            buffer = ""
        while len(sentence) > maximum:
            pieces.append(sentence[:maximum])
            sentence = sentence[maximum:]
        buffer += sentence
    if buffer:
        pieces.append(buffer)
    if "".join(pieces) != text or not pieces:
        raise ValueError("正文切分未完整保留")
    return pieces


def load_engine():
    global ENGINE, PROFILE
    try:
        profile = approved_profile(check_weights=True)
        engine_root = Path(profile["engine_root"])
        os.chdir(engine_root)
        os.environ.update(
            HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1"
        )
        sys.path[:0] = [str(engine_root), str(engine_root / "GPT_SoVITS")]
        import torch
        import yaml

        torch.set_num_threads(4)
        spec = importlib.util.spec_from_file_location(
            "approved_doro_portable", str(engine_root / "app.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        work = engine_root / "approved_runtime"
        work.mkdir(parents=True, exist_ok=True)
        configuration = yaml.safe_load(
            (engine_root / "GPT_SoVITS/configs/tts_infer.yaml").read_text(
                encoding="utf-8"
            )
        )
        custom = configuration["custom"]
        custom.update(
            t2s_weights_path=profile["gpt"]["path"],
            vits_weights_path=profile["sovits"]["path"],
            device="cuda",
            is_half=True,
        )
        for key in ("bert_base_path", "cnhuhbert_base_path"):
            custom[key] = str(engine_root / custom[key])
        config_path = work / "approved_doro.yaml"
        config_path.write_text(
            yaml.safe_dump(configuration, allow_unicode=True), encoding="utf-8"
        )
        module.CONFIG = str(config_path)
        module.OUT_DIR = str(work)
        module.REF_DIR = str(Path(profile["reference"]["path"]).parent)
        module.REF_PROMPTS = {
            Path(profile["reference"]["path"]).name: profile["prompt_text"]
        }
        module.log = lambda message: print(message, flush=True)
        engine = module.Engine()
        engine.load()
        if not engine.ready:
            raise RuntimeError("原训练模型加载失败：" + str(engine.error)[-700:])
        from process_ckpt import load_sovits_new

        verified = []
        for name, model, source in (
            ("gpt", engine.tts.t2s_model, profile["gpt"]),
            ("sovits", engine.tts.vits_model, profile["sovits"]),
        ):
            checkpoint = (
                torch.load(source["path"], map_location="cpu", weights_only=False)
                if name == "gpt"
                else load_sovits_new(source["path"])
            )
            count = 0
            for key, actual in model.state_dict().items():
                if key not in checkpoint["weight"] and key.startswith("enc_q."):
                    continue
                expected = checkpoint["weight"][key].to(dtype=actual.dtype)
                if actual.shape != expected.shape or not torch.equal(
                    actual.detach().cpu(), expected
                ):
                    raise RuntimeError("运行参数与原训练文件不一致：" + key)
                count += 1
            verified.append(count)
            del checkpoint, expected
            gc.collect()
        if verified != [295, 678]:
            raise RuntimeError("实际训练参数核对组数异常")
        original = engine.tts.run

        def frozen_run(inputs):
            inputs.update(profile["parameters"])
            if (
                Path(inputs["ref_audio_path"]).resolve()
                != Path(profile["reference"]["path"]).resolve()
                or inputs["prompt_text"] != profile["prompt_text"]
            ):
                raise ValueError("参考音或参考文字与已验收配置不符")
            yield from original(inputs)

        engine.tts.run = frozen_run
        ENGINE, PROFILE = engine, profile
        STATE.update(
            phase="ready",
            ready=True,
            ok=True,
            profile_id=profile["id"],
            prompt=profile["reference"]["path"],
            reference_sha=profile["reference"]["sha256"],
            accepted_sample_sha=profile["accepted_sample"]["sha256"],
            parameter_groups=verified,
            emotion_control_applied=False,
            warning="",
        )
    except Exception as error:
        STATE.update(phase="failed", ready=False, ok=False, warning=str(error)[-900:])
        print("声音服务加载未完成：" + str(error), flush=True)


def generate(text):
    """按验收参数合成全部正文；任何片段异常均拒绝返回残缺语音。"""
    chunks = split_text(text)
    pcm = []
    format_info = None
    for chunk in chunks:
        path, _, _ = ENGINE.synth(
            chunk, Path(PROFILE["reference"]["path"]).name, 1.0, 1.0, 15, seed=42
        )
        path = Path(path)
        try:
            with wave.open(str(path), "rb") as stream:
                actual_format = (
                    stream.getnchannels(),
                    stream.getsampwidth(),
                    stream.getframerate(),
                )
                frames = stream.readframes(stream.getnframes())
            samples = array.array("h", frames)
            if (
                actual_format[:2] != (1, 2)
                or not samples
                or max(abs(x) for x in samples) < 2
            ):
                raise RuntimeError("本段合成音频为空或格式异常")
            if sum(abs(x) >= 32760 for x in samples) / len(samples) > 0.005:
                raise RuntimeError("本段合成存在明显数字削顶")
            if format_info is not None and actual_format != format_info:
                raise RuntimeError("分段音频格式不一致")
            format_info = actual_format
            pcm.append(frames)
        finally:
            path.unlink(missing_ok=True)
    body = io.BytesIO()
    with wave.open(body, "wb") as stream:
        stream.setnchannels(format_info[0])
        stream.setsampwidth(format_info[1])
        stream.setframerate(format_info[2])
        stream.writeframes(b"".join(pcm))
    return body.getvalue(), len(chunks)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def reply(
        self, status, body, content_type="application/json; charset=utf-8", headers=None
    ):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, dict(STATE))
        else:
            self.reply(404, {"error": "接口不存在"})

    def do_POST(self):
        if self.path != "/tts":
            self.reply(404, {"error": "接口不存在"})
            return
        if not STATE["ready"]:
            self.reply(503, {"error": "已选声音服务尚未就绪"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 20000:
                raise ValueError("请求大小无效")
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            text = request.get("text", "")
            if not isinstance(text, str) or not text.strip() or len(text) > 900:
                raise ValueError("请提供一至九百字的朗读正文")
            if request.get("profile_id") != PROFILE["id"]:
                raise ValueError("请求未绑定用户选定的声音")
        except (ValueError, TypeError, UnicodeError):
            self.reply(400, {"error": "正文或声音绑定无效"})
            return
        if not LOCK.acquire(blocking=False):
            self.reply(503, {"error": "正在合成，请稍后重试"})
            return
        try:
            STATE["inflight"] = 1
            started = time.monotonic()
            # 每次核对参考和已验收样本，防止服务运行期间文件被无意替换。
            approved_profile()
            body, chunks = generate(text)
            elapsed = round((time.monotonic() - started) * 1000)
            STATE.update(total=STATE["total"] + 1, last_synth_ms=elapsed)
            self.reply(
                200,
                body,
                "audio/wav",
                {
                    "X-Engine": "gptsovits",
                    "X-Profile": PROFILE["id"],
                    "X-Ref-SHA": PROFILE["reference"]["sha256"],
                    "X-Synth-Ms": elapsed,
                    "X-Chunks": chunks,
                    "X-Fails": "-",
                },
            )
        except Exception as error:
            STATE["errors"] += 1
            self.reply(500, {"error": "已选声音合成未完成：" + type(error).__name__})
            print("本次合成未完成：" + str(error), flush=True)
        finally:
            STATE["inflight"] = 0
            LOCK.release()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 9880), Handler)
    server.daemon_threads = True
    threading.Thread(target=load_engine, name="加载已选多萝声音", daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
