import sqlite3
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger

from app.schemas.ai_result import AiOutputType, AiResultDetail, AiResultItem


class AiResultRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_results (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    output_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    request_context TEXT NOT NULL DEFAULT '{}',
                    content TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(ai_results)").fetchall()
            }
            if "request_context" not in columns:
                conn.execute(
                    "ALTER TABLE ai_results ADD COLUMN request_context TEXT NOT NULL DEFAULT '{}'"
                )
            conn.commit()

    def create_result(
        self,
        course_id: str,
        output_type: AiOutputType,
        title: str,
        request_context: dict[str, str] | None = None,
    ) -> AiResultItem:
        now = datetime.utcnow().isoformat()
        result_id = f"ai_{uuid4().hex[:12]}"
        request_context_json = json.dumps(request_context or {}, ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO ai_results (
                    id, course_id, output_type, title, status, char_count, request_context, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    course_id,
                    output_type,
                    title,
                    "queued",
                    0,
                    request_context_json,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_result_item(result_id)

    def list_results(self, course_id: str) -> list[AiResultItem]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, course_id, output_type, title, status, char_count, request_context, created_at, updated_at
                FROM ai_results
                WHERE course_id = ?
                ORDER BY datetime(created_at) DESC
                """,
                (course_id,),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_result_item(self, result_id: str) -> AiResultItem:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, course_id, output_type, title, status, char_count, request_context, created_at, updated_at
                FROM ai_results
                WHERE id = ?
                """,
                (result_id,),
            ).fetchone()
        if row is None:
            raise KeyError(result_id)
        return self._row_to_item(row)

    def get_result_detail(self, result_id: str) -> AiResultDetail:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, course_id, output_type, title, status, char_count, request_context,
                       content, error_message, created_at, updated_at
                FROM ai_results
                WHERE id = ?
                """,
                (result_id,),
            ).fetchone()
        if row is None:
            raise KeyError(result_id)
        return AiResultDetail(
            id=row["id"],
            course_id=row["course_id"],
            output_type=row["output_type"],
            title=row["title"],
            status=row["status"],
            char_count=row["char_count"],
            request_context=self._decode_json_object(row["request_context"]),
            content=row["content"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_latest_done_result(self, course_id: str, output_type: AiOutputType) -> AiResultDetail | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, course_id, output_type, title, status, char_count, request_context,
                       content, error_message, created_at, updated_at
                FROM ai_results
                WHERE course_id = ? AND output_type = ? AND status = 'done'
                ORDER BY datetime(updated_at) DESC
                LIMIT 1
                """,
                (course_id, output_type),
            ).fetchone()
        if row is None:
            return None
        return AiResultDetail(
            id=row["id"],
            course_id=row["course_id"],
            output_type=row["output_type"],
            title=row["title"],
            status=row["status"],
            char_count=row["char_count"],
            request_context=self._decode_json_object(row["request_context"]),
            content=row["content"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_results_by_batch(self, lesson_batch_id: str) -> list[AiResultDetail]:
        pattern = f'%\"lesson_batch_id\": \"{lesson_batch_id}\"%'
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, course_id, output_type, title, status, char_count, request_context,
                       content, error_message, created_at, updated_at
                FROM ai_results
                WHERE request_context LIKE ?
                ORDER BY datetime(created_at) ASC
                """,
                (pattern,),
            ).fetchall()
        results: list[AiResultDetail] = []
        for row in rows:
            results.append(
                AiResultDetail(
                    id=row["id"],
                    course_id=row["course_id"],
                    output_type=row["output_type"],
                    title=row["title"],
                    status=row["status"],
                    char_count=row["char_count"],
                    request_context=self._decode_json_object(row["request_context"]),
                    content=row["content"],
                    error_message=row["error_message"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            )
        return results

    def update_status(self, result_id: str, status: str) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE ai_results SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, result_id),
            )
            conn.commit()

    def append_content(self, result_id: str, chunk: str) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE ai_results
                SET content = COALESCE(content, '') || ?,
                    char_count = char_count + ?,
                    status = 'running',
                    updated_at = ?
                WHERE id = ?
                """,
                (chunk, len(chunk), now, result_id),
            )
            conn.commit()

    def update_request_context(self, result_id: str, updates: dict[str, str]) -> None:
        now = datetime.utcnow().isoformat()
        current = self.get_result_item(result_id).request_context
        merged = {**current}
        for key, value in updates.items():
            if value is None:
                continue
            merged[str(key)] = str(value)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE ai_results SET request_context = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), now, result_id),
            )
            conn.commit()

    def mark_done(self, result_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE ai_results SET status = 'done', updated_at = ? WHERE id = ?",
                (now, result_id),
            )
            conn.commit()

    def mark_failed(self, result_id: str, error_message: str) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE ai_results SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
                (error_message, now, result_id),
            )
            conn.commit()

    def abandon_unfinished_results(self) -> int:
        now = datetime.utcnow().isoformat()
        message = "服务重启后已放弃历史生成任务（恢复机制暂未启用）"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE ai_results
                SET status = 'failed',
                    error_message = ?,
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (message, now),
            )
            conn.commit()
        count = int(cursor.rowcount or 0)
        if count > 0:
            logger.info("AI 结果仓库启动清理：已放弃 {} 个历史未完成任务", count)
        else:
            logger.info("AI 结果仓库启动清理：无历史未完成任务需要放弃")
        return count

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> AiResultItem:
        return AiResultItem(
            id=row["id"],
            course_id=row["course_id"],
            output_type=row["output_type"],
            title=row["title"],
            status=row["status"],
            char_count=row["char_count"],
            request_context=AiResultRepository._decode_json_object(row["request_context"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _decode_json_object(raw: str | None) -> dict[str, str]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, dict):
            return {}
        result: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            if isinstance(item, str):
                result[key] = item
            elif item is not None:
                result[key] = str(item)
        return result
