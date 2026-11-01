"""检查实际试听文件与配对权重摘要，结果不替代用户的听感评价。"""

import array
import hashlib
import json
import wave
from pathlib import Path

folder = Path(__file__).resolve().parent
resources = json.loads((folder / "资源配置.local.json").read_text(encoding="utf-8"))
checked = []
for model in resources["models"]:
    for key in ("gpt", "sovits", "reference"):
        if (
            hashlib.sha256((folder / model[key]).read_bytes()).hexdigest()
            != model[key + "_sha256"]
        ):
            raise RuntimeError("权重或参考音频在试音期间发生变化")
    records = json.loads(
        (folder / (model["id"] + "_试听记录.json")).read_text(encoding="utf-8")
    )
    if len(records) != 4 or any(not record.get("ok") for record in records):
        raise RuntimeError("该音色尚未生成四条完整样例")
    for record in records:
        path = folder / "试听音频" / record["file"]
        with wave.open(str(path), "rb") as stream:
            if stream.getsampwidth() != 2:
                raise RuntimeError("试听不是预期的十六位波形文件")
            duration = stream.getnframes() / stream.getframerate()
            samples = array.array("h", stream.readframes(stream.getnframes()))
            channels, sample_rate = stream.getnchannels(), stream.getframerate()
        if (
            not samples
            or abs(duration - record["duration"]) > 0.01
            or max(abs(value) for value in samples) < 2
        ):
            raise RuntimeError("试听时长或波形内容异常")
        clipping = sum(abs(value) >= 32760 for value in samples) / len(samples)
        if clipping > 0.005:
            raise RuntimeError("试听有明显数字削顶，需重新生成")
        checked.append(
            {
                "音色": model["name"],
                "内容": record["title"],
                "文件": record["file"],
                "秒数": round(duration, 3),
                "采样率": sample_rate,
                "声道": channels,
                "数字削顶比例": round(clipping, 6),
                "状态": "文件核对通过，听感待确认",
            }
        )
receipt = {
    "样例数": len(checked),
    "权重与参考摘要": "全部保持一致",
    "改动日常声音": False,
    "发送聊天消息": False,
    "样例": checked,
}
(folder / "试听核对结果.json").write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(receipt, ensure_ascii=False))
