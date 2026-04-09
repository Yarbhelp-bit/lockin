#!/usr/bin/env python3
"""
LockIn — Video Confrontation Chain Manager

Orchestrates the escalating video confrontation chain.
Each video is a separate subprocess (video_player.py) so that
killing one doesn't stop the chain — the next one spawns immediately.

Escalation logic:
  - First trigger: plays all slots starting from 1
  - Re-trigger within 1 hour: skips slot 1 (the gentle one)
  - After the chain: 60-second cooldown/breathing screen

Usage:
    python3 video_chain.py                    # trigger the chain
    python3 video_chain.py --reason test      # trigger with custom reason
    python3 video_chain.py --init             # init DB + seed defaults
    python3 video_chain.py --list             # list configured slots
    python3 video_chain.py --quick            # test mode (3s per slot)
"""

import subprocess
import sys
import os
import time
import argparse

# Resolve paths so imports work regardless of how this is invoked
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from monitor.db import (
    init_db, get_video_slots, seed_default_video_slots,
    increment_play_count, log_chain_event, get_last_chain_trigger,
    ensure_video_dir, VIDEOS_DIR,
)
from intervention.keyboard_lock import KeyboardLock

PLAYER_SCRIPT = os.path.join(_HERE, "video_player.py")

COOLDOWN_MESSAGE = (
    "Take a deep breath.\n\n"
    "You didn't give in.\n"
    "That took strength.\n\n"
    "Now close this and do something\n"
    "you'll be proud of."
)
COOLDOWN_SECONDS = 60
ESCALATION_WINDOW = 3600  # 1 hour


class ChainManager:
    """Manages the escalating video confrontation chain."""

    def __init__(self, quick_mode=False):
        init_db()
        seed_default_video_slots()
        ensure_video_dir()
        self.quick_mode = quick_mode
        self._kb_lock = KeyboardLock()

        # Restore keybindings if a previous run crashed
        KeyboardLock.restore_if_crashed()

    def trigger(self, reason="blocklist_match"):
        """
        Launch the confrontation chain.

        If triggered again within ESCALATION_WINDOW, starts from slot 2
        (skips the gentle wake-up — you already got that chance).

        Alt+Tab, Super, and other escape shortcuts are disabled for the
        entire duration of the chain. Restored after completion or on crash.
        """
        now = time.time()
        last = get_last_chain_trigger()

        start_slot = 2 if (now - last < ESCALATION_WINDOW) else 1

        slots = get_video_slots(start_from=start_slot)

        with self._kb_lock:
            if not slots:
                self._play(
                    message="Stop.\n\nWhat are you doing?",
                    min_watch=5 if self.quick_mode else 10,
                    tier=2,
                    title="LockIn",
                )
                log_chain_event(reason, 1, True, start_slot)
                return

            slots_played = 0

            for slot in slots:
                video_path = slot.get("file_path")
                message = slot.get("message") or "Stop."
                min_watch = 3 if self.quick_mode else slot.get("min_watch_seconds", 10)
                tier = slot.get("tier", 1)
                title = slot.get("title", "")

                self._play(
                    video_path=video_path,
                    message=message,
                    min_watch=min_watch,
                    tier=tier,
                    title=title,
                )

                slots_played += 1
                if slot.get("id"):
                    increment_play_count(slot["id"])

            # Cooldown breathing screen — no camera, this is recovery
            cooldown_secs = 5 if self.quick_mode else COOLDOWN_SECONDS
            self._play(
                message=COOLDOWN_MESSAGE,
                min_watch=cooldown_secs,
                tier=1,
                title="Breathe",
                camera=False,
            )

        log_chain_event(reason, slots_played, True, start_slot)

    def _play(self, video_path=None, message=None, min_watch=10, tier=1,
              title="", camera=True):
        """Spawn a video_player.py subprocess and block until it exits."""
        cmd = [
            sys.executable, PLAYER_SCRIPT,
            "--min-watch", str(min_watch),
            "--tier", str(tier),
            "--title", title,
        ]

        if camera:
            cmd.append("--camera")

        if video_path and os.path.exists(video_path):
            cmd.extend(["--video", video_path])
        elif message:
            cmd.extend(["--message", message])

        proc = subprocess.Popen(cmd)
        proc.wait()


def list_slots():
    init_db()
    seed_default_video_slots()
    slots = get_video_slots(start_from=1)

    if not slots:
        print("No video slots configured.")
        return

    print(f"\n  Video Confrontation Chain — {len(slots)} slot(s)\n")
    print(f"  {'#':<4} {'Title':<22} {'Source':<14} {'Watch':<8} {'Tier':<6} {'Plays'}")
    print(f"  {'—'*4} {'—'*22} {'—'*14} {'—'*8} {'—'*6} {'—'*6}")

    for s in slots:
        has_video = "video" if s.get("file_path") and os.path.exists(s["file_path"] or "") else s.get("source", "default")
        print(f"  {s['slot_order']:<4} {(s.get('title') or '—'):<22} {has_video:<14} {s['min_watch_seconds']}s{'':<4} {s['tier']:<6} {s['play_count']}")

    print(f"\n  Videos directory: {VIDEOS_DIR}")
    print()


def main():
    parser = argparse.ArgumentParser(description="LockIn Video Chain Manager")
    parser.add_argument("--reason", default="manual_test", help="Trigger reason")
    parser.add_argument("--init", action="store_true", help="Init DB and seed defaults only")
    parser.add_argument("--list", action="store_true", help="List configured slots")
    parser.add_argument("--quick", action="store_true", help="Quick test (3s per slot)")
    args = parser.parse_args()

    if args.list:
        list_slots()
        return

    if args.init:
        init_db()
        seed_default_video_slots()
        ensure_video_dir()
        print(f"Initialized. Videos dir: {VIDEOS_DIR}")
        slots = get_video_slots()
        print(f"Slots configured: {len(slots)}")
        return

    manager = ChainManager(quick_mode=args.quick)
    print(f"Triggering chain (reason: {args.reason})...")
    manager.trigger(reason=args.reason)
    print("Chain complete.")


if __name__ == "__main__":
    main()
