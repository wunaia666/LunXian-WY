"""后台陪伴沿用主人当前模型与角色，不带入可执行网页指令。"""

import asyncio
import json
import re


async def ask(browser, payload, rules):
    owner = browser.life.owner
    provider = await browser.context.get_using_provider_async(umo=owner)
    if provider is None:
        raise RuntimeError("聊天模型尚未连接")
    config = browser.context.get_config(umo=owner)
    persona_id = (config.get("agent_runner", {}).get("config", {})
                  .get("persona", {}).get("persona_id", "default"))
    persona = await browser.context.persona_manager.get_persona(persona_id)
    response = await asyncio.wait_for(provider.text_chat(
        prompt=json.dumps(payload, ensure_ascii=False),
        system_prompt=(getattr(persona, "system_prompt", "") or "") + "\n" + rules,
        contexts=[], image_urls=[], request_max_retries=1,
    ), timeout=60)
    text = response.completion_text or ""
    match = re.search(r"\{.*\}", text, re.S)
    result = json.loads(match.group(0) if match else text)
    if not isinstance(result, dict):
        raise ValueError("后台模型未返回有效对象")
    return result
