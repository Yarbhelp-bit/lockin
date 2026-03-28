/* ============================================================
   LOCK IN // Command Center
   Single-Page Application — Vanilla JS
   ============================================================ */

// ── State ─────────────────────────────────────────────────────

const state = {
    selectedMinutes: 25,
    sites: [],
    timerInterval: null,
    refreshInterval: null,
    currentView: null,
    page: 1,
};

// ── API ───────────────────────────────────────────────────────

async function api(endpoint) {
    try {
        const res = await fetch(endpoint);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(`API GET ${endpoint}:`, e);
        return null;
    }
}

async function apiPost(endpoint, data) {
    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(`API POST ${endpoint}:`, e);
        return null;
    }
}

// ── Utilities ─────────────────────────────────────────────────

function formatTime(seconds) {
    if (seconds < 0) seconds = 0;
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function formatDuration(minutes) {
    if (minutes >= 60) {
        const h = Math.floor(minutes / 60);
        const m = minutes % 60;
        return m > 0 ? `${h}h ${m}m` : `${h}h`;
    }
    return `${minutes}m`;
}

function formatDate(timestamp) {
    const d = new Date(timestamp);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatTimeShort(timestamp) {
    const d = new Date(timestamp);
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function timeAgo(timestamp) {
    const seconds = Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return formatDate(timestamp);
}

function scoreColor(score) {
    if (score >= 90) return 'var(--success)';
    if (score >= 70) return 'var(--accent)';
    if (score >= 50) return 'var(--warning)';
    return 'var(--danger)';
}

function rarityColor(rarity) {
    const map = {
        common: 'var(--rarity-common)',
        rare: 'var(--rarity-rare)',
        epic: 'var(--rarity-epic)',
        legendary: 'var(--rarity-legendary)',
    };
    return map[rarity] || map.common;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Interval Cleanup ──────────────────────────────────────────

function clearIntervals() {
    if (state.timerInterval) {
        clearInterval(state.timerInterval);
        state.timerInterval = null;
    }
    if (state.refreshInterval) {
        clearInterval(state.refreshInterval);
        state.refreshInterval = null;
    }
}

// ── Site Persistence ──────────────────────────────────────────

function loadSites() {
    try {
        const saved = localStorage.getItem('lockin_sites');
        state.sites = saved ? JSON.parse(saved) : [];
    } catch {
        state.sites = [];
    }
}

function saveSites() {
    localStorage.setItem('lockin_sites', JSON.stringify(state.sites));
}

function addSite(site) {
    site = site.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/+$/, '');
    if (site && !state.sites.includes(site)) {
        state.sites.push(site);
        saveSites();
    }
}

function removeSite(site) {
    state.sites = state.sites.filter(s => s !== site);
    saveSites();
}

// ── Profile / XP Bar ──────────────────────────────────────────

async function updateProfile() {
    const data = await api('/api/status');
    if (!data) return;

    const prof = data.profile || {};
    const rank = prof.rank || 'Recruit';
    const level = prof.level || 1;
    const xp = prof.xp || 0;
    const xpNext = prof.xp_next || 100;
    const pct = Math.min(100, Math.round((xp / xpNext) * 100));
    const icon = prof.icon || '\u2606';

    const section = document.getElementById('profile-section');
    if (section) {
        section.innerHTML = `
            <div class="rank-display">
                <div class="rank-badge rare">${icon}</div>
                <div class="rank-info">
                    <div class="rank-name">${escapeHtml(rank)}</div>
                    <div class="rank-level">Level ${level}</div>
                </div>
            </div>
            <div class="xp-bar-container">
                <div class="xp-bar-label">
                    <span>${xp} XP</span>
                    <span>${xpNext} XP</span>
                </div>
                <div class="xp-bar">
                    <div class="xp-bar-fill" style="width:${pct}%"></div>
                </div>
            </div>
        `;
    }

    // System status
    const statusEl = document.getElementById('system-status');
    if (statusEl) {
        const active = data.active_session;
        if (active) {
            statusEl.innerHTML = `<span class="status-led active"></span><span>Session Active</span>`;
        } else {
            statusEl.innerHTML = `<span class="status-led idle"></span><span>System Idle</span>`;
        }
    }

    // Achievement toasts
    if (data.new_achievements && data.new_achievements.length > 0) {
        data.new_achievements.forEach((a, i) => {
            setTimeout(() => showAchievementToast(a), i * 600);
        });
    }
}

// ── Toast System ──────────────────────────────────────────────

function showAchievementToast(achievement) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const rarity = achievement.rarity || 'common';
    const toast = document.createElement('div');
    toast.className = `toast rarity-${rarity}`;
    toast.innerHTML = `
        <div class="toast-icon">${achievement.icon || '\u2605'}</div>
        <div class="toast-body">
            <div class="toast-title">Achievement Unlocked!</div>
            <div class="toast-desc">${escapeHtml(achievement.name || '')}</div>
            <div class="toast-xp">+${achievement.xp || 0} XP</div>
        </div>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ── Session Complete Effect ───────────────────────────────────

function showSessionComplete() {
    const overlay = document.createElement('div');
    overlay.className = 'session-complete-overlay';
    overlay.innerHTML = `
        <div class="session-complete-content">
            <h1>SESSION COMPLETE</h1>
            <p>Mission accomplished. Great focus.</p>
        </div>
    `;
    overlay.addEventListener('click', () => overlay.remove());
    document.body.appendChild(overlay);

    // Confetti
    const colors = ['#00d4ff', '#00ff88', '#ffd700', '#aa44ff', '#ff8800', '#4488ff'];
    for (let i = 0; i < 40; i++) {
        const particle = document.createElement('div');
        particle.className = 'confetti-particle';
        particle.style.left = Math.random() * 100 + 'vw';
        particle.style.top = '-10px';
        particle.style.background = colors[Math.floor(Math.random() * colors.length)];
        particle.style.animationDelay = Math.random() * 1 + 's';
        particle.style.animationDuration = (1.5 + Math.random() * 1.5) + 's';
        document.body.appendChild(particle);
        setTimeout(() => particle.remove(), 4000);
    }

    setTimeout(() => {
        if (overlay.parentNode) overlay.remove();
        navigate();
    }, 4000);
}

// ── Router ────────────────────────────────────────────────────

function getRoute() {
    const hash = window.location.hash || '#/';
    return hash;
}

function navigate(hash) {
    if (hash !== undefined) window.location.hash = hash;
    route();
}

function route() {
    clearIntervals();

    const hash = getRoute();
    const main = document.getElementById('main-content');
    if (!main) return;

    // Update active nav
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        const href = item.getAttribute('href');
        if (hash === href || (hash.startsWith('#/operation/') && href === '#/operations')) {
            item.classList.add('active');
        }
    });

    if (hash === '#/' || hash === '') {
        state.currentView = 'command';
        renderCommandCenter(main);
    } else if (hash === '#/operations') {
        state.currentView = 'operations';
        state.page = 1;
        renderOperations(main);
    } else if (hash.startsWith('#/operation/')) {
        state.currentView = 'operation';
        const id = hash.split('/')[2];
        renderOperation(main, id);
    } else if (hash === '#/intel') {
        state.currentView = 'intel';
        renderIntel(main);
    } else if (hash === '#/achievements') {
        state.currentView = 'achievements';
        renderAchievements(main);
    } else {
        state.currentView = 'command';
        renderCommandCenter(main);
    }

    updateProfile();
}

// ── View: Command Center ──────────────────────────────────────

async function renderCommandCenter(container) {
    container.innerHTML = '<div class="view-header"><div><div class="view-title">Command Center</div><div class="view-subtitle">Focus operations control</div></div></div><div id="cc-body"><div class="empty-state"><p>Loading...</p></div></div>';

    const data = await api('/api/status');
    const body = document.getElementById('cc-body');
    if (!body) return;

    if (data && data.active_session) {
        renderActiveSession(body, data);
    } else {
        renderSetupSession(body, data);
    }
}

function renderSetupSession(container, statusData) {
    const durations = [
        { min: 15, label: 'Sprint' },
        { min: 25, label: 'Pomodoro' },
        { min: 45, label: 'Standard' },
        { min: 60, label: 'Deep Work' },
        { min: 90, label: 'Extended' },
        { min: 120, label: 'Marathon' },
    ];

    const durationBtns = durations.map(d => `
        <button class="duration-btn ${state.selectedMinutes === d.min ? 'selected' : ''}" data-min="${d.min}">
            ${d.min >= 60 ? formatDuration(d.min) : d.min + 'm'}
            <span class="duration-label">${d.label}</span>
        </button>
    `).join('');

    const siteTags = state.sites.map(s => `
        <span class="site-tag" data-site="${escapeHtml(s)}">
            ${escapeHtml(s)}
            <span class="tag-remove">\u2715</span>
        </span>
    `).join('');

    const today = statusData?.today || {};

    container.innerHTML = `
        <div class="panel mb-20">
            <div class="panel-header">Session Configuration</div>

            <h3 style="margin-bottom:10px; font-size:11px; color:var(--text-dim);">Duration</h3>
            <div class="duration-grid" id="duration-grid">
                ${durationBtns}
            </div>

            <h3 style="margin-bottom:10px; font-size:11px; color:var(--text-dim);">Allowed Sites</h3>
            <div class="site-input-row">
                <input type="text" id="site-input" placeholder="e.g. github.com" style="flex:1">
                <button class="btn btn-primary btn-sm" id="add-site-btn">ADD</button>
            </div>
            <div class="site-tags" id="site-tags">${siteTags}</div>

            <button class="btn-lockin" id="lockin-btn" ${state.sites.length === 0 ? 'disabled' : ''}>
                LOCK IN
            </button>
        </div>

        <div class="quick-stats" id="today-stats">
            <div class="quick-stat">
                <span class="quick-stat-icon">\u25CE</span>
                <div class="quick-stat-info">
                    <span class="quick-stat-value">${today.sessions || 0}</span>
                    <span class="quick-stat-label">Sessions Today</span>
                </div>
            </div>
            <div class="quick-stat">
                <span class="quick-stat-icon">\u23F1</span>
                <div class="quick-stat-info">
                    <span class="quick-stat-value">${formatDuration(today.focus_minutes || 0)}</span>
                    <span class="quick-stat-label">Focus Time</span>
                </div>
            </div>
            <div class="quick-stat">
                <span class="quick-stat-icon">\u26A1</span>
                <div class="quick-stat-info">
                    <span class="quick-stat-value">${today.streak || 0}</span>
                    <span class="quick-stat-label">Day Streak</span>
                </div>
            </div>
        </div>
    `;

    // Duration buttons
    document.getElementById('duration-grid').addEventListener('click', e => {
        const btn = e.target.closest('.duration-btn');
        if (!btn) return;
        state.selectedMinutes = parseInt(btn.dataset.min);
        document.querySelectorAll('.duration-btn').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
    });

    // Site input
    const siteInput = document.getElementById('site-input');
    const addBtn = document.getElementById('add-site-btn');

    function handleAddSite() {
        const val = siteInput.value;
        if (val.trim()) {
            addSite(val);
            siteInput.value = '';
            refreshSiteTags();
            updateLockInBtn();
        }
    }

    addBtn.addEventListener('click', handleAddSite);
    siteInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') handleAddSite();
    });

    // Site tag removal
    document.getElementById('site-tags').addEventListener('click', e => {
        const tag = e.target.closest('.site-tag');
        if (!tag) return;
        removeSite(tag.dataset.site);
        refreshSiteTags();
        updateLockInBtn();
    });

    // Lock in button
    document.getElementById('lockin-btn').addEventListener('click', async () => {
        const btn = document.getElementById('lockin-btn');
        btn.disabled = true;
        btn.textContent = 'INITIALIZING...';

        const result = await apiPost('/api/start', {
            duration: state.selectedMinutes,
            sites: state.sites,
        });

        if (result && result.status === 'ok') {
            navigate('#/');
        } else {
            btn.disabled = false;
            btn.textContent = 'LOCK IN';
        }
    });
}

function refreshSiteTags() {
    const tagsEl = document.getElementById('site-tags');
    if (!tagsEl) return;
    tagsEl.innerHTML = state.sites.map(s => `
        <span class="site-tag" data-site="${escapeHtml(s)}">
            ${escapeHtml(s)}
            <span class="tag-remove">\u2715</span>
        </span>
    `).join('');
}

function updateLockInBtn() {
    const btn = document.getElementById('lockin-btn');
    if (btn) btn.disabled = state.sites.length === 0;
}

function renderActiveSession(container, data) {
    const session = data.active_session;
    const endTime = new Date(session.end_time).getTime();
    const startTime = new Date(session.start_time).getTime();
    const totalDuration = (endTime - startTime) / 1000;

    container.innerHTML = `
        <div class="panel active-session-panel mb-20">
            <div class="timer-display">
                <div class="timer-status">OPERATION IN PROGRESS</div>
                <div class="timer-ring-container">
                    <div class="timer-ring">
                        <svg viewBox="0 0 220 220">
                            <circle class="ring-bg" cx="110" cy="110" r="100"/>
                            <circle class="ring-progress" id="progress-ring" cx="110" cy="110" r="100"/>
                        </svg>
                        <div class="timer-value" id="timer-value">--:--</div>
                    </div>
                </div>
            </div>

            <div class="stats-grid mb-16">
                <div class="stat-card">
                    <div class="stat-label">Duration</div>
                    <div class="stat-value">${formatDuration(session.duration_minutes || Math.round(totalDuration / 60))}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Elapsed</div>
                    <div class="stat-value" id="elapsed-value">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Ends At</div>
                    <div class="stat-value" style="font-size:16px">${formatTimeShort(session.end_time)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Bypass Attempts</div>
                    <div class="stat-value" id="bypass-count">${session.bypass_attempts || 0}</div>
                </div>
            </div>
        </div>

        <div class="two-col">
            <div class="panel">
                <div class="panel-header">Activity Feed</div>
                <div class="activity-feed" id="activity-feed">
                    <div class="empty-state"><p>Waiting for activity...</p></div>
                </div>
            </div>
            <div class="panel">
                <div class="panel-header">Allowed Sites</div>
                <div id="allowed-sites-list">
                    ${(session.sites || []).map(s => `
                        <div style="padding:6px 0; border-bottom:1px solid var(--border); font-family:var(--font-mono); font-size:11px; color:var(--text);">
                            ${escapeHtml(s)}
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `;

    // Timer
    const circumference = 2 * Math.PI * 100;
    const progressRing = document.getElementById('progress-ring');
    if (progressRing) {
        progressRing.style.strokeDasharray = circumference;
    }

    function updateTimer() {
        const now = Date.now();
        const remaining = Math.max(0, (endTime - now) / 1000);
        const elapsed = Math.max(0, (now - startTime) / 1000);
        const progress = Math.min(1, elapsed / totalDuration);

        const timerEl = document.getElementById('timer-value');
        const elapsedEl = document.getElementById('elapsed-value');

        if (timerEl) timerEl.textContent = formatTime(remaining);
        if (elapsedEl) elapsedEl.textContent = formatDuration(Math.round(elapsed / 60));

        if (progressRing) {
            const offset = circumference * (1 - progress);
            progressRing.style.strokeDashoffset = offset;
        }

        if (remaining <= 0) {
            clearIntervals();
            showSessionComplete();
        }
    }

    updateTimer();
    state.timerInterval = setInterval(updateTimer, 1000);

    // Live data refresh
    async function refreshLive() {
        const live = await api('/api/live');
        if (!live) return;

        const feed = document.getElementById('activity-feed');
        if (feed && live.events && live.events.length > 0) {
            feed.innerHTML = live.events.slice(0, 10).map(ev => {
                const dotClass = ev.type === 'warning' ? 'warning' : ev.type === 'danger' ? 'danger' : ev.type === 'success' ? 'success' : 'info';
                return `
                    <div class="activity-item">
                        <span class="activity-dot ${dotClass}"></span>
                        <span class="activity-text">${escapeHtml(ev.message)}</span>
                        <span class="activity-time">${timeAgo(ev.timestamp)}</span>
                    </div>
                `;
            }).join('');
        }

        const bypassEl = document.getElementById('bypass-count');
        if (bypassEl && live.bypass_attempts !== undefined) {
            bypassEl.textContent = live.bypass_attempts;
        }
    }

    refreshLive();
    state.refreshInterval = setInterval(refreshLive, 5000);
}

// ── View: Operations ──────────────────────────────────────────

async function renderOperations(container) {
    container.innerHTML = `
        <div class="view-header">
            <div>
                <div class="view-title">Operations</div>
                <div class="view-subtitle">Session history & records</div>
            </div>
        </div>
        <div id="ops-body"><div class="empty-state"><p>Loading...</p></div></div>
    `;

    const data = await api(`/api/sessions?page=${state.page}`);
    const body = document.getElementById('ops-body');
    if (!body) return;

    if (!data || !data.sessions || data.sessions.length === 0) {
        body.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">\u25CE</div>
                <p>No operations recorded yet</p>
                <p style="margin-top:8px; color:var(--text-muted);">Complete a focus session to see it here.</p>
            </div>
        `;
        return;
    }

    const cards = data.sessions.map(s => {
        const score = s.productivity_score || 0;
        const sites = (s.sites || []).slice(0, 3);
        return `
            <div class="session-card" data-id="${s.id}" onclick="navigate('#/operation/${s.id}')">
                <div class="session-card-header">
                    <span class="session-date">${formatDate(s.start_time)}</span>
                    <span class="session-score" style="color:${scoreColor(score)}">${score}</span>
                </div>
                <div class="session-details">
                    <span>\u23F1 ${formatDuration(s.duration_minutes || 0)}</span>
                    <span>\u25CE Focus: ${s.focus_score || '--'}</span>
                </div>
                <div class="session-sites">
                    ${sites.map(site => `<span class="mini-tag">${escapeHtml(site)}</span>`).join('')}
                    ${(s.sites || []).length > 3 ? `<span class="mini-tag">+${s.sites.length - 3}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');

    const totalPages = data.total_pages || 1;

    body.innerHTML = `
        <div class="sessions-grid">${cards}</div>
        ${totalPages > 1 ? `
            <div class="pagination">
                <button class="btn btn-sm" id="prev-page" ${state.page <= 1 ? 'disabled' : ''}>\u2190 Prev</button>
                <span>Page ${state.page} of ${totalPages}</span>
                <button class="btn btn-sm" id="next-page" ${state.page >= totalPages ? 'disabled' : ''}>Next \u2192</button>
            </div>
        ` : ''}
    `;

    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    if (prevBtn) prevBtn.addEventListener('click', () => { state.page--; renderOperations(container); });
    if (nextBtn) nextBtn.addEventListener('click', () => { state.page++; renderOperations(container); });
}

// ── View: Operation Detail ────────────────────────────────────

async function renderOperation(container, id) {
    container.innerHTML = `
        <a class="back-link" href="#/operations">\u2190 Back to Operations</a>
        <div id="op-body"><div class="empty-state"><p>Loading...</p></div></div>
    `;

    const data = await api(`/api/session/${id}`);
    const body = document.getElementById('op-body');
    if (!body) return;

    if (!data) {
        body.innerHTML = '<div class="empty-state"><p>Operation not found.</p></div>';
        return;
    }

    const score = data.productivity_score || 0;
    const focus = data.focus_score || 0;

    body.innerHTML = `
        <div class="view-header">
            <div>
                <div class="view-title">Operation #${id}</div>
                <div class="view-subtitle">${formatDate(data.start_time)} \u2022 ${formatTimeShort(data.start_time)} - ${formatTimeShort(data.end_time)}</div>
            </div>
        </div>

        <div class="two-col mb-20">
            <div class="panel" style="text-align:center;">
                <div class="panel-header">Productivity Score</div>
                <div class="score-large" style="color:${scoreColor(score)}">${score}</div>
            </div>
            <div class="panel" style="text-align:center;">
                <div class="panel-header">Focus Score</div>
                <div class="score-large" style="color:${scoreColor(focus)}">${focus}</div>
            </div>
        </div>

        <div class="stats-grid mb-20">
            <div class="stat-card">
                <div class="stat-label">Duration</div>
                <div class="stat-value">${formatDuration(data.duration_minutes || 0)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Bypass Attempts</div>
                <div class="stat-value">${data.bypass_attempts || 0}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Distractions</div>
                <div class="stat-value">${data.distractions || 0}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">XP Earned</div>
                <div class="stat-value" style="color:var(--xp-gold)">${data.xp_earned || 0}</div>
            </div>
        </div>

        ${data.ai_summary ? `
            <div class="panel mb-20">
                <div class="panel-header">AI Analysis</div>
                <div class="ai-summary">${escapeHtml(data.ai_summary)}</div>
            </div>
        ` : ''}

        <div class="two-col-wide mb-20">
            <div class="panel">
                <div class="panel-header">Activity Timeline</div>
                <div class="timeline" id="timeline">
                    ${(data.events || []).map(ev => {
                        const cls = ev.type === 'warning' ? 'warning' : ev.type === 'danger' ? 'danger' : ev.type === 'success' ? 'success' : '';
                        return `
                            <div class="timeline-item ${cls}">
                                <div class="timeline-time">${formatTimeShort(ev.timestamp)}</div>
                                <div class="timeline-text">${escapeHtml(ev.message)}</div>
                            </div>
                        `;
                    }).join('') || '<div class="empty-state"><p>No events recorded.</p></div>'}
                </div>
            </div>

            <div class="panel">
                <div class="panel-header">Window Usage</div>
                <div class="bar-chart">
                    ${(data.window_usage || []).map(w => `
                        <div class="bar-item">
                            <span class="bar-label">${escapeHtml(w.name)}</span>
                            <div class="bar-track">
                                <div class="bar-fill" style="width:${w.percent || 0}%"></div>
                            </div>
                            <span class="bar-value">${w.percent || 0}%</span>
                        </div>
                    `).join('') || '<div class="empty-state"><p>No data.</p></div>'}
                </div>
            </div>
        </div>

        ${(data.screenshots && data.screenshots.length > 0) ? `
            <div class="panel mb-20">
                <div class="panel-header">Screenshots</div>
                <div class="screenshot-grid">
                    ${data.screenshots.map(s => `
                        <div class="screenshot-thumb">
                            <img src="${s.url}" alt="Screenshot" loading="lazy">
                        </div>
                    `).join('')}
                </div>
            </div>
        ` : ''}
    `;
}

// ── View: Intelligence ────────────────────────────────────────

async function renderIntel(container) {
    container.innerHTML = `
        <div class="view-header">
            <div>
                <div class="view-title">Intelligence</div>
                <div class="view-subtitle">Analytics & insights</div>
            </div>
        </div>
        <div id="intel-body"><div class="empty-state"><p>Loading...</p></div></div>
    `;

    const data = await api('/api/insights');
    const body = document.getElementById('intel-body');
    if (!body) return;

    if (!data) {
        body.innerHTML = '<div class="empty-state"><div class="empty-state-icon">\u2605</div><p>No intelligence data available yet.</p></div>';
        return;
    }

    const trendArrow = (val) => {
        if (val > 0) return `<span class="stat-trend up">\u2191 ${val}%</span>`;
        if (val < 0) return `<span class="stat-trend down">\u2193 ${Math.abs(val)}%</span>`;
        return `<span class="stat-trend neutral">\u2192 0%</span>`;
    };

    body.innerHTML = `
        <div class="stats-grid mb-20">
            <div class="stat-card">
                <div class="stat-label">Productivity Trend</div>
                <div class="stat-value">${data.productivity_avg || '--'}</div>
                ${trendArrow(data.productivity_trend || 0)}
            </div>
            <div class="stat-card">
                <div class="stat-label">Focus Trend</div>
                <div class="stat-value">${data.focus_avg || '--'}</div>
                ${trendArrow(data.focus_trend || 0)}
            </div>
            <div class="stat-card">
                <div class="stat-label">Day Streak</div>
                <div class="stat-value" style="color:var(--warning)">${data.streak || 0}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Sessions</div>
                <div class="stat-value">${data.total_sessions || 0}</div>
            </div>
        </div>

        <div class="intel-grid mb-20">
            <div class="intel-card">
                <h3>Best Performance</h3>
                <div style="padding:8px 0;">
                    <div class="label">Best Day</div>
                    <div style="font-family:var(--font-mono); font-size:14px; color:var(--text-bright); margin-top:4px;">
                        ${data.best_day ? formatDate(data.best_day.date) + ' \u2014 Score ' + data.best_day.score : 'N/A'}
                    </div>
                </div>
                <div style="padding:8px 0;">
                    <div class="label">Peak Hour</div>
                    <div style="font-family:var(--font-mono); font-size:14px; color:var(--text-bright); margin-top:4px;">
                        ${data.best_hour !== undefined ? data.best_hour + ':00' : 'N/A'}
                    </div>
                </div>
            </div>

            <div class="intel-card">
                <h3>Distraction Report</h3>
                <div style="padding:8px 0;">
                    <div class="label">Total Bypass Attempts</div>
                    <div style="font-family:var(--font-mono); font-size:14px; color:var(--danger); margin-top:4px;">
                        ${data.total_bypasses || 0}
                    </div>
                </div>
                <div style="padding:8px 0;">
                    <div class="label">Most Blocked Site</div>
                    <div style="font-family:var(--font-mono); font-size:14px; color:var(--text-bright); margin-top:4px;">
                        ${data.most_blocked_site || 'N/A'}
                    </div>
                </div>
            </div>
        </div>

        <div class="intel-grid mb-20">
            <div class="intel-card">
                <h3>Weekly Comparison</h3>
                <div class="stats-grid" style="margin-top:12px;">
                    <div class="stat-card">
                        <div class="stat-label">This Week</div>
                        <div class="stat-value">${formatDuration(data.this_week_minutes || 0)}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Last Week</div>
                        <div class="stat-value">${formatDuration(data.last_week_minutes || 0)}</div>
                    </div>
                </div>
            </div>

            <div class="intel-card">
                <h3>AI Insights</h3>
                <div>
                    ${(data.insights || []).map(ins => `
                        <div class="insight-item">${escapeHtml(ins)}</div>
                    `).join('') || '<div class="empty-state"><p>No insights yet.</p></div>'}
                </div>
            </div>
        </div>
    `;
}

// ── View: Achievements ────────────────────────────────────────

async function renderAchievements(container) {
    container.innerHTML = `
        <div class="view-header">
            <div>
                <div class="view-title">Achievements</div>
                <div class="view-subtitle">Medals, ranks & progression</div>
            </div>
        </div>
        <div id="ach-body"><div class="empty-state"><p>Loading...</p></div></div>
    `;

    const data = await api('/api/achievements');
    const body = document.getElementById('ach-body');
    if (!body) return;

    if (!data) {
        body.innerHTML = '<div class="empty-state"><div class="empty-state-icon">\u265B</div><p>No achievements data available.</p></div>';
        return;
    }

    const profile = data.profile || {};
    const achievements = data.achievements || [];

    // Sort: unlocked first, then by rarity weight
    const rarityWeight = { legendary: 0, epic: 1, rare: 2, common: 3 };
    achievements.sort((a, b) => {
        if (a.unlocked && !b.unlocked) return -1;
        if (!a.unlocked && b.unlocked) return 1;
        return (rarityWeight[a.rarity] || 3) - (rarityWeight[b.rarity] || 3);
    });

    const xpPct = profile.xp_next ? Math.min(100, Math.round((profile.xp / profile.xp_next) * 100)) : 0;
    const unlockedCount = achievements.filter(a => a.unlocked).length;

    body.innerHTML = `
        <div class="profile-header mb-20">
            <div class="profile-rank-large">${profile.icon || '\u2606'}</div>
            <div class="profile-info">
                <h2>${escapeHtml(profile.rank || 'Recruit')}</h2>
                <div class="profile-level">Level ${profile.level || 1} \u2022 ${profile.xp || 0} / ${profile.xp_next || 100} XP</div>
                <div class="profile-xp-bar">
                    <div class="profile-xp-fill" style="width:${xpPct}%"></div>
                </div>
            </div>
            <div class="profile-stats-row">
                <div class="profile-stat">
                    <div class="profile-stat-value">${unlockedCount}</div>
                    <div class="profile-stat-label">Unlocked</div>
                </div>
                <div class="profile-stat">
                    <div class="profile-stat-value">${achievements.length}</div>
                    <div class="profile-stat-label">Total</div>
                </div>
                <div class="profile-stat">
                    <div class="profile-stat-value">${profile.total_focus || '0h'}</div>
                    <div class="profile-stat-label">Focus Time</div>
                </div>
            </div>
        </div>

        <div class="achievements-grid">
            ${achievements.map(a => {
                const locked = !a.unlocked;
                const rarity = a.rarity || 'common';
                return `
                    <div class="achievement-card ${locked ? 'locked' : 'unlocked'} rarity-${rarity}">
                        <div class="achievement-icon">${locked ? '\uD83D\uDD12' : (a.icon || '\u2605')}</div>
                        <div class="achievement-name">${locked ? '???' : escapeHtml(a.name)}</div>
                        <div class="achievement-desc">${locked ? 'Keep going to unlock...' : escapeHtml(a.description || '')}</div>
                        <div class="achievement-xp">+${a.xp || 0} XP</div>
                        ${a.unlocked_at ? `<div class="achievement-date">${formatDate(a.unlocked_at)}</div>` : ''}
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

// ── Initialize ────────────────────────────────────────────────

window.navigate = navigate;

document.addEventListener('DOMContentLoaded', () => {
    loadSites();

    if (!window.location.hash || window.location.hash === '#') {
        window.location.hash = '#/';
    }

    route();
});

window.addEventListener('hashchange', route);
