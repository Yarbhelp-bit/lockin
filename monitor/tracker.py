"""
Lock In — Window, activity, and keystroke tracking module
Runs on GNOME/Wayland. Tracks:
  - Active window title + app classification (every 3s)
  - Rapid app-switching detection
  - Keystroke activity via /proc/interrupts polling (every 60s)
  - iptables bypass-attempt monitoring via journalctl
  - Idle detection (>2 min no keyboard/mouse)
"""

import logging
import os
import re
import subprocess
import threading
import time
from collections import deque

from . import db

log = logging.getLogger("lockin.tracker")

# ----- Configuration -----
WINDOW_POLL_INTERVAL = 3       # seconds
KEYSTROKE_LOG_INTERVAL = 60    # seconds
BYPASS_POLL_INTERVAL = 10      # seconds
IDLE_THRESHOLD = 120           # seconds
RAPID_SWITCH_WINDOW = 30       # seconds
RAPID_SWITCH_LIMIT = 5         # switches within window

# Known unproductive apps / title patterns
DISTRACTION_PATTERNS = [
    r"(?i)youtube", r"(?i)reddit", r"(?i)twitter", r"(?i)tiktok",
    r"(?i)instagram", r"(?i)facebook", r"(?i)twitch", r"(?i)netflix",
    r"(?i)discord",
]


class WindowTracker:
    """Tracks active window changes, detects distractions and rapid switching."""

    def __init__(self, session_id: int, allowed_sites: list[str],
                 stop_event: threading.Event):
        self.session_id = session_id
        self.allowed_sites = [s.strip().lower() for s in allowed_sites if s.strip()]
        self.stop_event = stop_event

        self._prev_title = None
        self._prev_app = None
        self._prev_change_ts = time.time()
        self._switch_times: deque[float] = deque()

        self._thread = threading.Thread(
            target=self._run, name="window-tracker", daemon=True
        )

    def start(self):
        self._thread.start()
        log.info("Window tracker started (interval=%ds)", WINDOW_POLL_INTERVAL)

    def join(self, timeout=None):
        self._thread.join(timeout=timeout)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                title = self._get_active_window_title()
                app = self._extract_app_name(title)
                now = time.time()

                if title != self._prev_title:
                    # Log the *previous* window's duration
                    if self._prev_title is not None:
                        duration = int(now - self._prev_change_ts)
                        productive = self._is_productive(self._prev_title)
                        db.log_window(
                            self.session_id,
                            self._prev_title,
                            self._prev_app or "unknown",
                            duration_seconds=duration,
                            is_productive=productive,
                        )

                    # Record switch for rapid-switching detection
                    if self._prev_title is not None:
                        self._switch_times.append(now)
                        self._detect_rapid_switching(now)

                    self._prev_title = title
                    self._prev_app = app
                    self._prev_change_ts = now

            except Exception:
                log.exception("Window tracking error")

            self._interruptible_sleep(WINDOW_POLL_INTERVAL)

        # Log final window on exit
        try:
            if self._prev_title is not None:
                duration = int(time.time() - self._prev_change_ts)
                productive = self._is_productive(self._prev_title)
                db.log_window(
                    self.session_id,
                    self._prev_title,
                    self._prev_app or "unknown",
                    duration_seconds=duration,
                    is_productive=productive,
                )
        except Exception:
            log.debug("Could not log final window", exc_info=True)

    def _detect_rapid_switching(self, now: float):
        """Check if there have been too many switches in the recent window."""
        # Discard old entries
        while self._switch_times and (now - self._switch_times[0]) > RAPID_SWITCH_WINDOW:
            self._switch_times.popleft()

        if len(self._switch_times) >= RAPID_SWITCH_LIMIT:
            db.log_activity(
                self.session_id,
                "distraction_detected",
                category="rapid_switch",
                data={"switches": len(self._switch_times), "window_seconds": RAPID_SWITCH_WINDOW},
            )
            log.info(
                "Rapid switching detected: %d switches in %ds",
                len(self._switch_times), RAPID_SWITCH_WINDOW,
            )
            self._switch_times.clear()  # reset so we don't spam

    def _is_productive(self, title: str) -> bool:
        """Classify a window title as productive or not."""
        if not title or title == "unknown":
            return True  # assume productive if we can't tell

        title_lower = title.lower()

        # If title contains an allowed site, it's productive
        for site in self.allowed_sites:
            if site in title_lower:
                return True

        # Check against known distracting patterns
        for pattern in DISTRACTION_PATTERNS:
            if re.search(pattern, title):
                return False

        # Default: assume productive (IDE, terminal, docs, etc.)
        return True

    @staticmethod
    def _extract_app_name(title: str) -> str:
        """Extract app name from window title heuristic.

        Common patterns:
        - "Page Title - Mozilla Firefox" -> "Firefox"
        - "file.py - Visual Studio Code" -> "Visual Studio Code"
        - "Terminal" -> "Terminal"
        """
        if not title or title == "unknown":
            return "unknown"

        parts = title.rsplit(" - ", 1)
        if len(parts) == 2:
            app = parts[1].strip()
            # Simplify common names
            if "Firefox" in app:
                return "Firefox"
            if "Chrome" in app or "Chromium" in app:
                return "Chrome"
            return app

        parts = title.rsplit(" — ", 1)
        if len(parts) == 2:
            return parts[1].strip()

        return title.strip()

    @staticmethod
    def _get_active_window_title() -> str:
        """Get active window title on GNOME/Wayland via D-Bus Shell.Eval."""
        try:
            r = subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.gnome.Shell",
                    "--object-path", "/org/gnome/Shell",
                    "--method", "org.gnome.Shell.Eval",
                    "global.display.focus_window ? global.display.focus_window.get_title() : 'unknown'",
                ],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                # Output format: (true, 'Window Title')
                m = re.search(r"'(.*)'", r.stdout.split(",", 1)[-1])
                if m:
                    return m.group(1)
        except Exception:
            log.debug("gdbus Shell.Eval failed", exc_info=True)

        # Fallback: try wmctrl
        try:
            r = subprocess.run(
                ["wmctrl", "-a", ":ACTIVE:", "-v"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            pass

        # Fallback: try xdotool (won't work on Wayland but doesn't hurt)
        try:
            r = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass

        return "unknown"

    def _interruptible_sleep(self, seconds: float):
        for _ in range(int(seconds)):
            if self.stop_event.is_set():
                return
            time.sleep(1)


class KeystrokeTracker:
    """Monitors keyboard activity via /proc/interrupts polling.

    Does NOT log actual keystrokes (privacy). Only counts activity level.
    """

    def __init__(self, session_id: int, stop_event: threading.Event):
        self.session_id = session_id
        self.stop_event = stop_event
        self._last_irq_count: int | None = None
        self._last_activity_time = time.time()
        self._thread = threading.Thread(
            target=self._run, name="keystroke-tracker", daemon=True
        )

    def start(self):
        self._thread.start()
        log.info("Keystroke tracker started (interval=%ds)", KEYSTROKE_LOG_INTERVAL)

    def join(self, timeout=None):
        self._thread.join(timeout=timeout)

    def _run(self):
        # Initial read
        self._last_irq_count = self._read_keyboard_irqs()

        while not self.stop_event.is_set():
            self._interruptible_sleep(KEYSTROKE_LOG_INTERVAL)
            if self.stop_event.is_set():
                return

            try:
                current = self._read_keyboard_irqs()
                if current is not None and self._last_irq_count is not None:
                    delta = current - self._last_irq_count
                    # Each keypress generates 2 interrupts (press + release)
                    keypress_count = max(0, delta // 2)
                    active = keypress_count > 5  # threshold: >5 keys/min = active typing
                    db.log_keystrokes(
                        self.session_id,
                        keypress_count=keypress_count,
                        active_typing=active,
                        interval=KEYSTROKE_LOG_INTERVAL,
                    )

                    if keypress_count > 0:
                        self._last_activity_time = time.time()

                    log.debug("Keystrokes in last %ds: %d (active=%s)",
                              KEYSTROKE_LOG_INTERVAL, keypress_count, active)
                else:
                    # Can't read IRQs — log zero
                    db.log_keystrokes(self.session_id, 0, False, KEYSTROKE_LOG_INTERVAL)

                self._last_irq_count = current

            except Exception:
                log.exception("Keystroke tracking error")

    @property
    def last_activity_time(self) -> float:
        return self._last_activity_time

    @staticmethod
    def _read_keyboard_irqs() -> int | None:
        """Sum all keyboard-related IRQ counts from /proc/interrupts."""
        try:
            with open("/proc/interrupts", "r") as f:
                total = 0
                for line in f:
                    # Keyboard IRQs are usually on i8042 (PS/2) or USB HID
                    if "i8042" in line or "keyboard" in line.lower():
                        parts = line.split()
                        # Sum CPU columns (all numbers between IRQ# and device name)
                        for part in parts[1:]:
                            if part.isdigit():
                                total += int(part)
                            else:
                                break
                        return total if total > 0 else None
                return None
        except Exception:
            return None

    def _interruptible_sleep(self, seconds: float):
        for _ in range(int(seconds)):
            if self.stop_event.is_set():
                return
            time.sleep(1)


class IdleDetector:
    """Detects idle periods (no keyboard/mouse activity for > threshold)."""

    def __init__(self, session_id: int, keystroke_tracker: KeystrokeTracker,
                 stop_event: threading.Event):
        self.session_id = session_id
        self.keystroke_tracker = keystroke_tracker
        self.stop_event = stop_event
        self._idle = False
        self._thread = threading.Thread(
            target=self._run, name="idle-detector", daemon=True
        )

    def start(self):
        self._thread.start()
        log.info("Idle detector started (threshold=%ds)", IDLE_THRESHOLD)

    def join(self, timeout=None):
        self._thread.join(timeout=timeout)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                idle_secs = time.time() - self.keystroke_tracker.last_activity_time
                if idle_secs >= IDLE_THRESHOLD and not self._idle:
                    self._idle = True
                    db.log_activity(
                        self.session_id,
                        "idle_detected",
                        category="idle",
                        data={"idle_seconds": int(idle_secs)},
                    )
                    log.info("User idle for %ds", int(idle_secs))
                elif idle_secs < IDLE_THRESHOLD and self._idle:
                    self._idle = False
                    db.log_activity(
                        self.session_id,
                        "idle_ended",
                        category="idle",
                        data={"idle_duration": int(idle_secs)},
                    )
                    log.info("User returned from idle")
            except Exception:
                log.exception("Idle detection error")

            for _ in range(10):
                if self.stop_event.is_set():
                    return
                time.sleep(1)


class BypassMonitor:
    """Monitors iptables LOG entries for blocked connection attempts."""

    LOG_PREFIX = "LOCKIN_BLOCK"

    def __init__(self, session_id: int, stop_event: threading.Event):
        self.session_id = session_id
        self.stop_event = stop_event
        self._seen_lines: set[str] = set()
        self._thread = threading.Thread(
            target=self._run, name="bypass-monitor", daemon=True
        )

    def start(self):
        self._setup_log_rule()
        self._thread.start()
        log.info("Bypass monitor started (interval=%ds)", BYPASS_POLL_INTERVAL)

    def join(self, timeout=None):
        self._thread.join(timeout=timeout)

    def cleanup(self):
        """Remove the LOG rule we added."""
        try:
            subprocess.run(
                ["iptables", "-D", "LOCKIN", "-j", "LOG",
                 "--log-prefix", f"{self.LOG_PREFIX}: ", "--log-level", "4"],
                capture_output=True, timeout=5,
            )
            log.debug("Removed iptables LOG rule")
        except Exception:
            log.debug("Could not remove iptables LOG rule", exc_info=True)

    def _setup_log_rule(self):
        """Add iptables LOG rule at the top of the LOCKIN chain."""
        try:
            # Check if LOCKIN chain exists
            r = subprocess.run(
                ["iptables", "-L", "LOCKIN", "-n"],
                capture_output=True, timeout=5,
            )
            if r.returncode != 0:
                log.warning("LOCKIN iptables chain does not exist, bypass monitoring disabled")
                return

            # Insert LOG rule at position 1 (before DROP rules)
            subprocess.run(
                ["iptables", "-I", "LOCKIN", "1", "-j", "LOG",
                 "--log-prefix", f"{self.LOG_PREFIX}: ", "--log-level", "4"],
                capture_output=True, timeout=5,
            )
            log.debug("Added iptables LOG rule")
        except Exception:
            log.warning("Could not add iptables LOG rule", exc_info=True)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self._check_logs()
            except Exception:
                log.exception("Bypass monitor error")

            for _ in range(BYPASS_POLL_INTERVAL):
                if self.stop_event.is_set():
                    return
                time.sleep(1)

    def _check_logs(self):
        """Read recent journal entries for LOCKIN_BLOCK prefix."""
        try:
            r = subprocess.run(
                ["journalctl", "-k", "--since", "1 minute ago",
                 "--grep", self.LOG_PREFIX, "--no-pager", "-o", "short"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return

            for line in r.stdout.strip().splitlines():
                line_hash = hash(line)
                if line_hash in self._seen_lines:
                    continue
                self._seen_lines.add(line_hash)

                # Extract destination IP
                dst = "unknown"
                m = re.search(r"DST=(\S+)", line)
                if m:
                    dst = m.group(1)

                db.log_activity(
                    self.session_id,
                    "bypass_attempt",
                    category="network",
                    data={"destination": dst, "raw": line[:200]},
                )
                log.info("Bypass attempt detected: DST=%s", dst)

        except FileNotFoundError:
            # journalctl not available, try kern.log
            self._check_kern_log()
        except Exception:
            log.debug("journalctl failed, trying kern.log", exc_info=True)
            self._check_kern_log()

    def _check_kern_log(self):
        """Fallback: read /var/log/kern.log for LOCKIN_BLOCK entries."""
        logfile = "/var/log/kern.log"
        if not os.path.isfile(logfile):
            return

        try:
            # Only read last 100 lines
            r = subprocess.run(
                ["tail", "-100", logfile],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                return

            for line in r.stdout.splitlines():
                if self.LOG_PREFIX not in line:
                    continue
                line_hash = hash(line)
                if line_hash in self._seen_lines:
                    continue
                self._seen_lines.add(line_hash)

                dst = "unknown"
                m = re.search(r"DST=(\S+)", line)
                if m:
                    dst = m.group(1)

                db.log_activity(
                    self.session_id,
                    "bypass_attempt",
                    category="network",
                    data={"destination": dst, "raw": line[:200]},
                )
        except Exception:
            log.debug("kern.log read failed", exc_info=True)
