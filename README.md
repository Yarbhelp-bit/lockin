# LOCK IN

**Unbypassable system-level focus lock for Linux.**

Block everything. No escape. Do the work.

Lock In combines kernel-level network blocking, behavioral monitoring, AI-powered analytics, and a game-like achievement system into one tool that forces you to focus.

---

## How It Works

When you start a session, Lock In applies **four layers of blocking** simultaneously:

1. **iptables firewall** — Blocks all HTTP/HTTPS/QUIC traffic except whitelisted domain IPs
2. **/etc/hosts** — Points 30+ distraction domains (YouTube, Reddit, Twitter, TikTok, etc.) to 127.0.0.1
3. **IPv6 disabled** — Prevents IPv6-based bypass attempts
4. **DNS lockdown** — Only allows the system resolver, blocks DoH/DoT providers

A **guard daemon** runs every 5 seconds to verify all protections are intact and re-applies them if tampered with. Session files and binaries are made immutable with `chattr +i`.

This affects **all browsers and all apps** — not just one browser extension.

---

## Features

### Command Center (Web GUI)
- Palantir-inspired dark interface with real-time session control
- Duration selection (15m, 25m, 45m, 1h, 1.5h, 2h)
- Allowed site management with persistent storage
- Live countdown timer with progress ring during active sessions
- Activity feed showing window switches, bypass attempts, distractions

### Behavioral Monitoring
Five background threads track your behavior during sessions:

| Monitor | Interval | What It Tracks |
|---------|----------|---------------|
| **Window Tracker** | 3s | Active window title, app name, productive vs distraction classification |
| **Keystroke Tracker** | 60s | Keyboard activity via `/proc/interrupts`, active typing periods |
| **Idle Detector** | continuous | Keyboard gaps > 2 minutes |
| **Screenshotter** | 30s | JPEG screenshots saved to disk with metadata |
| **Bypass Monitor** | 10s | iptables DROP events from `journalctl` |

### AI Analysis (Claude API)
- **Screenshot vision analysis** — Detects on-screen distractions with risk scoring
- **Session summaries** — Natural language recap with actionable recommendations
- **Daily insights** — AI coach reviews your day's sessions
- **Weekly reports** — Trend detection, distraction patterns, best/worst periods
- **Distraction pattern detection** — Time-of-day peaks, common distraction apps, session length correlations

All AI features are optional and fail gracefully. Local productivity/focus scores always work offline.

### Achievement System
20 achievements across 4 rarity tiers with XP rewards:

| Rarity | Achievements |
|--------|-------------|
| **Common** | First Lock, Operator (5 sessions), Sprint (15min), Hat Trick (3-day streak), Early Bird, Night Owl |
| **Rare** | Veteran (20 sessions), Marathon (2hr), High Score (90+ productivity), On Fire (7-day streak), Fortress (10 sessions 0 bypass), Dedicated (10hrs), Laser Focus (0 distractions), Comeback |
| **Epic** | Perfect Focus (100 score), Fortnight (14-day streak), Deep Work (5x 45min+ sessions) |
| **Legendary** | Centurion (100 sessions), Unstoppable (30-day streak), Obsessed (100hrs) |

### Leveling & Ranks
XP is earned per session: `duration_minutes × 10` with bonuses for high productivity (+50%), zero bypass (+25%), and high focus (+25%).

| Level | Rank |
|-------|------|
| 1–4 | RECRUIT |
| 5–9 | OPERATOR |
| 10–14 | AGENT |
| 15–19 | SPECIALIST |
| 20–24 | COMMANDER |
| 25–29 | DIRECTOR |
| 30+ | ARCHITECT |

### Analytics Dashboard
- 14-day productivity and focus trends
- Best day of week and best focus hour
- Distraction patterns and top distraction apps
- Weekly comparison (this week vs last)
- Session history with detailed breakdowns
- Window usage timelines, keystroke patterns, screenshot galleries

### Emergency Unlock
For genuine emergencies, `sudo lockin emergency` triggers a **10-minute cooldown** before unlocking. Designed to prevent impulse unlocking while allowing real emergencies.

---

## Architecture

```
lockin/
├── system/               # Kernel-level blocking (bash + systemd)
│   ├── lockin            # Main CLI
│   ├── lockin-guard      # Guardian daemon (5s loop)
│   ├── lockin-guard.service
│   └── install.sh
├── webapp/               # Unified web GUI + dashboard
│   ├── app.py            # Flask backend (API + page serving)
│   ├── achievements.py   # Achievement/XP/level system
│   ├── static/
│   │   ├── style.css     # Palantir-inspired design
│   │   └── app.js        # SPA frontend
│   └── templates/
│       └── index.html    # Shell template
├── monitor/              # Behavioral tracking daemon
│   ├── monitor.py        # Main daemon (5 threads)
│   ├── tracker.py        # Window, keystroke, idle, bypass trackers
│   ├── db.py             # SQLite database module
│   └── screenshotter.py  # Multi-backend screenshot capture
├── analyzer/             # AI analysis engine
│   ├── analyzer.py       # Claude API integration
│   └── reporter.py       # Report generation
├── dashboard/            # Legacy Flask dashboard
├── extension/            # Chrome extension (Manifest v3)
├── launcher.py           # Desktop app launcher (pywebview)
└── lockin-gui            # Legacy GTK3 GUI
```

### Data Flow
```
User clicks LOCK IN in web GUI
    → Flask calls lockin start via pkexec
    → iptables + /etc/hosts + IPv6 disabled
    → Guard daemon starts (5s verification loop)
    → Monitor daemon starts (5 tracking threads → SQLite)
    → Web GUI shows live countdown + activity feed
    → Timer expires → guard cleans up → analyzer runs AI analysis
    → XP awarded → achievements checked → results in dashboard
```

### Tech Stack
| Component | Stack |
|-----------|-------|
| System blocking | bash, iptables, /etc/hosts, chattr, sysctl, systemd |
| Web GUI | Flask, vanilla JS SPA, CSS (Palantir design) |
| Desktop wrapper | pywebview (GTK backend) |
| Monitoring | Python threading, sqlite3, PIL |
| AI analysis | Anthropic Claude API (claude-sonnet-4-6) |
| Database | SQLite3 with WAL mode |
| Browser extension | Chrome Manifest v3 |

---

## Installation

### Requirements
- Linux (tested on Ubuntu 24.04)
- Python 3.10+
- root/sudo access (for iptables and /etc/hosts)
- `dig` (from `dnsutils`)

### Install

```bash
# Clone
git clone https://github.com/Yarbhelp-bit/lockin.git
cd lockin

# Install system dependencies
sudo apt install python3-flask python3-gi python3-pil dnsutils

# Install Python packages
pip3 install pywebview anthropic

# Install system components
sudo bash system/install.sh
```

### Set up AI analysis (optional)
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

---

## Usage

### GUI (recommended)
```bash
# Launch the web GUI in a desktop window
python3 launcher.py

# Or run the web server directly (opens in browser)
cd webapp && python3 app.py
```

### CLI
```bash
# Start a 25-minute session allowing only github.com and stackoverflow.com
sudo lockin start 25 github.com stackoverflow.com

# Check session status
lockin status

# Emergency unlock (10-minute cooldown)
sudo lockin emergency
```

### Chrome Extension
Load `extension/` as an unpacked extension in `chrome://extensions` (enable Developer mode).

---

## Database

All data stored locally in SQLite at `/var/lib/lockin/monitor.db`:

- `sessions` — Session records with scores and AI summaries
- `activity` — Event log (window switches, bypass attempts, distractions)
- `window_log` — Active window tracking with productivity classification
- `keystroke_stats` — Typing activity per interval
- `screenshots` — Screenshot metadata and AI analysis
- `daily_stats` — Aggregated daily statistics
- `achievements` — Unlocked achievement records
- `player_stats` — XP, level, cumulative statistics

Screenshots stored at `/var/lib/lockin/screenshots/`.

---

## Design

The web interface uses a Palantir-inspired design language:
- Near-black backgrounds with subtle grid overlay
- Cyan accent colors with glow effects
- Monospace typography (JetBrains Mono)
- Data-dense panel layouts
- Animated progress indicators and achievement badges
- Rarity-colored achievement tiers (common → legendary)

---

## License

MIT
