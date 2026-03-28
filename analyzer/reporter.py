"""
Lock In — Report generation
Builds formatted reports from analyzed session data and
computes historical habit analytics.
"""

import sys
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitor import db
from analyzer.analyzer import SessionAnalyzer

logger = logging.getLogger("lockin.reporter")


class Reporter:
    """Generates reports and habit analytics from session data."""

    def __init__(self, analyzer: Optional[SessionAnalyzer] = None):
        self.analyzer = analyzer or SessionAnalyzer()

    # ------------------------------------------------------------------ #
    # End-of-session report
    # ------------------------------------------------------------------ #

    def end_of_session_report(self, session_id: int) -> dict:
        """Called when a session ends. Runs full analysis, updates DB,
        returns a structured report.

        Returns dict:
            session_id, duration_minutes, productivity_score, focus_score,
            summary, recommendations, formatted_report
        """
        session = db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # 1. Calculate local scores (always works)
        prod_score = self.analyzer.calculate_productivity_score(session_id)
        focus_score = self.analyzer.calculate_focus_score(session_id)

        # 2. Run AI analysis (may fail gracefully)
        try:
            analysis = self.analyzer.analyze_session(session_id)
            summary = analysis["summary"]
            recommendations = analysis["recommendations"]
            # analyze_session already called end_session and wrote scores
        except Exception as exc:
            logger.warning("Full analysis failed, using local scores: %s", exc)
            summary = self.analyzer._build_local_summary(
                session,
                db.get_session_windows(session_id),
                db.get_session_activity(session_id),
            )
            recommendations = []
            # Write local scores to DB
            db.end_session(session_id, prod_score, focus_score)
            self.analyzer._update_session_summary(session_id, summary)

        # 3. Update daily stats
        session_date = datetime.fromtimestamp(session["started_at"]).strftime("%Y-%m-%d")
        db.update_daily_stats(session_date)

        # 4. Build formatted report
        formatted = self.format_session_summary(session_id)

        return {
            "session_id": session_id,
            "duration_minutes": session.get("duration_minutes", 0),
            "productivity_score": round(prod_score, 1),
            "focus_score": round(focus_score, 1),
            "summary": summary,
            "recommendations": recommendations,
            "formatted_report": formatted,
        }

    # ------------------------------------------------------------------ #
    # Habit data (historical analytics)
    # ------------------------------------------------------------------ #

    def get_habit_data(self, days: int = 30) -> dict:
        """Compute habit analytics from historical data.

        Returns:
            sessions_by_day_of_week: {mon: N, tue: N, ...}
            sessions_by_hour: {9: N, 10: N, ...}
            avg_duration_trend: [{date, avg_minutes}, ...]
            productivity_trend: [{date, score}, ...]
            streak: current streak count
            best_streak: longest ever
            total_focus_hours: all-time float
            common_sites: most frequently allowed sites
        """
        cutoff = int(time.time()) - days * 86400
        all_sessions = db.get_sessions(limit=1000, offset=0)
        sessions = [s for s in all_sessions if s.get("started_at", 0) >= cutoff]

        # Sessions by day of week
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        by_dow: dict[str, int] = defaultdict(int)
        for s in sessions:
            dow = datetime.fromtimestamp(s["started_at"]).weekday()
            by_dow[day_names[dow]] += 1

        # Sessions by hour
        by_hour: dict[int, int] = defaultdict(int)
        for s in sessions:
            hour = datetime.fromtimestamp(s["started_at"]).hour
            by_hour[hour] += 1

        # Daily aggregates for trends
        daily_durations: dict[str, list[int]] = defaultdict(list)
        daily_scores: dict[str, list[float]] = defaultdict(list)
        for s in sessions:
            date_str = datetime.fromtimestamp(s["started_at"]).strftime("%Y-%m-%d")
            daily_durations[date_str].append(s.get("duration_minutes", 0))
            if s.get("productivity_score") is not None:
                daily_scores[date_str].append(s["productivity_score"])

        avg_duration_trend = sorted(
            [
                {"date": d, "avg_minutes": round(sum(v) / len(v), 1)}
                for d, v in daily_durations.items()
            ],
            key=lambda x: x["date"],
        )

        productivity_trend = sorted(
            [
                {"date": d, "score": round(sum(v) / len(v), 1)}
                for d, v in daily_scores.items()
            ],
            key=lambda x: x["date"],
        )

        # Streak
        streak = db.get_streak()
        best_streak = self._compute_best_streak()

        # Total focus hours (all time)
        all_ever = db.get_sessions(limit=10000, offset=0)
        total_minutes = sum(s.get("duration_minutes", 0) for s in all_ever)
        total_focus_hours = round(total_minutes / 60.0, 1)

        # Common allowed sites
        site_counts: dict[str, int] = defaultdict(int)
        for s in sessions:
            sites_str = s.get("allowed_sites", "")
            if sites_str:
                for site in sites_str.split(","):
                    site = site.strip()
                    if site:
                        site_counts[site] += 1

        common_sites = [
            site
            for site, _ in sorted(site_counts.items(), key=lambda x: -x[1])[:10]
        ]

        return {
            "sessions_by_day_of_week": dict(by_dow),
            "sessions_by_hour": dict(by_hour),
            "avg_duration_trend": avg_duration_trend,
            "productivity_trend": productivity_trend,
            "streak": streak,
            "best_streak": best_streak,
            "total_focus_hours": total_focus_hours,
            "common_sites": common_sites,
        }

    # ------------------------------------------------------------------ #
    # Human-readable session summary
    # ------------------------------------------------------------------ #

    def format_session_summary(self, session_id: int) -> str:
        """Build a human-readable session summary for display."""
        session = db.get_session(session_id)
        if not session:
            return f"Session {session_id} not found."

        start_time = datetime.fromtimestamp(session["started_at"]).strftime("%H:%M")
        end_str = ""
        if session.get("ended_at"):
            end_str = datetime.fromtimestamp(session["ended_at"]).strftime("%H:%M")

        duration = session.get("duration_minutes", 0)
        prod = session.get("productivity_score")
        focus = session.get("focus_score")
        bypasses = session.get("bypass_attempts", 0)
        distractions = session.get("distraction_count", 0)
        summary = session.get("ai_summary", "")

        # Score bar helper
        def bar(score: Optional[float], width: int = 20) -> str:
            if score is None:
                return "[not scored]"
            filled = int(score / 100 * width)
            return f"[{'#' * filled}{'-' * (width - filled)}] {score:.0f}/100"

        lines = [
            f"=== Session #{session_id} ===",
            f"Time:         {start_time} - {end_str or 'ongoing'}  ({duration} min)",
            f"Productivity: {bar(prod)}",
            f"Focus:        {bar(focus)}",
            f"Bypass attempts: {bypasses}",
            f"Distractions:    {distractions}",
        ]

        if summary:
            lines.append(f"\n{summary}")

        # Top apps
        windows = db.get_session_windows(session_id)
        if windows:
            app_time: dict[str, int] = defaultdict(int)
            for w in windows:
                app_time[w.get("app_name", "unknown")] += w.get("duration_seconds", 0)
            top_apps = sorted(app_time.items(), key=lambda x: -x[1])[:5]
            lines.append("\nTop apps:")
            for app, secs in top_apps:
                mins = secs / 60
                lines.append(f"  {app}: {mins:.1f} min")

        return "\n".join(lines)

    # ================================================================== #
    # Private helpers
    # ================================================================== #

    def _compute_best_streak(self) -> int:
        """Compute the longest ever daily streak from daily_stats."""
        conn = db.get_db()
        rows = conn.execute(
            "SELECT DISTINCT date FROM daily_stats WHERE sessions_count > 0 ORDER BY date"
        ).fetchall()
        conn.close()

        if not rows:
            return 0

        dates = [datetime.strptime(r["date"], "%Y-%m-%d").date() for r in rows]
        best = 1
        current = 1
        for i in range(1, len(dates)):
            if dates[i] - dates[i - 1] == timedelta(days=1):
                current += 1
                best = max(best, current)
            else:
                current = 1

        return best
