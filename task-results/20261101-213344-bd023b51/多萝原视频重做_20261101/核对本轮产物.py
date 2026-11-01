"""核对完整视频、音轨、增强与试听的来源和时长，听感始终单独标记。"""

import array
import hashlib
import json
import wave
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_wave(path, expected_duration):
    with wave.open(str(path), "rb") as stream:
        if stream.getsampwidth() != 2:
            raise RuntimeError("音轨不是预期的十六位波形")
        duration = stream.getnframes() / stream.getframerate()
        samples = array.array("h", stream.readframes(stream.getnframes()))
        rate, channels = stream.getframerate(), stream.getnchannels()
    if (
        not samples
        or abs(duration - expected_duration) > 0.02
        or max(abs(value) for value in samples) < 2
    ):
        raise RuntimeError("音轨为空或时长与记录不符")
    clipping = sum(abs(value) >= 32760 for value in samples) / len(samples)
    if clipping > 0.005:
        raise RuntimeError("音轨存在明显数字削顶")
    return {
        "文件": path.name,
        "秒数": round(duration, 3),
        "采样率": rate,
        "声道": channels,
        "数字削顶比例": round(clipping, 6),
    }


def main():
    folder = Path(__file__).resolve().parent
    source = json.loads((folder / "原视频提取记录.json").read_text(encoding="utf-8"))
    if (
        source["作品编号"] != "7500493303280946470"
        or abs(source["页面秒数"] - source["完整音轨秒数"]) > 0.2
    ):
        raise RuntimeError("原视频作品或完整时长不符")
    for file_key, sha_key in (
        ("完整视频文件", "视频摘要"),
        ("完整音轨文件", "音轨摘要"),
        ("原编码音轨文件", "原编码音轨摘要"),
        ("双声道原音文件", "双声道原音摘要"),
    ):
        if digest(folder / "原始素材" / source[file_key]) != source[sha_key]:
            raise RuntimeError("原始视频或音轨摘要不符")
    checked = [
        check_wave(folder / "原始素材" / source["完整音轨文件"], source["完整音轨秒数"])
    ]
    enhancement = json.loads(
        (folder / "完整人声增强记录.json").read_text(encoding="utf-8")
    )
    enhanced_path = folder / "处理素材" / enhancement["输出"]
    if digest(enhanced_path) != enhancement["输出摘要"]:
        raise RuntimeError("完整增强音轨摘要不符")
    checked.append(check_wave(enhanced_path, source["完整音轨秒数"]))
    references = json.loads((folder / "参考制作记录.json").read_text(encoding="utf-8"))
    if references["源音频摘要"] != enhancement["输出摘要"]:
        raise RuntimeError("参考并非来自本轮完整原音")
    for row in references["参考"]:
        path = folder / "参考候选" / row["文件"]
        if digest(path) != row["摘要"]:
            raise RuntimeError("参考音频摘要不符")
        checked.append(check_wave(path, row["秒数"]))
    actual = json.loads(
        (folder / "原视频重做试听记录.json").read_text(encoding="utf-8")
    )
    if (
        not actual["使用完整原训练配对"]
        or actual["使用基础语义权重"]
        or actual["使用其他说话人参考"]
        or len(actual["试听"]) != 3
        or actual["参考处理"] != references["参考"]
    ):
        raise RuntimeError("本轮完整配对、参考或试听记录不一致")
    if [row["逐项匹配的参数组数"] for row in actual["内存参数核对"]] != [295, 678]:
        raise RuntimeError("实际内存训练权重核对记录不符")
    for row in actual["试听"]:
        path = folder / "试听音频" / row["文件"]
        if digest(path) != row["音频摘要"]:
            raise RuntimeError("试听音频摘要不符")
        checked.append(check_wave(path, row["秒数"]))
    combined = json.loads(
        (folder / "训练权重组合试听记录.json").read_text(encoding="utf-8")
    )
    if (
        combined["使用基础语义权重"]
        or combined["组合"]
        != {"说话语义": "manhui-e1.ckpt", "目标音色": "doro_e20_s1580.pth"}
        or combined["语义码本兼容"] != "四组语义码本参数一致"
        or not combined["实际原唱续写检查"]
        or any(value != "未传入原唱发声序列" for value in combined["实际原唱续写检查"])
        or len(combined["试听"]) != 2
    ):
        raise RuntimeError("训练权重组合与实际生成检查记录不符")
    dialogue = json.loads(
        (folder / "真实对白原配对试听记录.json").read_text(encoding="utf-8")
    )
    speech_reference = json.loads(
        (folder / "真实对白参考记录.json").read_text(encoding="utf-8")
    )
    expected_speech = {row["文件"]: row for row in speech_reference["参考"]}
    if (
        not dialogue["使用完整原训练配对"]
        or dialogue["使用基础语义权重"]
        or not dialogue["参考取自同作者其他作品"]
        or dialogue["参考声线与原唱一致性"] != "未确认"
        or len(dialogue["试听"]) != 3
        or len(dialogue["参考处理"]) != 2
        or any(
            expected_speech[row["文件"]]["摘要"] != row["摘要"]
            for row in dialogue["参考处理"]
        )
    ):
        raise RuntimeError("真实对白原配对试听记录不符，或把待核对声线当成已确认")
    birthday = json.loads(
        (folder / "生日对白原配对试听记录.json").read_text(encoding="utf-8")
    )
    if (
        not birthday["使用完整原训练配对"]
        or birthday["使用基础语义权重"]
        or birthday["参考声线与原唱一致性"] != "未确认"
        or len(birthday["试听"]) != 2
        or birthday["参考处理"] != [expected_speech["04_生日动画_睁眼台词.wav"]]
    ):
        raise RuntimeError("新增生日对白试验的来源、原配对或验收标记不符")
    for metadata in (combined, dialogue, birthday):
        if [row["逐项匹配的参数组数"] for row in metadata["内存参数核对"]] != [
            295,
            678,
        ]:
            raise RuntimeError("新增试听未逐项核对实际内存权重")
        for row in metadata["试听"]:
            path = folder / "试听音频" / row["文件"]
            if digest(path) != row["音频摘要"] or row["听感"] != "待用户验收":
                raise RuntimeError("新增试听摘要或验收状态不符")
            checked.append(check_wave(path, row["秒数"]))
    other_sources = []
    for metadata_path in sorted((folder / "同作者素材").glob("*/原视频提取记录.json")):
        item = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            item["作者"] != "卖唱的doro"
            or abs(item["页面秒数"] - item["完整音轨秒数"]) > 0.2
        ):
            raise RuntimeError("同作者作品的作者或完整时长不符")
        for file_key, sha_key in (
            ("完整视频文件", "视频摘要"),
            ("完整音轨文件", "音轨摘要"),
            ("原编码音轨文件", "原编码音轨摘要"),
            ("双声道原音文件", "双声道原音摘要"),
        ):
            if (
                digest(metadata_path.parent / "原始素材" / item[file_key])
                != item[sha_key]
            ):
                raise RuntimeError("同作者完整素材摘要不符")
        other_sources.append(
            {"作品编号": item["作品编号"], "完整秒数": item["完整音轨秒数"]}
        )
    for row in speech_reference["参考"]:
        speech_source = json.loads(
            (folder / "同作者素材" / row["作品编号"] / "原视频提取记录.json").read_text(
                encoding="utf-8"
            )
        )
        if row["源音频摘要"] != speech_source["音轨摘要"]:
            raise RuntimeError("真实对白来源音轨不符")
        path = folder / "同作者说话候选" / row["文件"]
        if (
            digest(path) != row["摘要"]
            or abs(row["结束秒"] - row["起始秒"] - row["秒数"]) > 0.01
        ):
            raise RuntimeError("真实对白片段摘要或时间窗不符")
        checked.append(check_wave(path, row["秒数"]))
    listing = json.loads(
        (folder / "同作者公开作品清单.local.json").read_text(encoding="utf-8")
    )
    search = json.loads(
        (folder / "同作者作品搜索记录.local.json").read_text(encoding="utf-8")
    )
    resources = json.loads((folder / "资源配置.local.json").read_text(encoding="utf-8"))
    for row in resources["files"]:
        if digest(Path(row["path"])) != row["sha256"]:
            raise RuntimeError("原训练权重、源素材或日常配置在本轮期间变化")
    report = {
        "完整提取": "指定作品全长25.24秒，保留视频、原编码音轨、双声道音轨和分析音轨",
        "增强": "全长处理完成；背景抑制不等同于纯伴奏分离",
        "完整训练配对": "原文件与实际内存参数逐项一致",
        "训练权重组合": "满穗语义训练权重与多萝音色训练权重，已核对码本兼容和实际调用；独立实验，不是原配对",
        "真实对白试听": "原多萝完整训练配对，参考取自同作者动画；参考与目标原唱是否同声线仍待核对",
        "同作者素材": other_sources,
        "公开检索范围": {
            "主页显示总数": 210,
            "实际读取清单数量": listing["公开可见作品数"],
            "关键词搜索": search["公开搜索尝试"],
            "是否全量核对": False,
        },
        "产物文件检查": checked,
        "音色与去唱腔验收": "未完成；音色、唱腔、情绪与长段稳定性均待用户试听，自动识别与声纹分数不能代替验收",
        "日常配置与原训练文件": "本轮期间摘要未变化",
    }
    (folder / "本轮核对结果.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
