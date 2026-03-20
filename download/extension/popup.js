/**
 * popup.js — UI controller for the extension popup.
 *
 * • Loads detected media from the background service-worker.
 * • Sends download / analyze requests to the backend via the service-worker.
 * • Polls for download status while there are active tasks.
 */

document.addEventListener("DOMContentLoaded", () => {
  const serverDot   = document.getElementById("serverDot");
  const mediaList   = document.getElementById("mediaList");
  const downloadList= document.getElementById("downloadList");
  const manualUrl   = document.getElementById("manualUrl");
  const manualBtn   = document.getElementById("manualBtn");

  let currentTabId  = null;
  let pollTimer     = null;

  const AUDIO_TYPES = new Set(["mp3", "m4a", "ogg", "wav", "aac", "flac"]);

  // ── Tab switching ────────────────────────────────────────────────

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`panel-${tab.dataset.tab}`).classList.add("active");
      if (tab.dataset.tab === "downloads") refreshDownloads();
    });
  });

  // ── Health check ─────────────────────────────────────────────────

  function checkHealth() {
    chrome.runtime.sendMessage({ action: "health" }, (resp) => {
      if (chrome.runtime.lastError || !resp || !resp.ok) {
        serverDot.classList.remove("online");
        serverDot.title = "Backend offline";
      } else {
        serverDot.classList.add("online");
        serverDot.title = `Backend online | yt-dlp: ${resp.data.ytdlp_available ? "✓" : "✗"} | aria2: ${resp.data.aria2_available ? "✓" : "✗"}`;
      }
    });
  }

  checkHealth();
  setInterval(checkHealth, 10000);

  // ── Load detected media ──────────────────────────────────────────

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs[0]) return;
    currentTabId = tabs[0].id;

    chrome.runtime.sendMessage({ action: "getMedia", tabId: currentTabId }, (resp) => {
      if (chrome.runtime.lastError) return;
      renderMediaList(resp?.items || []);
    });
  });

  function badgeClass(type) {
    const t = type.toLowerCase();
    if (["mp4", "webm", "mkv", "avi", "mov", "flv"].includes(t)) return t === "mp4" || t === "webm" ? t : "mp4";
    if (["m3u8"].includes(t)) return "m3u8";
    if (["mpd"].includes(t)) return "mpd";
    if (AUDIO_TYPES.has(t)) return "audio";
    return "unknown";
  }

  function truncateUrl(url, max = 80) {
    if (url.length <= max) return url;
    return url.substring(0, max - 3) + "…";
  }

  function renderMediaList(items) {
    if (!items.length) {
      mediaList.innerHTML = '<p class="empty">No media detected on this page</p>';
      return;
    }

    mediaList.innerHTML = "";

    items.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "media-card";
      card.innerHTML = `
        <div class="row">
          <span class="badge ${badgeClass(item.type)}">${item.type}</span>
          <span class="badge unknown" style="font-size:0.6rem">${item.source || "?"}</span>
          <button class="btn btn-analyze" data-idx="${index}" title="Analyze URL">🔍</button>
          <button class="btn btn-download" data-idx="${index}" title="Download">⬇ Download</button>
        </div>
        <div class="media-url" title="${item.url}">${truncateUrl(item.url)}</div>
        <div class="analysis-result" id="analysis-${index}"></div>
      `;
      mediaList.appendChild(card);
    });

    // Wire buttons
    mediaList.querySelectorAll(".btn-analyze").forEach((btn) => {
      btn.addEventListener("click", () => analyzeItem(items[btn.dataset.idx], btn.dataset.idx));
    });

    mediaList.querySelectorAll(".btn-download").forEach((btn) => {
      btn.addEventListener("click", () => downloadItem(items[btn.dataset.idx], btn));
    });
  }

  function analyzeItem(item, idx) {
    const container = document.getElementById(`analysis-${idx}`);
    container.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem">Analyzing…</span>';

    chrome.runtime.sendMessage({ action: "analyze", url: item.url }, (resp) => {
      if (chrome.runtime.lastError || !resp?.ok) {
        container.innerHTML = `<span class="error-text">Analysis failed: ${resp?.error || "Backend unreachable"}</span>`;
        return;
      }
      const d = resp.data;
      const sizeStr = d.filesize ? formatBytes(d.filesize) : "unknown size";
      container.innerHTML = `
        <div style="font-size:0.72rem;color:var(--text-dim);margin-top:4px">
          <strong>${d.title || "—"}</strong><br>
          Type: ${d.media_type} | Method: ${d.recommended_method} | Size: ${sizeStr}
          ${d.platform ? "| Platform: " + d.platform : ""}
          ${d.formats.length ? "| Formats: " + d.formats.length : ""}
        </div>
      `;
    });
  }

  function downloadItem(item, btn) {
    btn.disabled = true;
    btn.textContent = "⏳";

    const payload = { url: item.url };

    chrome.runtime.sendMessage({ action: "download", payload }, (resp) => {
      if (chrome.runtime.lastError || !resp?.ok) {
        btn.textContent = "❌";
        btn.disabled = false;
        return;
      }
      btn.textContent = "✓ Queued";

      // Switch to downloads tab
      document.querySelector('[data-tab="downloads"]').click();
      startPolling();
    });
  }

  // ── Manual download ──────────────────────────────────────────────

  function triggerManualDownload() {
    const url = manualUrl.value.trim();
    if (!url) return;

    manualBtn.disabled = true;
    const payload = { url };

    chrome.runtime.sendMessage({ action: "download", payload }, (resp) => {
      manualBtn.disabled = false;
      if (chrome.runtime.lastError || !resp?.ok) {
        manualUrl.style.borderColor = "var(--error)";
        setTimeout(() => (manualUrl.style.borderColor = ""), 1500);
        return;
      }
      manualUrl.value = "";
      document.querySelector('[data-tab="downloads"]').click();
      startPolling();
    });
  }

  manualBtn.addEventListener("click", triggerManualDownload);
  manualUrl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") triggerManualDownload();
  });

  // ── Download status polling ──────────────────────────────────────

  function startPolling() {
    if (pollTimer) return;
    refreshDownloads();
    pollTimer = setInterval(refreshDownloads, 1500);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function refreshDownloads() {
    chrome.runtime.sendMessage({ action: "status" }, (resp) => {
      if (chrome.runtime.lastError || !resp?.ok) return;
      const tasks = resp.data.tasks || [];
      renderDownloadList(tasks);

      // Stop polling if no active tasks
      const hasActive = tasks.some((t) =>
        ["queued", "downloading", "retrying"].includes(t.status)
      );
      if (!hasActive && pollTimer) stopPolling();
    });
  }

  function renderDownloadList(tasks) {
    if (!tasks.length) {
      downloadList.innerHTML = '<p class="empty">No downloads</p>';
      return;
    }

    downloadList.innerHTML = "";

    // Newest first
    const sorted = [...tasks].sort(
      (a, b) => new Date(b.created_at) - new Date(a.created_at)
    );

    sorted.forEach((t) => {
      const card = document.createElement("div");
      card.className = "download-card";

      const pct = Math.round(t.progress);
      const fname = t.filename || t.url.split("/").pop().substring(0, 50);

      card.innerHTML = `
        <div class="title-row">
          <span class="filename" title="${fname}">${fname}</span>
          <span class="status-label ${t.status}">${t.status}</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" style="width:${pct}%"></div>
        </div>
        <div class="download-meta">
          <span>${pct}%${t.speed ? " • " + t.speed : ""}${t.eta ? " • ETA " + t.eta : ""}</span>
          <span>${t.method}</span>
        </div>
        ${t.error ? `<div class="error-text">${t.error}</div>` : ""}
      `;
      downloadList.appendChild(card);
    });
  }

  // ── Utility ──────────────────────────────────────────────────────

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  }

  // Start polling in case there are already active downloads
  startPolling();
});