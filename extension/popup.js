// ============================================================================
// LOCK IN — Popup (Hardened: no end session, no escape)
// ============================================================================

let selectedMinutes = 25;
let allowedSites = [];
let countdownInterval = null;

// DOM
const setupView = document.getElementById('setupView');
const activeView = document.getElementById('activeView');
const siteInput = document.getElementById('siteInput');
const addSiteBtn = document.getElementById('addSiteBtn');
const sitesList = document.getElementById('sitesList');
const lockinBtn = document.getElementById('lockinBtn');
const timerDisplay = document.getElementById('timerDisplay');
const progressFill = document.getElementById('progressFill');
const activeAllowedList = document.getElementById('activeAllowedList');

// ---- Init: check if session is already active ----
chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (res) => {
  if (res && res.active) {
    showActiveView(res);
  } else {
    loadSavedSites();
  }
});

// ---- Duration buttons ----
document.querySelectorAll('.dur-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.dur-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedMinutes = parseInt(btn.dataset.min);
  });
});

// ---- Add site ----
function addSite(domain) {
  domain = domain.trim().toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/^www\./, '')
    .replace(/\/.*$/, '');

  if (!domain || allowedSites.includes(domain)) return;
  allowedSites.push(domain);
  renderSites();
  saveSites();
}

addSiteBtn.addEventListener('click', () => {
  addSite(siteInput.value);
  siteInput.value = '';
  siteInput.focus();
});

siteInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    addSite(siteInput.value);
    siteInput.value = '';
  }
});

function removeSite(domain) {
  allowedSites = allowedSites.filter(s => s !== domain);
  renderSites();
  saveSites();
}

function renderSites() {
  sitesList.innerHTML = allowedSites.map(s => `
    <div class="site-tag">
      <span>${s}</span>
      <button class="site-tag-remove" data-site="${s}">&times;</button>
    </div>
  `).join('');

  sitesList.querySelectorAll('.site-tag-remove').forEach(btn => {
    btn.addEventListener('click', () => removeSite(btn.dataset.site));
  });
}

function saveSites() {
  chrome.storage.local.set({ lockin_saved_sites: allowedSites });
}

function loadSavedSites() {
  chrome.storage.local.get('lockin_saved_sites', (data) => {
    if (data.lockin_saved_sites) {
      allowedSites = data.lockin_saved_sites;
      renderSites();
    }
  });
}

// ---- Lock In ----
lockinBtn.addEventListener('click', () => {
  if (allowedSites.length === 0) {
    siteInput.style.borderColor = '#ef4444';
    siteInput.placeholder = 'Add at least one allowed site first';
    setTimeout(() => {
      siteInput.style.borderColor = '';
      siteInput.placeholder = 'e.g. github.com';
    }, 2000);
    return;
  }

  chrome.runtime.sendMessage({
    type: 'START_SESSION',
    minutes: selectedMinutes,
    allowedSites: allowedSites
  }, (res) => {
    if (res && res.ok) {
      chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (status) => {
        showActiveView(status);
      });
    }
  });
});

// ---- Active View ----
function showActiveView(status) {
  setupView.classList.remove('active');
  activeView.classList.add('active');

  activeAllowedList.innerHTML = status.allowedSites.map(s => `
    <div class="allowed-item">
      <div class="allowed-dot"></div>
      <span>${s}</span>
    </div>
  `).join('');

  startCountdown();
}

function startCountdown() {
  clearInterval(countdownInterval);

  function update() {
    chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (res) => {
      if (!res || !res.active) {
        clearInterval(countdownInterval);
        setupView.classList.add('active');
        activeView.classList.remove('active');
        loadSavedSites();
        return;
      }

      const remaining = Math.ceil(res.remainingMs / 1000);
      const total = res.totalSeconds;
      const mins = Math.floor(remaining / 60);
      const secs = remaining % 60;
      timerDisplay.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

      const progress = ((total - remaining) / total) * 100;
      progressFill.style.width = progress + '%';
    });
  }

  update();
  countdownInterval = setInterval(update, 1000);
}
