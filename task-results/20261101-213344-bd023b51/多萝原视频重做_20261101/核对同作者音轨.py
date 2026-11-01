"""完整识别同作者候选音轨，记录可核对时间窗，不将歌词标题当成说话证据。"""

import hashlib
import json
from pathlib import Path

import librosa
import torch
import whisper


def main():
    folder = Path(__file__).resolve().parent
    torch.set_num_threads(4)
    model = whisper.load_model(r"E:\sss_test\models\whisper\base.pt", device="cpu")
    records = []
    for metadata_path in sorted((folder / "同作者素材").glob("*/原视频提取记录.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("作者") != "卖唱的doro":
            raise RuntimeError("候选作品作者与指定账号不符")
        path = metadata_path.parent / "原始素材" / metadata["完整音轨文件"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != metadata["音轨摘要"]:
            raise RuntimeError("候选音轨与提取记录不一致")
        receipt = metadata_path.parent / "完整音轨识别.local.json"
        if receipt.is_file():
            previous = json.loads(receipt.read_text(encoding="utf-8"))
            if previous.get("音轨摘要") == digest:
                records.append(previous)
                continue
        audio, _ = librosa.load(str(path), sr=16000, mono=True)
        result = model.transcribe(
            audio,
            language="zh",
            fp16=False,
            temperature=0,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        segments = []
        for row in result.get("segments", []):
            text = row["text"].strip()
            count = sum("\u4e00" <= character <= "\u9fff" for character in text)
            duration = row["end"] - row["start"]
            segments.append(
                {
                    "起始秒": round(row["start"], 3),
                    "结束秒": round(row["end"], 3),
                    "文字": text,
                    "每秒中文字数": round(count / max(duration, 0.1), 2),
                    "对数概率": round(row["avg_logprob"], 3),
                    "无语音概率": round(row["no_speech_prob"], 3),
                    "词位置": row.get("words", []),
                }
            )
        record = {
            "作品编号": metadata["作品编号"],
            "作者": metadata["作者"],
            "描述": metadata["作品描述"],
            "完整秒数": metadata["完整音轨秒数"],
            "音轨摘要": digest,
            "自动识别全文": result.get("text", ""),
            "片段": segments,
            "使用边界": "识别速度、文字与置信度仅用于筛选，不能据此认定是同声音的正常说话",
        }
        receipt.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        records.append(record)
        print(
            json.dumps(
                {
                    "作品编号": record["作品编号"],
                    "描述": record["描述"],
                    "片段": [
                        {
                            key: value
                            for key, value in segment.items()
                            if key != "词位置"
                        }
                        for segment in segments
                    ],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    (folder / "同作者音轨核对汇总.local.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
