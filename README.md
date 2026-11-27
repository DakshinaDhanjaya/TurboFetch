# TurboFetch Download Manager

![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11%20(64--bit)-2563eb)
![Python](https://img.shields.io/badge/Python-3.11%2B-3b82f6)
![UI](https://img.shields.io/badge/UI-PySide6%20(Qt6)-1d4ed8)
![License](https://img.shields.io/badge/License-MIT-22c55e)

**TurboFetch** is a free, open-source, high-speed download manager for Windows built with Python, PySide6, `asyncio` / `httpx`, SQLite, `yt-dlp`, and a cross-browser Manifest V3 / Firefox extension. Designed to combine IDM-grade acceleration and browser catching with a low-idle-CPU dark-blue Fluent UI.

---

## Features

### Core Acceleration & Reliability
- **Dynamic Multi-Connection Engine**: Splits files across up to 32 parallel HTTP/HTTPS range connections and dynamically bisects the largest active segment when another finishes.
- **Crash-Safe Resume**: Persists segment byte offsets to SQLite (WAL mode) and verifies `ETag`, `Last-Modified`, and `Content-Length` before resuming.
- **Windows File-Lock Resilience**: Automatic completion-rename retries handle brief Windows Defender / Explorer scan locks on multi-gigabyte downloads.
- **Token-Bucket Bandwidth Limiter**: Supports both global speed limits and per-download speed caps (`KB/s`).
- **Protocol & Auth Support**: HTTP/HTTPS/SOCKS5 proxy routing, HTTP Basic Auth, custom Referer/headers, cookie forwarding, and `MD5` / `SHA1` / `SHA256` checksum verification.

### Video & Media Grabber (`yt-dlp` + `ffmpeg` + `mutagen`)
- **Windows Media Player Native Playback**: Automatically prefers H.264 (`avc1`) + AAC (`mp4a`) streams and remuxes into `.mp4` with `-movflags +faststart` using bundled `imageio-ffmpeg` and `mutagen` (cover art embedding without requiring external `ffprobe`).
- **Multi-Quality & Duplicate Safety**: Download the same video in multiple resolutions (`2160p`, `1440p`, `1080p`, `720p`, `480p`, `360p`, `Best`, or `Audio MP3`) without filename collisions (`Video [1080p].mp4`, `Video [720p].mp4`). Supports both landscape and portrait YouTube Shorts aspect ratios.
- **Live UTF-8 Streaming Progress**: Unbuffered subprocess streaming updates video title, file size, percentage, speed, and ETA live during transfer.
- **Playlists, Subtitles & Custom Folders**: Split playlist entries into separate queue items, download `.srt` subtitles, embed thumbnails, and pick custom output folders.

### Desktop Productivity & UI
- **Midnight-Navy & Sapphire-Blue Fluent Theme**: Dark, Light, and System theme modes with adjustable font size.
- **Live Speed Graph & Segment Visualizer**: Real-time throughput chart and per-segment progress bar with zero idle repaint CPU cost.
- **Site Grabber**: Scan any webpage for downloadable archives, executables, documents, media, and images with extension/keyword filtering.
- **Floating Drop Basket**: Always-on-top mini drag-and-drop dropzone showing active download count and live speed.
- **Queues & Power Scheduler**: Multi-queue management with drag-and-drop priority reordering and scheduled start/stop plus `Sleep` / `Hibernate` / `Shutdown` / `Close` completion actions.
- **Security & Disk Checks**: Optional Windows Defender post-download scan (`MpCmdRun.exe`), free disk space warnings, `.json` + `.txt` batch import/export, expired URL refresh, and **English (`en`) / Sinhala (`si`)** UI switching.

### Browser Extension (Chrome / Brave / Edge / Firefox)
- Automatically intercepts browser downloads with graceful browser fallback when the desktop app is offline and `Alt+Click` bypass.
- Optional IDM-style File Info confirmation dialog before starting browser downloads.
- Floating circular download button on video players (positioned cleanly to avoid YouTube Shorts controls) with a hover **Quick MP4** shortcut and inline DOM SVG rendering.
- Extension popup with per-download **Pause / Resume / Cancel** controls, active media detection, and desktop pairing.

---

## Project Structure

```text
TurboFetch/
├── turbofetch/
│   ├── app/
│   │   ├── db/            # SQLite persistence & models
│   │   ├── engine/        # Segmented downloader, yt-dlp runner, protocols, speed limiter
│   │   ├── scheduler/     # Queue manager & timed scheduler
│   │   ├── server/        # Authenticated localhost HTTP/WebSocket bridge
│   │   ├── ui/            # PySide6 MainWindow, dialogs, SpeedGraph, DropBasket, SiteGrabber
│   │   └── utils/         # Config, Defender scan, checksum, clipboard, i18n, updater
│   ├── extension/         # Chromium MV3 + Firefox WebExtension
│   ├── installer/         # Standalone setup wizard, build_installer.py, and Inno Setup script
│   └── tests/             # Unit & integration test suite
├── .github/workflows/     # Continuous Integration workflow
├── build.bat              # Automated test, PyInstaller stage, and Setup.exe builder
├── requirements.txt       # Pinned runtime & build dependencies
└── pyproject.toml
```

---

## Quick Start (Development)

### Prerequisites
- Windows 10 or Windows 11 (64-bit)
- Python 3.11 or newer (with `Add python.exe to PATH` enabled)
- *(Optional)* Node.js for solving YouTube JS signature challenges in `yt-dlp`

### Run from Source
```powershell
git clone https://github.com/DakshinaDhanjaya/TurboFetch.git
cd TurboFetch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m turbofetch.app.main
```

### Run Tests
```powershell
python -m unittest discover -s turbofetch/tests -v
```

---

## Installing the Browser Extension

1. Open Chrome, Brave, or Edge and navigate to `chrome://extensions` (`brave://extensions` / `edge://extensions`).
2. Enable **Developer mode**.
3. Click **Load unpacked** and select `turbofetch\extension` (or click **Settings > Extension > Open Extension Folder** inside TurboFetch).
4. In TurboFetch, open **Settings > Extension**, copy the **Pairing Token**, open the extension's **Options** page, paste the token, click **Pair**, and save.

*(For Firefox, rename or load `turbofetch/extension/manifest_firefox.json` as `manifest.json` via `about:debugging#/runtime/this-firefox`.)*

---

## Building the Windows Setup Installer (`TurboFetch-Setup.exe`)

Run the automated build script in PowerShell or Command Prompt:

```powershell
.\build.bat
```

This runs the full test suite, packages the application with PyInstaller into `build\portable\TurboFetch`, and outputs a single shareable installer at **`dist\TurboFetch-Setup.exe`** (using Inno Setup 6 if installed, or the built-in standalone Setup Wizard automatically).

---

## License

Released under the [MIT License](LICENSE).
