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
            
            # Use the same database location as DBHelper
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

    async def close(self):
        """Close database connection"""
        await Tortoise.close_connections() 