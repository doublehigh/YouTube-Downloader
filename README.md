# ⚡ YouTube Downloader Studio

A fast, modern YouTube video and audio downloader powered by **Flask** and **yt-dlp**, featuring a glassmorphic dark-mode UI with live real-time progress indicators, video preview, quality selectors, and download history.

---

## ✨ Features

- **Ultra-Modern Glassmorphic UI**: Deep obsidian theme with crimson YouTube glowing accents, responsive layout, and micro-animations.
- **Instant Video Inspection**: Live thumbnail preview, duration badge, video channel, view count, and available resolution options (4K, 1440p, 1080p, 720p, 480p, 360p).
- **Video & Audio Modes**:
  - 🎥 **Video**: Download MP4/WebM in up to 4K resolution.
  - 🎵 **Audio Only**: Extract to MP3, M4A, WAV, or OPUS.
- **Real-Time Progress Tracking**: Server-Sent Events (SSE) provide smooth, live updates on percent completion, download speed (MB/s), ETA, and transferred bytes.
- **One-Click Actions**:
  - 📂 **Reveal in Folder**: Highlights downloaded files directly in Windows File Explorer.
  - 📋 **Auto Paste**: Quickly paste from clipboard with a single click.
- **History Drawer**: Keeps track of recent downloads with quick reveal buttons and thumbnail previews.
- **Multiple Launch Modes**:
  - Web UI: Auto-launches in your default web browser (`http://127.0.0.1:5000`).
  - Desktop Window: Optional frameless native desktop window via `pywebview`.
  - Classic CLI: Full command-line interface retained for scripts and automation.

---

## 🚀 Quick Start

### 1. Launch the UI

Double-click `run_ui.bat` or run in terminal:

```bash
python app.py
```
*(Your default web browser will open automatically to `http://127.0.0.1:5000`)*

### 2. Launch as Native Desktop Window (Optional)

```bash
python run_desktop.py
```

### 3. Command Line Interface (CLI)

You can still use the CLI at any time:

```bash
# Download a video
python yt_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Download audio only as MP3
python yt_downloader.py URL --audio-only --audio-format mp3

# Download with max resolution
python yt_downloader.py URL --resolution 1080

# Launch UI directly via CLI
python yt_downloader.py --ui
```

---

## ⚙️ Requirements & Installation

Dependencies:
- Python 3.10+
- `yt-dlp`
- `Flask`
- `pywebview` (optional, for standalone desktop window)

To install dependencies:
```bash
python -m pip install yt-dlp Flask pywebview
```

### Note on FFmpeg
- Progressive video downloads (with built-in audio) and raw audio downloads work out of the box without FFmpeg.
- For separate 1080p+ 60fps video/audio merging or MP3 transcoding, installing FFmpeg is recommended:
  ```powershell
  winget install Gyan.FFmpeg
  ```
