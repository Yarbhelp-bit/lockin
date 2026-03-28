"""
Lock In -- Unified Web GUI + Dashboard
Flask application serving the Palantir-inspired focus interface.
"""

import sys
import os
import time
import json
import subprocess
from datetime import datetime, timedelta

# Import the shared db module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'monitor'))
import db

# Import achievements system
from achievements import (
    init_achievements_db,
    get_player_stats,
    get_all_achievements,
    get_unlocked_achievements,
    get_new_achievements,
    check_achievements,
    add_xp,
    calculate_session_xp,
    get_rank,
    get_level_progress,
    update_player_stats,
    get_leaderboard_stats,
)

from flask import Flask, render_template, jsonify, send_file, abort, request

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True

SCREENSHOTS_DIR = "/var/lib/lockin/screenshots"
SESSION_FILE = "/etc/lockin/session"


# ---- Helpers ----

def read_session_file():
    """Read the lockin session file and return parsed fields."""
    data = {}
    try:
        if os.path.isfile(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        key, value = line.split('=', 1)
                        data[key.strip()] = value.strip()
    except (PermissionError, OSError):
        pass
    return data


def format_timestamp(ts):
    """Convert unix timestamp to human-readable string."""
    if ts is None:
        return "--"
    return datetime.fromtimestamp(ts).strftime("%b %d, %Y at %I:%M %p")


def format_time_short(ts):
    """Convert unix timestamp to short time string."""
    if ts is None:
        return "--"
    return datetime.fromtimestamp(ts).strftime("%I:%M %p")


def format_duration(minutes):
    """Format minutes into hours and minutes."""
    if minutes is None or minutes == 0:
        return "0m"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def event_type_label(event_type):
    """Return human-readable label for event types."""
    labels = {
        'window_focus': 'Window Switch',
        'bypass_attempt': 'Bypass Attempt',
        'app_switch': 'App Switch',
        'idle_detected': 'Idle Detected',
        'screenshot_flagged': 'Screenshot Flagged',
        'distraction_detected': 'Distraction Detected',
    }
    return labels.get(event_type, event_type)


def event_type_color(event_type):
    """Return color for event type."""
    colors = {
        'window_focus': '#71717a',
        'bypass_attempt': '#ef4444',
        'app_switch': '#3b82f6',
        'idle_detected': '#6b7280',
        'screenshot_flagged': '#eab308',
        'distraction_detected': '#f97316',
    }
    return colors.get(event_type, '#71717a')


# ---- Initialize ----

db.init_db()
init_achievements_db()


# ---- Page Routes ----

@app.route('/')
def index():
    """Serve the main single-page application."""
    return render_template('index.html')


# ---- Session Control API ----

@app.route('/api/start', methods=['POST'])
def api_start():
    """Start a new focus session via the system lockin command."""
    try:
        data = request.get_json(force=True) if request.is_json else request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request body'}), 400

        minutes = data.get('minutes')
        sites = data.get('sites', [])

        if not minutes or not isinstance(minutes, int) or minutes < 1:
            return jsonify({'success': False, 'message': 'Invalid duration'}), 400

        # Build the command
        sites_str = ' '.join(str(s) for s in sites) if sites else ''
        cmd = f'lockin start {minutes}'
        if sites_str:
            cmd += f' {sites_str}'

        # Launch via pkexec in background (don't wait)
        subprocess.Popen(
            ['pkexec', 'bash', '-c', cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return jsonify({'success': True, 'message': f'Starting {minutes}-minute session'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/emergency', methods=['POST'])
def api_emergency():
    """Emergency unlock via the system lockin command."""
    try:
        subprocess.Popen(
            ['pkexec', 'bash', '-c', 'lockin emergency'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({'success': True, 'message': 'Emergency unlock initiated'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/status')
def api_status():
    """Full status: active session, timer, player stats, level progress, new achievements."""
    try:
        active = db.get_active_session()
        session_file = read_session_file()

        # Timer info
        timer = None
        if active:
            elapsed = time.time() - active['started_at']
            total_seconds = active['duration_minutes'] * 60
            remaining = max(0, total_seconds - elapsed)
            progress = min(100, (elapsed / total_seconds) * 100) if total_seconds > 0 else 0

            timer = {
                'elapsed_seconds': int(elapsed),
                'remaining_seconds': int(remaining),
                'total_seconds': total_seconds,
                'progress': round(progress, 1),
                'duration_minutes': active['duration_minutes'],
                'started_at': active['started_at'],
                'allowed_sites': active.get('allowed_sites', ''),
                'bypass_attempts': active.get('bypass_attempts', 0) or 0,
                'distraction_count': active.get('distraction_count', 0) or 0,
            }

        # Session file data
        session_config = None
        if session_file:
            session_config = {
                'end_time': session_file.get('END_TIME'),
                'allowed_domains': session_file.get('ALLOWED_DOMAINS'),
                'allowed_ips': session_file.get('ALLOWED_IPS'),
                'started_at': session_file.get('STARTED_AT'),
                'duration_minutes': session_file.get('DURATION_MINUTES'),
            }

        # Player stats
        player = get_player_stats()
        level_progress = get_level_progress()

        # New (unnotified) achievements
        new_achievements = get_new_achievements()

        # Today stats
        today_sessions = db.get_today_sessions()
        today_focus = sum(s.get('duration_minutes', 0) or 0 for s in today_sessions)
        today_count = len(today_sessions)
        streak = db.get_streak()

        return jsonify({
            'active': bool(active),
            'session': dict(active) if active else None,
            'timer': timer,
            'session_config': session_config,
            'player': player,
            'level_progress': level_progress,
            'new_achievements': new_achievements,
            'today_focus': today_focus,
            'today_count': today_count,
            'streak': streak,
        })
    except Exception as e:
        return jsonify({'active': False, 'error': str(e)}), 500


# ---- Data API ----

@app.route('/api/sessions')
def api_sessions():
    """Paginated session list."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)
        per_page = min(per_page, 100)  # Cap at 100
        offset = (page - 1) * per_page

        sessions = db.get_sessions(limit=per_page + 1, offset=offset)
        has_next = len(sessions) > per_page
        sessions = sessions[:per_page]

        return jsonify({
            'sessions': sessions,
            'page': page,
            'per_page': per_page,
            'has_next': has_next,
        })
    except Exception as e:
        return jsonify({'sessions': [], 'error': str(e)}), 500


@app.route('/api/session/<int:session_id>')
def api_session_detail(session_id):
    """Session detail with activity, windows, keystrokes, screenshots."""
    try:
        session = db.get_session(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        activity = db.get_session_activity(session_id)
        screenshots = db.get_session_screenshots(session_id)
        windows = db.get_session_windows(session_id)
        keystrokes = db.get_session_keystrokes(session_id)

        # Build window usage breakdown
        window_usage = {}
        for w in windows:
            app_name = w.get('app_name', 'Unknown') or 'Unknown'
            if app_name not in window_usage:
                window_usage[app_name] = {
                    'app_name': app_name,
                    'total_seconds': 0,
                    'is_productive': w.get('is_productive', 1),
                }
            window_usage[app_name]['total_seconds'] += w.get('duration_seconds', 0) or 0
        window_breakdown = sorted(window_usage.values(), key=lambda x: x['total_seconds'], reverse=True)

        # Parse activity data JSON
        parsed_activity = []
        for act in activity:
            entry = dict(act)
            if entry.get('data'):
                try:
                    entry['parsed_data'] = json.loads(entry['data'])
                except (json.JSONDecodeError, TypeError):
                    entry['parsed_data'] = None
            else:
                entry['parsed_data'] = None
            parsed_activity.append(entry)

        return jsonify({
            'session': session,
            'activity': parsed_activity,
            'screenshots': screenshots,
            'windows': windows,
            'window_breakdown': window_breakdown,
            'keystrokes': keystrokes,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def api_stats():
    """Chart data for the last N days."""
    try:
        days = request.args.get('days', 14, type=int)
        days = min(days, 365)
        daily_stats = db.get_daily_stats(days)
        daily_stats = list(reversed(daily_stats))

        return jsonify({
            'labels': [s['date'] for s in daily_stats],
            'productivity': [round(s.get('avg_productivity', 0) or 0, 1) for s in daily_stats],
            'focus_minutes': [s.get('total_minutes', 0) or 0 for s in daily_stats],
            'focus_scores': [round(s.get('avg_focus', 0) or 0, 1) for s in daily_stats],
            'sessions_count': [s.get('sessions_count', 0) or 0 for s in daily_stats],
            'bypass_attempts': [s.get('bypass_attempts', 0) or 0 for s in daily_stats],
            'distraction_events': [s.get('distraction_events', 0) or 0 for s in daily_stats],
        })
    except Exception as e:
        return jsonify({'error': str(e), 'labels': [], 'productivity': [], 'focus_minutes': []}), 500


@app.route('/api/insights')
def api_insights():
    """Full insights data: trends, best day, best hour, distractions, weekly comparison."""
    try:
        daily_stats = db.get_daily_stats(30)
        recent_sessions = db.get_sessions(limit=100)

        # Weekly stats
        weekly_stats = daily_stats[:7] if daily_stats else []
        prev_weekly = daily_stats[7:14] if len(daily_stats) > 7 else []

        # Productivity trend
        if len(weekly_stats) >= 2:
            recent_prod = [s['avg_productivity'] for s in weekly_stats if s.get('avg_productivity')]
            prod_trend = "improving" if len(recent_prod) >= 2 and recent_prod[0] > recent_prod[-1] else "declining"
            prod_avg = round(sum(recent_prod) / len(recent_prod), 1) if recent_prod else 0
        else:
            prod_trend = "neutral"
            prod_avg = 0

        # Focus duration trend
        if len(weekly_stats) >= 2:
            recent_focus = [s['total_minutes'] for s in weekly_stats if s.get('total_minutes')]
            focus_trend = "improving" if len(recent_focus) >= 2 and recent_focus[0] > recent_focus[-1] else "declining"
            focus_avg = round(sum(recent_focus) / len(recent_focus), 1) if recent_focus else 0
        else:
            focus_trend = "neutral"
            focus_avg = 0

        # Find most productive day of week
        day_productivity = {}
        for s in daily_stats:
            try:
                dt = datetime.strptime(s['date'], '%Y-%m-%d')
                day_name = dt.strftime('%A')
                if day_name not in day_productivity:
                    day_productivity[day_name] = []
                if s.get('avg_productivity'):
                    day_productivity[day_name].append(s['avg_productivity'])
            except (ValueError, KeyError):
                pass

        best_day = None
        best_day_score = 0
        for day, scores in day_productivity.items():
            if scores:
                avg = sum(scores) / len(scores)
                if avg > best_day_score:
                    best_day_score = avg
                    best_day = day

        # Find best focus hour
        hour_counts = {}
        hour_scores = {}
        for s in recent_sessions:
            if s.get('started_at'):
                hour = datetime.fromtimestamp(s['started_at']).hour
                if hour not in hour_counts:
                    hour_counts[hour] = 0
                    hour_scores[hour] = []
                hour_counts[hour] += 1
                if s.get('productivity_score') is not None:
                    hour_scores[hour].append(s['productivity_score'])

        best_hour = None
        best_hour_score = 0
        for hour, scores in hour_scores.items():
            if scores:
                avg = sum(scores) / len(scores)
                if avg > best_hour_score:
                    best_hour_score = avg
                    best_hour = hour

        best_hour_str = None
        if best_hour is not None:
            best_hour_str = datetime(2000, 1, 1, best_hour).strftime('%I %p').lstrip('0')

        # Distraction patterns
        total_bypass = sum(s.get('bypass_attempts', 0) or 0 for s in recent_sessions)
        avg_bypass_per_session = round(total_bypass / len(recent_sessions), 1) if recent_sessions else 0

        # Average time before first distraction
        first_distraction_times = []
        for s in recent_sessions:
            if s.get('started_at') and s.get('distraction_count', 0):
                activities = db.get_session_activity(s['id'])
                for act in activities:
                    if act.get('event_type') in ('distraction_detected', 'bypass_attempt'):
                        diff = (act['timestamp'] - s['started_at']) / 60
                        first_distraction_times.append(diff)
                        break

        avg_first_distraction = round(
            sum(first_distraction_times) / len(first_distraction_times), 1
        ) if first_distraction_times else None

        # Top distractions from daily_stats
        all_distractions = {}
        for s in daily_stats:
            if s.get('top_distractions'):
                try:
                    dists = json.loads(s['top_distractions'])
                    if isinstance(dists, dict):
                        for k, v in dists.items():
                            all_distractions[k] = all_distractions.get(k, 0) + v
                    elif isinstance(dists, list):
                        for d in dists:
                            all_distractions[d] = all_distractions.get(d, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

        top_distractions = sorted(all_distractions.items(), key=lambda x: x[1], reverse=True)[:5]

        # AI insights from daily stats
        ai_insights = []
        for s in weekly_stats:
            if s.get('ai_insights'):
                ai_insights.append({
                    'date': s['date'],
                    'insight': s['ai_insights'],
                })

        # Weekly comparison
        this_week_minutes = sum(s.get('total_minutes', 0) or 0 for s in weekly_stats)
        prev_week_minutes = sum(s.get('total_minutes', 0) or 0 for s in prev_weekly)
        week_diff = this_week_minutes - prev_week_minutes if prev_week_minutes else 0

        # Hour distribution for heatmap
        hour_distribution = []
        for h in range(24):
            hour_distribution.append({
                'hour': h,
                'label': datetime(2000, 1, 1, h).strftime('%I %p').lstrip('0'),
                'sessions': hour_counts.get(h, 0),
                'avg_score': round(
                    sum(hour_scores.get(h, [])) / len(hour_scores[h]), 1
                ) if hour_scores.get(h) else 0,
            })

        has_data = len(daily_stats) > 0 or len(recent_sessions) > 0

        return jsonify({
            'has_data': has_data,
            'prod_trend': prod_trend,
            'prod_avg': prod_avg,
            'focus_trend': focus_trend,
            'focus_avg': focus_avg,
            'best_day': best_day,
            'best_day_score': round(best_day_score, 1),
            'best_hour': best_hour_str,
            'best_hour_score': round(best_hour_score, 1),
            'total_bypass': total_bypass,
            'avg_bypass_per_session': avg_bypass_per_session,
            'avg_first_distraction': avg_first_distraction,
            'top_distractions': [{'name': d[0], 'count': d[1]} for d in top_distractions],
            'ai_insights': ai_insights,
            'this_week_minutes': this_week_minutes,
            'prev_week_minutes': prev_week_minutes,
            'week_diff': week_diff,
            'hour_distribution': hour_distribution,
        })
    except Exception as e:
        return jsonify({'has_data': False, 'error': str(e)}), 500


@app.route('/api/achievements')
def api_achievements():
    """All achievements with unlock status + player profile."""
    try:
        leaderboard = get_leaderboard_stats()
        return jsonify(leaderboard)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/live')
def api_live():
    """Live session data for polling during active session."""
    try:
        active = db.get_active_session()
        if not active:
            return jsonify({'active': False})

        activity = db.get_session_activity(active['id'])
        recent_activity = activity[-10:]

        elapsed = time.time() - active['started_at']
        total_seconds = active['duration_minutes'] * 60
        remaining = max(0, total_seconds - elapsed)
        progress = min(100, (elapsed / total_seconds) * 100) if total_seconds > 0 else 0

        # Recent screenshots
        screenshots = db.get_session_screenshots(active['id'])
        latest_screenshots = screenshots[-3:] if screenshots else []

        # Keystroke activity
        keystrokes = db.get_session_keystrokes(active['id'])
        recent_keystrokes = keystrokes[-10:] if keystrokes else []

        # Window log
        windows = db.get_session_windows(active['id'])
        recent_windows = windows[-5:] if windows else []

        return jsonify({
            'active': True,
            'session_id': active['id'],
            'started_at': active['started_at'],
            'duration_minutes': active['duration_minutes'],
            'elapsed_seconds': int(elapsed),
            'remaining_seconds': int(remaining),
            'progress': round(progress, 1),
            'allowed_sites': active.get('allowed_sites', ''),
            'bypass_attempts': active.get('bypass_attempts', 0) or 0,
            'distraction_count': active.get('distraction_count', 0) or 0,
            'recent_activity': [{
                'timestamp': a['timestamp'],
                'event_type': a['event_type'],
                'category': a.get('category'),
                'time_str': format_time_short(a['timestamp']),
                'label': event_type_label(a['event_type']),
                'color': event_type_color(a['event_type']),
            } for a in recent_activity],
            'latest_screenshots': [{
                'id': s['id'],
                'timestamp': s['timestamp'],
                'filepath': s['filepath'],
                'active_window': s.get('active_window'),
                'flagged': s.get('flagged', 0),
            } for s in latest_screenshots],
            'recent_keystrokes': [{
                'timestamp': k['timestamp'],
                'keypress_count': k['keypress_count'],
                'active_typing': k['active_typing'],
            } for k in recent_keystrokes],
            'recent_windows': [{
                'timestamp': w['timestamp'],
                'window_title': w.get('window_title'),
                'app_name': w.get('app_name'),
                'is_productive': w.get('is_productive', 1),
            } for w in recent_windows],
        })
    except Exception as e:
        return jsonify({'active': False, 'error': str(e)}), 500


# ---- Static Files ----

@app.route('/screenshot/<path:filepath>')
def serve_screenshot(filepath):
    """Serve screenshot files with path traversal protection."""
    full_path = os.path.join(SCREENSHOTS_DIR, filepath)
    real_path = os.path.realpath(full_path)
    real_base = os.path.realpath(SCREENSHOTS_DIR)
    if not real_path.startswith(real_base + os.sep) and real_path != real_base:
        abort(403)
    if not os.path.isfile(real_path):
        abort(404)
    return send_file(real_path)


# ---- Error Handlers ----

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('index.html'), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500


# ---- Main ----

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9999, debug=True)
