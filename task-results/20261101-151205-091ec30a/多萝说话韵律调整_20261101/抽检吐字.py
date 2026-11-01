"""使用本机已有识别权重复核候选语音，识别结果不代表音色或唱腔验收。"""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import librosa
import torch
import whisper


def main():
    parser = argparse.ArgumentParser(description="本地候选语音吐字复核")
    parser.add_argument("--pattern", default="*.wav")
    parser.add_argument("--model", choices=["base", "small"], default="base")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    torch.set_num_threads(4)
    model_dir = Path(r"E:\sss_test\models\whisper")
    checkpoint = model_dir / (args.model + ".pt")
    if not checkpoint.is_file():
        raise FileNotFoundError("本机复核权重不存在；不自动下载替代模型")
    if not zipfile.is_zipfile(checkpoint):
        raise RuntimeError("本机识别权重不是完整文件，未运行识别；不将失败记为复核通过")
    model = whisper.load_model(str(checkpoint), device="cpu")
    target = folder / (args.model + "_吐字复核.json")
    rows = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else []
    for path in sorted((folder / "试听音频").glob(args.pattern)):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if any(
            row.get("file") == path.name and row.get("audio_sha256") == digest
            for row in rows
        ):
            continue
        audio, _ = librosa.load(str(path), sr=16000, mono=True)
        result = model.transcribe(
            audio,
            language="zh",
            fp16=False,
            temperature=0,
            beam_size=5,
            condition_on_previous_text=False,
        )
        segments = result.get("segments") or []
        row = {
            "file": path.name,
            "audio_sha256": digest,
            "model": args.model,
            "text": result.get("text", ""),
            "avg_log_probability": round(
                sum(segment.get("avg_logprob", -9) for segment in segments)
                / max(1, len(segments)),
                3,
            ),
            "用途": "自动识别复核，不替代逐字听辨及用户听感验收",
        }
        rows = [item for item in rows if item.get("file") != path.name] + [row]
        target.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
