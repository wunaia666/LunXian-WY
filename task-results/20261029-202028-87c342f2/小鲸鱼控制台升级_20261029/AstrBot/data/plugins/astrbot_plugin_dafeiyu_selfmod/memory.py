"""按会话保存和检索个人记忆，以及自主分享的持久状态。"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path


class MemoryStore:
    """使用独立数据库保存记忆，避免不同会话互相读取。"""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL,
                    content TEXT NOT NULL, source TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL, expires REAL);
                CREATE INDEX IF NOT EXISTS memory_scope ON memories(scope, updated);
                CREATE TABLE IF NOT EXISTS companion_state (
                    scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY(scope, key));
                CREATE TABLE IF NOT EXISTS companion_shares (
                    scope TEXT NOT NULL, item_key TEXT NOT NULL, day TEXT NOT NULL,
                    ts REAL NOT NULL, status TEXT NOT NULL, content TEXT NOT NULL,
                    PRIMARY KEY(scope, item_key));
                """
            )
            columns = {r[1] for r in db.execute("PRAGMA table_info(memories)")}
            for name, spec in {
                "topic": "TEXT NOT NULL DEFAULT ''",
                "importance": "INTEGER NOT NULL DEFAULT 50",
                "access_count": "INTEGER NOT NULL DEFAULT 0",
                "last_accessed": "REAL",
                "pinned": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE memories ADD COLUMN {name} {spec}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memory_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT,
                    scope TEXT, action TEXT, previous TEXT, changed REAL);
                CREATE TABLE IF NOT EXISTS memory_jobs (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, message TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL, error TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS memory_topic ON memories(scope, topic);
            """)
            db.execute(
                "UPDATE memory_jobs SET status=CASE WHEN attempts<3 THEN 'pending' ELSE 'failed' END WHERE status='running' AND updated<?",
                (time.time() - 120,),
            )
            # 全文索引是现有记忆表的派生索引，正文仍只保存一份。
            try:
                exists = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='memory_fts'"
                ).fetchone()
                db.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content,topic,source,content='memories',content_rowid='rowid',tokenize='trigram');
                    CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memories BEGIN
                      INSERT INTO memory_fts(rowid,content,topic,source) VALUES(new.rowid,new.content,new.topic,new.source); END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memories BEGIN
                      INSERT INTO memory_fts(memory_fts,rowid,content,topic,source) VALUES('delete',old.rowid,old.content,old.topic,old.source); END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_update AFTER UPDATE OF content,topic,source ON memories BEGIN
                      INSERT INTO memory_fts(memory_fts,rowid,content,topic,source) VALUES('delete',old.rowid,old.content,old.topic,old.source);
                      INSERT INTO memory_fts(rowid,content,topic,source) VALUES(new.rowid,new.content,new.topic,new.source); END;
                """)
                if not exists:
                    db.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
            except sqlite3.OperationalError:
                # 旧运行环境没有全文扩展时，仍保留原有词片检索。
                pass

    def connect(self):
        """建立带写入等待时间的短连接。"""
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def remember(
        self,
        scope: str,
        content: str,
        kind: str = "preference",
        source: str = "用户对话",
        replace_id: str = "",
        expires_days: int = 0,
        topic: str = "",
        importance: int = 50,
    ) -> str:
        """新增或更正本会话的记忆，返回可供删除的编号。"""
        content = content.strip()[:1800]
        topic = topic.strip()[:80]
        importance = max(0, min(int(importance), 100))
        if not scope or not content:
            raise ValueError("会话和记忆内容不能为空")
        if kind not in {"preference", "event", "plan", "browse"}:
            raise ValueError("记忆分类无效")
        now = time.time()
        days = max(0, min(int(expires_days), 3650))
        expires = now + days * 86400 if days else None
        with closing(self.connect()) as db, db:
            if topic and not replace_id:
                same_topic = db.execute(
                    "SELECT id FROM memories WHERE scope=? AND topic=? AND kind=? ORDER BY updated DESC LIMIT 1",
                    (scope, topic, kind),
                ).fetchone()
                if same_topic:
                    replace_id = same_topic["id"]
            if replace_id:
                previous = db.execute(
                    "SELECT * FROM memories WHERE id=? AND scope=?", (replace_id, scope)
                ).fetchone()
                if previous:
                    if (
                        previous["content"] == content
                        and previous["kind"] == kind
                        and previous["source"] == source
                        and (not topic or previous["topic"] == topic)
                    ):
                        db.execute(
                            "UPDATE memories SET updated=?,expires=CASE WHEN pinned=1 THEN NULL ELSE ? END WHERE id=?",
                            (now, expires, replace_id),
                        )
                        return replace_id
                    db.execute(
                        "INSERT INTO memory_revisions(memory_id,scope,action,previous,changed) VALUES (?,?,?,?,?)",
                        (
                            replace_id,
                            scope,
                            "更正",
                            json.dumps(dict(previous), ensure_ascii=False),
                            now,
                        ),
                    )
                changed = db.execute(
                    "UPDATE memories SET content=?, kind=?, source=?, updated=?, expires=CASE WHEN pinned=1 THEN NULL ELSE ? END, topic=?, importance=? "
                    "WHERE id=? AND scope=?",
                    (
                        content,
                        kind,
                        source,
                        now,
                        expires,
                        topic or (previous["topic"] if previous else ""),
                        importance,
                        replace_id,
                        scope,
                    ),
                ).rowcount
                if not changed:
                    raise ValueError("本会话没有这个记忆编号")
                return replace_id
            hit = db.execute(
                "SELECT id FROM memories WHERE scope=? AND kind=? AND content=?",
                (scope, kind, content),
            ).fetchone()
            if hit:
                db.execute(
                    "UPDATE memories SET updated=?, expires=CASE WHEN pinned=1 THEN NULL ELSE ? END WHERE id=?",
                    (now, expires, hit["id"]),
                )
                return hit["id"]
            ident = uuid.uuid4().hex[:12]
            db.execute(
                "INSERT INTO memories(id,scope,kind,content,source,created,updated,expires,topic,importance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ident,
                    scope,
                    kind,
                    content,
                    source,
                    now,
                    now,
                    expires,
                    topic,
                    importance,
                ),
            )
            return ident

    def search(
        self, scope: str, query: str = "", limit: int = 8, include_expired: bool = False
    ) -> list[dict]:
        """按中文词片和完整关键词检索，保留少量稳定偏好作为补充。"""
        terms = set(re.findall(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]+", query.lower()))
        grams = set()
        for term in terms:
            if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
                grams.update(term[i : i + 2] for i in range(len(term) - 1))
            else:
                grams.add(term)
        grams = sorted(grams, key=lambda x: (-len(x), x))[:40]
        aliases = {
            "称呼": ("昵称", "怎么叫我", "叫我什么", "喊我什么"),
            "声音": ("音色", "奶音", "声线", "配音"),
            "猫": ("猫咪", "喵星人", "小猫"),
            "狗": ("狗狗", "汪星人", "小狗"),
            "生日": ("出生日期", "哪天出生"),
            "工作": ("职业", "上班", "做什么工作的"),
        }
        for word, variants in aliases.items():
            if any(variant in query for variant in variants):
                grams.append(word)
        grams = list(dict.fromkeys(grams))
        sql = "SELECT * FROM memories WHERE scope=?"
        args = [scope]
        if not include_expired:
            sql += " AND (expires IS NULL OR expires>?)"
            args.append(time.time())
        if grams:
            sql += (
                " AND (kind='preference' OR "
                + " OR ".join(
                    "instr(lower(content||' '||topic||' '||source), ?)>0" for _ in grams
                )
                + ")"
            )
            args.extend(grams)
        with closing(self.connect()) as db:
            rows = [dict(x) for x in db.execute(sql, args)]
            # 三字以上的词片使用全文索引；两字中文继续由原有检索补齐。
            phrases = sorted({g for g in terms if len(g) >= 3})
            if phrases:
                try:
                    match = " OR ".join(
                        '"' + g.replace('"', '""') + '"' for g in phrases
                    )
                    indexed = db.execute(
                        "SELECT m.* FROM memory_fts f JOIN memories m ON m.rowid=f.rowid WHERE memory_fts MATCH ? AND m.scope=?",
                        (match, scope),
                    )
                    known = {row["id"] for row in rows}
                    rows.extend(
                        dict(row)
                        for row in indexed
                        if row["id"] not in known
                        and (
                            include_expired
                            or row["expires"] is None
                            or row["expires"] > time.time()
                        )
                    )
                except sqlite3.OperationalError:
                    pass
        for row in rows:
            row["score"] = sum(
                len(g) * (3 if g in row["topic"].lower() else 1)
                for g in grams
                if g
                in (row["content"] + " " + row["topic"] + " " + row["source"]).lower()
            )
            row["expired"] = (
                row["expires"] is not None and row["expires"] <= time.time()
            )
        rows.sort(
            key=lambda r: (
                r["score"],
                r.get("pinned", 0),
                r["kind"] == "preference",
                r["updated"],
            ),
            reverse=True,
        )
        return rows[: max(1, min(int(limit), 20))]

    def recent_browse(self, scope: str, limit: int = 3) -> list[dict]:
        """按时间倒序取最近的浏览记忆。

        问“你刚才看了什么”这类泛问，关键词匹配不到具体标题，需要这条兜底，
        否则浏览记录明明存在却答不上来。
        """
        with closing(self.connect()) as db:
            rows = [
                dict(x)
                for x in db.execute(
                    "SELECT * FROM memories WHERE scope=? AND kind='browse' "
                    "AND (expires IS NULL OR expires>?) ORDER BY updated DESC LIMIT ?",
                    (scope, time.time(), max(1, min(int(limit), 10))),
                )
            ]
        for row in rows:
            row["score"] = 0
        return rows

    def forget(self, scope: str, ident: str) -> bool:
        """删除指定会话自己的记忆。"""
        with closing(self.connect()) as db, db:
            # 删除请求同时清除修订中的私密内容，防止旧版本继续被查看。
            db.execute(
                "DELETE FROM memory_revisions WHERE scope=? AND memory_id=?",
                (scope, ident),
            )
            return bool(
                db.execute(
                    "DELETE FROM memories WHERE scope=? AND id=?", (scope, ident)
                ).rowcount
            )

    def assemble(self, scope: str, query: str, budget: int = 6000) -> tuple[str, dict]:
        """分组预留预算，并记录本轮真正带入模型的记忆。"""
        budget = max(256, min(int(budget), 6000))
        related = self.search(scope, query, 20)
        relevant = [row for row in related if row.get("score", 0) > 0]
        browse_question = bool(
            re.search(
                r"看了什么|看什么|看过什么|看了啥|刚才看|最近看|刚看|浏览|逛了|刷了|视频|帖子",
                query,
            )
        )
        with closing(self.connect()) as db:
            stable = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM memories WHERE scope=? AND (kind='preference' OR pinned=1) AND (expires IS NULL OR expires>?) ORDER BY pinned DESC,importance DESC,updated DESC LIMIT 20",
                    (scope, time.time()),
                )
            ]
            plans = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM memories WHERE scope=? AND kind='plan' AND (expires IS NULL OR expires>?) ORDER BY updated DESC LIMIT 3",
                    (scope, time.time()),
                )
            ]
        # 核心称呼始终保留；先放相关事实，避免无关浏览抢占整轮预算。
        core = [row for row in stable if row["importance"] >= 95 or row.get("pinned")]
        core.sort(
            key=lambda row: (row["importance"], row.get("pinned", 0), row["updated"]),
            reverse=True,
        )
        remaining = [
            row for row in stable if row["importance"] < 95 and not row.get("pinned")
        ][:4]
        groups = [
            (
                "稳定偏好",
                core,
                int(
                    budget * (0.40 if any(row.get("pinned") for row in core) else 0.24)
                ),
            ),
            ("相关回忆", relevant, int(budget * 0.50)),
            ("当前约定", plans, int(budget * 0.15)),
            (
                "最近浏览",
                self.recent_browse(scope, 2) if browse_question else [],
                int(budget * 0.30),
            ),
            ("稳定偏好", remaining, int(budget * 0.20)),
        ]
        seen, included, omitted, lines = set(), [], [], []
        used = 0
        for title, rows, group_budget in groups:
            group_used = 0
            for row in rows:
                if row["id"] in seen:
                    continue
                stamp = time.strftime("%m-%d %H:%M", time.localtime(row["updated"]))
                source = row["source"][:120]
                line = f"[{row['id']}] {title}（{stamp}，来源：{source}）：{row['content']}"
                # 长条目仅提取与当前问题相邻的片段；数据库保留完整原文。
                available = min(group_budget - group_used, budget - used) - 1
                if len(line) > available and available >= 220:
                    prefix = f"[{row['id']}] {title}（{stamp}）："
                    content = row["content"]
                    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{2,}", query)
                    offset = next(
                        (content.find(term) for term in terms if term in content), 0
                    )
                    offset = max(0, offset - 50)
                    line = (
                        prefix
                        + content[offset : offset + available - len(prefix) - 6]
                        + "【节选】"
                    )
                if (
                    group_used + len(line) + 1 > group_budget
                    or used + len(line) + 1 > budget
                ):
                    omitted.append(row["id"])
                    continue
                lines.append(line)
                seen.add(row["id"])
                included.append({**row, "group": title})
                group_used += len(line) + 1
                used += len(line) + 1
        if seen:
            with closing(self.connect()) as db, db:
                db.executemany(
                    "UPDATE memories SET access_count=access_count+1,last_accessed=? WHERE scope=? AND id=?",
                    [(time.time(), scope, ident) for ident in seen],
                )
        return "\n".join(lines), {
            "included": included,
            "omitted_ids": list(
                dict.fromkeys(ident for ident in omitted if ident not in seen)
            ),
            "characters": used,
            "browse_requested": browse_question,
            "budget": budget,
        }

    def pin(self, scope: str, ident: str, enabled: bool = True) -> bool:
        """锁定重要记忆为长期保存，保留更正与用户主动删除能力。"""
        with closing(self.connect()) as db, db:
            row = db.execute(
                "SELECT * FROM memories WHERE scope=? AND id=?", (scope, ident)
            ).fetchone()
            if row is None:
                raise ValueError("当前会话没有这个记忆编号")
            db.execute(
                "INSERT INTO memory_revisions(memory_id,scope,action,previous,changed) VALUES(?,?,?,?,?)",
                (
                    ident,
                    scope,
                    "锁定" if enabled else "取消锁定",
                    json.dumps(dict(row), ensure_ascii=False),
                    time.time(),
                ),
            )
            db.execute(
                "UPDATE memories SET pinned=?,expires=CASE WHEN ? THEN NULL ELSE expires END WHERE scope=? AND id=?",
                (int(enabled), int(enabled), scope, ident),
            )
        return True

    def backup(self) -> dict:
        """通过数据库快照接口备份，包含一致的记忆、修订与整理队列。"""
        import hashlib

        folder = self.path.parent / "backups/memory"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (
            "记忆快照_"
            + time.strftime("%Y%m%d_%H%M%S")
            + "_"
            + uuid.uuid4().hex[:6]
            + ".db"
        )
        with (
            closing(self.connect()) as source,
            closing(sqlite3.connect(target)) as destination,
        ):
            source.backup(destination)
            if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("备份完整性检查失败")
        return {
            "文件": target.name,
            "时间": time.time(),
            "字节数": target.stat().st_size,
            "摘要": hashlib.sha256(target.read_bytes()).hexdigest(),
            "完整性": "通过",
        }

    def enqueue(self, scope: str, message_id: str, message: str) -> None:
        """持久保存待整理的用户原话，重启后继续处理。"""
        import hashlib

        ident = hashlib.sha256(f"{scope}:{message_id}:{message}".encode()).hexdigest()[
            :24
        ]
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO memory_jobs(id,scope,message,status,created,updated) VALUES (?,?,?,'pending',?,?)",
                (ident, scope, message[:4000], now, now),
            )

    def next_job(self):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE memory_jobs SET status=CASE WHEN attempts<3 THEN 'pending' ELSE 'failed' END WHERE status='running' AND updated<?",
                (time.time() - 120,),
            )
            row = db.execute(
                "SELECT * FROM memory_jobs WHERE status='pending' AND attempts<3 AND (attempts=0 OR updated<?) ORDER BY created LIMIT 1",
                (time.time() - 30,),
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE memory_jobs SET status='running',attempts=attempts+1,updated=? WHERE id=?",
                    (time.time(), row["id"]),
                )
                return dict(row)
        return None

    def finish_job(self, ident: str, error: str = "") -> None:
        with closing(self.connect()) as db, db:
            db.execute(
                "UPDATE memory_jobs SET status=CASE WHEN ?='' THEN 'done' WHEN attempts<3 THEN 'pending' ELSE 'failed' END,error=?,updated=? WHERE id=?",
                (error, error[:300], time.time(), ident),
            )

    def get(self, scope: str, key: str, default=None):
        """读取会话状态。"""
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT value FROM companion_state WHERE scope=? AND key=?",
                (scope, key),
            ).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, scope: str, key: str, value) -> None:
        """原子替换会话状态。"""
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO companion_state VALUES (?, ?, ?)",
                (scope, key, json.dumps(value, ensure_ascii=False)),
            )

    def claim_share(
        self,
        scope: str,
        key: str,
        content: str,
        day: str,
        now: float,
        daily_limit: int,
        cooldown: float,
    ) -> bool:
        """在发送前原子占用名额，防止并发发送突破配额或重复分享。"""
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT status FROM companion_shares WHERE scope=? AND item_key=?",
                (scope, key),
            ).fetchone()
            if previous and previous[0] in {"sent", "reserved"}:
                return False
            count, latest = db.execute(
                "SELECT count(*), max(ts) FROM companion_shares "
                "WHERE scope=? AND status IN ('sent','reserved') AND day=?",
                (scope, day),
            ).fetchone()
            last = db.execute(
                "SELECT max(ts) FROM companion_shares WHERE scope=? AND status IN ('sent','reserved')",
                (scope,),
            ).fetchone()[0]
            if (daily_limit > 0 and count >= daily_limit) or (
                cooldown > 0 and last is not None and now - last < cooldown
            ):
                return False
            db.execute(
                "INSERT OR REPLACE INTO companion_shares VALUES (?, ?, ?, ?, ?, ?)",
                (scope, key, day, now, "reserved", content),
            )
            return True

    def finish_share(self, scope: str, key: str, success: bool) -> None:
        """记录真实发送结果，失败不会被算成已经发出。"""
        with closing(self.connect()) as db, db:
            db.execute(
                "UPDATE companion_shares SET status=? WHERE scope=? AND item_key=?",
                ("sent" if success else "failed", scope, key),
            )

    def share_count(self, scope: str, day: str) -> int:
        """统计当天实际已发出的主动分享。"""
        with closing(self.connect()) as db:
            return db.execute(
                "SELECT count(*) FROM companion_shares WHERE scope=? "
                "AND day=? AND status='sent'",
                (scope, day),
            ).fetchone()[0]
