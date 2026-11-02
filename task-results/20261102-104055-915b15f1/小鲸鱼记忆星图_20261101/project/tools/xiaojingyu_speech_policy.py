"""为偶尔主动语音提供持久化限频，明确索要与网页手动生成可按需继续。"""

import json
import re
import time
from pathlib import Path

STATE = Path(r"E:\sss_test\dafeiyu_assets\runtime\speech_usage.json")
REQUEST = re.compile(r"语音|朗读|念给|读给|读完|念完|全文|说给我听|再说一句|再来一句")


def speech_allowed(scope, message, config, preview=False, now=None):
    """未明确索要时按会话限频；读取异常时保守地使用文字。"""
    if preview or REQUEST.search(message):
        return True, "明确请求或本地试听"
    policy = config.get("speech_policy", "occasional")
    if policy == "on_request":
        return False, "平时使用文字，需要语音时可明确提出或点击网页生成"
    now = time.time() if now is None else now
    interval = max(300, int(config.get("spontaneous_voice_interval_seconds", 1800)))
    try:
        state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        if not isinstance(state, dict):
            raise ValueError("记录格式异常")
        usage = state.get(scope, {})
        if not isinstance(usage, dict):
            raise ValueError("会话记录格式异常")
        previous = float(usage.get("last_sent", 0))
    except (OSError, ValueError, TypeError):
        return False, "语音使用记录暂不可读，本轮请用文字"
    if (
        previous > 0
        and 0 <= now - previous <= 600
        and re.fullmatch(
            r"(?:继续|接着说|再说|再来一条|再来一句|再发一条)[。！!\s]*",
            message.strip(),
        )
    ):
        return True, "用户要求继续刚才的语音"
    if now - previous < interval:
        return False, "平时以文字为主，距离上一条语音还较近；用户明确索要时可以继续"
    return True, "允许偶尔主动语音"


def mark_speech_sent(scope, now=None):
    """仅实际发送成功后记录；试听不占用主动语音次数。"""
    try:
        value = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    value[scope] = {"last_sent": time.time() if now is None else now}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATE)
