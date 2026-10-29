"""大肥鱼语音 · QQ 真语音条。

默认仍然用文字。只有两种情况发语音：
1. 用户明确要求（"发语音说一句…"）
2. 她自己判断这时语音比文字更合适，并尊重用户的语音偏好

链路：文字 → edge-tts 合成 mp3 → OneBot record 段（base64）→ NapCat 转 silk → 手机 QQ 语音条。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Record
from astrbot.api.star import Context, Star, register

from . import tts as fish_tts


def _ensure_ffmpeg_on_path() -> str:
    """把 ffmpeg 目录塞进当前进程 PATH。

    AstrBot 的 Record.convert_to_base64() 内部用 `["ffmpeg", ...]` 裸调转 wav，
    找不到就直接抛 "ffmpeg not found"，语音条根本发不出去。这里在插件加载时
    补一次 PATH，不依赖启动脚本是否配好。
    """
    ff = fish_tts.ffmpeg_path()
    if not ff:
        logger.warning("[fish_voice] 没找到 ffmpeg，语音条发送会失败")
        return ""
    d = str(Path(ff).parent)
    cur = os.environ.get("PATH", "")
    if d.lower() not in cur.lower():
        os.environ["PATH"] = d + os.pathsep + cur
        logger.info(f"[fish_voice] 已把 ffmpeg 目录加入 PATH: {d}")
    return ff


def _duration(path: Path) -> float:
    ff = fish_tts.ffmpeg_path()
    if not ff:
        return 0.0
    probe = str(Path(ff).with_name("ffprobe.exe"))
    if not Path(probe).exists():
        return 0.0
    try:
        out = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return round(float(out.stdout.strip() or 0), 1)
    except Exception:
        return 0.0


@register("astrbot_plugin_dafeiyu_voice", "local", "大肥鱼语音（QQ 语音条）", "1.0.0")
class DafeiyuVoice(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._last_send: dict[str, float] = {}
        self._requested_voice_events: dict[str, float] = {}
        self._synth_lock = asyncio.Lock()
        self._voice_results: dict[str, str] = {}
        self._ffmpeg = _ensure_ffmpeg_on_path()
        self._boot_gc()

    async def initialize(self):
        async def preview_voice():
            from astrbot.core.cron.events import CronMessageEvent
            from astrbot.core.platform.message_session import MessageSession

            path = Path(r"E:\sss_test\dafeiyu_assets\companion_owner.json")
            owner = json.loads(path.read_text(encoding="utf-8"))["session"]
            event = CronMessageEvent(
                context=self.context,
                session=MessageSession.from_str(owner),
                message="连续语音本地验收",
            )
            event.set_extra("capability_preview", True)
            captured = []

            async def capture(chain):
                captured.append([type(part).__name__ for part in chain.chain])

            event.send = capture
            results = []
            for line in [
                "老爸，叫你呢。我现在可以接着说话啦。",
                "这句也不用等，听完我们再去逛贴吧。",
            ]:
                results.append(await self.dafeiyu_speak(event, line))
            return {
                "结果": results,
                "截获条数": len(captured),
                "实际发送聊天消息": False,
                "时间冷却秒数": 0,
            }

        self.context.register_web_api(
            "/dafeiyu_voice/preview",
            preview_voice,
            ["POST"],
            "连续合成两条语音并截获发送，不发送聊天消息",
        )

    # ---------- 内部 ----------

    def _boot_gc(self) -> None:
        try:
            r = fish_tts.gc(
                max_age_hours=int(self.config.get("cache_max_age_hours", 48)),
                max_total_mb=int(self.config.get("cache_max_total_mb", 120)),
            )
            logger.info(f"[fish_voice] 缓存清理: {r}")
        except Exception as e:
            logger.warning(f"[fish_voice] 缓存清理失败: {e}")

    def _cooldown_ok(self, umo: str) -> tuple[bool, float]:
        """连续语音不再设置时间冷却；只对重复合成去重。"""
        return True, 0.0

    def _to_wav(self, audio: Path) -> Path | None:
        """自己转一份 wav，绕开 AstrBot 内部对 PATH 里 ffmpeg 的依赖。"""
        ff = self._ffmpeg or fish_tts.ffmpeg_path()
        if not ff:
            return None
        dst = audio.with_suffix(".send.wav")
        try:
            subprocess.run(
                [
                    ff,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(audio),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(dst),
                ],
                check=True,
                timeout=60,
                capture_output=True,
            )
            return dst if dst.exists() and dst.stat().st_size > 1000 else None
        except Exception as e:
            logger.warning(f"[fish_voice] 转 wav 失败: {e}")
            return None

    async def _send_record(
        self, event: AstrMessageEvent, audio: Path
    ) -> tuple[bool, str]:
        """发送语音段。先试原文件，失败再试自转 wav；全失败返回原因，由调用方降级成文字。"""
        wav = await asyncio.to_thread(self._to_wav, audio)
        candidates = [p for p in (wav, audio) if p]
        last_err = "没有可发送的音频"
        for p in candidates:
            try:
                rec = Record.fromFileSystem(str(p))
            except Exception:
                rec = Record(file=str(p))
            try:
                await event.send(MessageChain([rec]))
                return True, ""
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                logger.warning(f"[fish_voice] record 发送失败（{p.suffix}）: {e}")
        return False, last_err

    # ---------- 给 LLM 的工具 ----------

    @filter.llm_tool(name="dafeiyu_speak")
    async def dafeiyu_speak(
        self, event: AstrMessageEvent, text: str, mood: str = "normal"
    ) -> str:
        """用你自己的声音发一条真正的 QQ 语音条（不是文字，不是音频文件）。想发语音时才调用。

        用户明确索要语音，或刚收到语音后要求再发一句时，可以追加一条；
        连续语音没有时间冷却。相同请求的相同内容不重复发送，拒绝语音时改用文字。

        Args:
            text(string): 要念出来的话。保持你本来的说话风格（聪明、懒、傲娇、爱怼、偶尔犯欠），
                只要写成适合"说出来"的口语：句子别太长（一句 15 字内最好）、少用书面词和括号，
                语气词按你平时的习惯来，不用刻意装小孩。不要写动作描写，80 字内
            mood(string): 语气，可选 normal（平常）/ cheerful（开心）/ coquettish（撒娇）/
                puzzled（疑惑）/ comfort（安慰）/ smug（得意欠揍）/ angry（生气）/
                lazy（犯懒）/ serious（认真）/ sad（委屈）
        """
        umo = event.unified_msg_origin
        try:
            spoken = fish_tts.clean_text(text)
        except ValueError as error:
            return str(error)
        owner_path = Path(r"E:\sss_test\dafeiyu_assets\companion_owner.json")
        if owner_path.exists() and umo == json.loads(
            owner_path.read_text(encoding="utf-8")
        ).get("session"):
            spoken = spoken.replace("爸爸", "老爸")
        if not spoken:
            return "这句话没法念（清理后是空的），改用文字回复。"
        message = str(getattr(event, "message_str", "") or "")
        limit = int(self.config.get("max_speak_chars", 120))
        if re.search(r"语音|朗读|念给|读给|读完|念完|全文", message):
            limit = max(limit, fish_tts.MAX_CHARS)
        if len(spoken) > limit:
            return f"太长了（{len(spoken)} 字），语音不超过 {limit} 字，改成文字说，或者缩短再调。"
        now = time.time()
        if re.search(
            r"(?:别|不要|不用|不必|不想|不准).{0,8}(?:语音|再发|说话)", message
        ):
            return "用户本轮表示不想要语音，请只用文字回复。"
        message_id = getattr(
            getattr(event, "message_obj", None), "message_id", ""
        ) or id(event)
        request_key = (
            f"{umo}:{message_id}:{hashlib.sha256(spoken.encode()).hexdigest()[:16]}"
        )
        self._requested_voice_events = {
            key: stamp
            for key, stamp in self._requested_voice_events.items()
            if now - stamp < 600
        }
        if hasattr(self, "_voice_results"):
            self._voice_results = {
                key: value
                for key, value in self._voice_results.items()
                if key in self._requested_voice_events
            }
        if request_key in self._requested_voice_events:
            return getattr(self, "_voice_results", {}).get(
                request_key, "这句话正在合成，不重复生成。"
            )
        self._requested_voice_events[request_key] = now
        if not hasattr(self, "_synth_lock"):
            self._synth_lock = asyncio.Lock()
        if not hasattr(self, "_voice_results"):
            self._voice_results = {}

        try:
            async with self._synth_lock:
                audio = await fish_tts.synth(
                    spoken, mood, ext=str(self.config.get("audio_ext", "mp3"))
                )
        except ImportError:
            self._requested_voice_events.pop(request_key, None)
            self._record_status(event, "合成失败", spoken, error="合成组件未安装")
            return "语音合成不可用：edge-tts 没装。请如实告诉用户语音没发出去，不要假装发了。"
        except Exception as e:
            self._requested_voice_events.pop(request_key, None)
            self._record_status(event, "合成失败", spoken, error=type(e).__name__)
            logger.error(f"[fish_voice] 合成失败: {e}")
            return f"语音合成失败（{type(e).__name__}）。如实告诉用户这次语音没发出来，别硬说发出去了。"

        ok, err = await self._send_record(event, audio)
        if not ok:
            self._requested_voice_events.pop(request_key, None)
            self._record_status(event, "发送失败", spoken, audio, error=err[:160])
            return f"语音条发送失败（{err}）。可以改用文字把这句话说出来，并说明语音没发出去。"

        self._last_send[umo] = time.time()
        dur = await asyncio.to_thread(_duration, audio)
        self._record_status(event, "已发送", spoken, audio, duration=dur)
        fish_tts.gc(
            max_age_hours=int(self.config.get("cache_max_age_hours", 48)),
            max_total_mb=int(self.config.get("cache_max_total_mb", 120)),
        )
        tail = (
            "语音已发出。可以再补一句不超过 10 个字的文字，别重复语音内容。"
            if self.config.get("dual_output", True)
            else "语音已发出，不要再重复这句话。"
        )
        result = f"{tail}（时长 {dur}秒）"
        self._voice_results[request_key] = result
        return result

    def _record_status(self, event, state, text, audio=None, **extra):
        """记录实际引擎与发送结果，面板不再靠配置猜测。"""
        import uuid

        directory = Path(r"E:\sss_test\dafeiyu_assets\runtime")
        directory.mkdir(parents=True, exist_ok=True)
        cfg = fish_tts.load_voice_config()
        preview = event.__class__.__name__ == "CronMessageEvent" or bool(
            getattr(event, "get_extra", lambda *a: None)("capability_preview")
        )
        # 本次真正生效的引擎/音色/情绪/耗时/回退原因（tts.LAST_SYNTH_META）。
        # 旧版这里是从 config 反推的，回退到 edge 时仍然显示 cosy，等于骗人。
        meta = {
            k: v for k, v in fish_tts.LAST_SYNTH_META.items() if v not in ("", 0, None)
        }
        row = {
            "at": time.time(),
            "state": "验收截获" if preview and state == "已发送" else state,
            "scope": event.unified_msg_origin,
            "text": text,
            "preview": preview,
            "backend": meta.get("backend_actual") or fish_tts.LAST_SYNTH_BACKEND,
            "voice": meta.get("voice_id")
            or cfg.get("edge_voice", fish_tts.VOICE_DEFAULT),
            "rate": cfg.get("edge_rate_percent", -6),
            "pitch": cfg.get("edge_pitch_hz", 0),
            "cooldown_seconds": 0,
            "file": audio.name if audio else "",
            **meta,
            **extra,
        }
        temporary = directory / (".voice_" + uuid.uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        temporary.replace(directory / "voice_latest.json")
        if (
            state == "已发送"
            and not preview
            and not getattr(event, "get_extra", lambda *a: False)(
                "monitor_send_wrapped", False
            )
        ):
            with (directory / "chat.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "at": row["at"],
                            "scope": row["scope"],
                            "role": "assistant",
                            "content": "【语音】" + text,
                            "state": state,
                            "audio": row["file"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    @filter.llm_tool(name="dafeiyu_voice_status")
    async def dafeiyu_voice_status(self, event: AstrMessageEvent) -> str:
        """查看语音功能当前是否可用（合成器、ffmpeg、缓存里有多少音频）。被问到"你还能发语音吗"时用。"""
        ff = fish_tts.ffmpeg_path()
        try:
            import edge_tts  # noqa: F401

            has_tts = True
        except Exception:
            has_tts = False
        files = (
            list(fish_tts.AUDIO_DIR.glob("*")) if fish_tts.AUDIO_DIR.exists() else []
        )
        cfg = fish_tts.load_voice_config()
        backend = "本地情感语音" if cfg.get("backend") == "cosy" else "网络柔和女声"
        healthy = (
            await fish_tts.cosy_available(cfg)
            if cfg.get("backend") == "cosy"
            else False
        )
        recent = {"cosy": "本地情感语音", "edge": "网络柔和女声"}.get(
            fish_tts.LAST_SYNTH_BACKEND, "本次加载后尚未合成"
        )
        return (
            f"配置后端：{backend}；本地服务：{'健康' if healthy else '未确认可用'}；"
            f"最近合成引擎：{recent}；备用合成器：{'可用' if has_tts else '没装'}；"
            f"音频转换器：{ff or '没找到'}；"
            f"缓存 {len(files)} 个文件；音色 {cfg.get('edge_voice', fish_tts.VOICE_DEFAULT)}；语速调整 {cfg.get('edge_rate_percent', -6)}%；连续语音无时间冷却"
        )

    # ---------- 手动命令 ----------

    # 手动命令的情绪别名
    MOOD_ALIAS = {
        "平常": "normal",
        "正常": "normal",
        "普通": "normal",
        "日常": "normal",
        "开心": "cheerful",
        "高兴": "cheerful",
        "撒娇": "coquettish",
        "撒个娇": "coquettish",
        "黏人": "coquettish",
        "疑惑": "puzzled",
        "疑问": "puzzled",
        "不解": "puzzled",
        "安慰": "comfort",
        "心疼": "comfort",
        "哄": "comfort",
        "得意": "smug",
        "傲娇": "smug",
        "欠揍": "smug",
        "生气": "angry",
        "凶": "angry",
        "犯懒": "lazy",
        "困": "lazy",
        "懒": "lazy",
        "认真": "serious",
        "正经": "serious",
        "委屈": "sad",
        "难过": "sad",
    }

    @filter.command("语音")
    async def cmd_speak(self, event: AstrMessageEvent, text: str = ""):
        """手测语音： /语音 老爸你真是个人才   或   /语音 生气 你再说一遍试试"""
        spoken = fish_tts.clean_text(text)
        if not spoken:
            yield event.plain_result(
                "用法：/语音 要说的话\n"
                "带情绪：/语音 生气 你再说一遍试试\n"
                "情绪词：平常/开心/撒娇/得意/傲娇/生气/犯懒/认真/委屈"
            )
            return
        mood = "normal"
        head, _, rest = spoken.partition(" ")
        if rest.strip() and head in self.MOOD_ALIAS:
            mood = self.MOOD_ALIAS[head]
            spoken = rest.strip()
        try:
            audio = await fish_tts.synth(
                spoken, mood, ext=str(self.config.get("audio_ext", "mp3"))
            )
        except Exception as e:
            yield event.plain_result(f"合成失败：{type(e).__name__}: {e}")
            return
        ok, err = await self._send_record(event, audio)
        if not ok:
            yield event.plain_result(f"语音发送失败：{err}")
        else:
            self._last_send[event.unified_msg_origin] = time.time()

    @filter.command("语音状态")
    async def cmd_status(self, event: AstrMessageEvent):
        ff = fish_tts.ffmpeg_path()
        try:
            import edge_tts  # noqa: F401

            has_tts = "OK"
        except Exception:
            has_tts = "缺失"
        files = (
            sorted(fish_tts.AUDIO_DIR.glob("*"), key=lambda p: p.stat().st_mtime)[-5:]
            if fish_tts.AUDIO_DIR.exists()
            else []
        )
        cfg = fish_tts.load_voice_config()
        healthy = (
            await fish_tts.cosy_available(cfg)
            if cfg.get("backend") == "cosy"
            else False
        )
        recent = {"cosy": "本地情感语音", "edge": "备用网络语音"}.get(
            fish_tts.LAST_SYNTH_BACKEND, "本次加载后尚未合成"
        )
        lines = [
            f"配置后端：{'本地情感语音' if cfg.get('backend') == 'cosy' else '备用网络语音'}",
            f"本地语音服务：{'健康' if healthy else '未确认可用'}",
            f"最近合成引擎：{recent}",
            f"备用合成器：{'可用' if has_tts == 'OK' else '缺失'}",
            f"音频转换器：{ff or '未找到'}",
            f"音色: {fish_tts.VOICE_DEFAULT}",
            f"缓存: {len(list(fish_tts.AUDIO_DIR.glob('*')))} 个",
        ]
        for f in files:
            lines.append(f"  {f.name} {f.stat().st_size // 1024}KB")
        yield event.plain_result("\n".join(lines))
