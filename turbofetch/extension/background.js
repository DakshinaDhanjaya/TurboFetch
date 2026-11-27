const DEFAULT_SETTINGS = {
  enabled: true,
  port: 29512,
  token: "",
  minSizeBytes: 1048576,
  fileTypes: [
    "exe", "msi", "zip", "rar", "7z", "tar", "gz", "iso",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "mp4", "mkv", "avi", "mov", "webm", "mp3", "flac", "wav", "apk"
  ],
  excludedDomains: []
};

let serverOnline = false;
let altBypassUntil = 0;
const bypassUrls = new Set();
const handledDownloadIds = new Set();
const tabMediaMap = new Map();

async function getSettings() {
  const stored = await chrome.storage.local.get(DEFAULT_SETTINGS);
  return { ...DEFAULT_SETTINGS, ...stored };
}

function serverBaseUrl(settings) {
  return `http://127.0.0.1:${settings.port || 29512}`;
}

async function checkServerStatus(timeoutMs = 1500) {
  const settings = await getSettings();
  if (!settings.token) {
    serverOnline = false;
    return false;
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${serverBaseUrl(settings)}/api/status`, {
      headers: { Authorization: `Bearer ${settings.token}` },
      signal: controller.signal
    });
    serverOnline = resp.ok;
    return serverOnline;
  } catch (_) {
    serverOnline = false;
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function getExtension(filename, url) {
  const cleanName = (filename || "").split("?")[0].split("#")[0];
  const fromName = cleanName.includes(".") ? cleanName.split(".").pop().toLowerCase() : "";
  if (fromName) return fromName;
  try {
    const u = new URL(url);
    const extParam = u.searchParams.get("ext");
    if (extParam) return extParam.toLowerCase().replace(/^\./, "");
    const base = u.pathname.split("/").pop() || "";
    if (base.includes(".")) return base.split(".").pop().toLowerCase();
  } catch (_) {}
  return "";
}

function isMediaOrBinaryMime(mime) {
  if (!mime) return false;
  const m = mime.toLowerCase();
  return (
    m.startsWith("video/") ||
    m.startsWith("audio/") ||
    m === "application/octet-stream" ||
    m === "application/zip" ||
    m === "application/x-rar-compressed" ||
    m === "application/x-7z-compressed" ||
    m === "application/x-msdownload" ||
    m === "application/pdf" ||
    m === "application/x-iso9660-image"
  );
}

function isDomainExcluded(url, excludedDomains) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return excludedDomains.some((d) => {
      const dom = d.trim().toLowerCase();
      return dom && (host === dom || host.endsWith(`.${dom}`));
    });
  } catch (_) {
    return false;
  }
}

async function getCookiesForUrl(url) {
  try {
    const list = await chrome.cookies.getAll({ url });
    const out = {};
    for (const c of list) {
      out[c.name] = c.value;
    }
    return out;
  } catch (_) {
    return {};
  }
}

const VIDEO_PAGE_RE = /^https?:\/\/(www\.|m\.)?(youtube\.com\/(watch|shorts\/|live\/)|youtu\.be\/|vimeo\.com\/|dailymotion\.com\/video\/|twitch\.tv\/videos\/|tiktok\.com\/)/i;

async function sendVideoToDesktopApp(url, quick = false) {
  const settings = await getSettings();
  if (!settings.token) {
    throw new Error("Extension not paired");
  }
  const cookies = await getCookiesForUrl(url);
  const resp = await fetch(`${serverBaseUrl(settings)}/api/video`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${settings.token}`
    },
    body: JSON.stringify({ url, cookies, quick })
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const result = await resp.json();
  notifyDownloadCaught(quick ? "Quick Downloading Video..." : "Opening Video Downloader...");
  return result;
}

async function sendToDesktopApp(payload) {
  const settings = await getSettings();
  if (!settings.token) {
    throw new Error("Extension not paired");
  }
  const cookies = await getCookiesForUrl(payload.url);
  const resp = await fetch(`${serverBaseUrl(settings)}/api/download`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${settings.token}`
    },
    body: JSON.stringify({
      ...payload,
      cookies,
      user_agent: navigator.userAgent
    })
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const result = await resp.json();
  notifyDownloadCaught(result.filename || payload.filename || payload.url);
  return result;
}

function notifyDownloadCaught(label) {
  try {
    if (chrome.action && chrome.action.setBadgeText) {
      chrome.action.setBadgeBackgroundColor({ color: "#2563eb" }, () => {
        void chrome.runtime.lastError;
      });
      chrome.action.setBadgeText({ text: "GO" }, () => {
        void chrome.runtime.lastError;
      });
      setTimeout(() => {
        try {
          chrome.action.setBadgeText({ text: "" }, () => {
            void chrome.runtime.lastError;
          });
        } catch (_) {}
      }, 3000);
    }
    if (chrome.notifications && chrome.notifications.create) {
      chrome.notifications.create(
        {
          type: "basic",
          iconUrl: "icons/icon128.png",
          title: "TurboFetch Caught Download",
          message: label || "Downloading with TurboFetch"
        },
        () => {
          void chrome.runtime.lastError;
        }
      );
    }
  } catch (_) {}
}

async function matchesFilter(item, filenameHint) {
  const settings = await getSettings();
  if (!settings.enabled || !settings.token) {
    return false;
  }
  if (Date.now() < altBypassUntil) {
    return false;
  }
  const url = item.finalUrl || item.url || "";
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    return false;
  }
  if (bypassUrls.has(url)) {
    bypassUrls.delete(url);
    return false;
  }
  if (isDomainExcluded(url, settings.excludedDomains || [])) {
    return false;
  }
  const fileSize = typeof item.fileSize === "number" ? item.fileSize : -1;
  if (fileSize > 0 && fileSize < (settings.minSizeBytes || 0)) {
    return false;
  }
  const ext = getExtension(filenameHint || item.filename, url);
  const allowedExts = (settings.fileTypes || []).map((e) => e.toLowerCase());
  const matchesType = Boolean(ext && allowedExts.includes(ext));
  const matchesMime = isMediaOrBinaryMime(item.mime);
  const matchesSize = fileSize >= (settings.minSizeBytes || 1048576);
  return matchesType || matchesMime || matchesSize;
}

async function interceptDownload(item, filenameHint, suggest) {
  if (handledDownloadIds.has(item.id)) {
    if (suggest) suggest();
    return;
  }
  const match = await matchesFilter(item, filenameHint);
  if (!match) {
    if (suggest) suggest();
    return;
  }
  const online = await checkServerStatus(800);
  if (!online) {
    if (suggest) suggest();
    return;
  }
  handledDownloadIds.add(item.id);
  const url = item.finalUrl || item.url;
  if (suggest) {
    try {
      suggest();
    } catch (_) {}
  }
  try {
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({ id: item.id });
  } catch (_) {}

  try {
    await sendToDesktopApp({
      url,
      filename: filenameHint || item.filename || "",
      referrer: item.referrer || "",
      size: item.fileSize || -1,
      mime_type: item.mime || ""
    });
  } catch (_) {
    serverOnline = false;
    bypassUrls.add(url);
    chrome.downloads.download({ url });
  }
}

if (chrome.downloads && chrome.downloads.onDeterminingFilename) {
  chrome.downloads.onDeterminingFilename.addListener((item, suggest) => {
    interceptDownload(item, item.filename, suggest);
    return true;
  });
} else if (chrome.downloads && chrome.downloads.onCreated) {
  chrome.downloads.onCreated.addListener((item) => {
    interceptDownload(item, item.filename, null);
  });
}

function setupContextMenus() {
  chrome.contextMenus.removeAll(() => {
    void chrome.runtime.lastError;
    chrome.contextMenus.create(
      {
        id: "turbofetch-single",
        title: "Download with TurboFetch",
        contexts: ["link", "image", "video", "audio"]
      },
      () => {
        void chrome.runtime.lastError;
      }
    );
    chrome.contextMenus.create(
      {
        id: "turbofetch-all",
        title: "Download all links on this page",
        contexts: ["page"]
      },
      () => {
        void chrome.runtime.lastError;
      }
    );
  });
}

async function injectContentScriptIntoOpenTabs() {
  if (!chrome.scripting || !chrome.tabs) return;
  try {
    const tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
    for (const tab of tabs) {
      if (
        tab.id !== undefined &&
        !tab.discarded &&
        tab.url &&
        !tab.url.startsWith("https://chrome.google.com/webstore") &&
        !tab.url.startsWith("https://chromewebstore.google.com")
      ) {
        chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ["content.js"]
        }).catch(() => {});
      }
    }
  } catch (_) {}
}

chrome.runtime.onInstalled.addListener(() => {
  setupContextMenus();
  checkServerStatus();
  injectContentScriptIntoOpenTabs();
});

chrome.runtime.onStartup.addListener(() => {
  setupContextMenus();
  checkServerStatus();
  injectContentScriptIntoOpenTabs();
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "turbofetch-single") {
    const targetUrl = info.linkUrl || info.srcUrl;
    if (!targetUrl) return;
    try {
      if (VIDEO_PAGE_RE.test(targetUrl)) {
        await sendVideoToDesktopApp(targetUrl);
      } else {
        await sendToDesktopApp({
          url: targetUrl,
          referrer: info.pageUrl || (tab ? tab.url : "")
        });
      }
    } catch (_) {
      chrome.downloads.download({ url: targetUrl });
    }
  } else if (info.menuItemId === "turbofetch-all" && tab && tab.id !== undefined) {
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { type: "COLLECT_LINKS" });
      const links = (response && response.links) || [];
      if (links.length === 0) return;
      const settings = await getSettings();
      await fetch(`${serverBaseUrl(settings)}/api/download/batch`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${settings.token}`
        },
        body: JSON.stringify({ urls: links.map((u) => ({ url: u })) })
      });
    } catch (_) {}
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ALT_BYPASS") {
    altBypassUntil = Date.now() + 2500;
    sendResponse({ ok: true });
    return false;
  }
  if (message.type === "MEDIA_DETECTED" && sender.tab && sender.tab.id !== undefined) {
    const tabId = sender.tab.id;
    const existing = tabMediaMap.get(tabId) || [];
    const merged = Array.from(new Set([...existing, ...(message.urls || [])]));
    tabMediaMap.set(tabId, merged);
    sendResponse({ ok: true });
    return false;
  }
  if (message.type === "DOWNLOAD_VIDEO_PAGE" || message.type === "DOWNLOAD_VIDEO_QUICK") {
    const isQuick = message.type === "DOWNLOAD_VIDEO_QUICK";
    sendVideoToDesktopApp(message.url, isQuick)
      .then((res) => sendResponse({ ok: true, res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (message.type === "DOWNLOAD_MEDIA") {
    const handler = VIDEO_PAGE_RE.test(message.url || "")
      ? sendVideoToDesktopApp(message.url)
      : sendToDesktopApp({
          url: message.url,
          referrer: sender.tab ? sender.tab.url : ""
        });
    handler
      .then((res) => sendResponse({ ok: true, res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (message.type === "GET_STATE") {
    checkServerStatus()
      .then(async (online) => {
        const settings = await getSettings();
        const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
        let media = activeTab && activeTab.id !== undefined ? (tabMediaMap.get(activeTab.id) || []) : [];
        if (activeTab && activeTab.url && VIDEO_PAGE_RE.test(activeTab.url) && !media.includes(activeTab.url)) {
          media = [activeTab.url, ...media];
        }
        sendResponse({ online, settings, media });
      })
      .catch(() => {
        sendResponse({ online: false, settings: DEFAULT_SETTINGS, media: [] });
      });
    return true;
  }
  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  tabMediaMap.delete(tabId);
});

setInterval(checkServerStatus, 30000);
checkServerStatus();
