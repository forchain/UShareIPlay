from tortoise import Tortoise
from datetime import datetime, timedelta
from typing import Optional, List

class DatabaseManager:
    def __init__(self, db_url: str = "sqlite://db.sqlite3"):
        self.db_url = db_url

    async def init(self):
        """Initialize database connection and generate schemas"""
        await Tortoise.init(
            db_url=self.db_url,
            modules={'models': ['src.models']}
        )
        await Tortoise.generate_schemas()

    async def close(self):
        """Close database connection"""
        await Tortoise.close_connections() 