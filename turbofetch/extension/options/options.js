const DEFAULT_OPTIONS = {
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

async function loadOptions() {
  const opts = await chrome.storage.local.get(DEFAULT_OPTIONS);
  document.getElementById("port").value = opts.port || 29512;
  document.getElementById("token").value = opts.token || "";
  document.getElementById("min-size").value = ((opts.minSizeBytes || 0) / 1048576).toFixed(1);
  document.getElementById("file-types").value = (opts.fileTypes || []).join(", ");
  document.getElementById("excluded-domains").value = (opts.excludedDomains || []).join("\n");
}

async function saveOptions() {
  const port = parseInt(document.getElementById("port").value, 10) || 29512;
  const token = document.getElementById("token").value.trim();
  const minMb = parseFloat(document.getElementById("min-size").value);
  const minSizeBytes = Math.max(0, Math.round((isNaN(minMb) ? 1 : minMb) * 1048576));
  const fileTypes = document.getElementById("file-types").value
    .split(",")
    .map((s) => s.trim().toLowerCase().replace(/^\./, ""))
    .filter(Boolean);
  const excludedDomains = document.getElementById("excluded-domains").value
    .split(/\r?\n/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);

  await chrome.storage.local.set({
    port,
    token,
    minSizeBytes,
    fileTypes,
    excludedDomains
  });
  document.getElementById("save-status").textContent = "Settings saved.";
}

async function pairWithApp() {
  const port = parseInt(document.getElementById("port").value, 10) || 29512;
  const token = document.getElementById("token").value.trim();
  const statusEl = document.getElementById("pair-status");
  if (!token) {
    statusEl.textContent = "Enter the pairing token from TurboFetch desktop Settings.";
    return;
  }
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/api/pair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ extension_id: chrome.runtime.id, token })
    });
    if (!resp.ok) {
      statusEl.textContent = "Pairing failed: invalid token.";
      return;
    }
    await chrome.storage.local.set({ port, token });
    statusEl.textContent = "Successfully paired with TurboFetch desktop app.";
  } catch (_) {
    statusEl.textContent = "Could not reach TurboFetch desktop app on 127.0.0.1.";
  }
}

async function resetOptions() {
  await chrome.storage.local.set(DEFAULT_OPTIONS);
  await loadOptions();
  document.getElementById("save-status").textContent = "Reset to defaults.";
}

document.addEventListener("DOMContentLoaded", () => {
  loadOptions();
  document.getElementById("btn-save").addEventListener("click", saveOptions);
  document.getElementById("btn-pair").addEventListener("click", pairWithApp);
  document.getElementById("btn-reset").addEventListener("click", resetOptions);
});
