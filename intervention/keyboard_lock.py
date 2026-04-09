#!/usr/bin/env python3
"""
LockIn — Keyboard Lock

Disables system keyboard shortcuts (Alt+Tab, Super, terminal, etc.)
during video confrontation playback. Restores them when done.

Safety:
  - Saves original values to a backup file before disabling
  - On crash, the backup file persists so next run can restore
  - Signal handlers ensure cleanup on SIGTERM/SIGINT
  - Context manager for clean lock/unlock

Usage:
    with KeyboardLock() as lock:
        # Alt+Tab, Super, etc. are disabled here
        run_video_player()
    # Automatically restored

    # Or manually:
    lock = KeyboardLock()
    lock.lock()
    ...
    lock.unlock()

    # Crash recovery:
    KeyboardLock.restore_if_crashed()
"""

import subprocess
import json
import os
import signal
import atexit
import pwd

# When running as root, we need to target the desktop user's GNOME session
_REAL_USER = os.environ.get("SUDO_USER", os.environ.get("USER", ""))
_REAL_HOME = pwd.getpwnam(_REAL_USER).pw_dir if _REAL_USER else os.path.expanduser("~")
_REAL_UID = pwd.getpwnam(_REAL_USER).pw_uid if _REAL_USER else os.getuid()

BACKUP_FILE = os.path.join(_REAL_HOME, ".config", "lockin", ".keybindings_backup")

# schema, key, disabled_value
# For array keys: @as [] (empty array)
# For string keys: '' (empty string)
KEYBINDINGS = [
    ("org.gnome.desktop.wm.keybindings", "switch-windows", "@as []"),
    ("org.gnome.desktop.wm.keybindings", "switch-windows-backward", "@as []"),
    ("org.gnome.desktop.wm.keybindings", "switch-applications", "@as []"),
    ("org.gnome.desktop.wm.keybindings", "switch-applications-backward", "@as []"),
    ("org.gnome.desktop.wm.keybindings", "panel-main-menu", "@as []"),
    ("org.gnome.desktop.wm.keybindings", "activate-window-menu", "@as []"),
    ("org.gnome.mutter", "overlay-key", "''"),
    ("org.gnome.settings-daemon.plugins.media-keys", "terminal", "@as []"),
    ("org.gnome.shell.keybindings", "toggle-overview", "@as []"),
]


def _build_gsettings_cmd(action, schema, key, value=None):
    """Build a gsettings command, wrapping with sudo -u if running as root."""
    cmd = ["gsettings", action, schema, key]
    if value is not None:
        cmd.append(value)

    if os.getuid() == 0 and _REAL_USER:
        # Running as root — run gsettings as the desktop user with their dbus
        dbus_addr = f"unix:path=/run/user/{_REAL_UID}/bus"
        cmd = [
            "sudo", "-u", _REAL_USER,
            f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
        ] + cmd

    return cmd


def _gsettings_get(schema, key):
    try:
        r = subprocess.run(
            _build_gsettings_cmd("get", schema, key),
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _gsettings_set(schema, key, value):
    try:
        subprocess.run(
            _build_gsettings_cmd("set", schema, key, value),
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


class KeyboardLock:

    def __init__(self):
        self._locked = False

    def lock(self):
        """Save current keybindings and disable them."""
        if self._locked:
            return

        saved = {}
        for schema, key, _ in KEYBINDINGS:
            val = _gsettings_get(schema, key)
            if val is not None:
                saved[f"{schema} {key}"] = val

        # Persist backup to disk (crash recovery)
        os.makedirs(os.path.dirname(BACKUP_FILE), exist_ok=True)
        with open(BACKUP_FILE, "w") as f:
            json.dump(saved, f)

        # Disable all
        for schema, key, disabled in KEYBINDINGS:
            _gsettings_set(schema, key, disabled)

        self._locked = True

        # Safety: restore on unexpected exit
        atexit.register(self.unlock)
        signal.signal(signal.SIGTERM, lambda *_: self._signal_cleanup())
        signal.signal(signal.SIGINT, lambda *_: self._signal_cleanup())

    def unlock(self):
        """Restore keybindings from backup."""
        if not self._locked:
            return
        self._restore_from_backup()
        self._locked = False

    def _restore_from_backup(self):
        if not os.path.exists(BACKUP_FILE):
            return
        try:
            with open(BACKUP_FILE) as f:
                saved = json.load(f)
            for full_key, value in saved.items():
                schema, key = full_key.rsplit(" ", 1)
                _gsettings_set(schema, key, value)
            os.remove(BACKUP_FILE)
        except Exception:
            pass

    def _signal_cleanup(self):
        self.unlock()
        raise SystemExit(0)

    @staticmethod
    def restore_if_crashed():
        """Call on startup to restore keybindings if a previous run crashed."""
        if os.path.exists(BACKUP_FILE):
            lock = KeyboardLock()
            lock._locked = True
            lock.unlock()
            return True
        return False

    def __enter__(self):
        self.lock()
        return self

    def __exit__(self, *args):
        self.unlock()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--restore":
        if KeyboardLock.restore_if_crashed():
            print("Restored keybindings from crash backup.")
        else:
            print("No backup found — keybindings are fine.")
    elif len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Locking keyboard shortcuts for 5 seconds...")
        with KeyboardLock():
            import time
            for i in range(5, 0, -1):
                print(f"  Try Alt+Tab now... restoring in {i}s")
                time.sleep(1)
        print("Restored. Alt+Tab should work again.")
    else:
        print("Usage:")
        print("  python3 keyboard_lock.py --test     # Lock for 5s to test")
        print("  python3 keyboard_lock.py --restore  # Restore from crash backup")
