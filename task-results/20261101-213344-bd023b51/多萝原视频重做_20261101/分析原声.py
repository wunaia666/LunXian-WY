"""完整转写指定视频音轨并记录分段位置，自动结果只用于筛选参考。"""

import hashlib
import json
from pathlib import Path

import librosa
import numpy as np
import pyworld
import torch
import whisper


def main():
    folder = Path(__file__).resolve().parent
    source = folder / "原始素材/7500493303280946470_完整原音.wav"
    torch.set_num_threads(4)
    model = whisper.load_model(r"E:\sss_test\models\whisper\base.pt", device="cpu")
    audio, sample_rate = librosa.load(str(source), sr=16000, mono=True)
    transcription = model.transcribe(
        audio,
        language="zh",
        fp16=False,
        temperature=0,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    segments = []
    for segment in transcription.get("segments", []):
        segments.append(
            {
                "起始秒": round(segment["start"], 3),
                "结束秒": round(segment["end"], 3),
                "识别文字": segment["text"],
                "对数概率": round(segment["avg_logprob"], 3),
                "词位置": [
                    {
                        "文字": word["word"],
                        "起始秒": round(word["start"], 3),
                        "结束秒": round(word["end"], 3),
                        "概率": round(word["probability"], 3),
                    }
                    for word in segment.get("words", [])
                ],
            }
        )
    f0, times = pyworld.harvest(
        audio.astype(np.float64),
        sample_rate,
        f0_floor=100,
        f0_ceil=900,
        frame_period=10,
    )
    f0 = pyworld.stonemask(audio.astype(np.float64), f0, times, sample_rate)
    windows = []
    for start in np.arange(0, min(10, len(audio) / sample_rate), 0.5):
        selected = f0[(times >= start) & (times < start + 0.5)]
        voiced = selected[selected > 0]
        windows.append(
            {
                "起始秒": round(float(start), 2),
                "有声比例": round(float(np.mean(selected > 0)), 3),
                "音高中位数": round(float(np.median(voiced)), 1)
                if len(voiced)
                else None,
            }
        )
    result = {
        "音轨摘要": hashlib.sha256(source.read_bytes()).hexdigest(),
        "完整秒数": round(len(audio) / sample_rate, 3),
        "自动识别全文": transcription.get("text", ""),
        "分段": segments,
        "前十秒音高检查": windows,
        "验收": "识别文字与声学数值不能单独确定是否唱歌；参考片段需保留原声供核对",
    }
    (folder / "原声分析结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "全文": result["自动识别全文"],
                "分段": [
                    {key: value for key, value in row.items() if key != "词位置"}
                    for row in segments
                ],
                "前十秒音高检查": windows,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
