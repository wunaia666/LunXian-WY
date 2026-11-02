"""备份并接入记忆星图和偶尔语音策略，沿用既有数据库并记录明确用户决定。"""

import hashlib
import importlib.util
import json
import shutil
from datetime import datetime
from pathlib import Path


def reconcile_voice_memory(store, scope):
    """更正早期声音要求，沿用原记录和修订历史，避免同时注入冲突指令。"""
    with store.connect() as connection:
        previous = connection.execute(
            "SELECT id,content FROM memories WHERE scope=? AND topic=?",
            (scope, "指定原声来源"),
        ).fetchall()
    content = (
        "当前语音来源以用户已确认的第十条生日对白参考多萝声音为准，"
        "沿用该条完整训练配对、参考音和固定参数；早期素材选择的原话保留在修订历史中。"
    )
    changed = 0
    for row in previous:
        if row["content"] == content:
            continue
        store.remember(
            scope,
            content,
            replace_id=row["id"],
            topic="指定原声来源",
            source="用户后续确认：第十条生日对白参考原多萝配对长段，这个可以，就用这个吧",
            importance=98,
        )
        changed += 1
    return changed


def main():
    stage = Path(__file__).resolve().parent
    root = Path(r"E:\sss_test")
    assets = root / "dafeiyu_assets"
    monitor = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    gateway = assets / "qq_gateway.json"
    gateway_before = hashlib.sha256(gateway.read_bytes()).hexdigest()
    voice = assets / "voice_config.json"
    selected_before = json.loads(voice.read_text(encoding="utf-8"))["gptsovits"]
    backup = (
        root
        / "backups"
        / ("记忆星图与偶尔语音_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    )
    files = [
        (path, root / path.relative_to(stage / "project"))
        for path in (stage / "project").rglob("*.py")
    ]
    files += [
        (stage / "monitor" / name, monitor / name)
        for name in ("monitor.py", "dashboard.html", "memory-map.js", "memory-map.css")
    ]
    for source, target in files:
        if target.exists():
            relative = (
                Path("monitor") / target.name
                if target.parent == monitor
                else Path("project") / target.relative_to(root)
            )
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(voice, backup / "voice_config.json")
    memory_path = root / "AstrBot/data/plugins/astrbot_plugin_dafeiyu_selfmod/memory.py"
    spec = importlib.util.spec_from_file_location(
        "existing_memory_for_star_map", memory_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.MemoryStore(assets / "companion_memory.db")
    database_backup = store.backup()
    scope = json.loads((assets / "companion_owner.json").read_text(encoding="utf-8"))[
        "session"
    ]
    saved = []
    for topic, content, source in (
        (
            "语音使用方式",
            "用户希望小鲸鱼平时以文字交流为主，语音偶尔生成；明确索要语音或点击网页按钮时可以按需生成。",
            "用户原话：我要的是偶尔的生成",
        ),
        (
            "已确认的声音",
            "用户已确认采用第十条生日对白参考的多萝合成声音；生成语音时沿用该条的完整训练配对、参考音和固定参数。",
            "用户原话：10_生日对白参考_原多萝配对_长段.wav，这个可以，就用这个吧",
        ),
    ):
        ident = store.remember(
            scope, content, topic=topic, source=source, importance=100
        )
        store.pin(scope, ident, True)
        saved.append(ident)
    corrected = reconcile_voice_memory(store, scope)
    for source, target in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    configuration = json.loads(voice.read_text(encoding="utf-8"))
    configuration.update(
        speech_policy="occasional", spontaneous_voice_interval_seconds=1800
    )
    configuration["_使用方式"] = (
        "默认文字；只在合适时偶尔主动语音，主动语音距上一条至少三十分钟；明确索要或网页手动生成可按需继续。"
    )
    temporary = voice.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(configuration, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(voice)
    state_path = assets / "runtime/voice_studio.json"
    if state_path.exists():
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if value.get("production_changed"):
            value["message"] = (
                "已保留你认可的第十条声音，平时文字，需要时按需生成语音。"
            )
            state_path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    if (
        configuration["gptsovits"] != selected_before
        or hashlib.sha256(gateway.read_bytes()).hexdigest() != gateway_before
    ):
        raise RuntimeError("语音声线或聊天接入设置在安装期间发生意外变化")
    with store.connect() as connection:
        count, permanent, pinned = connection.execute(
            "SELECT COUNT(*),SUM(expires IS NULL),SUM(pinned) FROM memories WHERE scope=?",
            (scope,),
        ).fetchone()
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
    result = {
        "备份目录": str(backup),
        "记忆数据库备份": database_backup,
        "安装文件数": len(files),
        "保存的用户决定编号": saved,
        "记忆数": count,
        "长期保存": permanent,
        "已锁定": pinned,
        "数据库完整性": integrity,
        "声音配置未替换": True,
        "聊天接入配置未变": True,
        "更正的早期声音要求": corrected,
    }
    (stage / "安装结果.local.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"保存的用户决定编号", "记忆数据库备份"}
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
