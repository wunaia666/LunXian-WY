"""空间说说先保存可审阅草稿，只有主人发送确认命令后才发布。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

BASE = Path(r"E:\sss_test\dafeiyu_assets")
ACCOUNT = "3768021466"
RIGHTS = {"所有人": 1, "好友": 4, "仅自己": 64}


class QzonePosts:
    """使用已安装连接程序的原生接口，保存不确定结果以防重复发布。"""

    def __init__(self, context, base: Path = BASE):
        self.context = context
        self.base = base
        self.root = base / "qzone_drafts"
        self.lock = asyncio.Lock()

    def prepare(self, content: str, visibility: str = "好友") -> dict:
        """保存完整正文和可见范围，返回唯一确认编号。"""
        content = content.strip()
        if not 1 <= len(content) <= 2000 or visibility not in RIGHTS:
            raise ValueError("正文须为一至两千字，可见范围须为所有人、好友或仅自己")
        self.root.mkdir(parents=True, exist_ok=True)
        identity = uuid.uuid4().hex[:12]
        draft = {
            "编号": identity,
            "正文": content,
            "可见范围": visibility,
            "状态": "待确认",
            "创建时间": time.time(),
        }
        (self.root / (identity + ".json")).write_text(
            json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            **draft,
            "确认命令": "/确认发布说说 " + identity,
            "说明": "尚未发布；请审阅正文和可见范围后发送确认命令，草稿一天后过期",
        }

    async def publish(self, identity: str) -> dict:
        """只能由主人确认命令调用；超时保留未知状态，不自动重发。"""
        if len(identity) != 12 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("草稿编号无效")
        async with self.lock:
            path = self.root / (identity + ".json")
            draft = json.loads(path.read_text(encoding="utf-8"))
            if draft["状态"] != "待确认":
                return {
                    **draft,
                    "说明": "该草稿已处理，不重复发布；状态不明时请先查空间",
                }
            if time.time() - draft["创建时间"] > 86400:
                raise ValueError("草稿已过期，请重新生成并审阅")
            gateway = json.loads(
                (self.base / "qq_gateway.json").read_text(encoding="utf-8")
            )
            if gateway.get("state") == "paused_by_user":
                raise RuntimeError("聊天接入仍暂停，草稿已保留，未尝试发布或启动客户端")
            platform = self.context.get_platform_inst("napcat")
            if platform is None:
                raise RuntimeError("聊天连接尚未加载")
            bot = platform.get_client()
            login = await asyncio.wait_for(bot.call_action("get_login_info"), 10)
            if str(login.get("user_id")) != ACCOUNT:
                raise RuntimeError("当前账号不是绑定的小鲸鱼账号，未发布")
            draft["状态"] = "提交中，结果待核对"
            path.write_text(
                json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                result = await asyncio.wait_for(
                    bot.call_action(
                        "send_qzone_msg",
                        content=draft["正文"],
                        ugc_right=RIGHTS[draft["可见范围"]],
                    ),
                    40,
                )
                tid = str(result.get("tid") or "")
                if not tid:
                    raise RuntimeError("接口没有返回说说编号")
                draft.update(
                    {
                        "说说编号": tid,
                        "状态": "接口已接受，待回读",
                        "提交时间": time.time(),
                    }
                )
                recent = await asyncio.wait_for(
                    bot.call_action("get_qzone_msg_list", pos=0, num=20), 15
                )
                if any(
                    str(row.get("tid")) == tid and row.get("content") == draft["正文"]
                    for row in recent.get("msglist", [])
                ):
                    draft["状态"] = "已发布并回读正文"
            except Exception as error:
                draft["核对说明"] = (
                    "未确认完整结果：" + type(error).__name__ + "，不会自动重发"
                )
            finally:
                path.write_text(
                    json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            return draft
