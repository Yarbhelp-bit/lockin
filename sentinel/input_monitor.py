#!/usr/bin/env python3
"""
LockIn — Input Sentinel

Kernel-level keystroke monitor that catches blocked words typed
ANYWHERE on the system (browser, terminal, any app). When a
blocklist match is detected, triggers the video confrontation chain.

Reads raw evdev events from /dev/input/event* keyboard devices.
Requires root or membership in the 'input' group.

Privacy:
  - Raw keystrokes are NEVER written to disk
  - Only match events (word + category) are logged
  - The rolling buffer is in-memory only (max 100 chars)

Usage:
    sudo python3 input_monitor.py              # run the sentinel
    sudo python3 input_monitor.py --dry-run    # detect but don't trigger chain
    sudo python3 input_monitor.py --verbose    # show buffer state (debug)
"""

import sys
import os
import time
import signal
import subprocess
import argparse
import evdev
import select

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from sentinel.word_buffer import WordBuffer
from monitor.db import init_db, log_chain_event

CHAIN_SCRIPT = os.path.join(_ROOT, "intervention", "video_chain.py")

# Cooldown: don't re-trigger chain within this window
TRIGGER_COOLDOWN = 300  # 5 minutes

# Cross-watch: check guard every 30 seconds
GUARD_CHECK_INTERVAL = 30


def find_keyboards():
    """Find all keyboard input devices."""
    keyboards = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities().get(1, [])  # EV_KEY
            # A real keyboard has letter keys Q through M (keycodes 16-50)
            has_letters = any(16 <= k <= 50 for k in caps)
            if has_letters:
                keyboards.append(dev)
        except (PermissionError, OSError):
            continue
    return keyboards


class InputSentinel:
    """
    Monitors keyboard input system-wide and triggers interventions
    when blocklist patterns are detected.
    """

    def __init__(self, dry_run=False, verbose=False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.buffer = WordBuffer()
        self.keyboards = []
        self.last_trigger = 0
        self.last_guard_check = 0
        self._running = False

    def start(self):
        """Start monitoring keyboard input."""
        init_db()

        self.keyboards = find_keyboards()
        if not self.keyboards:
            print("ERROR: No keyboard devices found.")
            print("Make sure you're running as root or in the 'input' group.")
            print(f"  sudo usermod -aG input {os.environ.get('USER', 'your_user')}")
            sys.exit(1)

        print(f"LockIn Sentinel active — monitoring {len(self.keyboards)} keyboard(s):")
        for kb in self.keyboards:
            print(f"  {kb.path}: {kb.name}")
        if self.dry_run:
            print("  (dry-run mode — will detect but not trigger chain)")
        print()

        self._running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        self._event_loop()

    def _check_guard(self):
        """Cross-watch: verify the guard daemon is alive. Restart if dead."""
        now = time.time()
        if now - self.last_guard_check < GUARD_CHECK_INTERVAL:
            return
        self.last_guard_check = now

        try:
            r = subprocess.run(
                ["pgrep", "-f", "lockin-guard"],
                capture_output=True, timeout=5,
            )
            if r.returncode != 0:
                # Guard is dead — revive it
                print("  CROSS-WATCH: guard daemon dead. Restarting.")
                subprocess.run(
                    ["systemctl", "start", "lockin-guard"],
                    capture_output=True, timeout=10,
                )
        except Exception:
            pass

    def _event_loop(self):
        """Main event loop — reads from all keyboards using select()."""
        devices = {kb.fd: kb for kb in self.keyboards}

        while self._running:
            # Cross-watch the guard daemon
            self._check_guard()

            try:
                r, _, _ = select.select(devices.keys(), [], [], 1.0)
            except (ValueError, OSError):
                # Device disconnected
                break

            for fd in r:
                dev = devices.get(fd)
                if dev is None:
                    continue

                try:
                    for event in dev.read():
                        if event.type != evdev.ecodes.EV_KEY:
                            continue
                        self._handle_key(event.code, event.value)
                except (OSError, IOError):
                    # Device disconnected — remove and continue
                    print(f"Device disconnected: {dev.name}")
                    del devices[fd]
                    if not devices:
                        print("All keyboards disconnected. Exiting.")
                        self._running = False

    def _handle_key(self, keycode, key_state):
        """Process a single key event through the word buffer."""
        matches = self.buffer.feed_key(keycode, key_state)

        if self.verbose and key_state == 1:
            print(f"  buffer: [{self.buffer.current}]", end='\r')

        if not matches:
            return

        now = time.time()
        for pattern, category in matches:
            print(f"\n  MATCH: '{pattern}' (category: {category})")

            if now - self.last_trigger < TRIGGER_COOLDOWN:
                remaining = int(TRIGGER_COOLDOWN - (now - self.last_trigger))
                print(f"  Cooldown active ({remaining}s remaining) — skipping trigger")
                continue

            self.last_trigger = now
            self.buffer.clear()

            if self.dry_run:
                print("  [dry-run] Would trigger video chain")
            else:
                print("  Triggering video confrontation chain...")
                self._trigger_chain(pattern, category)

    def _trigger_chain(self, pattern, category):
        """Launch the video confrontation chain as a subprocess."""
        reason = f"sentinel:{category}:{pattern}"
        try:
            real_user = os.environ.get("SUDO_USER", os.environ.get("USER"))
            real_uid = os.environ.get("SUDO_UID")

            if real_uid and os.getuid() == 0:
                # Running as root — need to launch GUI as the desktop user
                # with access to their Wayland/X11/dbus session
                uid = real_uid
                runtime_dir = f"/run/user/{uid}"
                dbus_addr = f"unix:path={runtime_dir}/bus"
                wayland = f"wayland-0"

                env_vars = [
                    f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
                    f"WAYLAND_DISPLAY={wayland}",
                    f"XDG_RUNTIME_DIR={runtime_dir}",
                    f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
                    f"HOME=/home/{real_user}",
                    f"SUDO_USER={real_user}",
                    f"SUDO_UID={uid}",
                ]

                cmd = [
                    "sudo", "-u", real_user,
                ] + env_vars + [
                    sys.executable, CHAIN_SCRIPT,
                    "--reason", reason,
                ]
            else:
                cmd = [sys.executable, CHAIN_SCRIPT, "--reason", reason]

            subprocess.Popen(cmd)
        except Exception as e:
            print(f"  ERROR launching chain: {e}")

    def _shutdown(self, signum=None, frame=None):
        print("\nSentinel shutting down.")
        self._running = False
        for kb in self.keyboards:
            try:
                kb.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="LockIn Input Sentinel")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect matches but don't trigger chain")
    parser.add_argument("--verbose", action="store_true",
                        help="Show buffer state (debug)")
    args = parser.parse_args()

    sentinel = InputSentinel(dry_run=args.dry_run, verbose=args.verbose)
    sentinel.start()


if __name__ == "__main__":
    main()
