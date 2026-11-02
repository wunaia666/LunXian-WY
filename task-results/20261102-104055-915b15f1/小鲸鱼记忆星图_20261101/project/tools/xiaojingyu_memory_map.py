"""从本会话现有记忆生成只读星图，连线只表示真实分类和完全相同的主题。"""

import hashlib
import time
from collections import Counter

KINDS = {
    "preference": "偏好与个人事实",
    "event": "共同经历",
    "plan": "约定与计划",
    "browse": "浏览记录",
}
MAX_MEMORIES = 80


def build_memory_map(result):
    """生成最多九十七个节点；省略项保留数量，避免把局部视图描述为全部记忆。"""
    rows = result.get("items", [])[:MAX_MEMORIES]
    total = int(result.get("total", len(rows)))
    nodes = [
        {
            "id": "collection",
            "type": "collection",
            "label": "小鲸鱼的记忆",
            "count": total,
        }
    ]
    links = []
    counts = Counter(
        row.get("kind") if row.get("kind") in KINDS else "event" for row in rows
    )
    for kind, label in KINDS.items():
        if counts[kind]:
            nodes.append(
                {
                    "id": "kind:" + kind,
                    "type": "kind",
                    "kind": kind,
                    "label": label,
                    "count": counts[kind],
                }
            )
            links.append(
                {"source": "collection", "target": "kind:" + kind, "relation": "分类"}
            )
    topics = Counter(str(row.get("topic") or "").strip() for row in rows)
    shared = {topic for topic, count in topics.most_common(12) if topic and count > 1}
    for topic in sorted(shared):
        identifier = "topic:" + hashlib.sha256(topic.encode()).hexdigest()[:14]
        nodes.append(
            {"id": identifier, "type": "topic", "label": topic, "count": topics[topic]}
        )
    now = time.time()
    for row in rows:
        kind = row.get("kind") if row.get("kind") in KINDS else "event"
        content = str(row.get("content") or "")
        topic = str(row.get("topic") or "").strip()
        identifier = "memory:" + str(row["id"])
        nodes.append(
            {
                "id": identifier,
                "memory_id": str(row["id"]),
                "type": "memory",
                "kind": kind,
                "label": (topic or content.replace("\n", " "))[:18],
                "topic": topic,
                "content": content,
                "source": str(row.get("source") or "未标明来源"),
                "pinned": bool(row.get("pinned")),
                "importance": max(0, min(100, int(row.get("importance") or 0))),
                "expires": row.get("expires"),
                "expired": row.get("expires") is not None and row["expires"] <= now,
                "updated": row.get("updated"),
                "use_count": row.get("use_count", 0),
            }
        )
        links.append(
            {"source": "kind:" + kind, "target": identifier, "relation": "所属分类"}
        )
        if topic in shared:
            links.append(
                {
                    "source": "topic:"
                    + hashlib.sha256(topic.encode()).hexdigest()[:14],
                    "target": identifier,
                    "relation": "相同主题",
                }
            )
    valid = {row["id"] for row in nodes}
    links = [row for row in links if row["source"] in valid and row["target"] in valid]
    return {
        "nodes": nodes,
        "links": links,
        "total": total,
        "shown": len(rows),
        "omitted": max(0, total - len(rows)),
        "counts": dict(counts),
        "limit": MAX_MEMORIES,
        "relation_note": "实线表示所属分类，虚线表示记录中完全相同的主题；没有通过模型猜测人物或事件的关系。",
        "empty": not rows,
        "read_only": True,
    }
