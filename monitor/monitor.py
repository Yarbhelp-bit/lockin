#!/usr/bin/env python3
"""
Lock In — Main behavioral monitor daemon

Reads session config from /etc/lockin/session, initializes the database,
starts all tracker threads, and runs until the session ends.
Designed to be launched by the guard daemon as: python3 monitor.py
"""

import logging
import os
import signal
import sys
import threading
import time

# Ensure the package is importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor import db
from monitor.screenshotter import Screenshotter
from monitor.tracker import (
    BypassMonitor,
    IdleDetector,
    KeystrokeTracker,
    WindowTracker,
)

SESSION_CONFIG = "/etc/lockin/session"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lockin.monitor")


def read_session_config() -> dict:
    """Parse /etc/lockin/session for session parameters.

    Expected format (key=value, one per line):
        END_TIME=1710278400
        ALLOWED_DOMAINS=github.com,stackoverflow.com
        DURATION_MINUTES=25
    """
    config = {}
    if not os.path.isfile(SESSION_CONFIG):
        log.error("Session config not found: %s", SESSION_CONFIG)
        sys.exit(1)

    with open(SESSION_CONFIG, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()

    required = ["END_TIME", "DURATION_MINUTES"]
    for key in required:
        if key not in config:
            log.error("Missing required config key: %s", key)
            sys.exit(1)

    return config


def main():
    log.info("Lock In monitor starting")

    # ---- Read config ----
    config = read_session_config()
    end_time = int(config["END_TIME"])
    duration = int(config["DURATION_MINUTES"])
    allowed_sites = [
        s.strip() for s in config.get("ALLOWED_DOMAINS", "").split(",") if s.strip()
    ]

    log.info("Session: %d min, ends at %s, allowed: %s",
             duration, time.strftime("%H:%M:%S", time.localtime(end_time)), allowed_sites)

    # ---- Initialize DB ----
    db.init_db()
    session_id = db.create_session(duration, ",".join(allowed_sites))
    log.info("DB session created: id=%d", session_id)

    # ---- Shared stop event ----
    stop_event = threading.Event()

    def handle_signal(signum, _frame):
        log.info("Received signal %d, stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # ---- Start trackers ----
    trackers = []
    bypass_monitor = None

    # Window tracker
    try:
        wt = WindowTracker(session_id, allowed_sites, stop_event)
        wt.start()
        trackers.append(wt)
    except Exception:
        log.exception("Failed to start window tracker")

    # Keystroke tracker
    kt = None
    try:
        kt = KeystrokeTracker(session_id, stop_event)
        kt.start()
        trackers.append(kt)
    except Exception:
        log.exception("Failed to start keystroke tracker")

    # Idle detector (depends on keystroke tracker)
    if kt is not None:
        try:
            idle = IdleDetector(session_id, kt, stop_event)
            idle.start()
            trackers.append(idle)
        except Exception:
            log.exception("Failed to start idle detector")

    # Screenshotter
    try:
        ss = Screenshotter(session_id, stop_event)
        ss.start()
        trackers.append(ss)
    except Exception:
        log.exception("Failed to start screenshotter")

    # Bypass monitor
    try:
        bypass_monitor = BypassMonitor(session_id, stop_event)
        bypass_monitor.start()
        trackers.append(bypass_monitor)
    except Exception:
        log.exception("Failed to start bypass monitor")

    log.info("All trackers started (%d threads)", len(trackers))

    # ---- Run until session ends ----
    try:
        while not stop_event.is_set():
            now = time.time()
            if now >= end_time:
                log.info("Session time reached, stopping")
                break
            # Sleep in 1-second increments for responsive shutdown
            remaining = end_time - now
            sleep_time = min(remaining, 1.0)
            if sleep_time > 0:
                stop_event.wait(timeout=sleep_time)
    except KeyboardInterrupt:
        log.info("Keyboard interrupt, stopping")

    # ---- Shutdown ----
    log.info("Stopping all trackers")
    stop_event.set()

    for t in trackers:
        t.join(timeout=5)

    # Clean up iptables LOG rule
    if bypass_monitor is not None:
        bypass_monitor.cleanup()

    # End the DB session
    db.end_session(session_id)
    db.update_daily_stats()
    log.info("Session %d ended, daily stats updated", session_id)

    # ---- Run analyzer (if available) ----
    try:
        analyzer_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "analyzer.py"
        )
        if os.path.isfile(analyzer_path):
            log.info("Running post-session analyzer")
            import subprocess
            subprocess.Popen(
                [sys.executable, analyzer_path, str(session_id)],
                start_new_session=True,
            )
    except Exception:
        log.debug("Could not launch analyzer", exc_info=True)

    log.info("Monitor shutdown complete")


if __name__ == "__main__":
    main()
