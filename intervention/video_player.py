#!/usr/bin/env python3
"""
LockIn — Video Confrontation Player

Standalone full-screen GTK4 window that plays a video or displays
a confrontation message. Split-screen: left = confrontation,
right = YOUR FACE via live webcam. Cannot be closed until the
minimum watch time has passed.

Usage:
    python3 video_player.py --message "Stop." --min-watch 10 --tier 1
    python3 video_player.py --message "Stop." --camera --tier 3
    python3 video_player.py --video ~/vid.mp4 --camera --min-watch 15
    python3 video_player.py --camera-only --min-watch 10   # just the mirror
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gdk, GLib, Gst, GdkPixbuf
import argparse
import os
import time
import glob

Gst.init(None)

# Try to import GstApp for try_pull_sample; fall back to emit()
try:
    gi.require_version('GstApp', '1.0')
    from gi.repository import GstApp
    _HAS_GSTAPP = True
except (ValueError, ImportError):
    _HAS_GSTAPP = False


CSS = b"""
window.player-window {
    background-color: #000000;
}

/* --- Message tiers --- */

.message-tier1 {
    color: #e0e0e0;
    font-size: 48px;
    font-weight: 600;
    letter-spacing: 2px;
}

.message-tier2 {
    color: #ffffff;
    font-size: 48px;
    font-weight: 700;
    letter-spacing: 1px;
}

.message-tier3 {
    color: #ff1a1a;
    font-size: 54px;
    font-weight: 900;
    letter-spacing: 2px;
}

/* --- Layout --- */

.left-pane {
    background-color: #000000;
}

.right-pane {
    background-color: #0a0a0a;
}

.camera-label {
    color: rgba(255, 255, 255, 0.08);
    font-size: 13px;
    font-weight: 400;
    letter-spacing: 6px;
    padding: 16px;
}

/* --- Scrim overlays (darkens camera so text is readable) --- */

.scrim-tier1 {
    background-color: rgba(0, 0, 0, 0.55);
}

.scrim-tier2 {
    background-color: rgba(0, 0, 0, 0.50);
}

.scrim-tier3 {
    background-color: rgba(0, 0, 0, 0.40);
}

.slot-title {
    color: rgba(255, 255, 255, 0.15);
    font-size: 14px;
    font-weight: 400;
    letter-spacing: 4px;
    padding: 24px;
}

.countdown {
    color: rgba(255, 255, 255, 0.2);
    font-size: 22px;
    font-weight: 300;
    padding-bottom: 12px;
}

.dismiss-btn {
    background: rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    padding: 10px 36px;
    font-size: 14px;
    font-weight: 400;
    margin-bottom: 48px;
    transition: all 200ms ease;
}

.dismiss-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.6);
    border-color: rgba(255, 255, 255, 0.25);
}

.no-camera-text {
    color: rgba(255, 255, 255, 0.15);
    font-size: 18px;
    font-weight: 300;
}
"""


# ---------------------------------------------------------------------------
# Camera feed via GStreamer → Gtk.Picture
# ---------------------------------------------------------------------------

class CameraFeed:
    """Live webcam feed rendered into a Gtk.Picture widget."""

    def __init__(self, picture_widget, tier=1):
        self.picture = picture_widget
        self.pipeline = None
        self.appsink = None
        self._running = False

        # Detect camera device
        device = self._find_camera()
        if not device:
            return

        # Build pipeline: capture → flip (mirror) → desaturate → appsink
        # Slight desaturation + dim to make it feel heavy, not fun
        brightness = {1: -0.1, 2: -0.15, 3: -0.25}.get(tier, -0.1)
        saturation = {1: 0.7, 2: 0.5, 3: 0.3}.get(tier, 0.7)

        pipeline_str = (
            f"v4l2src device={device} ! "
            "videoconvert ! videoscale ! "
            "video/x-raw,format=RGB,width=640,height=480 ! "
            "videoflip method=horizontal-flip ! "
            f"videobalance brightness={brightness} saturation={saturation} ! "
            "appsink name=sink max-buffers=2 drop=true sync=false"
        )

        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
            self.appsink = self.pipeline.get_by_name("sink")
            self.pipeline.set_state(Gst.State.PLAYING)
            self._running = True
            # Poll frames on GTK main thread (~20fps)
            GLib.timeout_add(50, self._pull_frame)
        except Exception:
            self._running = False

    @staticmethod
    def _find_camera():
        """Find the first working camera device."""
        devices = sorted(glob.glob("/dev/video*"))
        for dev in devices:
            if os.access(dev, os.R_OK):
                # Quick test: can GStreamer open it?
                test = Gst.parse_launch(
                    f"v4l2src device={dev} num-buffers=1 ! fakesink"
                )
                test.set_state(Gst.State.PLAYING)
                # Wait briefly for state change
                ret = test.get_state(Gst.SECOND)
                test.set_state(Gst.State.NULL)
                if ret[0] == Gst.StateChangeReturn.SUCCESS:
                    return dev
        return None

    def _pull_frame(self):
        if not self._running or not self.appsink:
            return False

        try:
            if _HAS_GSTAPP:
                sample = self.appsink.try_pull_sample(0)
            else:
                sample = self.appsink.emit("try-pull-sample", 0)
        except Exception:
            return True

        if sample is None:
            return True

        buf = sample.get_buffer()
        caps = sample.get_caps()
        struct = caps.get_structure(0)
        width = struct.get_value("width")
        height = struct.get_value("height")

        success, mapinfo = buf.map(Gst.MapFlags.READ)
        if not success:
            return True

        # Copy data so we can unmap immediately
        data = bytes(mapinfo.data)
        buf.unmap(mapinfo)

        pixbuf = GdkPixbuf.Pixbuf.new_from_data(
            data, GdkPixbuf.Colorspace.RGB, False, 8,
            width, height, width * 3,
        )
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        self.picture.set_paintable(texture)

        return True  # keep polling

    @property
    def is_active(self):
        return self._running

    def stop(self):
        self._running = False
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class VideoPlayerWindow(Gtk.ApplicationWindow):

    def __init__(self, app, video_path, message, title, min_watch, tier,
                 use_camera=False, camera_only=False):
        super().__init__(application=app)

        self.app = app
        self.min_watch = min_watch
        self.start_time = time.time()
        self.can_dismiss = False
        self.camera_feed = None

        self.add_css_class("player-window")
        self.set_decorated(False)
        self.fullscreen()

        self.connect("close-request", self._on_close_request)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctrl)

        # --- Build layout ---
        root_overlay = Gtk.Overlay()
        self.set_child(root_overlay)

        if camera_only:
            self.content = self._build_camera_only(tier)
        elif use_camera:
            self.content = self._build_split(video_path, message, tier)
        else:
            self.content = self._build_solo(video_path, message, tier)

        self.content.set_opacity(0)
        root_overlay.set_child(self.content)

        # Slot title — top left
        if title:
            title_label = Gtk.Label(label=title.upper())
            title_label.add_css_class("slot-title")
            title_label.set_halign(Gtk.Align.START)
            title_label.set_valign(Gtk.Align.START)
            root_overlay.add_overlay(title_label)

        # Bottom: countdown + dismiss
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        bottom.set_halign(Gtk.Align.CENTER)
        bottom.set_valign(Gtk.Align.END)

        self.countdown_label = Gtk.Label(label=str(min_watch))
        self.countdown_label.add_css_class("countdown")
        bottom.append(self.countdown_label)

        self.dismiss_btn = Gtk.Button(label="I understand")
        self.dismiss_btn.add_css_class("dismiss-btn")
        self.dismiss_btn.set_opacity(0)
        self.dismiss_btn.set_sensitive(False)
        self.dismiss_btn.connect("clicked", self._on_dismiss)
        bottom.append(self.dismiss_btn)

        root_overlay.add_overlay(bottom)

        # --- Animations ---
        self._fade_step = 0
        GLib.timeout_add(40, self._fade_in_content)
        GLib.timeout_add(1000, self._tick_countdown)

    # --- Layout builders ---

    def _build_solo(self, video_path, message, tier):
        """Original layout: centered content on dark background."""
        if video_path and os.path.exists(video_path):
            return self._make_video_widget(video_path)
        return self._make_text_widget(message or "Stop.", tier)

    def _build_split(self, video_path, message, tier):
        """
        Camera fills the screen. Confrontation text overlaid on top
        with a dark scrim. You read the message while staring at yourself.
        """
        overlay = Gtk.Overlay()

        # Background: full-screen camera feed
        camera_pane = self._make_camera_pane(tier)
        camera_pane.set_hexpand(True)
        camera_pane.set_vexpand(True)
        overlay.set_child(camera_pane)

        # Dark scrim over the camera so text is readable
        scrim = Gtk.Box()
        scrim.add_css_class(f"scrim-tier{tier}")
        scrim.set_hexpand(True)
        scrim.set_vexpand(True)
        overlay.add_overlay(scrim)

        # Text on top of scrim
        if video_path and os.path.exists(video_path):
            text_content = self._make_video_widget(video_path)
        else:
            text_content = self._make_text_widget(message or "Stop.", tier)
        text_content.set_halign(Gtk.Align.CENTER)
        text_content.set_valign(Gtk.Align.CENTER)
        overlay.add_overlay(text_content)

        return overlay

    def _build_camera_only(self, tier):
        """Full-screen camera — just you, staring at yourself."""
        return self._make_camera_pane(tier, full=True)

    def _make_text_widget(self, message, tier):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        label = Gtk.Label(label=message)
        label.set_wrap(True)
        label.set_max_width_chars(32)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_use_markup(False)

        tier_class = {1: "message-tier1", 2: "message-tier2", 3: "message-tier3"}
        label.add_css_class(tier_class.get(tier, "message-tier1"))

        box.append(label)
        return box

    def _make_video_widget(self, path):
        video = Gtk.Video.new_for_filename(path)
        video.set_autoplay(True)
        video.set_loop(True)
        return video

    def _make_camera_pane(self, tier, full=False):
        """Build the camera pane with live feed + subtle label."""
        pane = Gtk.Overlay()
        pane.add_css_class("right-pane")

        # Camera image widget
        self.camera_picture = Gtk.Picture()
        self.camera_picture.set_can_shrink(True)
        self.camera_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.camera_picture.set_hexpand(True)
        self.camera_picture.set_vexpand(True)
        pane.set_child(self.camera_picture)

        # Start camera feed
        self.camera_feed = CameraFeed(self.camera_picture, tier=tier)

        if not self.camera_feed.is_active:
            # No camera — show fallback text
            fallback = Gtk.Label(label="Look at yourself.")
            fallback.add_css_class("no-camera-text")
            fallback.set_halign(Gtk.Align.CENTER)
            fallback.set_valign(Gtk.Align.CENTER)
            pane.add_overlay(fallback)
        else:
            # Subtle label at top of camera pane
            cam_label = Gtk.Label(label="THIS IS YOU RIGHT NOW")
            cam_label.add_css_class("camera-label")
            cam_label.set_halign(Gtk.Align.CENTER)
            cam_label.set_valign(Gtk.Align.START)
            pane.add_overlay(cam_label)

        return pane

    # --- Animations ---

    def _fade_in_content(self):
        self._fade_step += 1
        opacity = min(1.0, self._fade_step / 60.0)
        self.content.set_opacity(opacity)
        return self._fade_step < 60

    def _fade_in_dismiss(self):
        current = self.dismiss_btn.get_opacity()
        if current >= 1.0:
            return False
        self.dismiss_btn.set_opacity(min(1.0, current + 0.04))
        return True

    # --- Countdown ---

    def _tick_countdown(self):
        elapsed = time.time() - self.start_time
        remaining = self.min_watch - elapsed

        if remaining <= 0:
            self.can_dismiss = True
            self.countdown_label.set_visible(False)
            self.dismiss_btn.set_sensitive(True)
            GLib.timeout_add(30, self._fade_in_dismiss)
            return False

        self.countdown_label.set_label(str(int(remaining)))
        return True

    # --- Event handlers ---

    def _on_close_request(self, window):
        if self.camera_feed:
            self.camera_feed.stop()
        if not self.can_dismiss:
            return True
        return False

    def _on_key(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Super_L, Gdk.KEY_Super_R):
            return True
        if keyval == Gdk.KEY_F4 and (state & Gdk.ModifierType.ALT_MASK):
            return True
        return False

    def _on_dismiss(self, btn):
        if self.camera_feed:
            self.camera_feed.stop()
        self.can_dismiss = True
        self.close()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class VideoPlayerApp(Gtk.Application):

    def __init__(self, video_path, message, title, min_watch, tier,
                 use_camera, camera_only):
        super().__init__(application_id=None)
        self.video_path = video_path
        self.message = message
        self.title_text = title
        self.min_watch = min_watch
        self.tier = tier
        self.use_camera = use_camera
        self.camera_only = camera_only

    def do_activate(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        win = VideoPlayerWindow(
            app=self,
            video_path=self.video_path,
            message=self.message,
            title=self.title_text,
            min_watch=self.min_watch,
            tier=self.tier,
            use_camera=self.use_camera,
            camera_only=self.camera_only,
        )
        win.present()


def main():
    parser = argparse.ArgumentParser(description="LockIn Video Confrontation Player")
    parser.add_argument("--video", default=None, help="Path to video file (MP4)")
    parser.add_argument("--message", default=None, help="Text message (fallback if no video)")
    parser.add_argument("--title", default="", help="Slot title shown subtly in corner")
    parser.add_argument("--min-watch", type=int, default=10, help="Seconds before dismiss")
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2, 3],
                        help="Visual intensity: 1=calm, 2=firm, 3=confrontation")
    parser.add_argument("--camera", action="store_true",
                        help="Split screen: show live webcam on the right")
    parser.add_argument("--camera-only", action="store_true",
                        help="Full screen camera only — just the mirror")
    args = parser.parse_args()

    if not args.video and not args.message and not args.camera_only:
        args.message = "Stop.\n\nWhat are you doing?"

    app = VideoPlayerApp(
        video_path=args.video,
        message=args.message,
        title=args.title,
        min_watch=args.min_watch,
        tier=args.tier,
        use_camera=args.camera or args.camera_only,
        camera_only=args.camera_only,
    )
    app.run([])


if __name__ == "__main__":
    main()
