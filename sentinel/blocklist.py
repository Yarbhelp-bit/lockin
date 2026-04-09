"""
LockIn — Blocklist Engine

Fast multi-pattern matching against a rolling text buffer.
Uses Aho-Corasick automaton for O(n) matching against hundreds
of patterns simultaneously.

Patterns are organized by category so interventions can be
context-aware (explicit content triggers harder than social media).
"""


class AhoCorasick:
    """
    Aho-Corasick automaton for simultaneous multi-pattern string matching.
    Build once with all patterns, then feed characters one at a time.
    Returns matches as (pattern, category) tuples.
    """

    def __init__(self):
        self._goto = [{}]       # goto function: state → {char → state}
        self._fail = [0]        # failure function
        self._output = [[]]     # output function: state → [(pattern, category)]
        self._built = False

    def add(self, pattern, category="default"):
        """Add a pattern to the automaton (must call build() after all adds)."""
        pattern = pattern.lower()
        state = 0
        for ch in pattern:
            if ch not in self._goto[state]:
                self._goto[state][ch] = len(self._goto)
                self._goto.append({})
                self._fail.append(0)
                self._output.append([])
            state = self._goto[state][ch]
        self._output[state].append((pattern, category))
        self._built = False

    def build(self):
        """Construct failure links (BFS). Must call after adding all patterns."""
        from collections import deque
        queue = deque()

        # Depth-1 states: failure → root
        for ch, s in self._goto[0].items():
            self._fail[s] = 0
            queue.append(s)

        # BFS
        while queue:
            r = queue.popleft()
            for ch, s in self._goto[r].items():
                queue.append(s)
                state = self._fail[r]
                while state != 0 and ch not in self._goto[state]:
                    state = self._fail[state]
                self._fail[s] = self._goto[state].get(ch, 0)
                if self._fail[s] == s:
                    self._fail[s] = 0
                self._output[s] = self._output[s] + self._output[self._fail[s]]

        self._built = True

    def search(self, text):
        """Search text for all pattern matches. Returns [(end_pos, pattern, category)]."""
        if not self._built:
            self.build()

        state = 0
        results = []
        for i, ch in enumerate(text.lower()):
            while state != 0 and ch not in self._goto[state]:
                state = self._fail[state]
            state = self._goto[state].get(ch, 0)
            for pattern, category in self._output[state]:
                results.append((i, pattern, category))
        return results


# ── Default blocklist ──────────────────────────────────────────────────

BLOCKLIST = {
    "explicit": [
        # Core terms
        "porn", "pornhub", "xvideos", "xhamster", "xnxx", "redtube",
        "youporn", "tube8", "spankbang", "brazzers", "bangbros",
        "onlyfans", "fansly", "chaturbate", "stripchat", "livejasmin",
        "nudes", "hentai", "rule34", "nhentai", "hanime",
        "xxxvideos", "porntube", "beeg", "eporner",
        # Cam / chat
        "omegle", "ometv", "chatroulette", "camsurf", "chatrandom",
        "dirtyroulette", "camsoda", "bongacams", "myfreecams",
        # Subreddits / keywords
        "nsfw", "gonewild", "r/gonewild", "leaked nudes",
    ],

    "social_doom": [
        "tiktok.com", "instagram.com/reels", "youtube.com/shorts",
    ],

    "gambling": [
        "draftkings", "fanduel", "betway", "bovada", "bet365",
        "pokerstars", "stake.com",
    ],
}


def build_default_matcher():
    """Build an AhoCorasick matcher with the default blocklist."""
    ac = AhoCorasick()
    for category, patterns in BLOCKLIST.items():
        for pattern in patterns:
            ac.add(pattern, category)
    ac.build()
    return ac
