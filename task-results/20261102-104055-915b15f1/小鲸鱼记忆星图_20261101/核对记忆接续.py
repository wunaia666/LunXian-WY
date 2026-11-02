"""核对实际记忆的完整性、期限和本次用户决定可检索性，只输出汇总。"""

import importlib.util
import json
import sqlite3
import time
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    root = Path(r"E:\sss_test")
    assets = root / "dafeiyu_assets"
    scope = json.loads((assets / "companion_owner.json").read_text(encoding="utf-8"))[
        "session"
    ]
    path = assets / "companion_memory.db"
    with sqlite3.connect(
        "file:" + path.as_posix() + "?mode=ro", uri=True
    ) as connection:
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        total, permanent, pinned, expired = connection.execute(
            "SELECT COUNT(*),SUM(expires IS NULL),SUM(pinned),SUM(expires IS NOT NULL AND expires<=?) FROM memories WHERE scope=?",
            (time.time(), scope),
        ).fetchone()
        intervals = [
            {"分类": kind, "保留天数": days, "条数": count}
            for kind, days, count in connection.execute(
                "SELECT kind,ROUND((expires-created)/86400),COUNT(*) FROM memories WHERE scope=? AND expires IS NOT NULL GROUP BY kind,ROUND((expires-created)/86400)",
                (scope,),
            )
        ]
        index_ready = bool(
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='memory_fts'"
            ).fetchone()
        )
        decisions = connection.execute(
            "SELECT topic,expires,pinned FROM memories WHERE scope=? AND topic IN ('语音使用方式','已确认的声音')",
            (scope,),
        ).fetchall()
        voice_origin = connection.execute(
            "SELECT id,content FROM memories WHERE scope=? AND topic=?",
            (scope, "指定原声来源"),
        ).fetchone()
        origin_consistent = bool(
            voice_origin
            and "第十条" in voice_origin[1]
            and "仅使用视频" not in voice_origin[1]
        )
        origin_history = bool(
            voice_origin
            and connection.execute(
                "SELECT 1 FROM memory_revisions WHERE scope=? AND memory_id=? AND previous LIKE ? LIMIT 1",
                (scope, voice_origin[0], "%7689724715246372473%"),
            ).fetchone()
        )
    spec = importlib.util.spec_from_file_location(
        "verified_existing_memory",
        root / "AstrBot/data/plugins/astrbot_plugin_dafeiyu_selfmod/memory.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = object.__new__(module.MemoryStore)
    store.path = path
    policy_hit = any(
        row.get("topic") == "语音使用方式" and "偶尔" in row["content"]
        for row in store.search(scope, "语音使用方式")
    )
    voice_hit = any(
        row.get("topic") == "已确认的声音" and "第十条" in row["content"]
        for row in store.search(scope, "已确认的声音")
    )
    configuration = json.loads(
        (assets / "voice_config.json").read_text(encoding="utf-8")
    )
    budget = json.loads((assets / "context_budget.json").read_text(encoding="utf-8"))
    interface = json.loads(
        (folder / "星图界面验证结果.json").read_text(encoding="utf-8")
    )
    if not (
        integrity == "ok"
        and index_ready
        and len(decisions) == 2
        and all(expires is None and locked for _, expires, locked in decisions)
        and policy_hit
        and voice_hit
        and origin_consistent
        and origin_history
        and configuration.get("speech_policy") == "occasional"
        and interface["已锁定过滤条数"] == pinned
    ):
        raise RuntimeError("实际记忆、用户决定、语音策略或星图显示核对不一致")
    result = {
        "完成事项": [
            "现有网页已接入真实记忆星图",
            "分类与同主题连线依据明确",
            "节点可查正文、来源、期限与修订",
            "搜索、锁定筛选、列表和键盘缩放移动通过",
            "语音保持第十条声音，平时文字、偶尔生成",
        ],
        "数据库": {
            "完整性": "通过",
            "记录总数": total,
            "长期保存": permanent,
            "已锁定": pinned,
            "过期历史": expired or 0,
            "全文索引": index_ready,
            "有期限记录": intervals,
        },
        "本次决定可检索": {
            "偶尔语音": policy_hit,
            "第十条声音": voice_hit,
            "均长期锁定": True,
        },
        "早期声音要求已更正并留修订": origin_consistent and origin_history,
        "上下文记忆预算字数": budget["memory_characters"],
        "语音主动间隔秒数": configuration["spontaneous_voice_interval_seconds"],
        "语音请求边界": "主动语音默认至少间隔三十分钟；用户明确索要、要求继续或网页手动生成可按需继续",
        "星图": interface,
        "检查": {
            "新增单元检查": 8,
            "现有记忆归档检查": 8,
            "现有上下文回归": 10,
            "现有记忆管线检查": 14,
        },
        "仍有的边界": "长期保存不等于每轮全部发送给模型；每轮按相关性和字数预算取用。分钟级语音及其他情绪仍待独立验收。",
        "本轮发送聊天消息": False,
        "本轮自动生成语音": False,
        "本轮操作桌面聊天客户端": False,
        "私人数据": "实际数据库、记忆正文、运行配置及页面截图仅留本机，不登记上传",
    }
    (folder / "接续结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checkpoint = {
        "最新接续结果": str(folder / "接续结果.json"),
        "网页入口": "http://127.0.0.1:8765/",
        "记忆入口": "左侧记忆星图，可切换列表查看来源和修订",
        "语音使用方式": "平时文字、偶尔生成；主动语音至少间隔三十分钟，明确索要及网页手动生成可按需继续",
        "已确认声音": "第十条生日对白参考多萝声音，旧视频原声要求已更正且保留修订",
        "数据库": result["数据库"],
        "客户端限制": "禁止自动启动、登录、接管桌面聊天客户端；保留接入暂停及关闭自动加载",
        "待验收": "分钟级语音及其他情绪仍待独立听感验收，长期召回效果不能仅凭存库保证",
    }
    checkpoint_path = root / "交接/小鲸鱼_最新接续.json"
    temporary = checkpoint_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(checkpoint_path)
    print(
        json.dumps(
            {
                "数据库": result["数据库"],
                "本次决定可检索": result["本次决定可检索"],
                "上下文记忆预算字数": budget["memory_characters"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
