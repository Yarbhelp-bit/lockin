"""
Lock In — AI Behavioral Analyzer
Analyzes focus session data using Claude API and local metrics
to generate productivity insights, scores, and recommendations.
"""

import sys
import os
import json
import base64
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import anthropic

# Import the shared database module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitor import db

logger = logging.getLogger("lockin.analyzer")


class SessionAnalyzer:
    """Core analysis engine for Lock In focus sessions."""

    def __init__(self):
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
        self.model = "claude-sonnet-4-6"

    # ------------------------------------------------------------------ #
    # Full session analysis (post-session)
    # ------------------------------------------------------------------ #

    def analyze_session(self, session_id: int) -> dict:
        """Full post-session analysis.

        Returns dict with keys:
            productivity_score, focus_score, summary, recommendations
        """
        session = db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        windows = db.get_session_windows(session_id)
        activity = db.get_session_activity(session_id)
        keystrokes = db.get_session_keystrokes(session_id)
        screenshots = db.get_session_screenshots(session_id)

        # Always calculate local scores (no API needed)
        prod_score = self.calculate_productivity_score(session_id)
        focus_score = self.calculate_focus_score(session_id)

        # Attempt AI analysis; fall back gracefully
        summary = ""
        recommendations: list[str] = []
        try:
            ai_result = self._call_session_analysis(
                session, windows, activity, keystrokes, screenshots
            )
            summary = ai_result.get("summary", "")
            recommendations = ai_result.get("recommendations", [])
            # AI may also suggest adjusted scores — trust local calc but log
            if ai_result.get("productivity_score") is not None:
                logger.debug(
                    "AI suggested productivity=%s vs local=%s",
                    ai_result["productivity_score"],
                    prod_score,
                )
        except Exception as exc:
            logger.warning("AI analysis unavailable, using local scores only: %s", exc)
            summary = self._build_local_summary(session, windows, activity)

        # Persist scores and summary
        db.end_session(session_id, prod_score, focus_score)
        self._update_session_summary(session_id, summary)

        return {
            "productivity_score": round(prod_score, 1),
            "focus_score": round(focus_score, 1),
            "summary": summary,
            "recommendations": recommendations,
        }

    # ------------------------------------------------------------------ #
    # Screenshot analysis (vision)
    # ------------------------------------------------------------------ #

    def analyze_screenshot(self, screenshot_id: int) -> dict:
        """Analyze a single screenshot for distraction content via Claude vision.

        Returns dict:
            is_distraction, confidence, description, app_detected
        """
        conn = db.get_db()
        row = conn.execute(
            "SELECT * FROM screenshots WHERE id=?", (screenshot_id,)
        ).fetchone()
        conn.close()

        if not row:
            raise ValueError(f"Screenshot {screenshot_id} not found")

        screenshot = dict(row)
        filepath = screenshot["filepath"]

        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Screenshot file missing: {filepath}")

        # Determine media type
        ext = os.path.splitext(filepath)[1].lower()
        media_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        media_type = media_type_map.get(ext, "image/png")

        with open(filepath, "rb") as f:
            base64_image = base64.standard_b64encode(f.read()).decode("utf-8")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64_image,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Is this screen showing productive work or a distraction? "
                                    "What app/website is visible? Rate distraction risk 0-10. "
                                    'Reply as JSON only: {"app": "...", "description": "...", '
                                    '"distraction_risk": N, "is_productive": bool}'
                                ),
                            },
                        ],
                    }
                ],
            )

            text = response.content[0].text.strip()
            # Extract JSON from potential markdown fences
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            result = json.loads(text)
        except Exception as exc:
            logger.warning("Screenshot analysis failed: %s", exc)
            return {
                "is_distraction": False,
                "confidence": 0.0,
                "description": "Analysis unavailable",
                "app_detected": screenshot.get("active_window", "unknown"),
            }

        is_distraction = result.get("distraction_risk", 0) >= 6 or not result.get(
            "is_productive", True
        )
        confidence = min(result.get("distraction_risk", 0) / 10.0, 1.0)

        # Store analysis and flag if needed
        analysis_json = json.dumps(result)
        conn = db.get_db()
        conn.execute(
            "UPDATE screenshots SET ai_analysis=? WHERE id=?",
            (analysis_json, screenshot_id),
        )
        conn.commit()
        conn.close()

        if is_distraction:
            reason = result.get("description", "AI-flagged distraction")
            db.flag_screenshot(screenshot_id, reason)

        return {
            "is_distraction": is_distraction,
            "confidence": round(confidence, 2),
            "description": result.get("description", ""),
            "app_detected": result.get("app", "unknown"),
        }

    # ------------------------------------------------------------------ #
    # Local productivity score (no LLM)
    # ------------------------------------------------------------------ #

    def calculate_productivity_score(self, session_id: int) -> float:
        """Calculate 0-100 productivity score from raw metrics.

        Weights:
            40% — percentage of time on productive windows
            20% — typing activity ratio
            15% — low app-switching frequency
            15% — zero bypass attempts bonus
            10% — low idle time
        """
        session = db.get_session(session_id)
        if not session:
            return 0.0

        windows = db.get_session_windows(session_id)
        keystrokes = db.get_session_keystrokes(session_id)
        activity = db.get_session_activity(session_id)

        # --- Productive window time (40%) ---
        total_win_time = sum(w.get("duration_seconds", 0) for w in windows)
        productive_time = sum(
            w.get("duration_seconds", 0) for w in windows if w.get("is_productive")
        )
        productive_pct = (productive_time / total_win_time * 100) if total_win_time > 0 else 50
        window_score = min(productive_pct, 100)

        # --- Typing activity ratio (20%) ---
        total_intervals = len(keystrokes)
        active_intervals = sum(1 for k in keystrokes if k.get("active_typing"))
        typing_ratio = (active_intervals / total_intervals * 100) if total_intervals > 0 else 50
        typing_score = min(typing_ratio, 100)

        # --- App switching frequency (15%) ---
        app_switches = sum(
            1 for a in activity if a.get("event_type") == "app_switch"
        )
        duration_min = session.get("duration_minutes", 1) or 1
        switches_per_min = app_switches / duration_min
        # 0 switches/min = 100, 3+/min = 0
        switch_score = max(0, 100 - (switches_per_min / 3.0) * 100)

        # --- Bypass attempts (15%) ---
        bypass_count = session.get("bypass_attempts", 0) or 0
        bypass_score = 100 if bypass_count == 0 else max(0, 100 - bypass_count * 30)

        # --- Idle time (10%) ---
        idle_events = sum(
            1 for a in activity if a.get("event_type") == "idle_detected"
        )
        idle_per_min = idle_events / duration_min
        idle_score = max(0, 100 - (idle_per_min / 2.0) * 100)

        score = (
            window_score * 0.40
            + typing_score * 0.20
            + switch_score * 0.15
            + bypass_score * 0.15
            + idle_score * 0.10
        )
        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------ #
    # Local focus score (no LLM)
    # ------------------------------------------------------------------ #

    def calculate_focus_score(self, session_id: int) -> float:
        """Calculate 0-100 focus score measuring sustained attention.

        Components:
            - Longest continuous productive window stretch
            - App switching frequency (fewer = better)
            - Typing consistency (steady > bursty)
        """
        session = db.get_session(session_id)
        if not session:
            return 0.0

        windows = db.get_session_windows(session_id)
        keystrokes = db.get_session_keystrokes(session_id)
        activity = db.get_session_activity(session_id)
        duration_min = session.get("duration_minutes", 1) or 1
        duration_sec = duration_min * 60

        # --- Longest continuous productive stretch (40%) ---
        max_streak_sec = 0
        current_streak_sec = 0
        for w in windows:
            if w.get("is_productive"):
                current_streak_sec += w.get("duration_seconds", 0)
                max_streak_sec = max(max_streak_sec, current_streak_sec)
            else:
                current_streak_sec = 0

        stretch_ratio = (max_streak_sec / duration_sec) if duration_sec > 0 else 0
        stretch_score = min(stretch_ratio * 100, 100)

        # --- App switch frequency (35%) ---
        app_switches = sum(
            1 for a in activity if a.get("event_type") == "app_switch"
        )
        switches_per_min = app_switches / duration_min
        switch_score = max(0, 100 - (switches_per_min / 3.0) * 100)

        # --- Typing consistency (25%) ---
        if len(keystrokes) >= 2:
            counts = [k.get("keypress_count", 0) for k in keystrokes]
            mean_kps = sum(counts) / len(counts)
            if mean_kps > 0:
                variance = sum((c - mean_kps) ** 2 for c in counts) / len(counts)
                std_dev = variance ** 0.5
                cv = std_dev / mean_kps  # coefficient of variation
                # Low CV = consistent, high CV = bursty
                consistency_score = max(0, 100 - cv * 50)
            else:
                consistency_score = 30  # no typing at all is middling
        else:
            consistency_score = 50  # insufficient data

        score = (
            stretch_score * 0.40
            + switch_score * 0.35
            + consistency_score * 0.25
        )
        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------ #
    # Daily insights (AI)
    # ------------------------------------------------------------------ #

    def generate_daily_insights(self, date: Optional[str] = None) -> str:
        """Generate AI insights for a day's sessions.

        Args:
            date: YYYY-MM-DD string, defaults to today.
        """
        if date is None:
            date = time.strftime("%Y-%m-%d")

        # Gather sessions for the date
        start_ts = int(time.mktime(time.strptime(date, "%Y-%m-%d")))
        end_ts = start_ts + 86400

        conn = db.get_db()
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE started_at >= ? AND started_at < ? ORDER BY started_at",
            (start_ts, end_ts),
        ).fetchall()
        conn.close()
        sessions = [dict(s) for s in sessions]

        if not sessions:
            return f"No sessions recorded on {date}."

        # Build summary of each session
        session_lines = []
        for s in sessions:
            start = datetime.fromtimestamp(s["started_at"]).strftime("%H:%M")
            prod = s.get("productivity_score") or "N/A"
            focus = s.get("focus_score") or "N/A"
            bypasses = s.get("bypass_attempts", 0)
            distractions = s.get("distraction_count", 0)
            session_lines.append(
                f"- {start} | {s['duration_minutes']}min | "
                f"prod={prod} focus={focus} | "
                f"bypasses={bypasses} distractions={distractions} | "
                f"sites: {s.get('allowed_sites', 'N/A')}"
            )

        prompt = (
            "You are a focus and productivity coach. Analyze this day's work sessions "
            "and give concise, actionable insights.\n\n"
            f"Date: {date}\n"
            f"Sessions ({len(sessions)}):\n" + "\n".join(session_lines) + "\n\n"
            "Provide:\n"
            "1. Overall day rating and one-line summary\n"
            "2. What went well\n"
            "3. What to improve\n"
            "4. One specific actionable tip for tomorrow\n\n"
            "Be direct and motivational. Keep it under 200 words."
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            insights = response.content[0].text.strip()
        except Exception as exc:
            logger.warning("Daily insights generation failed: %s", exc)
            total_min = sum(s["duration_minutes"] for s in sessions)
            scores = [s["productivity_score"] for s in sessions if s.get("productivity_score")]
            avg = sum(scores) / len(scores) if scores else 0
            insights = (
                f"Daily summary for {date}: {len(sessions)} sessions, "
                f"{total_min} total minutes, avg productivity {avg:.0f}/100. "
                "(AI insights unavailable)"
            )

        # Persist insights in daily_stats
        db.update_daily_stats(date)
        conn = db.get_db()
        conn.execute(
            "UPDATE daily_stats SET ai_insights=? WHERE date=?", (insights, date)
        )
        conn.commit()
        conn.close()

        return insights

    # ------------------------------------------------------------------ #
    # Weekly report (AI)
    # ------------------------------------------------------------------ #

    def generate_weekly_report(self) -> str:
        """Generate a comprehensive weekly report analyzing the last 7 days."""
        daily_stats = db.get_daily_stats(days=7)
        sessions = db.get_sessions(limit=200, offset=0)

        # Filter sessions to last 7 days
        cutoff = int(time.time()) - 7 * 86400
        recent = [s for s in sessions if s.get("started_at", 0) >= cutoff]

        if not recent and not daily_stats:
            return "No data available for the past week."

        # Build data summary
        stats_lines = []
        for d in daily_stats:
            stats_lines.append(
                f"- {d['date']}: {d['sessions_count']} sessions, "
                f"{d['total_minutes']}min, "
                f"prod={d['avg_productivity']:.0f}, focus={d['avg_focus']:.0f}, "
                f"bypasses={d['bypass_attempts']}, distractions={d['distraction_events']}"
            )

        # Aggregate distraction patterns
        distraction_apps: dict[str, int] = {}
        for s in recent:
            windows = db.get_session_windows(s["id"])
            for w in windows:
                if not w.get("is_productive"):
                    app = w.get("app_name", "unknown")
                    distraction_apps[app] = distraction_apps.get(app, 0) + 1

        top_distractions = sorted(distraction_apps.items(), key=lambda x: -x[1])[:5]
        distraction_str = ", ".join(f"{app}({n})" for app, n in top_distractions) or "none"

        streak = db.get_streak()

        prompt = (
            "You are a focus and productivity coach. Write a weekly report.\n\n"
            f"Current streak: {streak} days\n\n"
            "Daily breakdown:\n" + "\n".join(stats_lines) + "\n\n"
            f"Top distraction apps: {distraction_str}\n"
            f"Total sessions this week: {len(recent)}\n\n"
            "Provide:\n"
            "1. Week summary with trend (improving/declining/steady)\n"
            "2. Best day and why\n"
            "3. Biggest challenge this week\n"
            "4. Top 3 specific recommendations for next week\n"
            "5. Motivational closing\n\n"
            "Be direct, data-driven, and constructive. ~300 words max."
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as exc:
            logger.warning("Weekly report generation failed: %s", exc)
            total_sessions = len(recent)
            total_min = sum(s["duration_minutes"] for s in recent)
            return (
                f"Weekly report (AI unavailable): {total_sessions} sessions, "
                f"{total_min} total minutes, streak={streak} days. "
                f"Top distractions: {distraction_str}."
            )

    # ------------------------------------------------------------------ #
    # Distraction pattern detection
    # ------------------------------------------------------------------ #

    def detect_distraction_patterns(self, days: int = 14) -> dict:
        """Analyze activity across sessions to find distraction patterns.

        Returns:
            time_of_day_distractions: {hour: count}
            common_distraction_apps: [{app, count}]
            avg_time_to_first_distraction_min: float
            session_length_vs_focus: [{duration_min, focus_score}]
        """
        cutoff = int(time.time()) - days * 86400
        all_sessions = db.get_sessions(limit=500, offset=0)
        sessions = [s for s in all_sessions if s.get("started_at", 0) >= cutoff]

        hour_distractions: dict[int, int] = {}
        app_distractions: dict[str, int] = {}
        first_distraction_times: list[float] = []
        length_vs_focus: list[dict] = []

        for s in sessions:
            sid = s["id"]
            session_start = s["started_at"]
            activity = db.get_session_activity(sid)
            windows = db.get_session_windows(sid)

            # Track focus vs length
            if s.get("focus_score") is not None:
                length_vs_focus.append(
                    {
                        "duration_min": s["duration_minutes"],
                        "focus_score": s["focus_score"],
                    }
                )

            # Distraction events by hour
            distraction_events = [
                a
                for a in activity
                if a.get("event_type") in ("distraction_detected", "bypass_attempt")
            ]
            for evt in distraction_events:
                hour = datetime.fromtimestamp(evt["timestamp"]).hour
                hour_distractions[hour] = hour_distractions.get(hour, 0) + 1

            # Time to first distraction
            if distraction_events:
                first_ts = distraction_events[0]["timestamp"]
                delta_min = (first_ts - session_start) / 60.0
                first_distraction_times.append(max(0, delta_min))

            # Unproductive window apps
            for w in windows:
                if not w.get("is_productive"):
                    app = w.get("app_name", "unknown")
                    app_distractions[app] = app_distractions.get(app, 0) + 1

        avg_first = (
            sum(first_distraction_times) / len(first_distraction_times)
            if first_distraction_times
            else None
        )

        sorted_apps = sorted(app_distractions.items(), key=lambda x: -x[1])
        common_apps = [{"app": app, "count": cnt} for app, cnt in sorted_apps[:10]]

        return {
            "time_of_day_distractions": hour_distractions,
            "common_distraction_apps": common_apps,
            "avg_time_to_first_distraction_min": round(avg_first, 1) if avg_first else None,
            "session_length_vs_focus": length_vs_focus,
        }

    # ================================================================== #
    # Private helpers
    # ================================================================== #

    def _call_session_analysis(
        self, session: dict, windows: list, activity: list,
        keystrokes: list, screenshots: list
    ) -> dict:
        """Build prompt and call Claude for session analysis."""
        duration = session.get("duration_minutes", 0)
        allowed = session.get("allowed_sites", "N/A")
        bypass_count = session.get("bypass_attempts", 0)

        # Format window log
        win_lines = []
        for w in windows[:60]:  # cap to control token usage
            ts = datetime.fromtimestamp(w["timestamp"]).strftime("%H:%M:%S")
            prod = "productive" if w.get("is_productive") else "DISTRACTION"
            win_lines.append(
                f"  {ts} | {w.get('app_name','?')} — {w.get('window_title','?')[:60]} "
                f"| {w.get('duration_seconds',0)}s | {prod}"
            )

        # Format activity log
        act_lines = []
        for a in activity[:40]:
            ts = datetime.fromtimestamp(a["timestamp"]).strftime("%H:%M:%S")
            act_lines.append(f"  {ts} | {a.get('event_type','')} | {a.get('category','')}")

        # Format keystroke summary
        key_lines = []
        for k in keystrokes[:30]:
            ts = datetime.fromtimestamp(k["timestamp"]).strftime("%H:%M:%S")
            active = "typing" if k.get("active_typing") else "idle"
            key_lines.append(f"  {ts} | {k.get('keypress_count',0)} keys/{k.get('interval_seconds',60)}s | {active}")

        flagged = sum(1 for s in screenshots if s.get("flagged"))

        prompt = (
            "You are a focus and productivity coach analyzing a user's work session data.\n\n"
            f"Session: {duration}min, allowed sites: {allowed}\n\n"
            "Window activity:\n" + "\n".join(win_lines or ["  (no data)"]) + "\n\n"
            "Activity events:\n" + "\n".join(act_lines or ["  (no data)"]) + "\n\n"
            "Typing patterns:\n" + "\n".join(key_lines or ["  (no data)"]) + "\n\n"
            f"Bypass attempts: {bypass_count}\n"
            f"Flagged screenshots: {flagged}\n\n"
            "Analyze this session and provide a JSON response with:\n"
            '{"productivity_score": 0-100, "focus_assessment": "...", '
            '"summary": "2-3 sentence summary", '
            '"recommendations": ["tip1", "tip2", "tip3"]}\n\n'
            "Be direct, honest, and constructive. Motivational but no-BS tone."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Extract JSON
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        return json.loads(text)

    def _build_local_summary(
        self, session: dict, windows: list, activity: list
    ) -> str:
        """Build a basic summary without AI when the API is unavailable."""
        duration = session.get("duration_minutes", 0)
        total_win = sum(w.get("duration_seconds", 0) for w in windows)
        prod_win = sum(
            w.get("duration_seconds", 0) for w in windows if w.get("is_productive")
        )
        prod_pct = (prod_win / total_win * 100) if total_win > 0 else 0
        bypasses = session.get("bypass_attempts", 0)
        distractions = sum(
            1 for a in activity if a.get("event_type") == "distraction_detected"
        )
        return (
            f"{duration}-minute session. {prod_pct:.0f}% of window time was productive. "
            f"{bypasses} bypass attempt(s), {distractions} distraction event(s)."
        )

    def _update_session_summary(self, session_id: int, summary: str) -> None:
        """Write the AI summary back to the sessions table."""
        conn = db.get_db()
        conn.execute(
            "UPDATE sessions SET ai_summary=? WHERE id=?", (summary, session_id)
        )
        conn.commit()
        conn.close()
