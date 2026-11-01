"""读取用户已选定的多萝声音，统一核对服务、监控与试听使用的配置。"""

import hashlib
import json
from pathlib import Path

ROOT = Path(r"E:\sss_test")
PROFILE_PATH = ROOT / "dafeiyu_assets/doro_approved_profile.json"


def approved_profile(check_weights=False):
    """核对用户接受的样本、参考音及固定参数，可在加载前核对完整训练文件。"""
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if (
        profile.get("id") != "doro-birthday-20261101-approved10"
        or profile.get("accepted") is not True
    ):
        raise ValueError("没有有效的用户选声记录")
    expected = {
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 1.0,
        "text_split_method": "cut0",
        "batch_size": 1,
        "speed_factor": 1.0,
        "fragment_interval": 0.3,
        "seed": 42,
        "return_fragment": False,
        "repetition_penalty": 1.35,
        "parallel_infer": False,
    }
    if (
        profile.get("parameters") != expected
        or profile.get("prompt_text") != "主人，你可以睁眼了。"
    ):
        raise ValueError("当前参数与用户选定试听的生成参数不一致")
    items = [profile["reference"], profile["accepted_sample"]]
    if check_weights:
        items += [profile["gpt"], profile["sovits"]]
    for item in items:
        path = Path(item["path"])
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("用户选定声音的文件缺失或摘要不一致：" + path.name)
    return profile
