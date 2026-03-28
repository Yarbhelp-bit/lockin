#!/usr/bin/env python3
"""
Lock In — Desktop Launcher
Opens the web GUI in a native desktop window using pywebview.
Falls back to browser if pywebview is not available.
"""

import os
import sys
import signal
import threading
import time
import webbrowser
import subprocess

PORT = 9999
HOST = "127.0.0.1"
WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")


def start_flask():
    """Start the Flask server in a background thread."""
    sys.path.insert(0, WEBAPP_DIR)
    from app import app
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


def main():
    # Start Flask in background thread
    server = threading.Thread(target=start_flask, daemon=True)
    server.start()

    # Wait for server to be ready
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/")
            break
        except Exception:
            time.sleep(0.1)

    url = f"http://{HOST}:{PORT}"

    # Try pywebview for native window
    try:
        import webview
        window = webview.create_window(
            "LOCK IN // Command Center",
            url,
            width=1400,
            height=900,
            min_size=(1100, 700),
            background_color="#06060a",
            text_select=True,
        )
        webview.start(gui="gtk")
    except ImportError:
        print(f"pywebview not installed. Opening in browser: {url}")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    except Exception as e:
        print(f"pywebview failed ({e}). Opening in browser: {url}")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
