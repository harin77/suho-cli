"""SQLite-backed memory store — sessions, tasks, long-term facts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import structlog

from suho_agent.agent.state import TaskState

log = structlog.get_logger(__name__)


class MemoryEntry:
    def __init__(
        self,
        id: str,
        key: str,
        value: str,
        category: str,
        importance: int,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.key = key
        self.value = value
        self.category = category
        self.importance = importance
        self.created_at = created_at

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
        }


class TaskHistoryEntry:
    def __init__(
        self,
        task_id: str,
        request: str,
        status: str,
        created_at: datetime,
        duration_ms: Optional[int],
        tool_calls: Optional[int],
    ) -> None:
        self.task_id = task_id
        self.request = request
        self.status = status
        self.created_at = created_at
        self.duration_ms = duration_ms
        self.tool_calls = tool_calls

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "request": self.request,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "duration_ms": self.duration_ms,
            "tool_calls": self.tool_calls,
        }


class MemoryStore:
    """
    SQLite-backed memory store.

    Tables:
    - tasks: task history and checkpoints
    - memories: long-term facts and preferences
    - tool_history: history of tool calls
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                request TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                duration_ms INTEGER,
                tool_calls INTEGER,
                files_changed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance INTEGER DEFAULT 5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                tool TEXT NOT NULL,
                args_json TEXT,
                success INTEGER NOT NULL,
                duration_ms INTEGER,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
            CREATE INDEX IF NOT EXISTS idx_tool_history_task ON tool_history(task_id);
        """)
        await self._db.commit()
        log.debug("Memory store initialized", path=str(self._db_path))

    async def save_task_state(self, state: TaskState) -> None:
        """Persist full task state as checkpoint."""
        now = datetime.now(timezone.utc).isoformat()
        state_json = state.model_dump_json()

        await self._db.execute("""
            INSERT INTO tasks (task_id, request, status, state_json, created_at, updated_at, duration_ms, tool_calls, files_changed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status = excluded.status,
                state_json = excluded.state_json,
                updated_at = excluded.updated_at,
                duration_ms = excluded.duration_ms,
                tool_calls = excluded.tool_calls,
                files_changed = excluded.files_changed
        """, (
            state.task_id,
            state.user_request[:500],
            state.status.value,
            state_json,
            state.start_time.isoformat(),
            now,
            state.duration_ms,
            state.tool_call_count,
            len(state.files_changed),
        ))
        await self._db.commit()

    async def load_task_state(self, task_id: str) -> Optional[TaskState]:
        """Load a task state from checkpoint."""
        async with self._db.execute(
            "SELECT state_json FROM tasks WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            return TaskState.model_validate_json(row[0])

    async def get_task_history(self, limit: int = 20) -> list[TaskHistoryEntry]:
        """Get recent task history."""
        entries = []
        async with self._db.execute(
            "SELECT task_id, request, status, created_at, duration_ms, tool_calls FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            async for row in cursor:
                entries.append(TaskHistoryEntry(
                    task_id=row[0],
                    request=row[1],
                    status=row[2],
                    created_at=datetime.fromisoformat(row[3]),
                    duration_ms=row[4],
                    tool_calls=row[5],
                ))
        return entries

    async def get_most_recent_task_id(self) -> Optional[str]:
        """Get the most recent task ID (for resume)."""
        async with self._db.execute(
            "SELECT task_id FROM tasks ORDER BY created_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def save_memory(self, key: str, value: str, category: str = "general", importance: int = 5) -> str:
        """Store a long-term memory."""
        import uuid
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("""
            INSERT INTO memories (id, key, value, category, importance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (entry_id, key, value, category, importance, now, now))
        await self._db.commit()
        return entry_id

    async def list_memories(self, limit: int = 20) -> list[MemoryEntry]:
        entries = []
        async with self._db.execute(
            "SELECT id, key, value, category, importance, created_at FROM memories ORDER BY importance DESC, created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            async for row in cursor:
                entries.append(MemoryEntry(
                    id=row[0], key=row[1], value=row[2],
                    category=row[3], importance=row[4],
                    created_at=datetime.fromisoformat(row[5]),
                ))
        return entries

    async def search_memories(self, query: str) -> list[MemoryEntry]:
        entries = []
        async with self._db.execute(
            "SELECT id, key, value, category, importance, created_at FROM memories WHERE key LIKE ? OR value LIKE ? LIMIT 20",
            (f"%{query}%", f"%{query}%"),
        ) as cursor:
            async for row in cursor:
                entries.append(MemoryEntry(
                    id=row[0], key=row[1], value=row[2],
                    category=row[3], importance=row[4],
                    created_at=datetime.fromisoformat(row[5]),
                ))
        return entries

    async def delete_memory(self, entry_id: str) -> None:
        await self._db.execute("DELETE FROM memories WHERE id = ?", (entry_id,))
        await self._db.commit()

    async def clear_memories(self) -> None:
        await self._db.execute("DELETE FROM memories")
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
