/**
 * background.js — MV3 Service Worker
 *
 * 1. Listens to chrome.webRequest to detect media network requests.
 * 2. Receives DOM-scan results from content.js.
 * 3. Stores detected media per tab in chrome.storage.session.
 * 4. Communicates with the Python backend.
 */

const BACKEND = "http://127.0.0.1:8765";

// ── Media-detection patterns ────────────────────────────────────────────

const MEDIA_EXTENSIONS = /\.(mp4|webm|mkv|avi|mov|flv|m3u8|mpd|mp3|m4a|ogg|wav|aac|ts)(\?|#|$)/i;
const MEDIA_CONTENT_TYPES = [
  "video/",
  "audio/",
  "application/vnd.apple.mpegurl",
  "application/x-mpegurl",
  "application/dash+xml",
];

// Minimum size to consider (bytes). Filters out tiny tracking pixels / thumbnails.
const MIN_CONTENT_LENGTH = 50_000; // 50 KB

// Ignore patterns
const IGNORE_PATTERNS = [
  /\.google\.(com|co\.\w+)\/(generate_204|pagead)/i,
  /doubleclick\.net/i,
  /googlesyndication/i,
  /analytics/i,
  /\.gif(\?|$)/i,
  /\.png(\?|$)/i,
  /\.jpg(\?|$)/i,
  /\.jpeg(\?|$)/i,
  /\.svg(\?|$)/i,
  /\.ico(\?|$)/i,
  /\.woff/i,
  /\.css(\?|$)/i,
  /\.js(\?|$)/i,
];

// ── State helpers ───────────────────────────────────────────────────────

async function getTabMedia(tabId) {
  const key = `media_${tabId}`;
  const data = await chrome.storage.session.get(key);
  return data[key] || [];
}

async function addTabMedia(tabId, entry) {
  const key = `media_${tabId}`;
  const existing = await getTabMedia(tabId);
  // Deduplicate by URL
  if (existing.some((e) => e.url === entry.url)) return;
  existing.push(entry);
  await chrome.storage.session.set({ [key]: existing });
  // Update badge
  chrome.action.setBadgeText({ text: String(existing.length), tabId });
  chrome.action.setBadgeBackgroundColor({ color: "#e94560", tabId });
}

// ── WebRequest listener ────────────────────────────────────────────────

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return; // background request
    const url = details.url;

    // Quick ignore
    if (IGNORE_PATTERNS.some((re) => re.test(url))) return;

    // Extension match
    if (MEDIA_EXTENSIONS.test(url)) {
      const ext = url.match(MEDIA_EXTENSIONS)[1].toLowerCase();
      addTabMedia(details.tabId, {
        url,
        type: ext,
        source: "network",
        timestamp: Date.now(),
      });
    }
  },
  { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "other"] }
);

// Header-based detection (content-type)
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const url = details.url;
    if (IGNORE_PATTERNS.some((re) => re.test(url))) return;

    const headers = details.responseHeaders || [];
    const ctHeader = headers.find((h) => h.name.toLowerCase() === "content-type");
    const clHeader = headers.find((h) => h.name.toLowerCase() === "content-length");

    if (!ctHeader) return;
    const ct = ctHeader.value.toLowerCase();
    const cl = clHeader ? parseInt(clHeader.value, 10) : 0;

    // Skip small responses
    if (cl > 0 && cl < MIN_CONTENT_LENGTH) return;

    const isMedia = MEDIA_CONTENT_TYPES.some((prefix) => ct.startsWith(prefix));
    if (!isMedia) return;

    // Already captured by URL pattern?
    if (MEDIA_EXTENSIONS.test(url)) return;

    let type = "unknown";
    if (ct.startsWith("video/")) type = ct.split("/")[1].split(";")[0];
    else if (ct.startsWith("audio/")) type = ct.split("/")[1].split(";")[0];
    else if (ct.includes("mpegurl")) type = "m3u8";
    else if (ct.includes("dash")) type = "mpd";

    addTabMedia(details.tabId, {
      url,
      type,
      size: cl || null,
      source: "header",
      timestamp: Date.now(),
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

// ── Content-script messages ────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "mediaFound" && sender.tab) {
    const entries = msg.entries || [];
    for (const entry of entries) {
      addTabMedia(sender.tab.id, {
        url: entry.url,
        type: entry.type || "unknown",
        source: "dom",
        timestamp: Date.now(),
      });
    }
    sendResponse({ ok: true });
  }

  if (msg.action === "getMedia") {
    (async () => {
      const items = await getTabMedia(msg.tabId);
      sendResponse({ items });
    })();
    return true; // async response
  }

  if (msg.action === "analyze") {
    (async () => {
      try {
        const resp = await fetch(`${BACKEND}/api/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: msg.url, page_url: msg.pageUrl }),
        });
        const data = await resp.json();
        sendResponse({ ok: true, data });
      } catch (err) {
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true;
  }

  if (msg.action === "download") {
    (async () => {
      try {
        const resp = await fetch(`${BACKEND}/api/download`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(msg.payload),
        });
        const data = await resp.json();
        sendResponse({ ok: true, data });
      } catch (err) {
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true;
  }

  if (msg.action === "status") {
    (async () => {
      try {
        const resp = await fetch(`${BACKEND}/api/status`);
        const data = await resp.json();
        sendResponse({ ok: true, data });
      } catch (err) {
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true;
  }

  if (msg.action === "health") {
    (async () => {
      try {
        const resp = await fetch(`${BACKEND}/api/health`);
        const data = await resp.json();
        sendResponse({ ok: true, data });
      } catch (err) {
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true;
  }
});

// ── Tab cleanup ────────────────────────────────────────────────────────

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`media_${tabId}`);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    // Clear media on navigation
    chrome.storage.session.remove(`media_${tabId}`);
    chrome.action.setBadgeText({ text: "", tabId });
  }
});