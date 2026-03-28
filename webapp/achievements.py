"""
Lock In -- Achievement and XP/Leveling System
Gamification layer for focus sessions.
"""

import sys
import os
import time
from datetime import datetime, timedelta

# Import the shared db module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'monitor'))
import db


# ---- Achievement Definitions ----

ACHIEVEMENTS = [
    {
        'id': 'first_lock',
        'name': 'First Lock',
        'description': 'Complete first session',
        'icon': 'I',
        'xp_reward': 100,
        'rarity': 'common',
    },
    {
        'id': 'five_sessions',
        'name': 'Operator',
        'description': 'Complete 5 sessions',
        'icon': 'V',
        'xp_reward': 250,
        'rarity': 'common',
    },
    {
        'id': 'twenty_sessions',
        'name': 'Veteran',
        'description': 'Complete 20 sessions',
        'icon': 'XX',
        'xp_reward': 500,
        'rarity': 'rare',
    },
    {
        'id': 'centurion',
        'name': 'Centurion',
        'description': 'Complete 100 sessions',
        'icon': 'C',
        'xp_reward': 2000,
        'rarity': 'legendary',
    },
    {
        'id': 'marathon',
        'name': 'Marathon',
        'description': 'Complete a 2-hour session',
        'icon': 'M',
        'xp_reward': 500,
        'rarity': 'rare',
    },
    {
        'id': 'sprint',
        'name': 'Sprint',
        'description': 'Complete a 15-min session',
        'icon': 'S',
        'xp_reward': 50,
        'rarity': 'common',
    },
    {
        'id': 'perfect_focus',
        'name': 'Perfect Focus',
        'description': '100 focus score',
        'icon': '*',
        'xp_reward': 300,
        'rarity': 'epic',
    },
    {
        'id': 'high_score',
        'name': 'High Score',
        'description': 'Productivity over 90',
        'icon': '^',
        'xp_reward': 300,
        'rarity': 'rare',
    },
    {
        'id': 'streak_3',
        'name': 'Hat Trick',
        'description': '3-day streak',
        'icon': '3',
        'xp_reward': 200,
        'rarity': 'common',
    },
    {
        'id': 'streak_7',
        'name': 'On Fire',
        'description': '7-day streak',
        'icon': '7',
        'xp_reward': 500,
        'rarity': 'rare',
    },
    {
        'id': 'streak_14',
        'name': 'Fortnight',
        'description': '14-day streak',
        'icon': '14',
        'xp_reward': 1000,
        'rarity': 'epic',
    },
    {
        'id': 'streak_30',
        'name': 'Unstoppable',
        'description': '30-day streak',
        'icon': '30',
        'xp_reward': 2000,
        'rarity': 'legendary',
    },
    {
        'id': 'fortress',
        'name': 'Fortress',
        'description': '10 sessions, zero bypass attempts',
        'icon': '#',
        'xp_reward': 500,
        'rarity': 'rare',
    },
    {
        'id': 'ten_hours',
        'name': 'Dedicated',
        'description': '10 total hours of focus',
        'icon': 'X',
        'xp_reward': 500,
        'rarity': 'rare',
    },
    {
        'id': 'hundred_hours',
        'name': 'Obsessed',
        'description': '100 total hours of focus',
        'icon': 'D',
        'xp_reward': 3000,
        'rarity': 'legendary',
    },
    {
        'id': 'early_bird',
        'name': 'Early Bird',
        'description': 'Session before 7 AM',
        'icon': 'E',
        'xp_reward': 150,
        'rarity': 'common',
    },
    {
        'id': 'night_owl',
        'name': 'Night Owl',
        'description': 'Session after 10 PM',
        'icon': 'N',
        'xp_reward': 150,
        'rarity': 'common',
    },
    {
        'id': 'no_distractions',
        'name': 'Laser Focus',
        'description': 'Session with 0 distractions',
        'icon': '!',
        'xp_reward': 200,
        'rarity': 'rare',
    },
    {
        'id': 'deep_work',
        'name': 'Deep Work',
        'description': '5 sessions over 45 min each',
        'icon': 'D',
        'xp_reward': 750,
        'rarity': 'epic',
    },
    {
        'id': 'comeback',
        'name': 'Comeback',
        'description': 'Session after 7+ days inactive',
        'icon': 'R',
        'xp_reward': 200,
        'rarity': 'rare',
    },
]

ACHIEVEMENTS_BY_ID = {a['id']: a for a in ACHIEVEMENTS}

# ---- Rank System ----

RANKS = [
    (1, 'RECRUIT'),
    (5, 'OPERATOR'),
    (10, 'AGENT'),
    (15, 'SPECIALIST'),
    (20, 'COMMANDER'),
    (25, 'DIRECTOR'),
    (30, 'ARCHITECT'),
]


def get_rank(level):
    """Return rank string for a given level."""
    rank = 'RECRUIT'
    for threshold, name in RANKS:
        if level >= threshold:
            rank = name
    return rank


def xp_for_level(level):
    """Return cumulative XP needed to reach a given level.

    Level 1 = 0 XP.  Level 2 = 400 XP total.  Level 3 = 1000 XP total.
    Each level N requires N*200 additional XP beyond the previous level.
    Cumulative = sum(k*200 for k in 2..level) = 200 * (sum(2..level))
               = 200 * ((level*(level+1)/2) - 1)  for level >= 2
    """
    if level <= 1:
        return 0
    return 200 * ((level * (level + 1)) // 2 - 1)


# ---- Database Init ----

def init_achievements_db():
    """Create achievements and player_stats tables."""
    conn = db.get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS achievements (
            id TEXT PRIMARY KEY,
            unlocked_at INTEGER,
            notified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            total_sessions INTEGER DEFAULT 0,
            total_focus_minutes INTEGER DEFAULT 0,
            longest_session INTEGER DEFAULT 0,
            best_productivity REAL DEFAULT 0,
            best_focus REAL DEFAULT 0,
            zero_bypass_streak INTEGER DEFAULT 0,
            sessions_today INTEGER DEFAULT 0,
            last_session_date TEXT
        );
    """)
    conn.commit()
    conn.close()


# ---- Player Stats ----

def get_player_stats():
    """Get or create the single player stats row."""
    conn = db.get_db()
    row = conn.execute("SELECT * FROM player_stats WHERE id = 1").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO player_stats (id) VALUES (1)"
        )
        conn.commit()
        row = conn.execute("SELECT * FROM player_stats WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def update_player_stats(session):
    """Update cumulative stats after a session ends."""
    stats = get_player_stats()
    conn = db.get_db()

    duration = session.get('duration_minutes', 0) or 0
    productivity = session.get('productivity_score') or 0
    focus = session.get('focus_score') or 0
    bypass = session.get('bypass_attempts', 0) or 0

    new_total_sessions = stats['total_sessions'] + 1
    new_total_minutes = stats['total_focus_minutes'] + duration
    new_longest = max(stats['longest_session'], duration)
    new_best_prod = max(stats['best_productivity'], productivity)
    new_best_focus = max(stats['best_focus'], focus)

    # Zero bypass streak
    if bypass == 0:
        new_bypass_streak = stats['zero_bypass_streak'] + 1
    else:
        new_bypass_streak = 0

    # Sessions today tracking
    today = time.strftime("%Y-%m-%d")
    if stats['last_session_date'] == today:
        new_sessions_today = stats['sessions_today'] + 1
    else:
        new_sessions_today = 1

    conn.execute("""
        UPDATE player_stats SET
            total_sessions = ?,
            total_focus_minutes = ?,
            longest_session = ?,
            best_productivity = ?,
            best_focus = ?,
            zero_bypass_streak = ?,
            sessions_today = ?,
            last_session_date = ?
        WHERE id = 1
    """, (
        new_total_sessions,
        new_total_minutes,
        new_longest,
        new_best_prod,
        new_best_focus,
        new_bypass_streak,
        new_sessions_today,
        today,
    ))
    conn.commit()
    conn.close()


# ---- XP and Leveling ----

def add_xp(amount):
    """Add XP, handle level ups. Returns dict with new_level if leveled up, else None."""
    stats = get_player_stats()
    new_xp = stats['total_xp'] + amount
    old_level = stats['level']

    # Calculate new level
    new_level = old_level
    while xp_for_level(new_level + 1) <= new_xp:
        new_level += 1

    conn = db.get_db()
    conn.execute(
        "UPDATE player_stats SET total_xp = ?, level = ? WHERE id = 1",
        (new_xp, new_level)
    )
    conn.commit()
    conn.close()

    if new_level > old_level:
        return {'leveled_up': True, 'new_level': new_level, 'rank': get_rank(new_level)}
    return {'leveled_up': False, 'new_level': new_level, 'rank': get_rank(new_level)}


def calculate_session_xp(session):
    """Calculate XP earned from a session.

    Base = duration_minutes * 10
    +50% if productivity > 80
    +25% if zero bypass attempts
    +25% if focus > 80
    """
    duration = session.get('duration_minutes', 0) or 0
    productivity = session.get('productivity_score') or 0
    focus = session.get('focus_score') or 0
    bypass = session.get('bypass_attempts', 0) or 0

    base_xp = duration * 10
    multiplier = 1.0

    if productivity > 80:
        multiplier += 0.5
    if bypass == 0:
        multiplier += 0.25
    if focus > 80:
        multiplier += 0.25

    return int(base_xp * multiplier)


def get_level_progress():
    """Return level progress info."""
    stats = get_player_stats()
    level = stats['level']
    total_xp = stats['total_xp']
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    xp_into_level = total_xp - current_level_xp
    xp_needed = next_level_xp - current_level_xp

    progress_pct = round((xp_into_level / xp_needed) * 100, 1) if xp_needed > 0 else 100.0

    return {
        'level': level,
        'xp': total_xp,
        'xp_into_level': xp_into_level,
        'xp_for_next': xp_needed,
        'progress_pct': progress_pct,
        'rank': get_rank(level),
    }


# ---- Achievements ----

def _is_unlocked(achievement_id):
    """Check if an achievement is already unlocked."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT id FROM achievements WHERE id = ?", (achievement_id,)
    ).fetchone()
    conn.close()
    return row is not None


def _unlock(achievement_id):
    """Unlock an achievement and award XP."""
    if _is_unlocked(achievement_id):
        return None

    definition = ACHIEVEMENTS_BY_ID.get(achievement_id)
    if not definition:
        return None

    conn = db.get_db()
    conn.execute(
        "INSERT OR IGNORE INTO achievements (id, unlocked_at, notified) VALUES (?, ?, 0)",
        (achievement_id, int(time.time()))
    )
    conn.commit()
    conn.close()

    # Award XP
    level_result = add_xp(definition['xp_reward'])
    return {
        'achievement': definition,
        'level_result': level_result,
    }


def get_all_achievements():
    """Return all achievement definitions with unlock status."""
    conn = db.get_db()
    rows = conn.execute("SELECT id, unlocked_at FROM achievements").fetchall()
    conn.close()

    unlocked_map = {r['id']: r['unlocked_at'] for r in rows}

    result = []
    for a in ACHIEVEMENTS:
        entry = dict(a)
        entry['unlocked'] = a['id'] in unlocked_map
        entry['unlocked_at'] = unlocked_map.get(a['id'])
        result.append(entry)
    return result


def get_unlocked_achievements():
    """Return only unlocked achievements."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT id, unlocked_at FROM achievements ORDER BY unlocked_at DESC"
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        definition = ACHIEVEMENTS_BY_ID.get(r['id'])
        if definition:
            entry = dict(definition)
            entry['unlocked'] = True
            entry['unlocked_at'] = r['unlocked_at']
            result.append(entry)
    return result


def get_new_achievements():
    """Return unlocked but not yet notified achievements, then mark them as notified."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT id, unlocked_at FROM achievements WHERE notified = 0"
    ).fetchall()

    result = []
    for r in rows:
        definition = ACHIEVEMENTS_BY_ID.get(r['id'])
        if definition:
            entry = dict(definition)
            entry['unlocked'] = True
            entry['unlocked_at'] = r['unlocked_at']
            result.append(entry)

    if rows:
        conn.execute("UPDATE achievements SET notified = 1 WHERE notified = 0")
        conn.commit()

    conn.close()
    return result


def check_achievements(session_data):
    """Check and unlock any new achievements after a session.

    session_data should be a dict with session fields.
    Returns a list of newly unlocked achievement results.
    """
    newly_unlocked = []
    stats = get_player_stats()

    total_sessions = stats['total_sessions']
    total_minutes = stats['total_focus_minutes']
    longest = stats['longest_session']
    best_prod = stats['best_productivity']
    best_focus = stats['best_focus']
    bypass_streak = stats['zero_bypass_streak']

    duration = session_data.get('duration_minutes', 0) or 0
    productivity = session_data.get('productivity_score') or 0
    focus = session_data.get('focus_score') or 0
    bypass = session_data.get('bypass_attempts', 0) or 0
    distractions = session_data.get('distraction_count', 0) or 0
    started_at = session_data.get('started_at')

    # Session count achievements
    if total_sessions >= 1:
        r = _unlock('first_lock')
        if r:
            newly_unlocked.append(r)
    if total_sessions >= 5:
        r = _unlock('five_sessions')
        if r:
            newly_unlocked.append(r)
    if total_sessions >= 20:
        r = _unlock('twenty_sessions')
        if r:
            newly_unlocked.append(r)
    if total_sessions >= 100:
        r = _unlock('centurion')
        if r:
            newly_unlocked.append(r)

    # Duration achievements
    if duration >= 120:
        r = _unlock('marathon')
        if r:
            newly_unlocked.append(r)
    if duration <= 15 and duration > 0:
        r = _unlock('sprint')
        if r:
            newly_unlocked.append(r)

    # Score achievements
    if focus >= 100:
        r = _unlock('perfect_focus')
        if r:
            newly_unlocked.append(r)
    if productivity > 90:
        r = _unlock('high_score')
        if r:
            newly_unlocked.append(r)

    # Streak achievements
    streak = db.get_streak()
    if streak >= 3:
        r = _unlock('streak_3')
        if r:
            newly_unlocked.append(r)
    if streak >= 7:
        r = _unlock('streak_7')
        if r:
            newly_unlocked.append(r)
    if streak >= 14:
        r = _unlock('streak_14')
        if r:
            newly_unlocked.append(r)
    if streak >= 30:
        r = _unlock('streak_30')
        if r:
            newly_unlocked.append(r)

    # Fortress: 10+ sessions with zero bypass attempts in a row
    if bypass_streak >= 10:
        r = _unlock('fortress')
        if r:
            newly_unlocked.append(r)

    # Total hours
    total_hours = total_minutes / 60
    if total_hours >= 10:
        r = _unlock('ten_hours')
        if r:
            newly_unlocked.append(r)
    if total_hours >= 100:
        r = _unlock('hundred_hours')
        if r:
            newly_unlocked.append(r)

    # Time of day achievements
    if started_at:
        hour = datetime.fromtimestamp(started_at).hour
        if hour < 7:
            r = _unlock('early_bird')
            if r:
                newly_unlocked.append(r)
        if hour >= 22:
            r = _unlock('night_owl')
            if r:
                newly_unlocked.append(r)

    # No distractions
    if distractions == 0 and duration > 0:
        r = _unlock('no_distractions')
        if r:
            newly_unlocked.append(r)

    # Deep work: 5 sessions over 45 min each
    conn = db.get_db()
    long_sessions = conn.execute(
        "SELECT COUNT(*) as cnt FROM sessions WHERE duration_minutes >= 45 AND ended_at IS NOT NULL"
    ).fetchone()
    conn.close()
    if long_sessions and long_sessions['cnt'] >= 5:
        r = _unlock('deep_work')
        if r:
            newly_unlocked.append(r)

    # Comeback: session after 7+ days inactive
    conn = db.get_db()
    prev_sessions = conn.execute(
        "SELECT started_at FROM sessions WHERE ended_at IS NOT NULL ORDER BY started_at DESC LIMIT 2"
    ).fetchall()
    conn.close()
    if len(prev_sessions) >= 2:
        latest = prev_sessions[0]['started_at']
        previous = prev_sessions[1]['started_at']
        gap_days = (latest - previous) / 86400
        if gap_days >= 7:
            r = _unlock('comeback')
            if r:
                newly_unlocked.append(r)

    return newly_unlocked


# ---- Leaderboard / Display Stats ----

def get_leaderboard_stats():
    """Return formatted stats for display."""
    stats = get_player_stats()
    progress = get_level_progress()
    unlocked = get_unlocked_achievements()
    all_achievements = get_all_achievements()

    total_hours = stats['total_focus_minutes'] / 60
    unlocked_count = len(unlocked)
    total_count = len(ACHIEVEMENTS)

    # Rarity breakdown
    rarity_counts = {'common': 0, 'rare': 0, 'epic': 0, 'legendary': 0}
    for a in unlocked:
        rarity_counts[a['rarity']] = rarity_counts.get(a['rarity'], 0) + 1

    return {
        'player': stats,
        'level_progress': progress,
        'achievements': all_achievements,
        'unlocked_achievements': unlocked,
        'unlocked_count': unlocked_count,
        'total_achievements': total_count,
        'completion_pct': round((unlocked_count / total_count) * 100, 1) if total_count > 0 else 0,
        'total_hours': round(total_hours, 1),
        'rarity_counts': rarity_counts,
    }
