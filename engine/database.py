# engine/database.py — Ghost Engine V6
import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from engine.models import VideoJob, JobState, FailureLog

# DB lives in memory/ so it can be committed with `git add memory/`
_DB_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "memory", "ghost_engine.db")


class SQLiteDB:
    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize_tables()

    def _connect(self):
        return sqlite3.connect(self.db_path, isolation_level=None)

    def _initialize_tables(self):
        with self._connect() as conn:
            c = conn.cursor()

            c.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id    TEXT NOT NULL,
                    topic         TEXT NOT NULL,
                    niche         TEXT NOT NULL,
                    state         TEXT NOT NULL,
                    script        TEXT,
                    metadata      TEXT,
                    audio_path    TEXT,
                    image_paths   TEXT,
                    video_path    TEXT,
                    youtube_id    TEXT,
                    attempts      INTEGER DEFAULT 0,
                    created_at    TEXT,
                    updated_at    TEXT,
                    UNIQUE(channel_id, topic)
                )
            ''')

            c.execute('''
                CREATE TABLE IF NOT EXISTS failures (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id        INTEGER,
                    channel_id    TEXT,
                    module        TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    traceback     TEXT,
                    timestamp     TEXT NOT NULL
                )
            ''')

            # Quota tracking — now persisted in DB AND mirrored to memory/quota_state.json
            # for cross-workflow awareness
            c.execute('''
                CREATE TABLE IF NOT EXISTS api_quotas (
                    date          TEXT PRIMARY KEY,
                    youtube_points INTEGER DEFAULT 0,
                    gemini_calls   INTEGER DEFAULT 0,
                    cf_images      INTEGER DEFAULT 0,
                    hf_images      INTEGER DEFAULT 0,
                    yt_last_used   TEXT
                )
            ''')

            # Per-channel content strategy (replaces lessons_learned.json)
            c.execute('''
                CREATE TABLE IF NOT EXISTS channel_intelligence (
                    channel_id        TEXT PRIMARY KEY,
                    emphasize         TEXT,    -- JSON list, time-decayed
                    avoid             TEXT,    -- JSON list, time-decayed
                    recent_tags       TEXT,    -- JSON list
                    preferred_visuals TEXT,    -- JSON list
                    hook_patterns     TEXT,    -- JSON list from competitor research
                    title_templates   TEXT,    -- JSON list from competitor research
                    competitor_tags   TEXT,    -- JSON list from competitor research
                    evolved_niche     TEXT,    -- AI-discovered niche evolution
                    rule_timestamps   TEXT,    -- JSON: {rule_index: iso_timestamp}
                    updated_at        TEXT
                )
            ''')

            # Video performance tracking for recency-weighted analysis
            c.execute('''
                CREATE TABLE IF NOT EXISTS video_performance (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id  TEXT NOT NULL,
                    youtube_id  TEXT UNIQUE,
                    title       TEXT,
                    views       INTEGER DEFAULT 0,
                    likes       INTEGER DEFAULT 0,
                    comments    INTEGER DEFAULT 0,
                    published_at TEXT,
                    fetched_at   TEXT
                )
            ''')

    # ── JOB METHODS ──────────────────────────────────────────────────────────

    def upsert_job(self, job: VideoJob) -> int:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO jobs
                    (channel_id, topic, niche, state, script, metadata,
                     audio_path, image_paths, video_path, youtube_id,
                     attempts, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(channel_id, topic) DO UPDATE SET
                    state=excluded.state, script=excluded.script,
                    metadata=excluded.metadata, audio_path=excluded.audio_path,
                    image_paths=excluded.image_paths, video_path=excluded.video_path,
                    youtube_id=excluded.youtube_id, attempts=excluded.attempts,
                    updated_at=excluded.updated_at
            ''', (
                job.channel_id, job.topic, job.niche, job.state.value,
                job.script, job.metadata, job.audio_path, job.image_paths,
                job.video_path, job.youtube_id, job.attempts,
                job.created_at, job.updated_at
            ))
            if not job.id:
                c.execute('SELECT id FROM jobs WHERE channel_id=? AND topic=?',
                          (job.channel_id, job.topic))
                row = c.fetchone()
                if row:
                    job.id = row[0]
        return job.id

    def get_jobs_by_state(self, channel_id: str, state: JobState,
                          limit: int = 5) -> List[VideoJob]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT * FROM jobs WHERE channel_id=? AND state=? ORDER BY created_at ASC LIMIT ?',
                (channel_id, state.value, limit)
            )
            return [self._row_to_job(r) for r in c.fetchall()]

    def get_unprocessed_count(self, channel_id: str) -> int:
        terminal = (JobState.PUBLISHED.value, JobState.FAILED.value)
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT COUNT(*) FROM jobs WHERE channel_id=? AND state NOT IN (?,?)',
                (channel_id, *terminal)
            )
            return c.fetchone()[0]

    def get_all_topics(self, channel_id: str) -> List[str]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('SELECT topic FROM jobs WHERE channel_id=?', (channel_id,))
            return [r[0].lower().strip() for r in c.fetchall()]

    def log_failure(self, failure: FailureLog):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT INTO failures (job_id, channel_id, module, error_message, traceback, timestamp) '
                'VALUES (?,?,?,?,?,?)',
                (failure.job_id, failure.channel_id, failure.module,
                 failure.error_message, failure.traceback, failure.timestamp)
            )

    def prune_old_jobs(self, days: int = 30):
        """Remove PUBLISHED and FAILED jobs older than N days to keep DB small."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        terminal = (JobState.PUBLISHED.value, JobState.FAILED.value)
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                'DELETE FROM jobs WHERE state IN (?,?) AND updated_at < ?',
                (*terminal, cutoff)
            )
            deleted = c.rowcount
        return deleted

    @staticmethod
    def _row_to_job(r) -> VideoJob:
        return VideoJob(
            id=r[0], channel_id=r[1], topic=r[2], niche=r[3],
            state=JobState(r[4]), script=r[5], metadata=r[6],
            audio_path=r[7], image_paths=r[8], video_path=r[9],
            youtube_id=r[10], attempts=r[11], created_at=r[12], updated_at=r[13]
        )

    # ── QUOTA METHODS ────────────────────────────────────────────────────────

    def get_quota_state(self, date_str: str) -> Optional[Dict]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM api_quotas WHERE date=?', (date_str,))
            row = c.fetchone()
            if row:
                return {"date": row[0], "youtube_points": row[1],
                        "gemini_calls": row[2], "cf_images": row[3],
                        "hf_images": row[4], "yt_last_used": row[5]}
        return None

    def init_quota_state(self, date_str: str, yt_last_used: str):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT OR IGNORE INTO api_quotas (date, yt_last_used) VALUES (?,?)',
                (date_str, yt_last_used)
            )

    def update_quota(self, date_str: str, provider_col: str, amount: int,
                     yt_last_used: str = None):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                f'UPDATE api_quotas SET {provider_col} = {provider_col} + ? WHERE date=?',
                (amount, date_str)
            )
            if yt_last_used:
                c.execute(
                    'UPDATE api_quotas SET yt_last_used=? WHERE date=?',
                    (yt_last_used, date_str)
                )

    # ── CHANNEL INTELLIGENCE METHODS ─────────────────────────────────────────

    def get_channel_intelligence(self, channel_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT emphasize, avoid, recent_tags, preferred_visuals, '
                'hook_patterns, title_templates, competitor_tags, evolved_niche, '
                'rule_timestamps FROM channel_intelligence WHERE channel_id=?',
                (channel_id,)
            )
            row = c.fetchone()
            if row:
                return {
                    "emphasize":        json.loads(row[0]) if row[0] else [],
                    "avoid":            json.loads(row[1]) if row[1] else [],
                    "recent_tags":      json.loads(row[2]) if row[2] else [],
                    "preferred_visuals":json.loads(row[3]) if row[3] else ["Cinematic"],
                    "hook_patterns":    json.loads(row[4]) if row[4] else [],
                    "title_templates":  json.loads(row[5]) if row[5] else [],
                    "competitor_tags":  json.loads(row[6]) if row[6] else [],
                    "evolved_niche":    row[7] or None,
                    "rule_timestamps":  json.loads(row[8]) if row[8] else {},
                }
        return {
            "emphasize": [], "avoid": [], "recent_tags": [],
            "preferred_visuals": ["Cinematic"], "hook_patterns": [],
            "title_templates": [], "competitor_tags": [],
            "evolved_niche": None, "rule_timestamps": {}
        }

    def upsert_channel_intelligence(self, channel_id: str, data: Dict):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO channel_intelligence
                    (channel_id, emphasize, avoid, recent_tags, preferred_visuals,
                     hook_patterns, title_templates, competitor_tags, evolved_niche,
                     rule_timestamps, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    emphasize=excluded.emphasize, avoid=excluded.avoid,
                    recent_tags=excluded.recent_tags,
                    preferred_visuals=excluded.preferred_visuals,
                    hook_patterns=excluded.hook_patterns,
                    title_templates=excluded.title_templates,
                    competitor_tags=excluded.competitor_tags,
                    evolved_niche=excluded.evolved_niche,
                    rule_timestamps=excluded.rule_timestamps,
                    updated_at=excluded.updated_at
            ''', (
                channel_id,
                json.dumps(data.get("emphasize", [])),
                json.dumps(data.get("avoid", [])),
                json.dumps(data.get("recent_tags", [])),
                json.dumps(data.get("preferred_visuals", ["Cinematic"])),
                json.dumps(data.get("hook_patterns", [])),
                json.dumps(data.get("title_templates", [])),
                json.dumps(data.get("competitor_tags", [])),
                data.get("evolved_niche"),
                json.dumps(data.get("rule_timestamps", {})),
                datetime.utcnow().isoformat()
            ))

    # ── VIDEO PERFORMANCE METHODS ─────────────────────────────────────────────

    def upsert_video_performance(self, channel_id: str, youtube_id: str,
                                  title: str, views: int, likes: int,
                                  comments: int, published_at: str):
        with self._connect() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO video_performance
                    (channel_id, youtube_id, title, views, likes, comments,
                     published_at, fetched_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(youtube_id) DO UPDATE SET
                    views=excluded.views, likes=excluded.likes,
                    comments=excluded.comments, fetched_at=excluded.fetched_at
            ''', (channel_id, youtube_id, title, views, likes, comments,
                  published_at, datetime.utcnow().isoformat()))

    def get_recent_performance(self, channel_id: str, days: int = 30) -> List[Dict]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            c = conn.cursor()
            c.execute(
                'SELECT youtube_id, title, views, likes, comments, published_at '
                'FROM video_performance WHERE channel_id=? AND published_at > ? '
                'ORDER BY views DESC',
                (channel_id, cutoff)
            )
            cols = ["youtube_id", "title", "views", "likes", "comments", "published_at"]
            return [dict(zip(cols, r)) for r in c.fetchall()]


db = SQLiteDB()
