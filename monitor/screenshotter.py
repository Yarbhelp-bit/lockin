"""
Lock In — Screenshot capture module
Takes periodic screenshots during focus sessions using Wayland-compatible methods.
Tries multiple capture backends in order: grim, gnome-screenshot, freedesktop portal, PIL.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from PIL import Image

from . import db

log = logging.getLogger("lockin.screenshotter")

SCREENSHOT_INTERVAL = 30  # seconds
JPEG_QUALITY = 50


class Screenshotter:
    """Periodically captures screenshots and logs them to the database."""

    def __init__(self, session_id: int, stop_event: threading.Event):
        self.session_id = session_id
        self.stop_event = stop_event
        self._thread = threading.Thread(
            target=self._run, name="screenshotter", daemon=True
        )

    def start(self):
        self._thread.start()
        log.info("Screenshotter started (interval=%ds)", SCREENSHOT_INTERVAL)

    def join(self, timeout=None):
        self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------ loop

    def _run(self):
        while not self.stop_event.is_set():
            try:
                filepath = self._capture()
                if filepath:
                    active_window = self._get_active_window_title()
                    db.log_screenshot(
                        self.session_id,
                        filepath,
                        active_window=active_window,
                    )
                    log.debug("Screenshot saved: %s", filepath)
                else:
                    log.warning("All screenshot methods failed")
            except Exception:
                log.exception("Screenshot capture error")

            # Sleep in small increments so we can react to stop_event quickly
            for _ in range(SCREENSHOT_INTERVAL):
                if self.stop_event.is_set():
                    return
                time.sleep(1)

    # --------------------------------------------------------------- capture

    def _capture(self) -> str | None:
        """Try capture methods in order. Returns final JPEG path or None."""
        ts = int(time.time())
        final_path = os.path.join(
            db.SCREENSHOTS_DIR,
            f"session_{self.session_id}_{ts}.jpg",
        )

        # Each method should write a file (any format) and return its path,
        # or return None on failure.
        for method in (
            self._try_grim,
            self._try_gnome_screenshot,
            self._try_portal,
            self._try_pil,
        ):
            try:
                raw_path = method()
                if raw_path and os.path.isfile(raw_path):
                    self._convert_to_jpeg(raw_path, final_path)
                    # Clean up temp file if it differs from final
                    if raw_path != final_path:
                        try:
                            os.unlink(raw_path)
                        except OSError:
                            pass
                    return final_path
            except Exception:
                log.debug("Capture method %s failed", method.__name__, exc_info=True)
                continue

        return None

    # ----- individual backends -----

    def _try_grim(self) -> str | None:
        if not shutil.which("grim"):
            return None
        tmp = self._tmp_path("png")
        r = subprocess.run(["grim", tmp], capture_output=True, timeout=10)
        return tmp if r.returncode == 0 else None

    def _try_gnome_screenshot(self) -> str | None:
        if not shutil.which("gnome-screenshot"):
            return None
        tmp = self._tmp_path("png")
        r = subprocess.run(
            ["gnome-screenshot", "--file", tmp],
            capture_output=True,
            timeout=10,
        )
        return tmp if r.returncode == 0 else None

    def _try_portal(self) -> str | None:
        """Use the freedesktop Screenshot portal via gdbus.

        The portal is async: we invoke the method, then poll for the result
        file.  The portal normally writes the screenshot to a temp location
        and returns a file:// URI in its Response signal.  We parse the URI
        from the gdbus output (GNOME's portal implementation often returns
        synchronously when permission has been granted).
        """
        if not shutil.which("gdbus"):
            return None

        token = f"lockin_{uuid.uuid4().hex[:8]}"
        cmd = [
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.portal.Desktop",
            "--object-path", "/org/freedesktop/portal/desktop",
            "--method", "org.freedesktop.portal.Screenshot.Screenshot",
            "", f'{{"handle_token": <"{token}">}}',
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
        except subprocess.TimeoutExpired:
            return None

        if result.returncode != 0:
            return None

        # Try to get the URI from the portal response.
        # The portal may write the screenshot asynchronously. We listen for
        # the Response signal on the request object.
        request_path = f"/org/freedesktop/portal/desktop/request/{os.getuid()}/{token}"

        # Poll via gdbus for the Response signal (up to 5s)
        uri = self._poll_portal_response(request_path, token)
        if uri and uri.startswith("file://"):
            path = uri[7:]  # strip file://
            if os.path.isfile(path):
                return path

        # Fallback: check if the portal response was embedded in stdout
        uri = self._parse_uri_from_output(result.stdout)
        if uri and uri.startswith("file://"):
            path = uri[7:]
            if os.path.isfile(path):
                return path

        return None

    def _poll_portal_response(self, request_path: str, token: str) -> str | None:
        """Use gdbus monitor to wait for the portal Response signal."""
        try:
            proc = subprocess.Popen(
                [
                    "gdbus", "monitor", "--session",
                    "--dest", "org.freedesktop.portal.Desktop",
                    "--object-path", request_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # Wait up to 5 seconds for a response
            deadline = time.monotonic() + 5
            lines = []
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                # Read available output (non-blocking-ish via timeout)
                import select
                ready, _, _ = select.select([proc.stdout], [], [], 0.5)
                if ready:
                    line = proc.stdout.readline()
                    if line:
                        lines.append(line)
                        if "file://" in line:
                            break
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

            combined = "\n".join(lines)
            return self._parse_uri_from_output(combined)
        except Exception:
            return None

    def _parse_uri_from_output(self, text: str) -> str | None:
        """Extract a file:// URI from gdbus output text."""
        import re
        match = re.search(r"file://[^\s'\">,)]+", text)
        return match.group(0) if match else None

    def _try_pil(self) -> str | None:
        """Last resort: PIL ImageGrab (usually fails on Wayland)."""
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            tmp = self._tmp_path("png")
            img.save(tmp)
            return tmp
        except Exception:
            return None

    # ----- helpers -----

    @staticmethod
    def _tmp_path(ext: str) -> str:
        return os.path.join(tempfile.gettempdir(), f"lockin_cap_{uuid.uuid4().hex[:8]}.{ext}")

    @staticmethod
    def _convert_to_jpeg(src: str, dst: str):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        img = Image.open(src)
        img = img.convert("RGB")
        img.save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True)

    @staticmethod
    def _get_active_window_title() -> str:
        """Best-effort active window title for screenshot metadata."""
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
                import re
                m = re.search(r"'([^']*)'", r.stdout.split(",", 1)[-1])
                if m:
                    return m.group(1)
        except Exception:
            pass
        return "unknown"
