let currentSettings = null;

function baseUrl() {
  const port = (currentSettings && currentSettings.port) || 29512;
  return `http://127.0.0.1:${port}`;
}

function authHeaders() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${(currentSettings && currentSettings.token) || ""}`
  };
}

function renderStatus(online) {
  const badge = document.getElementById("status-badge");
  if (!currentSettings || !currentSettings.token) {
    badge.textContent = "Not Paired (Open Options)";
    badge.className = "status offline";
  } else if (online) {
    badge.textContent = "Connected to Desktop App";
    badge.className = "status online";
  } else {
    badge.textContent = "Desktop App Offline";
    badge.className = "status offline";
  }
}

function renderMedia(media) {
  const section = document.getElementById("media-section");
  const list = document.getElementById("media-list");
  list.innerHTML = "";
  if (!media || media.length === 0) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");
  for (const url of media.slice(0, 4)) {
    const row = document.createElement("div");
    row.className = "item";
    const name = document.createElement("span");
    name.className = "item-name";
    const isYt = /youtube\.com\/(watch|shorts\/)|youtu\.be\//i.test(url);
    name.textContent = isYt ? "Current Page Video (YouTube)" : (url.split("/").pop().split("?")[0] || url);
    name.title = url;
    const btn = document.createElement("button");
    btn.className = "btn small primary";
    btn.textContent = "Download";
    btn.addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "DOWNLOAD_MEDIA", url }, () => {
        void chrome.runtime.lastError;
      });
    });
    row.appendChild(name);
    row.appendChild(btn);
    list.appendChild(row);
  }
}

async function fetchDownloads() {
  if (!currentSettings || !currentSettings.token) return;
  try {
    const resp = await fetch(`${baseUrl()}/api/downloads`, { headers: authHeaders() });
    if (!resp.ok) {
      renderStatus(false);
      return;
    }
    renderStatus(true);
    const data = await resp.json();
    const list = document.getElementById("downloads-list");
    const items = (data.downloads || []).slice(0, 5);
    list.innerHTML = "";
    if (items.length === 0) {
      list.innerHTML = '<div class="empty">No active downloads</div>';
      return;
    }
    for (const dl of items) {
      const card = document.createElement("div");
      card.className = "dl-card";
      const headerRow = document.createElement("div");
      headerRow.className = "dl-row";
      const title = document.createElement("div");
      title.className = "dl-title";
      title.textContent = dl.filename || dl.url;
      title.title = dl.filename || dl.url;

      const btns = document.createElement("div");
      btns.className = "dl-btns";
      if (dl.status === "downloading" || dl.status === "probing") {
        const btnPause = document.createElement("button");
        btnPause.className = "btn mini";
        btnPause.textContent = "Pause";
        btnPause.addEventListener("click", () => sendDownloadAction(dl.id, "pause"));
        btns.appendChild(btnPause);
      } else if (dl.status === "paused" || dl.status === "stopped" || dl.status === "failed" || dl.status === "queued") {
        const btnResume = document.createElement("button");
        btnResume.className = "btn mini primary";
        btnResume.textContent = "Resume";
        btnResume.addEventListener("click", () => sendDownloadAction(dl.id, "resume"));
        btns.appendChild(btnResume);
      }
      if (dl.status !== "completed") {
        const btnCancel = document.createElement("button");
        btnCancel.className = "btn mini";
        btnCancel.textContent = "X";
        btnCancel.title = "Cancel";
        btnCancel.addEventListener("click", () => sendDownloadAction(dl.id, "cancel"));
        btns.appendChild(btnCancel);
      }
      headerRow.appendChild(title);
      headerRow.appendChild(btns);

      const meta = document.createElement("div");
      meta.className = "dl-meta";
      meta.textContent = `${dl.status} - ${dl.progress}%`;
      const bar = document.createElement("div");
      bar.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = `${Math.min(100, Math.max(0, dl.progress || 0))}%`;
      bar.appendChild(fill);
      card.appendChild(headerRow);
      card.appendChild(meta);
      card.appendChild(bar);
      list.appendChild(card);
    }
  } catch (_) {
    renderStatus(false);
  }
}

async function sendDownloadAction(id, action) {
  if (!currentSettings || !id) return;
  try {
    await fetch(`${baseUrl()}/api/download/${id}/${action}`, {
      method: "POST",
      headers: authHeaders()
    });
    fetchDownloads();
  } catch (_) {}
}

function init() {
  chrome.runtime.sendMessage({ type: "GET_STATE" }, (state) => {
    if (chrome.runtime.lastError || !state) return;
    currentSettings = state.settings;
    document.getElementById("toggle-enabled").checked = Boolean(currentSettings.enabled);
    renderStatus(state.online);
    renderMedia(state.media);
    if (state.online) fetchDownloads();
  });

  document.getElementById("toggle-enabled").addEventListener("change", async (e) => {
    await chrome.storage.local.set({ enabled: e.target.checked });
  });

  document.getElementById("btn-add").addEventListener("click", async () => {
    const input = document.getElementById("quick-url");
    const url = input.value.trim();
    if (!url || !currentSettings) return;
    await fetch(`${baseUrl()}/api/download`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ url })
    });
    input.value = "";
    fetchDownloads();
  });

  document.getElementById("btn-pause-all").addEventListener("click", async () => {
    if (!currentSettings) return;
    const resp = await fetch(`${baseUrl()}/api/downloads`, { headers: authHeaders() });
    const data = await resp.json();
    for (const dl of data.downloads || []) {
      if (dl.status === "downloading") {
        await fetch(`${baseUrl()}/api/download/${dl.id}/pause`, {
          method: "POST",
          headers: authHeaders()
        });
      }
    }
    fetchDownloads();
  });

  document.getElementById("btn-resume-all").addEventListener("click", async () => {
    if (!currentSettings) return;
    const resp = await fetch(`${baseUrl()}/api/downloads`, { headers: authHeaders() });
    const data = await resp.json();
    for (const dl of data.downloads || []) {
      if (dl.status === "paused" || dl.status === "stopped") {
        await fetch(`${baseUrl()}/api/download/${dl.id}/resume`, {
          method: "POST",
          headers: authHeaders()
        });
      }
    }
    fetchDownloads();
  });

  document.getElementById("btn-options").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });

  setInterval(fetchDownloads, 2000);
}

document.addEventListener("DOMContentLoaded", init);
