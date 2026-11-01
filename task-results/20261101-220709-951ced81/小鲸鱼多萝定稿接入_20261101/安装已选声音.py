"""备份并安装用户明确选择的声音，仅更新语音与对应的监控入口。"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


def main():
    stage = Path(__file__).resolve().parent
    root = Path(r"E:\sss_test")
    experiment = Path(r"E:\sss\多萝原视频重做_20261101")
    receipt = json.loads(
        (experiment / "生日对白原配对试听记录.json").read_text(encoding="utf-8")
    )
    selected = next(
        row
        for row in receipt["试听"]
        if row["文件"] == "10_生日对白参考_原多萝配对_长段.wav"
    )
    resources = json.loads(
        (experiment / "资源配置.local.json").read_text(encoding="utf-8")
    )
    original = Path(resources["original_root"])
    reference = experiment / "同作者说话候选/04_生日动画_睁眼台词.wav"
    sample = experiment / "试听音频" / selected["文件"]
    if (
        hashlib.sha256(sample.read_bytes()).hexdigest()
        != "20c311aec5c0a2649b7b88574d1afda52829c53c3fe2d6a7e149bdc8765dc074"
        or hashlib.sha256(reference.read_bytes()).hexdigest()
        != "80fa21878b8b012950429c73007a81dd33dbb8a2d6eb506c9aa8cfc909ce5a04"
    ):
        raise RuntimeError("用户选定的样本或对应参考音与记录不符")
    profile_path = root / "dafeiyu_assets/doro_approved_profile.json"
    if profile_path.exists():
        raise RuntimeError("已存在选声配置，不重复覆盖；请先核对已有安装记录")
    gateway_sha = hashlib.sha256(
        (root / "dafeiyu_assets/qq_gateway.json").read_bytes()
    ).hexdigest()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = root / "backups" / ("已选多萝声音_" + stamp)
    files = [
        (source, root / source.relative_to(stage / "project"))
        for source in (stage / "project").rglob("*")
        if source.is_file() and source.suffix in {".py", ".sh"}
    ]
    monitor = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    files += [
        (stage / "monitor" / name, monitor / name)
        for name in ("monitor.py", "dashboard.html")
    ]
    for source, target in files:
        location = (
            backup
            / ("monitor" if target.parent == monitor else "project")
            / (target.name if target.parent == monitor else target.relative_to(root))
        )
        if target.exists():
            location.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, location)
    config_path = root / "dafeiyu_assets/voice_config.json"
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, backup / "voice_config.json")
    ref_target = root / "dafeiyu_assets/audio/_gptsovits_ref/doro_birthday_ref.wav"
    sample_target = root / "dafeiyu_assets/audio/accepted/doro_approved_sample10.wav"
    for source, target in ((reference, ref_target), (sample, sample_target)):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    parameters = {
        key: value
        for key, value in selected["实际请求"].items()
        if key
        not in {"text", "text_lang", "prompt_text", "prompt_lang", "ref_audio_path"}
    }
    profile = {
        "id": "doro-birthday-20261101-approved10",
        "accepted": True,
        "accepted_at": datetime.now().isoformat(timespec="seconds"),
        "user_selection": "第十条可以，就用这个",
        "engine_root": resources["engine_root"],
        "reference": {
            "path": str(ref_target),
            "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            "source_video_id": "7654195128684482171",
            "source_range_seconds": [18.05, 21.35],
        },
        "accepted_sample": {
            "path": str(sample_target),
            "sha256": selected["音频摘要"],
            "text": selected["文案"],
            "duration": selected["秒数"],
        },
        "gpt": {
            "path": str(original / "GPT_weights_v2Pro/doro-e15.ckpt"),
            "sha256": "98bee68fb46a0d9e1c396a67fa42b919b27e4f7141e268978b5a98ae401074c0",
        },
        "sovits": {
            "path": str(original / "SoVITS_weights_v2Pro/doro_e20_s1580.pth"),
            "sha256": "c75d8779ea73357c00a6352e713bf022dea4e3dc3478b629c0fbfab03253207d",
        },
        "prompt_text": selected["实际请求"]["prompt_text"],
        "parameters": parameters,
        "acceptance_scope": "用户接受指定第十条试听并要求采用对应声音；其他情绪、语速及分钟级语音尚未单独验收",
    }
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for source, target in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.update(
        backend="gptsovits",
        reference_only=True,
        fallback="none",
        cosy_timeout_sec=180,
        cosy_pitch_match=False,
        cosy_preserve_dynamics=True,
        cosy_tempo=1.0,
        voice_style="用户已确认的多萝第十条声音，原训练配对、生日对白参考与原速",
    )
    config["_说明"] = (
        "用户已选定第十条试听；日常沿用其完整训练配对和固定参数，失败时不切换其他音色。"
    )
    config["_模型"] = {
        "engine": "gptsovits",
        "source_video_id": "7654195128684482171",
        "ref_wav_wsl": str(ref_target),
        "ref_wav_path": str(ref_target),
        "ref_text": profile["prompt_text"],
        "profile_id": profile["id"],
    }
    config["gptsovits"] = {
        "url": "http://127.0.0.1:9880",
        "profile_id": profile["id"],
        "reference_path": str(ref_target),
        "reference_sha": profile["reference"]["sha256"],
        "accepted_sample_path": str(sample_target),
        "accepted_sample_sha": profile["accepted_sample"]["sha256"],
    }
    temporary = config_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(config_path)
    if (
        hashlib.sha256(
            (root / "dafeiyu_assets/qq_gateway.json").read_bytes()
        ).hexdigest()
        != gateway_sha
    ):
        raise RuntimeError("安装期间聊天接入配置发生变化，需要单独核对")
    result = {
        "选声记录已保存": True,
        "配置已安装": True,
        "服务验证": "待启动核对",
        "备份": str(backup),
        "安装文件数": len(files),
        "聊天配置未变化": True,
    }
    (stage / "安装结果.local.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
