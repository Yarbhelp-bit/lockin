"""
Lock In — Shared database module
SQLite storage for behavioral monitoring data.
Used by monitor, dashboard, and analyzer.
"""

import sqlite3
import os
import time
import json

_SYSTEM_DB = "/var/lib/lockin/monitor.db"
_USER_DB = os.path.join(os.path.expanduser("~"), ".local", "share", "lockin", "monitor.db")

# Use system DB if writable, else fall back to user-local
if os.path.exists(_SYSTEM_DB) and os.access(_SYSTEM_DB, os.W_OK):
    DB_PATH = _SYSTEM_DB
elif os.access(os.path.dirname(_SYSTEM_DB), os.W_OK) if os.path.isdir(os.path.dirname(_SYSTEM_DB)) else False:
    DB_PATH = _SYSTEM_DB
else:
    DB_PATH = _USER_DB

SCREENSHOTS_DIR = os.path.join(os.path.dirname(DB_PATH), "screenshots")


def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def get_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            duration_minutes INTEGER NOT NULL,
            allowed_sites TEXT NOT NULL,
            productivity_score REAL,
            focus_score REAL,
            distraction_count INTEGER DEFAULT 0,
            bypass_attempts INTEGER DEFAULT 0,
            ai_summary TEXT
        );

        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            timestamp INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            category TEXT,
            data TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            timestamp INTEGER NOT NULL,
            filepath TEXT NOT NULL,
            ocr_text TEXT,
            active_window TEXT,
            ai_analysis TEXT,
            flagged INTEGER DEFAULT 0,
            flag_reason TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS window_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            timestamp INTEGER NOT NULL,
            window_title TEXT,
            app_name TEXT,
            duration_seconds INTEGER DEFAULT 0,
            is_productive INTEGER DEFAULT 1,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_minutes INTEGER DEFAULT 0,
            sessions_count INTEGER DEFAULT 0,
            avg_productivity REAL DEFAULT 0,
            avg_focus REAL DEFAULT 0,
            bypass_attempts INTEGER DEFAULT 0,
            distraction_events INTEGER DEFAULT 0,
            top_distractions TEXT,
            ai_insights TEXT
        );

        CREATE TABLE IF NOT EXISTS keystroke_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            timestamp INTEGER NOT NULL,
            interval_seconds INTEGER DEFAULT 60,
            keypress_count INTEGER DEFAULT 0,
            active_typing INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_activity_session ON activity(session_id);
        CREATE INDEX IF NOT EXISTS idx_activity_type ON activity(event_type);
        CREATE INDEX IF NOT EXISTS idx_screenshots_session ON screenshots(session_id);
        CREATE INDEX IF NOT EXISTS idx_window_log_session ON window_log(session_id);
        CREATE INDEX IF NOT EXISTS idx_keystroke_session ON keystroke_stats(session_id);

        -- Video Confrontation System
        CREATE TABLE IF NOT EXISTS video_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_order INTEGER NOT NULL,
            title TEXT,
            file_path TEXT,
            message TEXT,
            source TEXT DEFAULT 'default',
            min_watch_seconds INTEGER DEFAULT 10,
            tier INTEGER DEFAULT 1,
            created_at INTEGER,
            play_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS chain_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            trigger_reason TEXT,
            slots_played INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            start_slot INTEGER DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_video_slots_order ON video_slots(slot_order);
        CREATE INDEX IF NOT EXISTS idx_chain_events_ts ON chain_events(timestamp);
    """)
    conn.commit()
    conn.close()


# ---- Session helpers ----

def create_session(duration_minutes, allowed_sites):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO sessions (started_at, duration_minutes, allowed_sites) VALUES (?, ?, ?)",
        (int(time.time()), duration_minutes, allowed_sites)
    )
    session_id = cur.lastrowid
    conn.commit()
    conn.close()
    return session_id


def end_session(session_id, productivity_score=None, focus_score=None):
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET ended_at=?, productivity_score=?, focus_score=? WHERE id=?",
        (int(time.time()), productivity_score, focus_score, session_id)
    )
    conn.commit()
    conn.close()


def get_active_session():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_session(session_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_sessions(limit=50, offset=0):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_sessions():
    today = time.strftime("%Y-%m-%d")
    start = int(time.mktime(time.strptime(today, "%Y-%m-%d")))
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE started_at >= ? ORDER BY started_at DESC",
        (start,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Activity logging ----

def log_activity(session_id, event_type, category=None, data=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO activity (session_id, timestamp, event_type, category, data) VALUES (?, ?, ?, ?, ?)",
        (session_id, int(time.time()), event_type, category, json.dumps(data) if data else None)
    )
    conn.commit()
    conn.close()


def get_session_activity(session_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activity WHERE session_id=? ORDER BY timestamp",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Screenshots ----

def log_screenshot(session_id, filepath, active_window=None, ocr_text=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO screenshots (session_id, timestamp, filepath, active_window, ocr_text) VALUES (?, ?, ?, ?, ?)",
        (session_id, int(time.time()), filepath, active_window, ocr_text)
    )
    screenshot_id = cur.lastrowid
    conn.commit()
    conn.close()
    return screenshot_id


def flag_screenshot(screenshot_id, reason):
    conn = get_db()
    conn.execute(
        "UPDATE screenshots SET flagged=1, flag_reason=? WHERE id=?",
        (reason, screenshot_id)
    )
    conn.commit()
    conn.close()


def get_session_screenshots(session_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM screenshots WHERE session_id=? ORDER BY timestamp",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Window tracking ----

def log_window(session_id, window_title, app_name, duration_seconds=0, is_productive=True):
    conn = get_db()
    conn.execute(
        "INSERT INTO window_log (session_id, timestamp, window_title, app_name, duration_seconds, is_productive) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, int(time.time()), window_title, app_name, duration_seconds, 1 if is_productive else 0)
    )
    conn.commit()
    conn.close()


def get_session_windows(session_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM window_log WHERE session_id=? ORDER BY timestamp",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Keystroke stats ----

def log_keystrokes(session_id, keypress_count, active_typing, interval=60):
    conn = get_db()
    conn.execute(
        "INSERT INTO keystroke_stats (session_id, timestamp, interval_seconds, keypress_count, active_typing) VALUES (?, ?, ?, ?, ?)",
        (session_id, int(time.time()), interval, keypress_count, 1 if active_typing else 0)
    )
    conn.commit()
    conn.close()


def get_session_keystrokes(session_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM keystroke_stats WHERE session_id=? ORDER BY timestamp",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Daily stats ----

def update_daily_stats(date=None):
    if date is None:
        date = time.strftime("%Y-%m-%d")
    start = int(time.mktime(time.strptime(date, "%Y-%m-%d")))
    end = start + 86400

    conn = get_db()
    sessions = conn.execute(
        "SELECT * FROM sessions WHERE started_at >= ? AND started_at < ?",
        (start, end)
    ).fetchall()

    total_minutes = sum(s['duration_minutes'] or 0 for s in sessions)
    count = len(sessions)
    scores = [s['productivity_score'] for s in sessions if s['productivity_score'] is not None]
    avg_prod = sum(scores) / len(scores) if scores else 0
    focus_scores = [s['focus_score'] for s in sessions if s['focus_score'] is not None]
    avg_focus = sum(focus_scores) / len(focus_scores) if focus_scores else 0
    bypass = sum(s['bypass_attempts'] or 0 for s in sessions)
    distractions = sum(s['distraction_count'] or 0 for s in sessions)

    conn.execute("""
        INSERT OR REPLACE INTO daily_stats
        (date, total_minutes, sessions_count, avg_productivity, avg_focus, bypass_attempts, distraction_events)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (date, total_minutes, count, avg_prod, avg_focus, bypass, distractions))
    conn.commit()
    conn.close()


def get_daily_stats(days=30):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?",
        (days,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_streak():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT date FROM daily_stats WHERE sessions_count > 0 ORDER BY date DESC"
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    from datetime import datetime, timedelta
    streak = 0
    today = datetime.now().date()
    for row in rows:
        expected = today - timedelta(days=streak)
        if datetime.strptime(row['date'], "%Y-%m-%d").date() == expected:
            streak += 1
        else:
            break
    return streak


# ---- Video confrontation chain ----

VIDEOS_DIR = os.path.join(os.path.expanduser("~"), ".config", "lockin", "videos")


def ensure_video_dir():
    os.makedirs(VIDEOS_DIR, exist_ok=True)


def get_video_slots(start_from=1):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM video_slots WHERE slot_order >= ? ORDER BY slot_order",
        (start_from,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_video_slot(slot_order, title, file_path=None, message=None, source="default",
                   min_watch_seconds=10, tier=1):
    conn = get_db()
    conn.execute(
        """INSERT INTO video_slots
           (slot_order, title, file_path, message, source, min_watch_seconds, tier, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (slot_order, title, file_path, message, source, min_watch_seconds, tier, int(time.time()))
    )
    conn.commit()
    conn.close()


def update_video_slot(slot_id, **kwargs):
    allowed = {"title", "file_path", "message", "source", "min_watch_seconds", "tier", "slot_order"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn = get_db()
    conn.execute(f"UPDATE video_slots SET {set_clause} WHERE id=?",
                 (*fields.values(), slot_id))
    conn.commit()
    conn.close()


def delete_video_slot(slot_id):
    conn = get_db()
    conn.execute("DELETE FROM video_slots WHERE id=?", (slot_id,))
    conn.commit()
    conn.close()


def increment_play_count(slot_id):
    conn = get_db()
    conn.execute("UPDATE video_slots SET play_count = play_count + 1 WHERE id=?", (slot_id,))
    conn.commit()
    conn.close()


def log_chain_event(trigger_reason, slots_played, completed, start_slot):
    conn = get_db()
    conn.execute(
        """INSERT INTO chain_events (timestamp, trigger_reason, slots_played, completed, start_slot)
           VALUES (?, ?, ?, ?, ?)""",
        (int(time.time()), trigger_reason, slots_played, 1 if completed else 0, start_slot)
    )
    conn.commit()
    conn.close()


def get_last_chain_trigger():
    conn = get_db()
    row = conn.execute(
        "SELECT timestamp FROM chain_events ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_chain_history(limit=50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM chain_events ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def seed_default_video_slots():
    """Seed the default confrontation slots if none exist."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM video_slots").fetchone()[0]
    if count > 0:
        conn.close()
        return

    defaults = [
        (1, "Wake Up",
         "Stop.\n\nWhat are you doing right now?",
         8, 1),
        (2, "The Mirror",
         "Remember why you started.\n\nYou have goals. You have a future.\nThis moment of weakness doesn't define you\n— but giving in to it does.",
         12, 2),
        (3, "The Confrontation",
         "THIS IS YOUR FUTURE\nYOU'RE THROWING AWAY.\n\nYou know exactly what happens next.\nThe guilt. The shame. The wasted time.\nThe promise you'll stop — again.\n\nBe the person you told yourself\nyou'd become.",
         15, 3),
    ]
    for order, title, message, watch_secs, tier in defaults:
        conn.execute(
            """INSERT INTO video_slots
               (slot_order, title, message, source, min_watch_seconds, tier, created_at)
               VALUES (?, ?, ?, 'default', ?, ?, ?)""",
            (order, title, message, watch_secs, tier, int(time.time()))
        )
    conn.commit()
    conn.close()
