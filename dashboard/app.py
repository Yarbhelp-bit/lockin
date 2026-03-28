"""
Lock In — Analytics Dashboard
Flask web app for viewing behavioral monitoring data.
"""

import sys
import os
import time
import json
from datetime import datetime, timedelta

# Import the shared db module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'monitor'))
import db

from flask import Flask, render_template, jsonify, send_file, abort, request

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

SCREENSHOTS_DIR = "/var/lib/lockin/screenshots"


# ---- Helpers ----

def db_available():
    """Check if the database file exists and has tables."""
    try:
        db.get_db().close()
        return True
    except Exception:
        return False


def format_timestamp(ts):
    """Convert unix timestamp to human-readable string."""
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%b %d, %Y at %I:%M %p")


def format_time_short(ts):
    """Convert unix timestamp to short time string."""
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%I:%M %p")


def format_date(ts):
    """Convert unix timestamp to date string."""
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%b %d, %Y")


def format_duration(minutes):
    """Format minutes into hours and minutes."""
    if minutes is None or minutes == 0:
        return "0m"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def time_ago(ts):
    """Convert unix timestamp to relative time string."""
    if ts is None:
        return "—"
    diff = time.time() - ts
    if diff < 60:
        return "just now"
    elif diff < 3600:
        m = int(diff // 60)
        return f"{m}m ago"
    elif diff < 86400:
        h = int(diff // 3600)
        return f"{h}h ago"
    else:
        d = int(diff // 86400)
        return f"{d}d ago"


def score_color(score):
    """Return CSS color class based on productivity/focus score."""
    if score is None:
        return "#71717a"
    if score >= 80:
        return "#22c55e"
    elif score >= 60:
        return "#f97316"
    elif score >= 40:
        return "#eab308"
    else:
        return "#ef4444"


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


def event_type_icon(event_type):
    """Return icon/symbol for event type."""
    icons = {
        'window_focus': '&#9635;',
        'bypass_attempt': '&#9888;',
        'app_switch': '&#8644;',
        'idle_detected': '&#9208;',
        'screenshot_flagged': '&#128247;',
        'distraction_detected': '&#9888;',
    }
    return icons.get(event_type, '&#8226;')


# Register template filters
app.jinja_env.filters['format_timestamp'] = format_timestamp
app.jinja_env.filters['format_time_short'] = format_time_short
app.jinja_env.filters['format_date'] = format_date
app.jinja_env.filters['format_duration'] = format_duration
app.jinja_env.filters['time_ago'] = time_ago
app.jinja_env.filters['score_color'] = score_color
app.jinja_env.filters['event_type_label'] = event_type_label
app.jinja_env.filters['event_type_color'] = event_type_color
app.jinja_env.filters['event_type_icon'] = event_type_icon
app.jinja_env.globals['now'] = time.time


# ---- Routes ----

@app.route('/')
def overview():
    """Main dashboard overview."""
    try:
        today_sessions = db.get_today_sessions()
        active = db.get_active_session()
        streak = db.get_streak()
        daily_stats = db.get_daily_stats(14)
        recent_sessions = db.get_sessions(limit=8)

        # Today's totals
        today_focus = sum(s.get('duration_minutes', 0) or 0 for s in today_sessions)
        today_count = len(today_sessions)
        today_scores = [s['productivity_score'] for s in today_sessions if s.get('productivity_score') is not None]
        today_avg_prod = round(sum(today_scores) / len(today_scores), 1) if today_scores else None
        today_bypass = sum(s.get('bypass_attempts', 0) or 0 for s in today_sessions)
        today_distractions = sum(s.get('distraction_count', 0) or 0 for s in today_sessions)

        # Yesterday's bypass for trend
        yesterday_bypass = 0
        if daily_stats and len(daily_stats) > 1:
            yesterday_bypass = daily_stats[1].get('bypass_attempts', 0) or 0

        # Active session details
        active_activity = []
        if active:
            active_activity = db.get_session_activity(active['id'])
            # Get last 10 activities for live feed
            active_activity = active_activity[-10:]

        has_data = len(recent_sessions) > 0

        return render_template('overview.html',
                               active=active,
                               active_activity=active_activity,
                               today_focus=today_focus,
                               today_count=today_count,
                               today_avg_prod=today_avg_prod,
                               streak=streak,
                               today_bypass=today_bypass,
                               yesterday_bypass=yesterday_bypass,
                               today_distractions=today_distractions,
                               daily_stats=list(reversed(daily_stats)),
                               recent_sessions=recent_sessions,
                               has_data=has_data)
    except Exception as e:
        return render_template('overview.html',
                               active=None,
                               active_activity=[],
                               today_focus=0,
                               today_count=0,
                               today_avg_prod=None,
                               streak=0,
                               today_bypass=0,
                               yesterday_bypass=0,
                               today_distractions=0,
                               daily_stats=[],
                               recent_sessions=[],
                               has_data=False,
                               error=str(e))


@app.route('/sessions')
def sessions_list():
    """Session history list with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 12
    offset = (page - 1) * per_page

    try:
        sessions = db.get_sessions(limit=per_page + 1, offset=offset)
        has_next = len(sessions) > per_page
        sessions = sessions[:per_page]

        return render_template('sessions.html',
                               sessions=sessions,
                               page=page,
                               has_next=has_next,
                               has_data=len(sessions) > 0)
    except Exception:
        return render_template('sessions.html',
                               sessions=[],
                               page=1,
                               has_next=False,
                               has_data=False)


@app.route('/session/<int:session_id>')
def session_detail(session_id):
    """Detailed session view."""
    try:
        session = db.get_session(session_id)
        if not session:
            abort(404)

        activity = db.get_session_activity(session_id)
        screenshots = db.get_session_screenshots(session_id)
        windows = db.get_session_windows(session_id)
        keystrokes = db.get_session_keystrokes(session_id)

        # Build window usage breakdown (aggregate by app_name)
        window_usage = {}
        for w in windows:
            app = w.get('app_name', 'Unknown') or 'Unknown'
            if app not in window_usage:
                window_usage[app] = {
                    'app_name': app,
                    'total_seconds': 0,
                    'is_productive': w.get('is_productive', 1),
                }
            window_usage[app]['total_seconds'] += w.get('duration_seconds', 0) or 0

        window_breakdown = sorted(window_usage.values(), key=lambda x: x['total_seconds'], reverse=True)

        # Parse activity data JSON
        for act in activity:
            if act.get('data'):
                try:
                    act['parsed_data'] = json.loads(act['data'])
                except (json.JSONDecodeError, TypeError):
                    act['parsed_data'] = None
            else:
                act['parsed_data'] = None

        return render_template('session.html',
                               session=session,
                               activity=activity,
                               screenshots=screenshots,
                               windows=windows,
                               window_breakdown=window_breakdown,
                               keystrokes=keystrokes)
    except Exception as e:
        if '404' in str(e):
            abort(404)
        return render_template('session.html',
                               session=None,
                               activity=[],
                               screenshots=[],
                               windows=[],
                               window_breakdown=[],
                               keystrokes=[],
                               error=str(e))


@app.route('/insights')
def insights():
    """AI insights page with trends and recommendations."""
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

        # Find best focus hour (from session start times)
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

        # Average time before first distraction (in minutes)
        first_distraction_times = []
        for s in recent_sessions:
            if s.get('started_at') and s.get('distraction_count', 0):
                activities = db.get_session_activity(s['id'])
                for act in activities:
                    if act.get('event_type') in ('distraction_detected', 'bypass_attempt'):
                        diff = (act['timestamp'] - s['started_at']) / 60
                        first_distraction_times.append(diff)
                        break

        avg_first_distraction = round(sum(first_distraction_times) / len(first_distraction_times), 1) if first_distraction_times else None

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
                    'insight': s['ai_insights']
                })

        # Weekly comparison
        this_week_minutes = sum(s.get('total_minutes', 0) or 0 for s in weekly_stats)
        prev_week_minutes = sum(s.get('total_minutes', 0) or 0 for s in prev_weekly)
        week_diff = this_week_minutes - prev_week_minutes if prev_week_minutes else 0

        has_data = len(daily_stats) > 0 or len(recent_sessions) > 0

        return render_template('insights.html',
                               daily_stats=list(reversed(daily_stats)),
                               weekly_stats=weekly_stats,
                               prod_trend=prod_trend,
                               prod_avg=prod_avg,
                               focus_trend=focus_trend,
                               focus_avg=focus_avg,
                               best_day=best_day,
                               best_day_score=round(best_day_score, 1),
                               best_hour=best_hour_str,
                               best_hour_score=round(best_hour_score, 1),
                               total_bypass=total_bypass,
                               avg_bypass_per_session=avg_bypass_per_session,
                               avg_first_distraction=avg_first_distraction,
                               top_distractions=top_distractions,
                               ai_insights=ai_insights,
                               this_week_minutes=this_week_minutes,
                               prev_week_minutes=prev_week_minutes,
                               week_diff=week_diff,
                               has_data=has_data)
    except Exception:
        return render_template('insights.html',
                               daily_stats=[],
                               weekly_stats=[],
                               prod_trend="neutral",
                               prod_avg=0,
                               focus_trend="neutral",
                               focus_avg=0,
                               best_day=None,
                               best_day_score=0,
                               best_hour=None,
                               best_hour_score=0,
                               total_bypass=0,
                               avg_bypass_per_session=0,
                               avg_first_distraction=None,
                               top_distractions=[],
                               ai_insights=[],
                               this_week_minutes=0,
                               prev_week_minutes=0,
                               week_diff=0,
                               has_data=False)


@app.route('/api/live')
def api_live():
    """JSON endpoint for live session data (auto-refresh)."""
    try:
        active = db.get_active_session()
        if not active:
            return jsonify({'active': False})

        activity = db.get_session_activity(active['id'])
        recent_activity = activity[-10:]

        elapsed = time.time() - active['started_at']
        remaining = max(0, (active['duration_minutes'] * 60) - elapsed)
        progress = min(100, (elapsed / (active['duration_minutes'] * 60)) * 100) if active['duration_minutes'] else 0

        return jsonify({
            'active': True,
            'session_id': active['id'],
            'started_at': active['started_at'],
            'duration_minutes': active['duration_minutes'],
            'elapsed_seconds': int(elapsed),
            'remaining_seconds': int(remaining),
            'progress': round(progress, 1),
            'allowed_sites': active.get('allowed_sites', ''),
            'bypass_attempts': active.get('bypass_attempts', 0),
            'distraction_count': active.get('distraction_count', 0),
            'recent_activity': [{
                'timestamp': a['timestamp'],
                'event_type': a['event_type'],
                'category': a.get('category'),
                'time_str': format_time_short(a['timestamp']),
                'label': event_type_label(a['event_type']),
                'color': event_type_color(a['event_type']),
            } for a in recent_activity],
        })
    except Exception as e:
        return jsonify({'active': False, 'error': str(e)})


@app.route('/api/stats')
def api_stats():
    """JSON endpoint for chart data."""
    days = request.args.get('days', 14, type=int)
    try:
        daily_stats = db.get_daily_stats(days)
        daily_stats = list(reversed(daily_stats))

        return jsonify({
            'labels': [s['date'] for s in daily_stats],
            'productivity': [round(s.get('avg_productivity', 0) or 0, 1) for s in daily_stats],
            'focus_minutes': [s.get('total_minutes', 0) or 0 for s in daily_stats],
            'sessions_count': [s.get('sessions_count', 0) or 0 for s in daily_stats],
            'bypass_attempts': [s.get('bypass_attempts', 0) or 0 for s in daily_stats],
            'distraction_events': [s.get('distraction_events', 0) or 0 for s in daily_stats],
        })
    except Exception as e:
        return jsonify({'error': str(e), 'labels': [], 'productivity': [], 'focus_minutes': []})


@app.route('/screenshot/<path:filepath>')
def serve_screenshot(filepath):
    """Serve screenshot images."""
    full_path = os.path.join(SCREENSHOTS_DIR, filepath)
    if not os.path.isfile(full_path):
        abort(404)
    # Security: ensure we're not serving files outside screenshots dir
    real_path = os.path.realpath(full_path)
    real_base = os.path.realpath(SCREENSHOTS_DIR)
    if not real_path.startswith(real_base):
        abort(403)
    return send_file(real_path)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('base.html', content='<div class="empty-state"><h2>404 — Page not found</h2><p>The page you\'re looking for doesn\'t exist.</p><a href="/" class="btn-primary">Back to Dashboard</a></div>'), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9999, debug=True)
