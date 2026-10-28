"""只修改小鲸鱼自己的角色昵称、签名和已确认的角色头像。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

BASE = Path(r"E:\sss_test\dafeiyu_assets")
ACCOUNT = "3768021466"
AVATAR = BASE / "base_ref.png"
STATE = BASE / "public_profile.json"


class PublicProfile:
    """角色资料可以自选，账号安全、真实身份资料不在此接口内。"""

    def __init__(self, context):
        self.context = context
        self.lock = asyncio.Lock()

    def owner(self) -> str:
        return json.loads((BASE / "companion_owner.json").read_text(encoding="utf-8"))[
            "session"
        ]

    def status(self) -> dict:
        return (
            json.loads(STATE.read_text(encoding="utf-8"))
            if STATE.exists()
            else {"资料已设置": False}
        )

    async def inspect_avatar(self):
        """从固定的官方头像地址取当前公开图片，不使用本地角色参考图冒充。"""
        import base64
        import hashlib
        import io

        import httpx
        from mcp.types import CallToolResult, ImageContent, TextContent
        from PIL import Image

        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(
                "https://q1.qlogo.cn/g",
                params={"b": "qq", "nk": ACCOUNT, "s": 640},
                headers={"Cache-Control": "no-cache"},
            )
            response.raise_for_status()
            if len(response.content) > 5 * 1024 * 1024:
                raise ValueError("头像文件过大")
        with Image.open(io.BytesIO(response.content)) as original:
            picture = original.convert("RGB")
            picture.thumbnail((1024, 1024))
            buffer = io.BytesIO()
            picture.save(buffer, "JPEG", quality=82)
        folder = BASE / "profile_observations"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "当前线上头像.jpg").write_bytes(buffer.getvalue())
        evidence = {
            "来源": "官方公开头像接口本次返回",
            "获取时间": time.time(),
            "图片摘要": hashlib.sha256(response.content).hexdigest(),
            "说明": "这是本次联网取得的公开头像；可能受平台缓存影响，不等于客户端已登录",
        }
        (folder / "avatar.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(evidence, ensure_ascii=False)),
                ImageContent(
                    type="image",
                    mimeType="image/jpeg",
                    data=base64.b64encode(buffer.getvalue()).decode(),
                ),
            ]
        )

    async def apply(
        self, nickname: str, personal_note: str, use_character_avatar: bool = False
    ) -> dict:
        """只向已经绑定的机器人账号提交有限的角色公开资料。"""
        transport = BASE / "chat_transport.json"
        if (
            transport.exists()
            and json.loads(transport.read_text(encoding="utf-8")).get("mode")
            == "qq_official"
        ):
            raise RuntimeError(
                "已切换官方机器人，个人账号资料接口保持关闭；官方资料须按开发平台支持的方式设置"
            )
        nickname, personal_note = nickname.strip(), personal_note.strip()
        if not 1 <= len(nickname) <= 20 or len(personal_note) > 80:
            raise ValueError("昵称须为一至二十字，签名最多八十字")
        if any(
            re.search(r"https?://|\d{7,}|[\r\n]", text)
            for text in [nickname, personal_note]
        ):
            raise ValueError("角色资料不能包含链接、联系方式或多行内容")
        async with self.lock:
            state = self.status()
            if (
                state.get("昵称") == nickname
                and state.get("签名") == personal_note
                and not use_character_avatar
            ):
                return {**state, "说明": "当前已经是这份资料，无须重复提交"}
            platform = self.context.get_platform_inst("napcat")
            if platform is None:
                raise RuntimeError("聊天连接尚未加载")
            bot = platform.get_client()
            login = await bot.call_action("get_login_info")
            if str(login.get("user_id")) != ACCOUNT:
                raise RuntimeError("当前登录的不是绑定的小鲸鱼账号，未修改资料")
            before = BASE / "public_profile_before.json"
            if not before.exists():
                before.write_text(
                    json.dumps(
                        {"nickname": login.get("nickname", "")}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
            await bot.call_action(
                "set_qq_profile", nickname=nickname, personal_note=personal_note
            )
            actual = await bot.call_action("get_login_info")
            if actual.get("nickname") != nickname:
                raise RuntimeError("尚未读到提交后的昵称，未标记资料设置成功")
            state = {
                "资料已设置": True,
                "昵称": nickname,
                "签名": personal_note,
                "昵称已回读": True,
                "签名状态": "接口已接受，等待独立回读",
                "头像状态": "保留当前头像",
                "更新时间戳": time.time(),
            }
            try:
                info = await bot.call_action(
                    "get_stranger_info", user_id=int(ACCOUNT), no_cache=True
                )
                if any(
                    info.get(key) == personal_note
                    for key in [
                        "long_nick",
                        "longNick",
                        "personal_note",
                        "sign",
                        "signature",
                    ]
                ):
                    state["签名状态"] = "已回读确认"
            except Exception:
                pass
            if use_character_avatar:
                try:
                    await bot.call_action("set_qq_avatar", file=AVATAR.as_uri())
                    state["头像状态"] = "角色头像接口已接受，等待客户端显示"
                except Exception as error:
                    state["头像状态"] = "头像未确认更新：" + type(error).__name__
            STATE.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return state

    async def choose(self) -> dict:
        """由现有聊天模型按原人设决定资料，不使用好友资料和聊天记录。"""
        transport = BASE / "chat_transport.json"
        if (
            transport.exists()
            and json.loads(transport.read_text(encoding="utf-8")).get("mode")
            == "qq_official"
        ):
            return {
                "当前通道": "官方机器人",
                "官方资料已设置": False,
                "说明": "原个人小号的头像昵称不会自动成为官方机器人资料，请在官方开发平台按要求设置",
            }
        if self.status().get("资料已设置"):
            return self.status()
        owner = self.owner()
        provider = await self.context.get_using_provider_async(umo=owner)
        if provider is None:
            raise RuntimeError("聊天模型尚未连接")
        config = self.context.get_config(umo=owner)
        persona_id = (
            config.get("agent_runner", {})
            .get("config", {})
            .get("persona", {})
            .get("persona_id", "default")
        )
        persona = await self.context.persona_manager.get_persona(persona_id)
        response = await asyncio.wait_for(
            provider.text_chat(
                prompt=(
                    "老爸已经授权你自己设置这个角色账号的公开资料。当前注册昵称是小鲸鱼，优先沿用这个名字。"
                    "按你现有的性格，自选一句自然的中文个性签名，最多四十字，不像工作汇报。"
                    "头像可选已存在的蓝发鲸鱼女孩角色参考图。不要编造真实年龄、生日、学校、地址、职业和联系方式。"
                    "只输出一个对象，字段 nickname、personal_note、use_character_avatar（布尔）。"
                ),
                system_prompt=persona.system_prompt
                + "\n当前对话对象称呼为老爸。现在只选择角色公开资料，不发送聊天消息，不执行其他操作。",
                contexts=[],
            ),
            timeout=75,
        )
        text = response.completion_text or ""
        match = re.search(r"\{.*\}", text, re.S)
        selected = json.loads(match.group(0) if match else text)
        return await self.apply(
            str(selected.get("nickname", "")),
            str(selected.get("personal_note", "")),
            selected.get("use_character_avatar") is True,
        )
