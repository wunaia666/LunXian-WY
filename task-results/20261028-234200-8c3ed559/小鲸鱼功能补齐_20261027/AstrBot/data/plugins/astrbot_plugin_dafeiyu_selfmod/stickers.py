"""收藏当前私聊收到的原图，按编号或名字取回，保留动图原文件。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
from pathlib import Path

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Image, Reply
from PIL import Image as RasterImage

BASE = Path(r"E:\sss_test\dafeiyu_assets")
MOODS = {
    "happy",
    "confused",
    "shocked",
    "angry",
    "smug",
    "sad",
    "neutral",
    "speechless",
    "excited",
    "sleepy",
}
CATALOG_LOCKS = {}


class StickerLibrary:
    """只收藏绑定私聊的图片，不接受模型提供的任意路径或网址。"""

    def __init__(self, context, memory, base: Path = BASE):
        self.context = context
        self.memory = memory
        self.base = base
        self.root = base / "collected_emojis"
        self.catalog = self.root / "catalog.json"
        # 聊天收藏与手机原图收藏共用目录锁，避免同时保存时覆盖索引。
        self.lock = CATALOG_LOCKS.setdefault(str(self.root.resolve()), asyncio.Lock())

    def owner(self) -> str:
        """读取已经绑定的老爸私聊。"""
        path = self.base / "companion_owner.json"
        return (
            json.loads(path.read_text(encoding="utf-8")).get("session", "")
            if path.exists()
            else ""
        )

    def rows(self, scope: str) -> list[dict]:
        """返回当前会话有权读取、且文件仍存在的收藏。"""
        if not self.catalog.exists():
            return []
        rows = json.loads(self.catalog.read_text(encoding="utf-8"))
        return [
            row
            for row in rows
            if row.get("scope") == scope
            and Path(row["path"]).resolve().is_relative_to(self.root.resolve())
            and Path(row["path"]).is_file()
        ]

    async def capture(self, event) -> None:
        """仅记录收到的图片引用；永久收藏仍需明确调用收藏工具。"""
        if event.unified_msg_origin != self.owner() or event.get_group_id():
            return
        images = [part for part in event.get_messages() if isinstance(part, Image)]
        if images:
            part = images[-1]
            self.memory.put(
                event.unified_msg_origin,
                "latest_received_image",
                {
                    "file": part.file,
                    "url": part.url,
                    "ts": time.time(),
                    "message_id": str(event.message_obj.message_id),
                },
            )

    async def received_image(
        self, event, name: str = "", mood: str = "neutral", message_id: str = ""
    ) -> dict:
        """收藏当前图片、引用图片，或本会话最近收到的一张图片。"""
        scope = event.unified_msg_origin
        if scope != self.owner() or event.get_group_id():
            raise ValueError("只允许老爸在绑定私聊中收藏表情包")
        if mood not in MOODS:
            raise ValueError("这个情绪分类不存在")
        if message_id and not message_id.lstrip("-").isdigit():
            raise ValueError("图片消息编号格式不正确")
        parts = event.get_messages()
        images = [part for part in parts if isinstance(part, Image)]
        if not images:
            images = [
                child
                for part in parts
                if isinstance(part, Reply)
                for child in (part.chain or [])
                if isinstance(child, Image)
            ]
        image = images[-1] if images else None
        source_id = str(event.message_obj.message_id)
        if image is None and not message_id:
            recent = self.memory.get(scope, "latest_received_image", {})
            if recent and time.time() - recent.get("ts", 0) < 86400:
                image = Image(file=recent.get("file", ""), url=recent.get("url", ""))
                source_id = recent.get("message_id", "")
        if image is None:
            bot = getattr(event, "bot", None)
            if bot is None:
                platform = self.context.get_platform_inst(event.get_platform_id())
                bot = platform.get_client() if platform else None
            if bot is not None:
                history = await bot.call_action(
                    "get_friend_msg_history",
                    user_id=int(event.get_sender_id()),
                    count=50,
                )
                candidates = []
                for message in history.get("messages", []):
                    if message_id and str(message.get("message_id", "")) != message_id:
                        continue
                    sender = str(
                        message.get("user_id")
                        or (message.get("sender") or {}).get("user_id", "")
                    )
                    if (
                        sender != str(event.get_sender_id())
                        or time.time() - message.get("time", 0) > 86400
                    ):
                        continue
                    for segment in message.get("message", []):
                        if isinstance(segment, dict) and segment.get("type") == "image":
                            candidates.append((message, segment["data"]))
                if candidates:
                    message, data = max(
                        candidates, key=lambda item: item[0].get("time", 0)
                    )
                    image = Image(file=data.get("url") or data.get("file", ""))
                    source_id = str(message.get("message_id", ""))
        if image is None:
            raise ValueError("没有找到你最近发来的图片，请引用要收藏的原图或再发一次")
        return image, source_id

    async def save(
        self, event, name: str = "", mood: str = "neutral", message_id: str = ""
    ) -> dict:
        """收藏当前图片、引用图片，或本会话最近收到的一张图片。"""
        image, source_id = await self.received_image(event, name, mood, message_id)
        source = Path(await image.convert_to_file_path())
        return await self.import_file(
            event.unified_msg_origin, source, name, mood, source_message_id=source_id
        )

    async def import_file(
        self,
        scope: str,
        source: Path,
        name: str = "",
        mood: str = "neutral",
        source_message_id: str = "",
        source_page: str = "",
    ) -> dict:
        """供已校验的聊天原图或公开浏览原图内部调用，不向模型开放任意文件路径。"""
        if not scope or scope != self.owner() or mood not in MOODS:
            raise ValueError("只允许绑定会话收藏有效分类的图片")
        source_id = source_message_id
        if not source.is_file() or source.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("原图不存在或超过十二兆，未收藏")
        with RasterImage.open(source) as picture:
            image_format = picture.format
            picture.verify()
        suffix = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}.get(
            image_format
        )
        if suffix is None:
            raise ValueError("只收藏常用图片格式")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        identity = digest[:16]
        async with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            rows = (
                json.loads(self.catalog.read_text(encoding="utf-8"))
                if self.catalog.exists()
                else []
            )
            existing = next(
                (
                    row
                    for row in rows
                    if row.get("scope") == scope and row.get("id") == identity
                ),
                None,
            )
            folder = self.root / hashlib.sha256(scope.encode()).hexdigest()[:12]
            folder.mkdir(exist_ok=True)
            target = folder / (digest + suffix)
            if not target.exists():
                shutil.copy2(source, target)
            row = existing or {"id": identity, "scope": scope, "created": time.time()}
            row.update(
                name=(name.strip() or row.get("name") or "老爸发来的表情")[:60],
                mood=mood,
                path=str(target),
                source_message_id=source_id,
                source_page=source_page,
                sha256=digest,
            )
            if existing is None:
                rows.append(row)
            temporary = self.catalog.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.catalog)
            self.memory.remember(
                scope,
                f"已把{'公开浏览原图' if source_page else '老爸发来的图片'}永久收藏为表情包《{row['name']}》，编号{identity}。以后可用发送收藏表情工具取回原图。",
                kind="event",
                source="本地表情库实际保存成功",
            )
            return {
                "收藏成功": True,
                "编号": identity,
                "名称": row["name"],
                "已存在": existing is not None,
                "说明": "原图已保存在本地表情库，尚未发送",
            }

    async def send(self, event, key: str) -> str:
        """只发送当前会话收藏中的图片，找不到或发送失败时不报告成功。"""
        if event.unified_msg_origin != self.owner() or event.get_group_id():
            return "只允许老爸在绑定私聊中使用收藏表情"
        rows = self.rows(event.unified_msg_origin)
        matches = [row for row in rows if row["id"] == key or row["name"] == key]
        if not matches:
            matches = [row for row in rows if key and key in row["name"]]
        if len(matches) != 1:
            return "没有找到唯一对应的收藏，请先查看收藏表情列表"
        row = matches[0]
        await event.send(MessageChain([Image.fromFileSystem(row["path"])]))
        event.set_extra("collected_sticker_sent", True)
        return f"已发送收藏表情《{row['name']}》"
