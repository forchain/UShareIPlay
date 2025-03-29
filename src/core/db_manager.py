from tortoise import Tortoise
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
            modules={'models': ['src.models']}
        )
        await Tortoise.generate_schemas()

    async def close(self):
        """Close database connection"""
        await Tortoise.close_connections() 