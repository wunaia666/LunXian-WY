"""仅执行已确认声音的记忆更正，不重复安装或重启服务。"""

import importlib.util
import json
from pathlib import Path

from 安装记忆星图 import reconcile_voice_memory


def main():
    assets = Path(r"E:\sss_test\dafeiyu_assets")
    scope = json.loads((assets / "companion_owner.json").read_text(encoding="utf-8"))[
        "session"
    ]
    path = Path(
        r"E:\sss_test\AstrBot\data\plugins\astrbot_plugin_dafeiyu_selfmod\memory.py"
    )
    spec = importlib.util.spec_from_file_location(
        "existing_voice_memory_revision", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.MemoryStore(assets / "companion_memory.db")
    store.backup()
    changed = reconcile_voice_memory(store, scope)
    with store.connect() as connection:
        row = connection.execute(
            "SELECT id,content,pinned,expires FROM memories WHERE scope=? AND topic=?",
            (scope, "指定原声来源"),
        ).fetchone()
        historical = bool(
            row
            and connection.execute(
                "SELECT 1 FROM memory_revisions WHERE scope=? AND memory_id=? "
                "AND previous LIKE ? LIMIT 1",
                (scope, row["id"], "%7689724715246372473%"),
            ).fetchone()
        )
    if not (
        row
        and "第十条" in row["content"]
        and "仅使用视频" not in row["content"]
        and row["pinned"]
        and row["expires"] is None
        and historical
    ):
        raise RuntimeError("声音要求的更正或历史修订核对失败")
    print(
        json.dumps(
            {
                "本次更正条数": changed,
                "当前声音要求已统一": True,
                "原话修订已保留": historical,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
