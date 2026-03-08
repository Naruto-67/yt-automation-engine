# engine/database.py
import sqlite3
import os
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from engine.models import VideoJob, JobState, FailureLog
from engine.logger import logger

class SQLiteDB:
    def __init__(self, db_path="memory/ghost_engine.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize_tables()

    def _connect(self):
        return sqlite3.connect(self.db_path, isolation_level=None)

    def _initialize_tables(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
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
                    updated_at TEXT,
                    UNIQUE(channel_id, topic)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    channel_id TEXT,
                    module TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    traceback TEXT,
                    timestamp TEXT NOT NULL
                )
            ''')

            # 🚨 V5 UPGRADE: Eliminating api_state.json
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_quotas (
                    date TEXT PRIMARY KEY,
                    youtube_points INTEGER DEFAULT 0,
                    gemini_calls INTEGER DEFAULT 0,
                    cf_images INTEGER DEFAULT 0,
                    hf_images INTEGER DEFAULT 0,
                    yt_last_used TEXT
                )
            ''')

            # 🚨 V5 UPGRADE: Eliminating lessons_learned.json
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_intelligence (
                    channel_id TEXT PRIMARY KEY,
                    emphasize TEXT,
                    avoid TEXT,
                    recent_tags TEXT,
                    preferred_visuals TEXT,
                    updated_at TEXT
                )
            ''')

    # --- JOB METHODS ---
    def upsert_job(self, job: VideoJob) -> int:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO jobs (
                    channel_id, topic, niche, state, script, metadata, 
                    audio_path, image_paths, video_path, youtube_id, 
                    attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, topic) DO UPDATE SET
                    state=excluded.state, script=excluded.script, metadata=excluded.metadata,
                    audio_path=excluded.audio_path, image_paths=excluded.image_paths,
                    video_path=excluded.video_path, youtube_id=excluded.youtube_id,
                    attempts=excluded.attempts, updated_at=excluded.updated_at
            ''', (
                job.channel_id, job.topic, job.niche, job.state.value, 
                job.script, job.metadata, job.audio_path, job.image_paths, 
                job.video_path, job.youtube_id, job.attempts, job.created_at, job.updated_at
            ))
            if not job.id:
                cursor.execute('SELECT id FROM jobs WHERE channel_id = ? AND topic = ?', (job.channel_id, job.topic))
                job.id = cursor.fetchone()[0]
            return job.id

    def get_jobs_by_state(self, channel_id: str, state: JobState, limit: int = 5) -> List[VideoJob]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM jobs WHERE channel_id = ? AND state = ? ORDER BY created_at ASC LIMIT ?', 
                           (channel_id, state.value, limit))
            rows = cursor.fetchall()
            jobs = []
            for r in rows:
                jobs.append(VideoJob(
                    id=r[0], channel_id=r[1], topic=r[2], niche=r[3], state=JobState(r[4]),
                    script=r[5], metadata=r[6], audio_path=r[7], image_paths=r[8],
                    video_path=r[9], youtube_id=r[10], attempts=r[11],
                    created_at=r[12], updated_at=r[13]
                ))
            return jobs

    def log_failure(self, failure: FailureLog):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO failures (job_id, channel_id, module, error_message, traceback, timestamp) VALUES (?, ?, ?, ?, ?, ?)', 
                           (failure.job_id, failure.channel_id, failure.module, failure.error_message, failure.traceback, failure.timestamp))

    # --- QUOTA METHODS ---
    def get_quota_state(self, date_str: str) -> Optional[Dict]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM api_quotas WHERE date = ?', (date_str,))
            row = c.fetchone()
            if row: return {"date": row[0], "youtube_points": row[1], "gemini_calls": row[2], "cf_images": row[3], "hf_images": row[4], "yt_last_used": row[5]}
            return None

    def init_quota_state(self, date_str: str, yt_last_used: str):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO api_quotas (date, yt_last_used) VALUES (?, ?)', (date_str, yt_last_used))

    def update_quota(self, date_str: str, provider_col: str, amount: int, yt_last_used: str = None):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(f'UPDATE api_quotas SET {provider_col} = {provider_col} + ? WHERE date = ?', (amount, date_str))
            if yt_last_used:
                c.execute('UPDATE api_quotas SET yt_last_used = ? WHERE date = ?', (yt_last_used, date_str))

    # --- INTELLIGENCE METHODS ---
    def get_channel_intelligence(self, channel_id: str) -> Dict[str, List]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('SELECT emphasize, avoid, recent_tags, preferred_visuals FROM channel_intelligence WHERE channel_id = ?', (channel_id,))
            row = c.fetchone()
            if row:
                return {
                    "emphasize": json.loads(row[0]) if row[0] else [],
                    "avoid": json.loads(row[1]) if row[1] else [],
                    "recent_tags": json.loads(row[2]) if row[2] else [],
                    "preferred_visuals": json.loads(row[3]) if row[3] else ["Cinematic"]
                }
            return {"emphasize": [], "avoid": [], "recent_tags": [], "preferred_visuals": ["Cinematic"]}

    def upsert_channel_intelligence(self, channel_id: str, emphasize: List, avoid: List, tags: List, visuals: List):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO channel_intelligence (channel_id, emphasize, avoid, recent_tags, preferred_visuals, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    emphasize=excluded.emphasize, avoid=excluded.avoid,
                    recent_tags=excluded.recent_tags, preferred_visuals=excluded.preferred_visuals,
                    updated_at=excluded.updated_at
            ''', (channel_id, json.dumps(emphasize), json.dumps(avoid), json.dumps(tags), json.dumps(visuals), datetime.utcnow().isoformat()))

db = SQLiteDB()
