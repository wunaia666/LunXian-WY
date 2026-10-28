"""真实电脑桌面的观察与输入校验，复用已有鼠标键盘执行器。"""

from __future__ import annotations

import io
import json
import time
import uuid
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(r"E:\sss_test")
BLOCKED = {"qq", "weixin", "wechat", "wxwork", "dnplayer", "ldplayer"}
INPUTS = {"move", "click", "drag", "scroll", "type", "key", "hotkey"}


def capture():
    """压缩真实电脑桌面，返回原始大小以准确换算坐标。"""
    image = ImageGrab.grab(all_screens=True)
    original = image.size
    image.thumbnail((1568, 1568))
    stream = io.BytesIO()
    image.convert("RGB").save(stream, format="JPEG", quality=80)
    return stream.getvalue(), original, image.size


class DesktopSession:
    def __init__(self, root=ROOT):
        self.root = root
        self.observation = None

    async def bridge(self, run, action, parameters=None):
        command = [
            "powershell.exe",
            "-NoProfile",
            "-File",
            str(self.root / "tools/gui-control.ps1"),
            "-Action",
            action,
        ]
        for key, value in (parameters or {}).items():
            command.extend(["-" + key, str(value)])
        result = await run(command, self.root, 20)
        if result["退出码"] != 0 or result.get("超时"):
            raise RuntimeError("电脑执行器未正常返回")
        value = json.loads(result["输出"])
        if value.get("ok") is not True:
            raise RuntimeError(value.get("error", "电脑动作未成功"))
        return value

    def save(self, value, image=None):
        folder = self.root / "dafeiyu_assets/runtime"
        folder.mkdir(parents=True, exist_ok=True)
        if image is not None:
            temporary = folder / "desktop_latest.tmp"
            temporary.write_bytes(image)
            temporary.replace(folder / "desktop_latest.jpg")
        temporary = folder / "desktop_latest.json.tmp"
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(folder / "desktop_latest.json")

    async def observe(self, run):
        import asyncio

        before = await self.bridge(run, "info")
        image, original, preview = await asyncio.to_thread(capture)
        after = await self.bridge(run, "info")
        if (
            before["foreground"] != after["foreground"]
            or before["virtualDesktop"] != after["virtualDesktop"]
        ):
            raise ValueError("截图期间窗口发生变化，请重新观察电脑")
        desktop = after["virtualDesktop"]
        if tuple(original) != (desktop["width"], desktop["height"]):
            raise ValueError("截图和桌面坐标范围不一致，本轮禁止输入")
        value = {
            "来源": "真实电脑桌面",
            "观察编号": uuid.uuid4().hex,
            "时间": time.time(),
            "前台窗口": after["foreground"],
            "桌面范围": desktop,
            "原始尺寸": original,
            "图片尺寸": preview,
            "坐标说明": "默认使用本次图片坐标，系统会换算到真实电脑坐标；每次动作后重新观察。",
        }
        self.observation = value
        self.save(value, image)
        return value, image

    async def windows(self, run):
        value = await self.bridge(run, "windows")
        result = {
            "来源": "真实电脑窗口",
            "观察编号": uuid.uuid4().hex,
            "时间": time.time(),
            "窗口": value.get("windows", []),
        }
        self.observation = result
        self.save(result)
        return result

    def validate(self, action, parameters):
        if not isinstance(parameters, dict):
            raise ValueError("电脑参数必须是对象")
        valid = {
            "X",
            "Y",
            "ToX",
            "ToY",
            "Button",
            "Count",
            "Delta",
            "DurationMs",
            "Text",
            "Key",
            "Keys",
            "ExpectTitle",
            "Window",
            "ProcessId",
            "ObservationId",
            "CoordinateSpace",
        }
        if set(parameters) - valid:
            raise ValueError("电脑参数包含不支持的字段")
        observation = self.observation
        if (
            not observation
            or parameters.get("ObservationId") != observation["观察编号"]
            or time.time() - observation["时间"] > 60
        ):
            raise ValueError("请先重新观察真实电脑，并提供本次观察编号")
        return observation

    @staticmethod
    def check_window(window):
        process = str(window.get("process", "")).lower().removesuffix(".exe")
        if process in BLOCKED:
            raise ValueError("当前窗口为聊天客户端或模拟器，请选择要操作的电脑软件窗口")

    async def act(self, run, action, parameters):
        observation = self.validate(action, parameters)
        self.observation = None
        arguments = dict(parameters)
        arguments.pop("ObservationId", None)
        space = arguments.pop("CoordinateSpace", "image")
        if action == "activate":
            choices = [
                w
                for w in observation.get("窗口", [])
                if str(w["pid"]) == str(arguments.get("ProcessId"))
            ]
            if len(choices) != 1:
                raise ValueError("只能激活本次窗口列表中唯一的进程编号")
            self.check_window(choices[0])
            return await self.bridge(run, action, {"ProcessId": choices[0]["pid"]})
        if action not in INPUTS or "前台窗口" not in observation:
            raise ValueError("输入前必须观察电脑画面")
        expected = observation["前台窗口"]
        self.check_window(expected)
        if arguments.get("ExpectTitle") != expected["title"] or not expected["title"]:
            raise ValueError("输入必须绑定本次观察到的完整窗口标题")
        current = await self.bridge(run, "info")
        if (
            current["foreground"] != expected
            or current["virtualDesktop"] != observation["桌面范围"]
        ):
            raise ValueError("前台窗口或桌面范围已改变，本轮未输入")
        arguments["ExpectProcessId"] = expected["pid"]
        arguments["LiteralTitle"] = "true"
        desktop = observation["桌面范围"]
        width, height = observation["图片尺寸"]
        if space not in {"image", "desktop"}:
            raise ValueError("坐标空间只能选择图片或桌面")
        for first, second in (("X", "Y"), ("ToX", "ToY")):
            if first in arguments or second in arguments:
                x, y = arguments.get(first), arguments.get(second)
                if type(x) is not int or type(y) is not int:
                    raise ValueError("必须同时提供整数横纵坐标")
                if space == "image":
                    if not (0 <= x < width and 0 <= y < height):
                        raise ValueError("坐标超出本次电脑截图")
                    x = desktop["x"] + int(x * desktop["width"] / width)
                    y = desktop["y"] + int(y * desktop["height"] / height)
                if not (
                    desktop["x"] <= x < desktop["x"] + desktop["width"]
                    and desktop["y"] <= y < desktop["y"] + desktop["height"]
                ):
                    raise ValueError("坐标超出真实电脑桌面")
                arguments[first], arguments[second] = x, y
        if (
            action in {"click", "move", "drag", "scroll"}
            and not {"X", "Y"} <= arguments.keys()
        ):
            raise ValueError("鼠标动作必须提供本次观察的坐标")
        if action == "drag" and not {"ToX", "ToY"} <= arguments.keys():
            raise ValueError("拖动必须提供终点坐标")
        if "Text" in arguments and len(str(arguments["Text"])) > 4000:
            raise ValueError("单次电脑输入不能超过四千字")
        for name, minimum, maximum in (
            ("Count", 1, 3),
            ("Delta", -8, 8),
            ("DurationMs", 1, 3000),
        ):
            if name in arguments and (
                type(arguments[name]) is not int
                or not minimum <= arguments[name] <= maximum
            ):
                raise ValueError("鼠标参数超出单次动作范围")
        return await self.bridge(run, action, arguments)
