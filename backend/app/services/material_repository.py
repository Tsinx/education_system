import sqlite3
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger

from app.schemas.material import MaterialChapter, MaterialChunk, MaterialDetail, MaterialItem, MaterialKnowledgePoint


class CourseItem:
    def __init__(self, id: str, name: str, description: str, hours: int, sessions: int, created_at: str):
        self.id = id
        self.name = name
        self.description = description
        self.hours = hours
        self.sessions = sessions
        self.created_at = created_at


class MaterialRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS courses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    hours INTEGER NOT NULL DEFAULT 0,
                    sessions INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chapters (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(course_id) REFERENCES courses(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chapters_course_id ON chapters(course_id)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS materials (
                    id TEXT PRIMARY KEY,
                    course_id TEXT,
                    filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_blob BLOB NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    process_stage TEXT,
                    markdown TEXT,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    summary TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cols = [r[1] for r in conn.execute("PRAGMA table_info(materials)").fetchall()]
            if "summary" not in cols:
                conn.execute("ALTER TABLE materials ADD COLUMN summary TEXT")
            if "process_stage" not in cols:
                conn.execute("ALTER TABLE materials ADD COLUMN process_stage TEXT")
            if "knowledge_extracted" not in cols:
                conn.execute("ALTER TABLE materials ADD COLUMN knowledge_extracted INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS material_chunks (
                    id TEXT PRIMARY KEY,
                    material_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    sentence_count INTEGER NOT NULL,
                    start_sentence INTEGER NOT NULL,
                    end_sentence INTEGER NOT NULL,
                    embedding TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(material_id) REFERENCES materials(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_chunks_material_id ON material_chunks(material_id)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_material_chunks_unique ON material_chunks(material_id, chunk_index)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS material_chapters (
                    id TEXT PRIMARY KEY,
                    material_id TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL,
                    section TEXT NOT NULL,
                    first_sentence TEXT NOT NULL DEFAULT '',
                    last_sentence TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(material_id) REFERENCES materials(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_chapters_material_id ON material_chapters(material_id)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_material_chapters_unique ON material_chapters(material_id, chapter_index)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS material_knowledge_points (
                    id TEXT PRIMARY KEY,
                    material_id TEXT NOT NULL,
                    chapter_id TEXT,
                    chapter_index INTEGER NOT NULL,
                    chapter_section TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    parent_name TEXT,
                    child_points TEXT NOT NULL DEFAULT '[]',
                    prerequisite_points TEXT NOT NULL DEFAULT '[]',
                    postrequisite_points TEXT NOT NULL DEFAULT '[]',
                    related_points TEXT NOT NULL DEFAULT '[]',
                    level INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(material_id) REFERENCES materials(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_knowledge_material_id ON material_knowledge_points(material_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_knowledge_chapter ON material_knowledge_points(material_id, chapter_index)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS material_knowledge_edges (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    source_point_id TEXT NOT NULL,
                    target_point_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    relation_score REAL NOT NULL DEFAULT 0.0,
                    relation_source TEXT NOT NULL DEFAULT 'llm_refine',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_knowledge_edges_course ON material_knowledge_edges(course_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_knowledge_edges_source ON material_knowledge_edges(source_point_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_material_knowledge_edges_target ON material_knowledge_edges(target_point_id)"
            )
            conn.commit()

    def create_material(self, filename: str, content: bytes, course_id: str | None = None) -> MaterialItem:
        now = datetime.utcnow().isoformat()
        material_id = f"mat_{uuid4().hex[:12]}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO materials (
                    id, course_id, filename, file_size, file_blob, status, progress, process_stage, char_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (material_id, course_id, filename, len(content), content, "queued", 0, "排队中", 0, now, now),
            )
            conn.commit()
        logger.info("DB: 资料创建 | id={} | file={} | course={} | size={}", material_id, filename, course_id, len(content))
        return self.get_material_item(material_id)

    def list_materials(self, course_id: str | None = None, limit: int = 100) -> list[MaterialItem]:
        query = """
            SELECT id, course_id, filename, file_size, status, progress, char_count,
                   process_stage, summary, knowledge_extracted, created_at, updated_at
            FROM materials
        """
        params: list[object] = []
        if course_id:
            query += " WHERE course_id = ?"
            params.append(course_id)
        query += " ORDER BY datetime(created_at) DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_material_item(self, material_id: str) -> MaterialItem:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, course_id, filename, file_size, status, progress, char_count,
                       process_stage, summary, knowledge_extracted, created_at, updated_at
                FROM materials
                WHERE id = ?
                """,
                (material_id,),
            ).fetchone()
        if row is None:
            raise KeyError(material_id)
        return self._row_to_item(row)

    def get_material_detail(self, material_id: str) -> MaterialDetail:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, course_id, filename, file_size, status, progress, char_count,
                       process_stage, markdown, summary, error_message, knowledge_extracted, created_at, updated_at
                FROM materials
                WHERE id = ?
                """,
                (material_id,),
            ).fetchone()
        if row is None:
            raise KeyError(material_id)
        return MaterialDetail(
            id=row["id"],
            course_id=row["course_id"],
            filename=row["filename"],
            file_size=row["file_size"],
            status=row["status"],
            progress=row["progress"],
            process_stage=row["process_stage"],
            char_count=row["char_count"],
            markdown=row["markdown"],
            summary=row["summary"],
            error_message=row["error_message"],
            knowledge_extracted=bool(row["knowledge_extracted"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_material_blob(self, material_id: str) -> tuple[str, bytes]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT filename, file_blob FROM materials WHERE id = ?",
                (material_id,),
            ).fetchone()
        if row is None:
            raise KeyError(material_id)
        return row[0], row[1]

    def update_status(
        self,
        material_id: str,
        status: str,
        progress: int,
        process_stage: str | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if process_stage is None:
                conn.execute(
                    "UPDATE materials SET status = ?, progress = ?, updated_at = ? WHERE id = ?",
                    (status, progress, now, material_id),
                )
            else:
                conn.execute(
                    "UPDATE materials SET status = ?, progress = ?, process_stage = ?, updated_at = ? WHERE id = ?",
                    (status, progress, process_stage, now, material_id),
                )
            conn.commit()

    def save_markdown(self, material_id: str, markdown: str, progress: int = 55) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE materials
                SET markdown = ?, char_count = ?, progress = ?, process_stage = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (markdown, len(markdown), progress, "Markdown 转换完成", None, now, material_id),
            )
            conn.commit()
        logger.info("DB: Markdown 已保存 | id={} | chars={}", material_id, len(markdown))

    def mark_done(self, material_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE materials
                SET status = ?, progress = ?, process_stage = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                ("done", 100, "处理完成", None, now, material_id),
            )
            conn.commit()
        logger.info("DB: 资料处理完成 | id={}", material_id)

    def save_summary(self, material_id: str, summary: str) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE materials SET summary = ?, updated_at = ? WHERE id = ?",
                (summary, now, material_id),
            )
            conn.commit()
        logger.info("DB: 摘要保存 | id={} | len={}", material_id, len(summary))

    def mark_knowledge_extracted(self, material_id: str, extracted: bool = True) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE materials SET knowledge_extracted = ?, updated_at = ? WHERE id = ?",
                (1 if extracted else 0, now, material_id),
            )
            conn.commit()
        logger.info("DB: 知识点标记 | id={} | extracted={}", material_id, extracted)

    def replace_chunks(self, material_id: str, chunks: list[dict[str, object]]) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM material_chunks WHERE material_id = ?", (material_id,))
            for item in chunks:
                chunk_id = f"chk_{uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO material_chunks (
                        id, material_id, chunk_index, content, char_count, sentence_count,
                        start_sentence, end_sentence, embedding, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        material_id,
                        int(item["chunk_index"]),
                        str(item["content"]),
                        int(item["char_count"]),
                        int(item["sentence_count"]),
                        int(item["start_sentence"]),
                        int(item["end_sentence"]),
                        str(item["embedding"]),
                        now,
                    ),
                )
            conn.commit()
        logger.info("DB: chunks 替换写入 | id={} | count={}", material_id, len(chunks))

    def list_chunks(self, material_id: str) -> list[MaterialChunk]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, material_id, chunk_index, content, char_count, sentence_count,
                       start_sentence, end_sentence, created_at
                FROM material_chunks
                WHERE material_id = ?
                ORDER BY chunk_index ASC
                """,
                (material_id,),
            ).fetchall()
        return [
            MaterialChunk(
                id=row["id"],
                material_id=row["material_id"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                char_count=row["char_count"],
                sentence_count=row["sentence_count"],
                start_sentence=row["start_sentence"],
                end_sentence=row["end_sentence"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def replace_chapters(self, material_id: str, chapters: list[dict[str, object]]) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM material_chapters WHERE material_id = ?", (material_id,))
            for item in chapters:
                chapter_id = f"chp_{uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO material_chapters (
                        id, material_id, chapter_index, section, first_sentence, last_sentence,
                        content, char_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chapter_id,
                        material_id,
                        int(item["chapter_index"]),
                        str(item["section"]),
                        str(item["first_sentence"]),
                        str(item["last_sentence"]),
                        str(item["content"]),
                        int(item["char_count"]),
                        now,
                    ),
                )
            conn.commit()
        logger.info("DB: chapters 替换写入 | id={} | count={}", material_id, len(chapters))

    def list_chapters(self, material_id: str) -> list[MaterialChapter]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, material_id, chapter_index, section, first_sentence, last_sentence,
                       content, char_count, created_at
                FROM material_chapters
                WHERE material_id = ?
                ORDER BY chapter_index ASC
                """,
                (material_id,),
            ).fetchall()
        return [
            MaterialChapter(
                id=row["id"],
                material_id=row["material_id"],
                chapter_index=row["chapter_index"],
                section=row["section"],
                first_sentence=row["first_sentence"],
                last_sentence=row["last_sentence"],
                content=row["content"],
                char_count=row["char_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def replace_knowledge_points(self, material_id: str, points: list[dict[str, object]]) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM material_knowledge_points WHERE material_id = ?", (material_id,))
            for item in points:
                point_id = f"kp_{uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO material_knowledge_points (
                        id, material_id, chapter_id, chapter_index, chapter_section,
                        name, description, parent_name, child_points,
                        prerequisite_points, postrequisite_points, related_points,
                        level, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        point_id,
                        material_id,
                        str(item["chapter_id"]) if item.get("chapter_id") else None,
                        int(item["chapter_index"]),
                        str(item["chapter_section"]),
                        str(item["name"]),
                        str(item["description"]),
                        str(item["parent_name"]) if item.get("parent_name") else None,
                        json.dumps(item.get("child_points", []), ensure_ascii=False),
                        json.dumps(item.get("prerequisite_points", []), ensure_ascii=False),
                        json.dumps(item.get("postrequisite_points", []), ensure_ascii=False),
                        json.dumps(item.get("related_points", []), ensure_ascii=False),
                        int(item.get("level", 1)),
                        now,
                    ),
                )
            conn.commit()
        logger.info("DB: knowledge_points 替换写入 | id={} | count={}", material_id, len(points))

    def list_knowledge_points(
        self,
        material_id: str,
        chapter_index: int | None = None,
    ) -> list[MaterialKnowledgePoint]:
        query = """
            SELECT id, material_id, chapter_id, chapter_index, chapter_section, name, description,
                   parent_name, child_points, prerequisite_points, postrequisite_points, related_points,
                   level, created_at
            FROM material_knowledge_points
            WHERE material_id = ?
        """
        params: list[object] = [material_id]
        if chapter_index is not None:
            query += " AND chapter_index = ?"
            params.append(chapter_index)
        query += " ORDER BY chapter_index ASC, level ASC, name ASC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [
            MaterialKnowledgePoint(
                id=row["id"],
                material_id=row["material_id"],
                chapter_id=row["chapter_id"],
                chapter_index=row["chapter_index"],
                chapter_section=row["chapter_section"],
                name=row["name"],
                description=row["description"],
                parent_name=row["parent_name"],
                child_points=self._decode_json_list(row["child_points"]),
                prerequisite_points=self._decode_json_list(row["prerequisite_points"]),
                postrequisite_points=self._decode_json_list(row["postrequisite_points"]),
                related_points=self._decode_json_list(row["related_points"]),
                level=row["level"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def list_course_knowledge_points(self, course_id: str) -> list[MaterialKnowledgePoint]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT k.id, k.material_id, k.chapter_id, k.chapter_index, k.chapter_section, k.name, k.description,
                       k.parent_name, k.child_points, k.prerequisite_points, k.postrequisite_points, k.related_points,
                       k.level, k.created_at
                FROM material_knowledge_points k
                INNER JOIN materials m ON m.id = k.material_id
                WHERE m.course_id = ?
                ORDER BY k.material_id ASC, k.chapter_index ASC, k.level ASC, k.name ASC
                """,
                (course_id,),
            ).fetchall()
        return [
            MaterialKnowledgePoint(
                id=row["id"],
                material_id=row["material_id"],
                chapter_id=row["chapter_id"],
                chapter_index=row["chapter_index"],
                chapter_section=row["chapter_section"],
                name=row["name"],
                description=row["description"],
                parent_name=row["parent_name"],
                child_points=self._decode_json_list(row["child_points"]),
                prerequisite_points=self._decode_json_list(row["prerequisite_points"]),
                postrequisite_points=self._decode_json_list(row["postrequisite_points"]),
                related_points=self._decode_json_list(row["related_points"]),
                level=row["level"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def update_knowledge_point_relations(self, updates: list[dict[str, object]]) -> int:
        if not updates:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for item in updates:
                cur.execute(
                    """
                    UPDATE material_knowledge_points
                    SET prerequisite_points = ?, postrequisite_points = ?, related_points = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(item.get("prerequisite_points", []), ensure_ascii=False),
                        json.dumps(item.get("postrequisite_points", []), ensure_ascii=False),
                        json.dumps(item.get("related_points", []), ensure_ascii=False),
                        str(item["id"]),
                    ),
                )
            conn.commit()
            affected = cur.rowcount if cur.rowcount is not None else 0
        logger.info("DB: 知识图谱关系更新 | records={}", len(updates))
        return affected

    def replace_course_knowledge_edges(self, course_id: str, edges: list[dict[str, object]]) -> int:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM material_knowledge_edges WHERE course_id = ?", (course_id,))
            for edge in edges:
                edge_id = f"kpe_{uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO material_knowledge_edges (
                        id, course_id, source_point_id, target_point_id,
                        relation_type, relation_score, relation_source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge_id,
                        course_id,
                        str(edge["source_point_id"]),
                        str(edge["target_point_id"]),
                        str(edge["relation_type"]),
                        float(edge.get("relation_score", 0.0)),
                        str(edge.get("relation_source", "llm_refine")),
                        now,
                    ),
                )
            conn.commit()
        logger.info("DB: 课程知识关系边替换写入 | course={} | count={}", course_id, len(edges))
        return len(edges)

    def list_course_knowledge_edges(self, course_id: str) -> list[dict[str, object]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, source_point_id, target_point_id, relation_type, relation_score, relation_source, created_at
                FROM material_knowledge_edges
                WHERE course_id = ?
                ORDER BY datetime(created_at) DESC
                """,
                (course_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "source_point_id": row["source_point_id"],
                "target_point_id": row["target_point_id"],
                "relation_type": row["relation_type"],
                "relation_score": float(row["relation_score"] or 0.0),
                "relation_source": row["relation_source"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def delete_course_knowledge_point(
        self,
        course_id: str,
        point_id: str,
        delete_descendants: bool = False,
    ) -> dict[str, object]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT k.id, k.material_id, k.chapter_id, k.chapter_index, k.chapter_section, k.name, k.description,
                       k.parent_name, k.child_points, k.prerequisite_points, k.postrequisite_points, k.related_points,
                       k.level, k.created_at
                FROM material_knowledge_points k
                INNER JOIN materials m ON m.id = k.material_id
                WHERE m.course_id = ?
                ORDER BY k.material_id ASC, k.chapter_index ASC, k.level ASC, k.name ASC
                """,
                (course_id,),
            ).fetchall()

            row_by_id = {str(row["id"]): row for row in rows}
            target = row_by_id.get(point_id)
            if target is None:
                raise KeyError(point_id)

            def find_children(parent_row: sqlite3.Row) -> list[sqlite3.Row]:
                parent_name = (parent_row["name"] or "").strip()
                parent_level = int(parent_row["level"] or 1)
                result: list[sqlite3.Row] = []
                for row in rows:
                    if row["id"] == parent_row["id"]:
                        continue
                    if str(row["material_id"]) != str(parent_row["material_id"]):
                        continue
                    if int(row["chapter_index"]) != int(parent_row["chapter_index"]):
                        continue
                    if (row["parent_name"] or "").strip() != parent_name:
                        continue
                    if int(row["level"] or 1) <= parent_level:
                        continue
                    result.append(row)
                result.sort(key=lambda item: (int(item["level"] or 1), str(item["name"])))
                return result

            direct_children = find_children(target)
            descendants: list[sqlite3.Row] = []
            descendant_ids: set[str] = set()
            queue = list(direct_children)
            while queue:
                current = queue.pop(0)
                current_id = str(current["id"])
                if current_id in descendant_ids:
                    continue
                descendant_ids.add(current_id)
                descendants.append(current)
                queue.extend(find_children(current))

            delete_rows = [target, *descendants] if delete_descendants else [target]
            delete_ids = [str(row["id"]) for row in delete_rows]
            deleted_names = {
                str(row["name"]).strip()
                for row in delete_rows
                if isinstance(row["name"], str) and str(row["name"]).strip()
            }

            promoted_children = descendants if not delete_descendants else []
            direct_child_ids = {str(row["id"]) for row in direct_children}
            for row in promoted_children:
                new_parent_name = target["parent_name"] if str(row["id"]) in direct_child_ids else row["parent_name"]
                new_level = max(1, int(row["level"] or 1) - 1)
                conn.execute(
                    """
                    UPDATE material_knowledge_points
                    SET parent_name = ?, level = ?
                    WHERE id = ?
                    """,
                    (new_parent_name, new_level, str(row["id"])),
                )

            promoted_child_names = [
                str(row["name"]).strip()
                for row in direct_children
                if isinstance(row["name"], str) and str(row["name"]).strip()
            ]
            target_name = str(target["name"]).strip()
            remaining_rows = [row for row in rows if str(row["id"]) not in delete_ids]
            for row in remaining_rows:
                child_points = self._decode_json_list(row["child_points"])
                prerequisite_points = self._decode_json_list(row["prerequisite_points"])
                postrequisite_points = self._decode_json_list(row["postrequisite_points"])
                related_points = self._decode_json_list(row["related_points"])

                next_child_points = [item for item in child_points if item not in deleted_names]
                if not delete_descendants and target_name and target_name in child_points:
                    for name in promoted_child_names:
                        if name not in next_child_points:
                            next_child_points.append(name)

                next_prerequisite_points = [item for item in prerequisite_points if item not in deleted_names]
                next_postrequisite_points = [item for item in postrequisite_points if item not in deleted_names]
                next_related_points = [item for item in related_points if item not in deleted_names]

                if (
                    next_child_points == child_points
                    and next_prerequisite_points == prerequisite_points
                    and next_postrequisite_points == postrequisite_points
                    and next_related_points == related_points
                ):
                    continue

                conn.execute(
                    """
                    UPDATE material_knowledge_points
                    SET child_points = ?, prerequisite_points = ?, postrequisite_points = ?, related_points = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(next_child_points, ensure_ascii=False),
                        json.dumps(next_prerequisite_points, ensure_ascii=False),
                        json.dumps(next_postrequisite_points, ensure_ascii=False),
                        json.dumps(next_related_points, ensure_ascii=False),
                        str(row["id"]),
                    ),
                )

            if delete_ids:
                placeholders = ", ".join(["?"] * len(delete_ids))
                conn.execute(
                    f"""
                    DELETE FROM material_knowledge_edges
                    WHERE course_id = ? AND (
                        source_point_id IN ({placeholders}) OR target_point_id IN ({placeholders})
                    )
                    """,
                    [course_id, *delete_ids, *delete_ids],
                )
                conn.execute(
                    f"DELETE FROM material_knowledge_points WHERE id IN ({placeholders})",
                    delete_ids,
                )

            conn.commit()

        logger.info(
            "DB: 知识点删除 | course={} | point={} | recursive={} | deleted={} | promoted={}",
            course_id,
            point_id,
            delete_descendants,
            len(delete_ids),
            len(promoted_children),
        )
        return {
            "deleted_count": len(delete_ids),
            "promoted_count": len(promoted_children),
            "recursive": delete_descendants,
        }

    def bind_materials_to_course(self, material_ids: list[str], course_id: str) -> int:
        if not material_ids:
            return 0
        now = datetime.utcnow().isoformat()
        placeholders = ", ".join(["?"] * len(material_ids))
        params: list[object] = [course_id, now, *material_ids]
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                f"""
                UPDATE materials
                SET course_id = ?, updated_at = ?
                WHERE id IN ({placeholders}) AND course_id IS NULL
                """,
                params,
            )
            conn.commit()
            affected = cur.rowcount
        logger.info("DB: 资料绑定课程 | course={} | 绑定{}条资料", course_id, affected)
        return affected

    def delete_material(self, material_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            point_rows = conn.execute(
                "SELECT id FROM material_knowledge_points WHERE material_id = ?",
                (material_id,),
            ).fetchall()
            point_ids = [str(row[0]) for row in point_rows]
            if point_ids:
                placeholders = ", ".join(["?"] * len(point_ids))
                conn.execute(
                    f"""
                    DELETE FROM material_knowledge_edges
                    WHERE source_point_id IN ({placeholders}) OR target_point_id IN ({placeholders})
                    """,
                    [*point_ids, *point_ids],
                )
            conn.execute("DELETE FROM material_chunks WHERE material_id = ?", (material_id,))
            conn.execute("DELETE FROM material_chapters WHERE material_id = ?", (material_id,))
            conn.execute("DELETE FROM material_knowledge_points WHERE material_id = ?", (material_id,))
            cur = conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
            conn.commit()
            affected = cur.rowcount
        logger.info("DB: 资料删除 | id={} | affected={}", material_id, affected)
        return affected > 0

    def mark_failed(self, material_id: str, error_message: str) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE materials
                SET status = ?, progress = ?, process_stage = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                ("failed", 100, "处理失败", error_message, now, material_id),
            )
            conn.commit()

    def abandon_unfinished_tasks(self) -> int:
        now = datetime.utcnow().isoformat()
        reason = "服务重启后已放弃历史任务（恢复机制暂未启用）"
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                UPDATE materials
                SET status = 'failed',
                    progress = 100,
                    process_stage = '已放弃',
                    error_message = ?,
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (reason, now),
            )
            conn.commit()
            affected = cur.rowcount if cur.rowcount is not None else 0
        return affected

    # 保留恢复机制实现：当前版本按产品策略“重启即放弃历史任务”，
    # 因此不再对外启用该入口，后续如需恢复重放可直接接回 worker.start。
    def reset_unfinished_to_queue(self) -> list[str]:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id
                FROM materials
                WHERE status IN ('queued', 'running')
                ORDER BY datetime(created_at) ASC
                """
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                conn.execute(
                    """
                    UPDATE materials
                    SET status = 'queued', progress = 0, process_stage = '排队中', updated_at = ?
                    WHERE status IN ('queued', 'running')
                    """,
                    (now,),
                )
                conn.commit()
        return ids

    def list_course_chunk_vectors(self, course_id: str) -> list[dict[str, object]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT c.id, c.material_id, c.chunk_index, c.content, c.embedding, c.char_count, c.sentence_count,
                       c.start_sentence, c.end_sentence, c.created_at, m.filename
                FROM material_chunks c
                INNER JOIN materials m ON m.id = c.material_id
                WHERE m.course_id = ? AND m.status = 'done'
                ORDER BY datetime(c.created_at) DESC, c.chunk_index ASC
                """,
                (course_id,),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            embedding = self._decode_embedding(row["embedding"])
            if not embedding:
                continue
            result.append(
                {
                    "id": row["id"],
                    "material_id": row["material_id"],
                    "filename": row["filename"],
                    "chunk_index": row["chunk_index"],
                    "content": row["content"],
                    "embedding": embedding,
                    "char_count": row["char_count"],
                    "sentence_count": row["sentence_count"],
                    "start_sentence": row["start_sentence"],
                    "end_sentence": row["end_sentence"],
                    "created_at": row["created_at"],
                }
            )
        return result

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MaterialItem:
        return MaterialItem(
            id=row["id"],
            course_id=row["course_id"],
            filename=row["filename"],
            file_size=row["file_size"],
            status=row["status"],
            progress=row["progress"],
            process_stage=row["process_stage"],
            char_count=row["char_count"],
            summary=row["summary"] if "summary" in row.keys() else None,
            knowledge_extracted=bool(row["knowledge_extracted"]) if "knowledge_extracted" in row.keys() else False,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _decode_json_list(raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result

    @staticmethod
    def _decode_embedding(raw: str | None) -> list[float]:
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []
        result: list[float] = []
        for item in value:
            try:
                result.append(float(item))
            except (TypeError, ValueError):
                return []
        return result

    def create_course(self, name: str, description: str = "", hours: int = 0, sessions: int = 0) -> CourseItem:
        now = datetime.utcnow().isoformat()
        course_id = f"course_{uuid4().hex[:12]}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO courses (id, name, description, hours, sessions, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (course_id, name, description, hours, sessions, now),
            )
            conn.commit()
        logger.info("DB: 课程创建 | id={} | name={}", course_id, name)
        return self.get_course(course_id)

    def list_courses(self) -> list[CourseItem]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, name, description, hours, sessions, created_at
                FROM courses
                ORDER BY datetime(created_at) DESC
                """
            ).fetchall()
        return [
            CourseItem(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                hours=row["hours"],
                sessions=row["sessions"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_course(self, course_id: str) -> CourseItem:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, name, description, hours, sessions, created_at
                FROM courses
                WHERE id = ?
                """,
                (course_id,),
            ).fetchone()
        if row is None:
            raise KeyError(course_id)
        return CourseItem(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            hours=row["hours"],
            sessions=row["sessions"],
            created_at=row["created_at"],
        )

    def delete_course(self, course_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
            conn.execute("DELETE FROM chapters WHERE course_id = ?", (course_id,))
            conn.execute("UPDATE materials SET course_id = NULL WHERE course_id = ?", (course_id,))
            conn.commit()
            affected = cur.rowcount
        logger.info("DB: 课程删除 | id={} | affected={}", course_id, affected)
        return affected > 0

    def add_chapter(self, course_id: str, title: str) -> dict:
        now = datetime.utcnow().isoformat()
        chapter_id = f"ch_{uuid4().hex[:12]}"
        with sqlite3.connect(self.db_path) as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM chapters WHERE course_id = ?",
                (course_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO chapters (id, course_id, title, sort_order, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chapter_id, course_id, title, max_order + 1, now),
            )
            conn.commit()
        logger.info("DB: 章节添加 | course={} | title={}", course_id, title)
        return self.get_chapter(chapter_id)

    def list_course_chapters(self, course_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT c.id, c.course_id, c.title, c.sort_order,
                       COUNT(m.id) as material_count
                FROM chapters c
                LEFT JOIN materials m ON m.course_id = c.course_id
                WHERE c.course_id = ?
                GROUP BY c.id
                ORDER BY c.sort_order ASC
                """,
                (course_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "course_id": row["course_id"],
                "title": row["title"],
                "sort_order": row["sort_order"],
                "material_count": row["material_count"],
            }
            for row in rows
        ]

    def get_chapter(self, chapter_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, course_id, title, sort_order, created_at
                FROM chapters
                WHERE id = ?
                """,
                (chapter_id,),
            ).fetchone()
        if row is None:
            raise KeyError(chapter_id)
        return {
            "id": row["id"],
            "course_id": row["course_id"],
            "title": row["title"],
            "sort_order": row["sort_order"],
            "material_count": 0,
        }
