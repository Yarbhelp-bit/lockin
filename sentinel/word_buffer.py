"""
LockIn — Rolling Word Buffer

Translates evdev keycodes into characters and maintains a rolling
text buffer. Feeds each new character to the Aho-Corasick matcher
and returns any blocklist matches.

Privacy: the buffer is in-memory only, max 100 chars, and is
cleared every 30 seconds. Raw keystrokes never touch disk.
"""

import time
import evdev

from sentinel.blocklist import AhoCorasick, build_default_matcher

# evdev keycode → character mapping (US QWERTY)
# Only lowercase — shift state tracked separately
_KEYMAP = {
    evdev.ecodes.KEY_Q: 'q', evdev.ecodes.KEY_W: 'w', evdev.ecodes.KEY_E: 'e',
    evdev.ecodes.KEY_R: 'r', evdev.ecodes.KEY_T: 't', evdev.ecodes.KEY_Y: 'y',
    evdev.ecodes.KEY_U: 'u', evdev.ecodes.KEY_I: 'i', evdev.ecodes.KEY_O: 'o',
    evdev.ecodes.KEY_P: 'p', evdev.ecodes.KEY_A: 'a', evdev.ecodes.KEY_S: 's',
    evdev.ecodes.KEY_D: 'd', evdev.ecodes.KEY_F: 'f', evdev.ecodes.KEY_G: 'g',
    evdev.ecodes.KEY_H: 'h', evdev.ecodes.KEY_J: 'j', evdev.ecodes.KEY_K: 'k',
    evdev.ecodes.KEY_L: 'l', evdev.ecodes.KEY_Z: 'z', evdev.ecodes.KEY_X: 'x',
    evdev.ecodes.KEY_C: 'c', evdev.ecodes.KEY_V: 'v', evdev.ecodes.KEY_B: 'b',
    evdev.ecodes.KEY_N: 'n', evdev.ecodes.KEY_M: 'm',
    # Numbers
    evdev.ecodes.KEY_1: '1', evdev.ecodes.KEY_2: '2', evdev.ecodes.KEY_3: '3',
    evdev.ecodes.KEY_4: '4', evdev.ecodes.KEY_5: '5', evdev.ecodes.KEY_6: '6',
    evdev.ecodes.KEY_7: '7', evdev.ecodes.KEY_8: '8', evdev.ecodes.KEY_9: '9',
    evdev.ecodes.KEY_0: '0',
    # Punctuation that appears in URLs/search terms
    evdev.ecodes.KEY_DOT: '.', evdev.ecodes.KEY_SLASH: '/',
    evdev.ecodes.KEY_MINUS: '-', evdev.ecodes.KEY_EQUAL: '=',
    evdev.ecodes.KEY_SEMICOLON: ';', evdev.ecodes.KEY_APOSTROPHE: "'",
    evdev.ecodes.KEY_COMMA: ',',
}

# Keys that break word context (reset buffer)
_BREAK_KEYS = {
    evdev.ecodes.KEY_ENTER, evdev.ecodes.KEY_TAB,
    evdev.ecodes.KEY_ESC,
}

BUFFER_MAX = 100
BUFFER_CLEAR_INTERVAL = 30  # seconds


class WordBuffer:
    """
    Rolling character buffer that feeds an Aho-Corasick matcher.

    Usage:
        buf = WordBuffer()
        matches = buf.feed_key(keycode)  # returns list of (pattern, category) or []
    """

    def __init__(self, matcher=None):
        self._buffer = ""
        self._matcher = matcher or build_default_matcher()
        self._last_clear = time.time()
        self._shift_held = False

    def feed_key(self, keycode, key_state):
        """
        Process a key event. Returns list of (pattern, category) matches, or [].

        keycode: evdev keycode (e.g. evdev.ecodes.KEY_P)
        key_state: 1 = press, 0 = release, 2 = repeat
        """
        # Track shift state
        if keycode in (evdev.ecodes.KEY_LEFTSHIFT, evdev.ecodes.KEY_RIGHTSHIFT):
            self._shift_held = (key_state != 0)
            return []

        # Only process key presses (not releases or repeats)
        if key_state != 1:
            return []

        # Periodic clear for privacy
        now = time.time()
        if now - self._last_clear > BUFFER_CLEAR_INTERVAL:
            self._buffer = ""
            self._last_clear = now

        # Break keys reset the buffer
        if keycode in _BREAK_KEYS:
            self._buffer = ""
            return []

        # Backspace
        if keycode == evdev.ecodes.KEY_BACKSPACE:
            self._buffer = self._buffer[:-1]
            return []

        # Space acts as a word separator (keep it in buffer for multi-word matches)
        if keycode == evdev.ecodes.KEY_SPACE:
            self._buffer += " "
            if len(self._buffer) > BUFFER_MAX:
                self._buffer = self._buffer[-BUFFER_MAX:]
            return []

        # Translate keycode to character
        char = _KEYMAP.get(keycode)
        if char is None:
            return []

        # Append to buffer
        self._buffer += char
        if len(self._buffer) > BUFFER_MAX:
            self._buffer = self._buffer[-BUFFER_MAX:]

        # Check for matches in current buffer
        matches = self._matcher.search(self._buffer)
        if matches:
            # Return unique (pattern, category) pairs
            seen = set()
            results = []
            for _, pattern, category in matches:
                key = (pattern, category)
                if key not in seen:
                    seen.add(key)
                    results.append(key)
            return results

        return []

    def clear(self):
        """Manually clear the buffer."""
        self._buffer = ""

    @property
    def current(self):
        """Current buffer contents (for debugging only — never persist this)."""
        return self._buffer
