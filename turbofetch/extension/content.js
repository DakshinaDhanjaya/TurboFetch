(() => {
  const TF_VER = 8;
  if (window.__turbofetchVer === TF_VER) return;
  if (typeof window.__turbofetchCleanup === "function") {
    try {
      window.__turbofetchCleanup();
    } catch (_) {}
  }
  window.__turbofetchVer = TF_VER;
  const oldBtn = document.getElementById("turbofetch-floating-video-btn");
  if (oldBtn) oldBtn.remove();

  const MEDIA_EXT_RE = /\.(mp4|webm|m3u8|mpd)(\?.*)?$/i;
  const VIDEO_PAGE_RE = /^https?:\/\/(?:[a-z0-9-]+\.)?(?:youtube\.com\/(?:watch|shorts\/|live\/)|youtu\.be\/|vimeo\.com\/|dailymotion\.com\/video\/|twitch\.tv\/videos\/|tiktok\.com\/)/i;
  const detectedUrls = new Set();
  const timers = [];
  let floatingBtn = null;
  let lastCheckedHref = "";
  let perfObserver = null;
  let mutationObserver = null;
  let cleanedUp = false;

  function isContextValid() {
    try {
      return !cleanedUp && typeof chrome !== "undefined" && Boolean(chrome.runtime && chrome.runtime.id);
    } catch (_) {
      return false;
    }
  }

  function cleanup() {
    if (cleanedUp) return;
    cleanedUp = true;
    for (const id of timers) {
      clearTimeout(id);
    }
    timers.length = 0;
    if (perfObserver) {
      try {
        perfObserver.disconnect();
      } catch (_) {}
      perfObserver = null;
    }
    if (mutationObserver) {
      try {
        mutationObserver.disconnect();
      } catch (_) {}
      mutationObserver = null;
    }
    document.removeEventListener("click", onAltClick, true);
    window.removeEventListener("yt-navigate-finish", checkPageChange);
    window.removeEventListener("yt-page-data-updated", checkPageChange);
    window.removeEventListener("popstate", checkPageChange);
    if (floatingBtn) {
      floatingBtn.remove();
      floatingBtn = null;
    }
  }
  window.__turbofetchCleanup = cleanup;

  function safeSendMessage(msg) {
    if (!isContextValid()) {
      cleanup();
      return;
    }
    try {
      chrome.runtime.sendMessage(msg, () => {
        try {
          if (typeof chrome !== "undefined" && chrome.runtime) {
            void chrome.runtime.lastError;
          }
        } catch (_) {}
      });
    } catch (_) {
      cleanup();
    }
  }

  function onAltClick(event) {
    if (event.altKey) {
      safeSendMessage({ type: "ALT_BYPASS" });
    }
  }
  document.addEventListener("click", onAltClick, true);

  function isVideoPage() {
    return VIDEO_PAGE_RE.test(window.location.href);
  }

  function reportMedia(url) {
    if (!url || !url.startsWith("http") || detectedUrls.has(url)) return;
    detectedUrls.add(url);
    safeSendMessage({ type: "MEDIA_DETECTED", urls: [url] });
    updateFloatingButton();
  }

  function scanNode(root) {
    if (!root || root.nodeType !== 1) return;
    if (root.matches && root.matches("video, audio, source")) {
      const src = root.currentSrc || root.src;
      if (typeof src === "string" && src.startsWith("http")) reportMedia(src);
    }
    if (root.querySelectorAll) {
      root.querySelectorAll("video, audio, source").forEach((el) => {
        const src = el.currentSrc || el.src;
        if (typeof src === "string" && src.startsWith("http")) reportMedia(src);
      });
    }
  }

  function checkPageChange() {
    const href = window.location.href;
    if (href !== lastCheckedHref) {
      lastCheckedHref = href;
      if (isVideoPage()) {
        safeSendMessage({ type: "MEDIA_DETECTED", urls: [href] });
      }
    }
    updateFloatingButton();
  }

  function findPlayerContainer() {
    const onShorts = /^\/shorts\//i.test(window.location.pathname);
    if (onShorts) {
      const shortsHost =
        document.querySelector("ytd-reel-video-renderer[is-active] #shorts-player") ||
        document.querySelector("ytd-reel-video-renderer[is-active] .html5-video-player") ||
        document.querySelector("#shorts-player");
      if (shortsHost) return { host: shortsHost, insidePlayer: true, isShorts: true };
    }
    const ytPlayer = document.querySelector("#movie_player");
    if (ytPlayer) return { host: ytPlayer, insidePlayer: true, isShorts: false };
    const vid = document.querySelector("video");
    if (vid && vid.parentElement) {
      const rect = vid.getBoundingClientRect();
      if (rect.width >= 200 && rect.height >= 120) {
        return { host: vid.parentElement, insidePlayer: true, isShorts: onShorts };
      }
    }
    return { host: document.body || document.documentElement, insidePlayer: false, isShorts: onShorts };
  }

  function applyStyles(wrap, insidePlayer, isShorts) {
    if (!wrap || !wrap.style) return;
    const styles = {
      position: insidePlayer ? "absolute" : "fixed",
      top: insidePlayer ? (isShorts ? "62px" : "14px") : "auto",
      bottom: insidePlayer ? "auto" : "20px",
      right: insidePlayer ? "14px" : "20px",
      "z-index": "2147483647",
      display: "inline-flex",
      "align-items": "center",
      "justify-content": "flex-end",
      width: "auto",
      height: "auto",
      padding: "0",
      margin: "0",
      background: "transparent",
      border: "none",
      visibility: "visible",
      overflow: "visible"
    };
    for (const [k, v] of Object.entries(styles)) {
      wrap.style.setProperty(k, v, "important");
    }
  }

  function createSvgIcon() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("fill", "none");
    svg.style.setProperty("pointer-events", "none", "important");
    svg.style.setProperty("display", "block", "important");

    const arrow = document.createElementNS(ns, "path");
    arrow.setAttribute("d", "M12 4v10m0 0l-4-4m4 4l4-4");
    arrow.setAttribute("stroke", "#60a5fa");
    arrow.setAttribute("stroke-width", "2.4");
    arrow.setAttribute("stroke-linecap", "round");
    arrow.setAttribute("stroke-linejoin", "round");

    const tray = document.createElementNS(ns, "path");
    tray.setAttribute("d", "M5 17v2a1 1 0 001 1h12a1 1 0 001-1v-2");
    tray.setAttribute("stroke", "#f8fafc");
    tray.setAttribute("stroke-width", "2.2");
    tray.setAttribute("stroke-linecap", "round");
    tray.setAttribute("stroke-linejoin", "round");

    svg.appendChild(arrow);
    svg.appendChild(tray);
    return svg;
  }

  function createIconButton() {
    const wrap = document.createElement("div");
    wrap.id = "turbofetch-floating-video-btn";

    const quickPill = document.createElement("button");
    quickPill.type = "button";
    quickPill.textContent = "Quick MP4";
    quickPill.title = "Quick Download Best MP4 with TurboFetch";
    const pillStyles = {
      display: "none",
      "align-items": "center",
      height: "28px",
      padding: "0 10px",
      margin: "0 6px 0 0",
      background: "rgba(17, 26, 46, 0.92)",
      color: "#f8fafc",
      border: "1px solid #3b82f6",
      "border-radius": "14px",
      "font-family": '"Segoe UI", system-ui, sans-serif',
      "font-size": "11px",
      "font-weight": "600",
      cursor: "pointer",
      "white-space": "nowrap",
      "box-shadow": "0 4px 12px rgba(0, 0, 0, 0.45)"
    };
    for (const [k, v] of Object.entries(pillStyles)) {
      quickPill.style.setProperty(k, v, "important");
    }
    quickPill.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (isVideoPage()) {
        safeSendMessage({ type: "DOWNLOAD_VIDEO_QUICK", url: window.location.href });
      }
    });

    const btn = document.createElement("button");
    btn.type = "button";
    btn.title = "Choose Video Quality with TurboFetch";
    btn.setAttribute("aria-label", "Download Video with TurboFetch");
    const btnStyles = {
      display: "inline-flex",
      "align-items": "center",
      "justify-content": "center",
      width: "36px",
      height: "36px",
      padding: "0",
      margin: "0",
      background: "rgba(17, 26, 46, 0.85)",
      border: "1.5px solid #3b82f6",
      "border-radius": "50%",
      cursor: "pointer",
      visibility: "visible",
      opacity: "0.88",
      overflow: "hidden",
      transition: "transform 0.15s ease, opacity 0.15s ease",
      "box-shadow": "0 4px 12px rgba(0, 0, 0, 0.45)"
    };
    for (const [k, v] of Object.entries(btnStyles)) {
      btn.style.setProperty(k, v, "important");
    }
    btn.appendChild(createSvgIcon());

    wrap.appendChild(quickPill);
    wrap.appendChild(btn);

    let hoverTimer = null;
    wrap.addEventListener("mouseenter", () => {
      btn.style.setProperty("opacity", "1", "important");
      btn.style.setProperty("transform", "scale(1.08)", "important");
      if (isVideoPage()) {
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(() => {
          quickPill.style.setProperty("display", "inline-flex", "important");
        }, 280);
      }
    });
    wrap.addEventListener("mouseleave", () => {
      clearTimeout(hoverTimer);
      quickPill.style.setProperty("display", "none", "important");
      btn.style.setProperty("opacity", "0.88", "important");
      btn.style.setProperty("transform", "scale(1)", "important");
    });
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (isVideoPage()) {
        safeSendMessage({ type: "DOWNLOAD_VIDEO_PAGE", url: window.location.href });
      } else {
        const urls = Array.from(detectedUrls);
        if (urls.length > 0) {
          safeSendMessage({ type: "DOWNLOAD_MEDIA", url: urls[0] });
        }
      }
    });
    return wrap;
  }

  function ensureMounted() {
    const target = findPlayerContainer();
    if (!target.host) return false;
    if (!floatingBtn) {
      floatingBtn = createIconButton();
    }
    applyStyles(floatingBtn, target.insidePlayer, target.isShorts);
    if (floatingBtn.parentElement !== target.host) {
      target.host.appendChild(floatingBtn);
    }
    return true;
  }

  function updateFloatingButton() {
    const shouldShow = isVideoPage() || detectedUrls.size > 0;
    if (!shouldShow) {
      if (floatingBtn) floatingBtn.style.setProperty("display", "none", "important");
      return;
    }
    if (ensureMounted()) {
      floatingBtn.style.setProperty("display", "inline-flex", "important");
    }
  }

  if (typeof PerformanceObserver !== "undefined") {
    try {
      perfObserver = new PerformanceObserver((list) => {
        if (!isContextValid()) {
          cleanup();
          return;
        }
        for (const entry of list.getEntries()) {
          if (typeof entry.name === "string" && MEDIA_EXT_RE.test(entry.name)) {
            reportMedia(entry.name);
          }
        }
      });
      perfObserver.observe({ entryTypes: ["resource"] });
    } catch (_) {}
  }

  if (isContextValid() && chrome.runtime.onMessage) {
    try {
      chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
        if (!isContextValid()) return false;
        if (msg && msg.type === "COLLECT_LINKS") {
          const links = new Set();
          document.querySelectorAll("a[href]").forEach((a) => {
            if (a.href && (a.href.startsWith("http://") || a.href.startsWith("https://"))) {
              links.add(a.href);
            }
          });
          sendResponse({ links: Array.from(links) });
          return false;
        }
        return false;
      });
    } catch (_) {}
  }

  window.addEventListener("yt-navigate-finish", checkPageChange);
  window.addEventListener("yt-page-data-updated", checkPageChange);
  window.addEventListener("popstate", checkPageChange);
  checkPageChange();
  timers.push(setTimeout(checkPageChange, 800));
  timers.push(setTimeout(checkPageChange, 2500));
  if (document.body) {
    scanNode(document.body);
  }
  const observeTarget = document.body || document.documentElement;
  if (typeof MutationObserver !== "undefined" && observeTarget) {
    mutationObserver = new MutationObserver((mutations) => {
      if (!isContextValid()) {
        cleanup();
        return;
      }
      checkPageChange();
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          scanNode(node);
        }
      }
    });
    mutationObserver.observe(observeTarget, { childList: true, subtree: true });
  }
})();
