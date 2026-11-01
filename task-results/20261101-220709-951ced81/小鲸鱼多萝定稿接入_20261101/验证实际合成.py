"""从机器人使用的真实合成入口复现已验收文本，并比较实际波形。"""

import asyncio
import hashlib
import importlib.util
import json
import wave
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    root = Path(r"E:\sss_test")
    profile = json.loads(
        (root / "dafeiyu_assets/doro_approved_profile.json").read_text(encoding="utf-8")
    )
    spec = importlib.util.spec_from_file_location(
        "approved_live_tts",
        root / "AstrBot/data/plugins/astrbot_plugin_dafeiyu_voice/tts.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.AUDIO_DIR = folder / "实际合成验证"
    actual_path = asyncio.run(
        module.synth(profile["accepted_sample"]["text"], ext="wav")
    )
    sample_path = Path(profile["accepted_sample"]["path"])

    def pcm(path):
        with wave.open(str(path), "rb") as stream:
            params = (
                stream.getnchannels(),
                stream.getsampwidth(),
                stream.getframerate(),
                stream.getnframes(),
            )
            return params, stream.readframes(stream.getnframes())

    actual_format, actual_pcm = pcm(actual_path)
    sample_format, sample_pcm = pcm(sample_path)
    result = {
        "实际合成文件": str(actual_path),
        "实际引擎": module.LAST_SYNTH_BACKEND,
        "实际元数据": module.LAST_SYNTH_META,
        "参数和采样点数一致": actual_format == sample_format,
        "波形逐字节一致": actual_pcm == sample_pcm,
        "实际文件摘要": hashlib.sha256(actual_path.read_bytes()).hexdigest(),
        "用户已验收样本摘要": profile["accepted_sample"]["sha256"],
        "实际秒数": round(actual_format[3] / actual_format[2], 3),
        "实际发送聊天消息": False,
    }
    (folder / "实际合成验证结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not result["参数和采样点数一致"] or not result["波形逐字节一致"]:
        raise RuntimeError("日常合成结果与已验收样本波形不一致，详见验证记录")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
