"""按用户启用主动联系的要求验证一次主人私聊，保留平台消息回执。"""

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(r"E:\sss_test")
sys.path.insert(0, str(ROOT / "AstrBot"))


async def main():
    from data.plugins.astrbot_plugin_dafeiyu_browser.companion import AutonomousLife

    settings = json.loads((ROOT / "napcat/shell/config/onebot11_3768021466.json").read_text(encoding="utf-8"))
    endpoint = next(row for row in settings["network"]["httpServers"]
                    if row.get("enable") and row.get("host") in {"127.0.0.1", "localhost"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    async def action(name, **kwargs):
        def request():
            req = urllib.request.Request(f"http://127.0.0.1:{int(endpoint['port'])}/{name}",
                data=json.dumps(kwargs).encode(), headers={"Content-Type": "application/json",
                "Authorization": "Bearer " + endpoint.get("token", "")})
            with opener.open(req, timeout=15) as response:
                result = json.load(response)
            if result.get("retcode") != 0:
                raise RuntimeError("平台没有确认本次操作")
            return result.get("data") or {}
        return await asyncio.to_thread(request)

    config = json.loads((ROOT / "AstrBot/data/config/astrbot_plugin_dafeiyu_browser_config.json").read_text(encoding="utf-8"))
    bot = SimpleNamespace(call_action=action)
    context = SimpleNamespace(get_platform_inst=lambda name: SimpleNamespace(get_client=lambda: bot))
    life = AutonomousLife(SimpleNamespace(context=context, config=config))
    if life.owner != "napcat:FriendMessage:1443192477":
        raise RuntimeError("主人私聊未核实")
    if not life.contact_allowed(time.time()):
        print("当前处于暂停、刚聊过或夜间安静时段，未发送测试消息。")
        return
    if life.store.get(life.owner, "delivery_unknown"):
        raise RuntimeError("已有未确认的发送结果，停止新测试")
    state = life.store.get(life.owner, "novel_current", {})
    name = state.get("书名")
    if not name:
        raise RuntimeError("尚未实际选中书籍，不能声称已选书")
    previous = life.store.get(life.owner, "pending")
    life.store.put(life.owner, "pending_before_contact_test", previous)
    life.store.put(life.owner, "pending", {
        "key": "initiative-demo:20261103", "url": "", "ts": time.time(),
        "message": f"老爸，我来找你啦。我给自己挑了《{name}》，正在慢慢看。等有了想聊的，我再跑来和你说。"})
    result = await life.deliver_pending()
    if result.get("发送"):
        life.store.put(life.owner, "initiative_result", "已实测主动私聊，并取得平台消息编号")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
