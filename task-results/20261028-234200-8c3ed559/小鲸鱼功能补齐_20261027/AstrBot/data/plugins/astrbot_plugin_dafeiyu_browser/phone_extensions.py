"""专用安卓的原图收藏和桌面便签，不开放任意设备命令。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from ..astrbot_plugin_dafeiyu_selfmod.stickers import StickerLibrary

BASE = Path(r"E:\sss_test\dafeiyu_assets")


async def collect_image(
    device, context, memory, owner: str, observation_id: str, image_id: str
) -> dict:
    """仅从刚观察过的贴吧帖子图片调用原图保存，再读取新加入相册的文件。"""
    async with device.lock:
        old = device.observations.get(observation_id)
        if not old or time.time() - old["time"] > 90:
            raise ValueError("图片观察已过期，请重新读屏")
        current = await asyncio.to_thread(device._observe)
        if (
            current["blocked"]
            or current["package"] != "com.baidu.tieba"
            or not current.get("内容详情页")
            or old.get("package") != current["package"]
        ):
            raise ValueError("只保存当前公开帖子详情中的原图")
        previous = next(
            (x for x in old.get("image_targets", []) if x["id"] == image_id), None
        )
        target = next(
            (x for x in current.get("image_targets", []) if x["id"] == image_id), None
        )
        if not target or target != previous:
            raise ValueError("图片位置已经变化，请重新读屏")

        def media_rows():
            data = device._adb(
                "shell",
                "content",
                "query",
                "--uri",
                "content://media/external/images/media",
                "--projection",
                "_id:_data:date_added",
            ).decode("utf-8", "replace")
            rows = {}
            for line in data.splitlines():
                match = re.search(r"_id=(\d+), _data=(.*?), date_added=(\d+)", line)
                if match:
                    rows[match[1]] = match[2]
            return rows

        before = await asyncio.to_thread(media_rows)
        x1, y1, x2, y2 = target["bounds"]
        width, height = current["screen_size"]
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("图片超出屏幕")
        await asyncio.to_thread(
            device._ui.long_click, (x1 + x2) // 2, (y1 + y2) // 2, duration=0.8
        )
        await asyncio.sleep(0.6)
        xml = await asyncio.to_thread(
            device._ui.dump_hierarchy, compressed=False, root_in_active=True
        )
        nodes = list(ET.fromstring(xml).iter("node"))
        # 只响应刚弹出的明确保存项，权限、登录和其他互动按钮一律不点击。
        choices = [
            n
            for n in nodes
            if n.get("text") in {"保存图片", "保存到相册", "保存原图"}
            and n.get("package") == "com.baidu.tieba"
        ]
        if len(choices) != 1:
            raise RuntimeError("没有出现唯一的原图保存菜单，未点击其他按钮")
        bounds = list(map(int, re.findall(r"\d+", choices[0].get("bounds", ""))))
        if len(bounds) != 4 or not (
            0 <= bounds[0] < bounds[2] <= width and 0 <= bounds[1] < bounds[3] <= height
        ):
            raise ValueError("保存菜单位置无效")
        await asyncio.to_thread(
            device._ui.click, (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2
        )
        after = before
        for _ in range(8):
            await asyncio.sleep(0.5)
            after = await asyncio.to_thread(media_rows)
            if set(after) - set(before):
                break
        new_files = [after[key] for key in set(after) - set(before)]
        if len(new_files) != 1:
            raise RuntimeError(
                "未识别到唯一新保存的原图；可能需要相册权限或该图已经保存"
            )
        source = new_files[0]
        if (
            not source.startswith(("/storage/emulated/0/", "/sdcard/"))
            or ".." in Path(source).parts
        ):
            raise ValueError("新图片不在专用安卓相册目录")
        inbox = BASE / "browse_images"
        inbox.mkdir(parents=True, exist_ok=True)
        local = inbox / (uuid.uuid4().hex + Path(source).suffix)
        await asyncio.to_thread(device._adb, "pull", source, str(local), timeout=30)
        page = current.get("当前帖子标题", "当前贴吧帖子")
        result = await StickerLibrary(context, memory).import_file(
            owner,
            local,
            name=page[:40] + "的表情",
            source_page="专用安卓贴吧公开帖子：" + page,
        )
        await asyncio.to_thread(device._observe)
        return result


async def leave_note(device, text: str) -> dict:
    """向本地便签发送有限文本，核对存储摘要和桌面挂件数量。"""
    text = text.strip()
    if not 1 <= len(text) <= 500:
        raise ValueError("手机留言须为一至五百字")
    async with device.lock:
        installed = await asyncio.to_thread(
            device._adb, "shell", "pm", "path", "local.xiaojingyu.note"
        )
        if not installed.strip().startswith(b"package:"):
            raise RuntimeError("专用安卓尚未安装小鲸鱼便签，未假装留言成功")
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        await asyncio.to_thread(
            device._adb,
            "shell",
            "am",
            "broadcast",
            "-n",
            "local.xiaojingyu.note/.NoteReceiver",
            "-a",
            "local.xiaojingyu.note.UPDATE",
            "--es",
            "text_b64",
            encoded,
        )
        state = json.loads(
            (
                await asyncio.to_thread(
                    device._adb,
                    "shell",
                    "run-as",
                    "local.xiaojingyu.note",
                    "cat",
                    "files/note_state.json",
                )
            ).decode("utf-8")
        )
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if state.get("sha256") != expected:
            raise RuntimeError("便签内容回读不一致")
        visible = int(state.get("widgets", 0)) > 0
        result = {
            "已保存": True,
            "桌面挂件已绑定": visible,
            "字数": len(text),
            "说明": "已更新桌面便签，未操作聊天客户端"
            if visible
            else "留言已保存；首次需打开小鲸鱼便签并添加到桌面",
        }
        (BASE / "phone_note_state.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result
