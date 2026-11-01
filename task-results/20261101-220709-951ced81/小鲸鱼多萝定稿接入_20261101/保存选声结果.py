"""保存用户选声与真实合成验证结果，同步监控的已确认状态。"""

import json
import time
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    root = Path(r"E:\sss_test")
    profile = json.loads(
        (root / "dafeiyu_assets/doro_approved_profile.json").read_text(encoding="utf-8")
    )
    verified = json.loads(
        (folder / "实际合成验证结果.json").read_text(encoding="utf-8")
    )
    if (
        not verified["波形逐字节一致"]
        or verified["实际文件摘要"] != profile["accepted_sample"]["sha256"]
    ):
        raise RuntimeError("没有取得与已验收样本一致的真实合成结果")
    runtime = root / "dafeiyu_assets/runtime"
    state = {
        "id": "doro-approved-10-20261101",
        "phase": "ready",
        "evaluation": "accepted",
        "production_changed": True,
        "message": "你已选定第十条声音，日常合成已切换并复现相同波形。",
        "file": Path(profile["accepted_sample"]["path"]).name,
        "duration": profile["accepted_sample"]["duration"],
        "text": profile["accepted_sample"]["text"],
        "profile": "expressive",
        "mood": "normal",
        "tempo": 1.0,
        "profile_id": profile["id"],
        "reference_sha": profile["reference"]["sha256"],
        "meta": verified["实际元数据"],
        "accepted_at": time.time(),
        "at": time.time(),
        "sent_messages": False,
    }
    for name, value in (
        ("voice_studio.json", state),
        (
            "voice_latest.json",
            {
                **verified["实际元数据"],
                "file": state["file"],
                "state": "已确认声音接入验证通过",
                "duration": state["duration"],
                "preview": True,
                "at": time.time(),
                "sent_messages": False,
            },
        ),
    ):
        path = runtime / name
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    samples_path = runtime / "voice_samples.json"
    try:
        samples = json.loads(samples_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        samples = []
    samples = [row for row in samples if row.get("file") != state["file"]]
    samples.append(
        {
            "name": "已确认的多萝声音 · 第十条",
            "file": state["file"],
            "text": state["text"],
            "description": "用户已确认采用，原训练配对与固定参数；真实合成已复现相同波形。",
            "reference_sha": state["reference_sha"],
            "evaluation": "accepted",
        }
    )
    samples_path.write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    experiment_checkpoint = Path(r"E:\sss\多萝原视频重做_20261101\接续断点.json")
    checkpoint = json.loads(experiment_checkpoint.read_text(encoding="utf-8"))
    checkpoint["最新用户决定"] = {
        "选择": "第十条试听可以，就用这个",
        "状态": "已接入日常合成，真实输出与已验收样本逐字节一致",
        "本轮记录": str(folder / "接续结果.json"),
    }
    for row in checkpoint["候选状态"]:
        if row["文件"].endswith("10_生日对白参考_原多萝配对_长段.wav"):
            row["状态"] = (
                "用户已接受并指定采用；日常合成已接入同一模型、参考与参数，逐采样复现一致"
            )
    experiment_checkpoint.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = {
        "用户选定样本": "10_生日对白参考_原多萝配对_长段.wav",
        "听感状态": "用户已确认采用此样本",
        "日常合成状态": "已安装并启动所选声音服务",
        "实际引擎": "gptsovits",
        "完整训练配对": ["doro-e15.ckpt", "doro_e20_s1580.pth"],
        "参数": profile["parameters"],
        "参考音摘要": profile["reference"]["sha256"],
        "已验收样本摘要": profile["accepted_sample"]["sha256"],
        "真实合成验证": {
            "参数和采样点数一致": verified["参数和采样点数一致"],
            "波形逐字节一致": verified["波形逐字节一致"],
            "实际文件摘要": verified["实际文件摘要"],
            "秒数": verified["实际秒数"],
        },
        "回归检查": "五项新增检查与六项现有原声保护检查通过；守护启动入口语法检查通过；监控浏览器只读检查通过",
        "仍待验收": [
            "其他情绪与语速",
            "新文本中的个别发音",
            "分钟级长语音的听感和稳定性",
        ],
        "实际发送聊天消息": False,
        "桌面聊天客户端操作": False,
        "备份记录": "安装结果.local.json",
        "运行日志": r"E:\sss\语音权重试听_20261101\engine\approved_doro_service.log",
    }
    (folder / "接续结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("用户选声、监控状态与真实波形验证记录已保存。")


if __name__ == "__main__":
    main()
