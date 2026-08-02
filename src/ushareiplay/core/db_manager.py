from tortoise import Tortoise
from tortoise import connections
from datetime import datetime, timedelta
from typing import Optional, List
from pathlib import Path

class DatabaseManager:
    def __init__(self, db_url: str = None):
        if db_url is None:
            # Create db directory if it doesn't exist
            db_dir = Path('data')
            db_dir.mkdir(exist_ok=True)
            
            # Use the runtime SQLite database location
            db_path = db_dir / 'soul_bot.db'
            self.db_url = f"sqlite://{db_path}"
        else:
            self.db_url = db_url

    async def init(self):
        """Initialize database connection and generate schemas"""
        await Tortoise.init(
            db_url=self.db_url,
            modules={'models': ['ushareiplay.models']},
            use_tz=False,
        )
        await Tortoise.generate_schemas()
        await self._ensure_user_canonical_column()
        await self._ensure_keyword_mode_column()
        await self._ensure_keyword_allowed_users_column()
        await self._ensure_focus_events_created_at()
        await self._ensure_receive_events_created_at()

    async def _ensure_focus_events_created_at(self) -> None:
        """
        既有 focus_events 表若 created_at 为 NULL（早期 null=True 模型），回填为当前时间；
        新插入由 Tortoise auto_now_add 写入。
        """
        conn = connections.get("default")
        try:
            tables = await conn.execute_query_dict(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='focus_events'"
            )
            if not tables:
                return
        except Exception:
            return
        await conn.execute_script(
            "UPDATE focus_events SET created_at = datetime('now') WHERE created_at IS NULL;"
        )

    async def _ensure_receive_events_created_at(self) -> None:
        """
        确保 receive_events 表的 created_at 列具备标准 SQL 默认值 `DEFAULT CURRENT_TIMESTAMP`；
        已有的 NULL 记录回填为当前时间。
        """
        conn = connections.get("default")
        try:
            tables = await conn.execute_query_dict(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='receive_events'"
            )
            if not tables:
                return
        except Exception:
            return

        await conn.execute_script(
            "UPDATE receive_events SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL;"
        )

        rows = await conn.execute_query_dict("PRAGMA table_info(receive_events)")
        columns = {r.get("name"): r for r in rows}
        created_at_col = columns.get("created_at")

        if not created_at_col:
            await conn.execute_script(
                "ALTER TABLE receive_events ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
            )
        elif created_at_col.get("dflt_value") is None:
            await conn.execute_script(
                """
                CREATE TABLE receive_events_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                    command TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE
                );
                INSERT INTO receive_events_new (id, command, created_at, user_id)
                SELECT id, command, COALESCE(created_at, CURRENT_TIMESTAMP), user_id FROM receive_events;
                DROP TABLE receive_events;
                ALTER TABLE receive_events_new RENAME TO receive_events;
                """
            )




    async def _ensure_user_canonical_column(self) -> None:
        """
        Tortoise `generate_schemas()` does not evolve existing SQLite tables.
        We apply a minimal additive schema patch for the new `users.canonical_user_id` column.
        """
        conn = connections.get("default")
        rows = await conn.execute_query_dict("PRAGMA table_info(users)")
        columns = {r.get("name") for r in rows}
        if "canonical_user_id" in columns:
            return

        await conn.execute_script(
            """
            ALTER TABLE users ADD COLUMN canonical_user_id INTEGER NULL REFERENCES users(id);
            CREATE INDEX IF NOT EXISTS idx_users_canonical_user_id ON users(canonical_user_id);
            """
        )

    async def _ensure_keyword_mode_column(self) -> None:
        """
        为既有数据库补充 keywords.mode 列。
        默认 sequence（按命令列表顺序执行）。
        """
        conn = connections.get("default")
        rows = await conn.execute_query_dict("PRAGMA table_info(keywords)")
        columns = {r.get("name") for r in rows}
        if "mode" in columns:
            return

        await conn.execute_script(
            """
            ALTER TABLE keywords ADD COLUMN mode VARCHAR(32) NOT NULL DEFAULT 'sequence';
            """
        )

    async def _ensure_keyword_allowed_users_column(self) -> None:
        """
        为既有数据库补充 keywords.allowed_user_ids 列。
        用 JSON 数组文本存储允许执行私有关键字的 canonical user id 列表。
        默认 []（仅创建者可执行）。
        """
        conn = connections.get("default")
        rows = await conn.execute_query_dict("PRAGMA table_info(keywords)")
        columns = {r.get("name") for r in rows}
        if "allowed_user_ids" in columns:
            return

        await conn.execute_script(
            """
            ALTER TABLE keywords ADD COLUMN allowed_user_ids TEXT NOT NULL DEFAULT '[]';
            """
        )

    async def close(self):
        """Close database connection"""
        await Tortoise.close_connections()
