"""检查本轮试听来源、关闭参考续写的证据及文件完整性，不替代听感验收。"""

import array
import hashlib
import json
import wave
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    folder = Path(__file__).resolve().parent
    resources = json.loads((folder / "资源配置.local.json").read_text(encoding="utf-8"))
    model = resources["models"][0]
    for key in ("gpt", "base_gpt", "sovits", "reference"):
        if digest(Path(model[key])) != model[key + "_sha256"]:
            raise RuntimeError("权重或乙参考发生变化")
    baseline = json.loads(
        (folder / "日常配置基线.local.json").read_text(encoding="utf-8")
    )
    for config in baseline:
        if digest(Path(config["path"])) != config["sha256"]:
            raise RuntimeError("日常配置摘要与生成期间的基线不符，需要人工核对")
    checked = []
    for mode, names in (
        ("trained", {"01_原权重_关闭韵律续写.wav", "03_原权重_长段.wav"}),
        ("base", {"02_基础语义_保留乙音色.wav", "04_基础语义_长段.wav"}),
        ("guided", {"05_同音色说话引导_短句.wav", "06_同音色说话引导_长段.wav"}),
    ):
        rows = json.loads(
            (folder / (mode + "_试听记录.json")).read_text(encoding="utf-8")
        )
        if len(rows) != 2 or {row.get("file") for row in rows} != names:
            raise RuntimeError("本轮三组试听记录不完整")
        semantic_key = "gpt" if mode == "trained" else "base_gpt"
        for row in rows:
            if not row.get("ok") or row.get("semantic") != mode:
                raise RuntimeError("该样例未成功生成或语义权重记录不符")
            expected = {
                "gpt_sha256": model[semantic_key + "_sha256"],
                "sovits_sha256": model["sovits_sha256"],
                "reference_sha256": model["reference_sha256"],
            }
            if any(row.get(key) != value for key, value in expected.items()):
                raise RuntimeError("样例未使用约定的权重或乙参考")
            request = row["request"]
            guide = row.get("semantic_guide")
            if mode == "guided":
                guide_path = folder / "试听音频" / "02_基础语义_保留乙音色.wav"
                guide_row = next(
                    item
                    for item in json.loads(
                        (folder / "base_试听记录.json").read_text(encoding="utf-8")
                    )
                    if item.get("file") == guide_path.name
                )
                if not guide or guide.get("sha256") != digest(guide_path):
                    raise RuntimeError("说话引导并非本轮生成的同音色短句")
                expected_prompt = guide_row["text"]
                evidence = "仅同音色短句引导，未传入乙参考发声序列"
            else:
                expected_prompt = ""
                evidence = "未传入"
            if (
                request["prompt_text"] != expected_prompt
                or request["speed_factor"] != 1.0
                or request["text_split_method"] != "cut5"
                or Path(request["ref_audio_path"]).resolve()
                != Path(model["reference"]).resolve()
                or not row.get("infer_calls")
                or any(
                    call.get("参考发声序列") != evidence for call in row["infer_calls"]
                )
            ):
                raise RuntimeError("未落实关闭参考发声续写、原速或分句设置")
            path = folder / "试听音频" / row["file"]
            if digest(path) != row.get("audio_sha256"):
                raise RuntimeError("音频摘要不符")
            with wave.open(str(path), "rb") as stream:
                if stream.getsampwidth() != 2 or stream.getnchannels() != 1:
                    raise RuntimeError("音频编码或声道不符")
                sample_rate = stream.getframerate()
                duration = stream.getnframes() / sample_rate
                samples = array.array("h", stream.readframes(stream.getnframes()))
            if (
                not samples
                or abs(duration - row["duration"]) > 0.01
                or max(abs(value) for value in samples) < 2
                or duration > 80
            ):
                raise RuntimeError("音频为空、时长异常或近乎静音")
            clipping = sum(abs(value) >= 32760 for value in samples) / len(samples)
            if clipping > 0.005:
                raise RuntimeError("音频存在明显数字削顶")
            checked.append(
                {
                    "文件": row["file"],
                    "语义权重": row["semantic_name"],
                    "秒数": round(duration, 3),
                    "采样率": sample_rate,
                    "分句数": len(row["infer_calls"]),
                    "数字削顶比例": round(clipping, 6),
                    "结果": "来源与文件检查通过，唱腔与音色待试听",
                }
            )
    report = {
        "样例数": len(checked),
        "参考音色": "用户指定乙参考，完整原文件，未经音高或速度处理",
        "参考发声序列续写": "六条均未传入乙参考发声序列；引导组仅传入本轮同音色短句序列",
        "日常配置": "生成期间两项配置摘要均未变化",
        "样例": sorted(checked, key=lambda row: row["文件"]),
        "听感验收": "待用户试听；程序检查不能判断唱腔已经消失",
    }
    (folder / "本轮检查结果.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
