import sqlite3
from datetime import datetime
import os
from pathlib import Path
from collections import defaultdict

class DBHelper:
    def __init__(self):
        # Create db directory if it doesn't exist
        db_dir = Path('data')
        db_dir.mkdir(exist_ok=True)
        
        self.db_path = db_dir / 'soul_bot.db'
        self.conn = sqlite3.connect(str(self.db_path))
        self.cursor = self.conn.cursor()
        self.init_db()

    def init_db(self):
        # Create tables if they don't exist
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_hellos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_username TEXT NOT NULL,
            sender_name TEXT NOT NULL, 
            song_name TEXT NOT NULL,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        self.conn.commit()

    def add_pending_hello(self, target_username, sender_name, song_name, message):
        self.cursor.execute('''
        INSERT INTO pending_hellos 
        (target_username, sender_name, song_name, message)
        VALUES (?, ?, ?, ?)
        ''', (target_username, sender_name, song_name, message))
        self.conn.commit()

    def get_pending_hellos(self):
        """Get all pending hellos and convert to defaultdict format
        Returns:
            defaultdict: {username: [(sender, message, song), ...]}
        """
        self.cursor.execute('''
        SELECT target_username, sender_name, message, song_name
        FROM pending_hellos
        ''')
        results = self.cursor.fetchall()
        
        # Convert to defaultdict(list) format
        pending = defaultdict(list)
        for username, sender, message, song in results:
            pending[username].append((sender, message, song))
            
        return pending

    def delete_hello(self, username):
        """Delete all hellos for given username"""
        self.cursor.execute('''
        DELETE FROM pending_hellos
        WHERE target_username = ?
        ''', (username,))
        self.conn.commit()

    def __del__(self):
        self.conn.close() 