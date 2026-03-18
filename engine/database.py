# engine/database.py
import sqlite3
import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from engine.logger import logger
from engine.models import VideoJob, JobState, FailureLog
from engine.config_manager import config_manager

class DatabaseManager:
    def __init__(self):
        settings = config_manager.get_settings()
        self.test_mode = os.environ.get("TEST_MODE", "false").lower() == "true"
        self.db_path = settings["paths"]["test_database"] if self.test_mode else settings["paths"]["database"]
        
        logger.engine(f"📁 [DATABASE] Pointing to: {self.db_path}")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.create_tables()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def create_tables(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    niche TEXT NOT NULL,
                    state TEXT NOT NULL,
                    script TEXT,
                    metadata TEXT,
                    audio_path TEXT,
                    image_paths TEXT,
                    video_path TEXT,
                    youtube_id TEXT,
                    attempts INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quota_usage (
                    date TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    youtube_points INTEGER DEFAULT 0,
                    gemini_calls INTEGER DEFAULT 0,
                    cf_images INTEGER DEFAULT 0,
                    hf_images INTEGER DEFAULT 0,
                    last_yt_update TEXT,
                    PRIMARY KEY (date, target_id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_intelligence (
                    channel_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT
                )
            ''')
            conn.commit()

    def get_quota_state(self, date: str, target_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM quota_usage WHERE date=? AND target_id=?', (date, target_id))
            row = cursor.fetchone()
            return dict(row) if row else None

    def init_quota_state(self, date: str, target_id: str, yt_update: str = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO quota_usage (date, target_id, last_yt_update) VALUES (?, ?, ?)', 
                          (date, target_id, yt_update))
            conn.commit()

    def update_quota(self, date: str, target_id: str, column: str, amount: int, yt_update: str = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE quota_usage SET {column} = {column} + ?, last_yt_update = ? WHERE date=? AND target_id=?', 
                          (amount, yt_update, date, target_id))
            conn.commit()

    def upsert_job(self, job: VideoJob) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            job.updated_at = datetime.utcnow().isoformat()
            if job.id:
                cursor.execute('''
                    UPDATE video_jobs SET state=?, script=?, metadata=?, audio_path=?, video_path=?, updated_at=? WHERE id=?
                ''', (job.state.value, job.script, job.metadata, job.audio_path, job.video_path, job.updated_at, job.id))
            else:
                cursor.execute('''
                    INSERT INTO video_jobs (channel_id, topic, niche, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                ''', (job.channel_id, job.topic, job.niche, job.state.value, job.created_at, job.updated_at))
                job.id = cursor.lastrowid
            conn.commit()
            return job.id

    def get_jobs_by_state(self, channel_id: str, state: JobState, limit: int = 5) -> List[VideoJob]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM video_jobs WHERE channel_id=? AND state=? LIMIT ?', (channel_id, state.value, limit))
            return [VideoJob(**dict(row)) for row in cursor.fetchall()]

    def get_channel_intelligence(self, channel_id: str) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT data FROM channel_intelligence WHERE channel_id=?', (channel_id,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row else {"emphasize": [], "avoid": [], "preferred_visuals": [], "hook_patterns": [], "evolved_niche": None}

    def upsert_channel_intelligence(self, channel_id: str, data: dict):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO channel_intelligence (channel_id, data, updated_at) VALUES (?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at', 
                          (channel_id, json.dumps(data), datetime.utcnow().isoformat()))
            conn.commit()

db = DatabaseManager()
