// ============================================================================
// LOCK IN — Hardened Background Service Worker
// No end session. Blocks chrome://extensions. No escape from the extension.
// ============================================================================

let session = null; // { endTime, allowedSites, totalSeconds }

// ---- Helpers ----
function getDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

function isAllowed(url, allowedSites) {
  // Always allow extension pages and new tab
  if (!url || url.startsWith('chrome-extension://') || url === 'chrome://newtab/') {
    return true;
  }
  // Block ALL other chrome:// and about: pages during session
  // This prevents accessing chrome://extensions to uninstall
  if (url.startsWith('chrome://') || url.startsWith('about:') || url.startsWith('edge://')) {
    return false;
  }
  const domain = getDomain(url);
  return allowedSites.some(site => {
    const allowed = site.replace(/^www\./, '');
    return domain === allowed || domain.endsWith('.' + allowed);
  });
}

function getBlockedURL(originalUrl) {
  return chrome.runtime.getURL('blocked.html') + '?url=' + encodeURIComponent(originalUrl);
}

// ---- Session management ----
async function startSession(minutes, allowedSites) {
  const endTime = Date.now() + minutes * 60 * 1000;
  session = { endTime, allowedSites, totalSeconds: minutes * 60 };

  await chrome.storage.local.set({
    lockin_session: session,
    lockin_active: true
  });

  // Set alarm for session end
  chrome.alarms.create('lockin_end', { when: endTime });

  // Set badge
  chrome.action.setBadgeText({ text: 'ON' });
  chrome.action.setBadgeBackgroundColor({ color: '#f97316' });

  // Block existing non-allowed tabs
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (tab.url && !isAllowed(tab.url, allowedSites) && !tab.url.includes('blocked.html')) {
      chrome.tabs.update(tab.id, { url: getBlockedURL(tab.url) });
    }
  }
}

async function endSession() {
  session = null;
  await chrome.storage.local.set({
    lockin_session: null,
    lockin_active: false
  });
  chrome.alarms.clear('lockin_end');
  chrome.action.setBadgeText({ text: '' });

  chrome.notifications.create('lockin_done', {
    type: 'basic',
    iconUrl: 'icons/icon128.png',
    title: 'Session Complete',
    message: 'You locked in. Time for a break.',
    priority: 2
  });
}

// ---- Restore session on startup ----
async function restoreSession() {
  const data = await chrome.storage.local.get(['lockin_session', 'lockin_active']);
  if (data.lockin_active && data.lockin_session) {
    if (Date.now() < data.lockin_session.endTime) {
      session = data.lockin_session;
      chrome.action.setBadgeText({ text: 'ON' });
      chrome.action.setBadgeBackgroundColor({ color: '#f97316' });
      // Re-block any non-allowed tabs that opened while service worker was inactive
      const tabs = await chrome.tabs.query({});
      for (const tab of tabs) {
        if (tab.url && !isAllowed(tab.url, session.allowedSites) && !tab.url.includes('blocked.html')) {
          chrome.tabs.update(tab.id, { url: getBlockedURL(tab.url) });
        }
      }
    } else {
      await endSession();
    }
  }
}

restoreSession();

// ---- Alarm listener ----
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'lockin_end') {
    const data = await chrome.storage.local.get('lockin_history');
    const history = data.lockin_history || [];
    if (session) {
      history.push({
        minutes: Math.round(session.totalSeconds / 60),
        date: new Date().toISOString().split('T')[0],
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      });
      await chrome.storage.local.set({ lockin_history: history });
    }
    await endSession();
  }
});

// ---- Tab navigation blocking (primary defense) ----
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!session || Date.now() >= session.endTime) return;
  if (changeInfo.url) {
    if (!isAllowed(changeInfo.url, session.allowedSites) && !changeInfo.url.includes('blocked.html')) {
      chrome.tabs.update(tabId, { url: getBlockedURL(changeInfo.url) });
    }
  }
});

// ---- Block new tabs navigating to non-allowed sites ----
chrome.webNavigation.onBeforeNavigate.addListener((details) => {
  if (!session || Date.now() >= session.endTime) return;
  if (details.frameId !== 0) return; // Only main frame
  if (!isAllowed(details.url, session.allowedSites) && !details.url.includes('blocked.html')) {
    chrome.tabs.update(details.tabId, { url: getBlockedURL(details.url) });
  }
});

// ---- Block chrome://extensions specifically ----
// Poll active tab to catch chrome:// pages that bypass onUpdated
setInterval(async () => {
  if (!session || Date.now() >= session.endTime) return;
  try {
    const tabs = await chrome.tabs.query({ active: true });
    for (const tab of tabs) {
      if (tab.url && !isAllowed(tab.url, session.allowedSites) && !tab.url.includes('blocked.html')) {
        chrome.tabs.update(tab.id, { url: getBlockedURL(tab.url) });
      }
    }
  } catch {}
}, 1000);

// ---- Periodic check: re-block any escaped tabs ----
setInterval(async () => {
  if (!session || Date.now() >= session.endTime) return;
  try {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
      if (tab.url && !isAllowed(tab.url, session.allowedSites) && !tab.url.includes('blocked.html')) {
        chrome.tabs.update(tab.id, { url: getBlockedURL(tab.url) });
      }
    }
  } catch {}
}, 3000);

// ---- Message handler (NO END_SESSION — that's the point) ----
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'START_SESSION') {
    startSession(msg.minutes, msg.allowedSites).then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type === 'GET_STATUS') {
    if (session && Date.now() < session.endTime) {
      sendResponse({
        active: true,
        remainingMs: session.endTime - Date.now(),
        totalSeconds: session.totalSeconds,
        allowedSites: session.allowedSites
      });
    } else {
      sendResponse({ active: false });
    }
    return true;
  }
});
