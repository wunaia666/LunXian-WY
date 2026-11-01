"""显式组合用户给的说话语义权重和多萝音色权重，不加载基础语义模型。"""

import array
import gc
import hashlib
import importlib.util
import json
import os
import sys
import wave
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    folder = Path(__file__).resolve().parent
    resources = json.loads((folder / "资源配置.local.json").read_text(encoding="utf-8"))
    portable = Path(resources["original_root"])
    engine_root = Path(resources["engine_root"])
    work = folder / "work"
    output = folder / "试听音频"
    work.mkdir(exist_ok=True)
    output.mkdir(exist_ok=True)
    required = resources["files"]
    for item in required:
        if digest(item["path"]) != item["sha256"]:
            raise RuntimeError("原始模型、参考或配置摘要不符，停止生成")
    if digest(portable / "app.py") != digest(engine_root / "app.py"):
        raise RuntimeError("运行副本与原便携包入口不一致")
    if digest(portable / "GPT_SoVITS/TTS_infer_pack/TTS.py") != digest(
        engine_root / "GPT_SoVITS/TTS_infer_pack/TTS.py"
    ):
        raise RuntimeError("运行副本与原便携包推理引擎不一致")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PATH"] = (
        str(engine_root / "runtime") + os.pathsep + os.environ.get("PATH", "")
    )
    sys.path.insert(0, str(engine_root))
    sys.path.insert(0, str(engine_root / "GPT_SoVITS"))
    spec = importlib.util.spec_from_file_location(
        "original_portable", str(engine_root / "app.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT_DIR = str(output)
    reference_info = json.loads(
        (folder / "参考制作记录.json").read_text(encoding="utf-8")
    )
    reference_info["参考"] = [
        row for row in reference_info["参考"] if row["文件"] == "01_背景抑制参考.wav"
    ]
    module.REF_DIR = str(folder / "参考候选")
    module.REF_PROMPTS = {row["文件"]: "" for row in reference_info["参考"]}

    def local_log(message):
        with (work / "原入口状态日志.txt").open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")

    module.log = local_log
    import torch
    import yaml

    torch.set_num_threads(4)
    if not torch.cuda.is_available():
        raise RuntimeError("本轮原配置使用显卡，但显卡当前不可用")
    configuration = yaml.safe_load(
        (portable / "GPT_SoVITS/configs/tts_infer.yaml").read_text(encoding="utf-8")
    )
    settings = configuration["custom"]
    expected_paths = {
        "t2s_weights_path": Path(resources["speech_gpt"]),
        "vits_weights_path": portable / "SoVITS_weights_v2Pro/doro_e20_s1580.pth",
    }
    for key, path in expected_paths.items():
        settings[key] = str(path)
    for key in ("bert_base_path", "cnhuhbert_base_path"):
        settings[key] = str(engine_root / settings[key])
    config_path = work / "训练权重组合配置.yaml"
    config_path.write_text(
        yaml.safe_dump(configuration, allow_unicode=True), encoding="utf-8"
    )
    module.CONFIG = str(config_path)
    engine = module.Engine()
    engine.load()
    if not engine.ready:
        raise RuntimeError("原入口加载失败：" + (engine.error or "无错误详情")[-800:])
    for key, expected in expected_paths.items():
        if Path(getattr(engine.tts.configs, key)).resolve() != expected.resolve():
            raise RuntimeError("实际加载路径不是用户原始训练文件")

    from process_ckpt import load_sovits_new

    other_decoder = load_sovits_new(resources["speech_sovits"])["weight"]
    target_state = engine.tts.vits_model.state_dict()
    shared_keys = [key for key in target_state if "quantizer" in key]
    if len(shared_keys) != 4 or any(
        key not in other_decoder
        or not torch.equal(
            target_state[key].detach().cpu(),
            other_decoder[key].to(dtype=target_state[key].dtype),
        )
        for key in shared_keys
    ):
        raise RuntimeError("两套模型的语义码本并不一致，停止组合试验")
    del other_decoder, target_state

    verified = []
    for name, current, checkpoint in (
        (
            "语义训练权重",
            engine.tts.t2s_model,
            torch.load(
                str(expected_paths["t2s_weights_path"]),
                map_location="cpu",
                weights_only=False,
            ),
        ),
        (
            "音色训练权重",
            engine.tts.vits_model,
            load_sovits_new(str(expected_paths["vits_weights_path"])),
        ),
    ):
        saved = checkpoint["weight"]
        state = current.state_dict()
        count = 0
        ignored = []
        for key, actual in state.items():
            if key not in saved:
                # 后验编码器只用于训练，原便携包加载时也允许缺少这一部分。
                if key.startswith("enc_q."):
                    ignored.append(key)
                    continue
                raise RuntimeError("实际推理参数未包含在训练文件中：" + key)
            expected = saved[key].to(dtype=actual.dtype)
            if actual.shape != expected.shape or not torch.equal(
                actual.detach().cpu(), expected
            ):
                raise RuntimeError("实际内存参数与训练文件不一致：" + key)
            count += 1
        verified.append(
            {
                "类型": name,
                "逐项匹配的参数组数": count,
                "未参与推理的训练编码器缺失组数": len(ignored),
            }
        )
        del checkpoint, state
        gc.collect()
    print(
        json.dumps(
            {"状态": "原始训练文件与实际内存参数逐项核对通过", "核对": verified},
            ensure_ascii=False,
        ),
        flush=True,
    )

    original_run = engine.tts.run
    calls = []
    prompt_checks = []
    original_naive = engine.tts.t2s_model.model.infer_panel_naive_batched

    def check_semantics(*values, **keywords):
        prompt = values[2] if len(values) > 2 else keywords.get("prompts")
        if prompt is not None:
            raise RuntimeError("组合试验仍传入了原唱发声序列")
        prompt_checks.append("未传入原唱发声序列")
        return original_naive(*values, **keywords)

    engine.tts.t2s_model.model.infer_panel_naive_batched = check_semantics

    def checked_run(inputs):
        inputs["text_split_method"] = "cut0"
        inputs["parallel_infer"] = False
        reference_name = Path(inputs["ref_audio_path"]).name
        if (
            reference_name not in module.REF_PROMPTS
            or Path(inputs["ref_audio_path"]).resolve()
            != (folder / "参考候选" / reference_name).resolve()
            or inputs["prompt_text"] != module.REF_PROMPTS[reference_name]
            or inputs["text_split_method"] != "cut0"
            or inputs["speed_factor"] != 1.0
        ):
            raise RuntimeError("原入口生成参数与本轮约定不符")
        calls.append(dict(inputs))
        yield from original_run(inputs)

    engine.tts.run = checked_run
    cases = [
        (
            "04_训练说话节奏_短句.wav",
            "你回来啦。今天过得怎么样？累了就先休息一会儿，我陪着你。",
            "01_背景抑制参考.wav",
        ),
        (
            "05_训练说话节奏_长段.wav",
            "今天不用急着把所有事情都做完。先喝点水，坐下来休息一会儿。你想聊什么都可以，我会认真听你说。",
            "01_背景抑制参考.wav",
        ),
    ]
    rows = []
    for filename, text, reference_name in cases:
        generated, reported_duration, _ = engine.synth(
            text, reference_name, 1.0, 1.0, 15, seed=42
        )
        if not prompt_checks:
            raise RuntimeError("未核对实际语义生成调用")
        path = output / filename
        Path(generated).replace(path)
        with wave.open(str(path), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
            samples = array.array("h", stream.readframes(stream.getnframes()))
            if (
                stream.getsampwidth() != 2
                or not samples
                or abs(duration - reported_duration) > 0.01
            ):
                raise RuntimeError("实际生成音频格式或时长异常")
        if max(abs(value) for value in samples) < 2:
            raise RuntimeError("生成结果近乎静音")
        clipping = sum(abs(value) >= 32760 for value in samples) / len(samples)
        if clipping > 0.005:
            raise RuntimeError("生成结果存在明显数字削顶")
        row = {
            "文件": filename,
            "文案": text,
            "秒数": round(duration, 3),
            "音频摘要": digest(path),
            "数字削顶比例": clipping,
            "实际请求": calls[-1],
            "参考类型": next(
                row["类型"]
                for row in reference_info["参考"]
                if row["文件"] == reference_name
            ),
            "听感": "待用户验收",
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    for item in required:
        if digest(item["path"]) != item["sha256"]:
            raise RuntimeError("生成期间原始文件或日常配置发生变化，需要核对")
    result = {
        "使用用户提供的训练权重": True,
        "组合": {"说话语义": "manhui-e1.ckpt", "目标音色": "doro_e20_s1580.pth"},
        "语义码本兼容": "四组语义码本参数一致",
        "实际原唱续写检查": prompt_checks,
        "使用基础语义权重": False,
        "使用其他说话人参考": False,
        "参考处理": reference_info["参考"],
        "原始文件及日常配置": "摘要均未变化",
        "内存参数核对": verified,
        "入口": "与原便携包摘要一致的原生合成入口",
        "试听": rows,
        "验收": "只确认模型来源和文件有效，不能据此认定唱腔已解决",
    }
    (folder / "训练权重组合试听记录.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
