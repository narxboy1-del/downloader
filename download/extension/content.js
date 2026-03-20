/**
 * content.js — DOM scanner
 *
 * Runs at document_idle on every page.
 * Scans for <video>, <audio>, <source>, <meta og:video>, and
 * watches for dynamically inserted elements via MutationObserver.
 */

(() => {
  "use strict";

  const SCANNED = new Set();

  function getMediaType(url) {
    const lower = url.toLowerCase();
    if (lower.includes(".m3u8")) return "m3u8";
    if (lower.includes(".mpd")) return "mpd";
    if (lower.includes(".mp4")) return "mp4";
    if (lower.includes(".webm")) return "webm";
    if (lower.includes(".mkv")) return "mkv";
    if (lower.includes(".mp3")) return "mp3";
    if (lower.includes(".m4a")) return "m4a";
    if (lower.includes(".ogg")) return "ogg";
    if (lower.includes(".wav")) return "wav";
    if (lower.includes(".flv")) return "flv";
    return "unknown";
  }

  function absoluteUrl(src) {
    if (!src) return null;
    try {
      return new URL(src, document.location.href).href;
    } catch {
      return null;
    }
  }

  function collectMedia() {
    const entries = [];

    // <video> and <audio> elements
    document.querySelectorAll("video, audio").forEach((el) => {
      const src = el.currentSrc || el.src;
      if (src && !src.startsWith("blob:") && !SCANNED.has(src)) {
        SCANNED.add(src);
        entries.push({ url: src, type: getMediaType(src) });
      }
    });

    // <source> elements
    document.querySelectorAll("source").forEach((el) => {
      const src = absoluteUrl(el.src);
      if (src && !src.startsWith("blob:") && !SCANNED.has(src)) {
        SCANNED.add(src);
        entries.push({ url: src, type: getMediaType(src) });
      }
    });

    // Open Graph video meta tags
    document
      .querySelectorAll(
        'meta[property="og:video"], meta[property="og:video:url"], meta[property="og:video:secure_url"]'
      )
      .forEach((el) => {
        const src = absoluteUrl(el.content);
        if (src && !SCANNED.has(src)) {
          SCANNED.add(src);
          entries.push({ url: src, type: getMediaType(src) });
        }
      });

    // twitter:player
    document.querySelectorAll('meta[name="twitter:player:stream"]').forEach((el) => {
      const src = absoluteUrl(el.content);
      if (src && !SCANNED.has(src)) {
        SCANNED.add(src);
        entries.push({ url: src, type: getMediaType(src) });
      }
    });

    // JSON-LD structured data
    document.querySelectorAll('script[type="application/ld+json"]').forEach((el) => {
      try {
        const json = JSON.parse(el.textContent);
        const urls = extractVideoFromJsonLd(json);
        for (const u of urls) {
          if (!SCANNED.has(u)) {
            SCANNED.add(u);
            entries.push({ url: u, type: getMediaType(u) });
          }
        }
      } catch {
        /* ignore parse errors */
      }
    });

    return entries;
  }

  function extractVideoFromJsonLd(obj) {
    const urls = [];
    if (!obj) return urls;
    if (Array.isArray(obj)) {
      for (const item of obj) urls.push(...extractVideoFromJsonLd(item));
      return urls;
    }
    if (typeof obj !== "object") return urls;
    if (obj.contentUrl) urls.push(obj.contentUrl);
    if (obj.embedUrl) urls.push(obj.embedUrl);
    for (const val of Object.values(obj)) {
      if (typeof val === "object") urls.push(...extractVideoFromJsonLd(val));
    }
    return urls;
  }

  function sendMedia(entries) {
    if (entries.length === 0) return;
    chrome.runtime.sendMessage({ action: "mediaFound", entries });
  }

  // ── Initial scan ───────────────────────────────────────────────────

  sendMedia(collectMedia());

  // ── Mutation observer for dynamic content ─────────────────────────

  const observer = new MutationObserver(() => {
    const newEntries = collectMedia();
    sendMedia(newEntries);
  });

  observer.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true,
  });
})();