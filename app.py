#!/usr/bin/env python3
"""
YouTube Downloader Web Application Backend
Powered by Flask & yt-dlp
"""

import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Please run: pip install yt-dlp")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Paths and Config
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DOWNLOAD_DIR = BASE_DIR / "downloads"
DEFAULT_DOWNLOAD_DIR.mkdir(exist_ok=True)
CONFIG_FILE = BASE_DIR / "config.json"
HISTORY_FILE = BASE_DIR / "downloads_history.json"
PENDING_FILE = BASE_DIR / "pending_downloads.json"

# Ensure ffmpeg.exe in BASE_DIR or imageio_ffmpeg is on PATH
if str(BASE_DIR) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(BASE_DIR) + os.pathsep + os.environ.get("PATH", "")

# In-memory download task tracker
# task_id -> { status, progress, speed, eta, title, filename, error, total_bytes, downloaded_bytes, ... }
tasks = {}
tasks_lock = threading.Lock()

# Default yt-dlp extractor args to prevent YouTube's 'This video is not available' / client restrictions
DEFAULT_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["android", "web"]
    }
}


# Pause control: task_id -> threading.Event (set=running, clear=paused)
pause_events = {}

# Task cancellation tracking
cancelled_tasks = set()
cancelled_lock = threading.Lock()

class DownloadCancelledError(Exception):
    pass

def is_task_cancelled(task_id):
    with cancelled_lock:
        return task_id in cancelled_tasks

def request_task_cancel(task_id):
    with cancelled_lock:
        cancelled_tasks.add(task_id)

def clear_task_cancel(task_id):
    with cancelled_lock:
        cancelled_tasks.discard(task_id)

def delete_uncompleted_download(download_dir, title="", filepath=""):
    """Delete partial and temporary download files (.part, .ytdl, .temp, and stream fragments)."""
    try:
        d = Path(download_dir).resolve() if download_dir else None
        if filepath:
            p = Path(filepath).resolve()
            if not d:
                d = p.parent
            stem = p.stem.lower()
            # Check direct candidates and extension variations
            candidates = [
                p,
                p.with_suffix(p.suffix + ".part"),
                p.with_suffix(p.suffix + ".ytdl"),
                p.with_suffix(p.suffix + ".temp"),
                Path(str(p) + ".part"),
                Path(str(p) + ".ytdl"),
                Path(str(p) + ".temp")
            ]
            for cand in candidates:
                if cand.exists() and cand.is_file():
                    try:
                        cand.unlink()
                    except Exception:
                        pass
            
            # Check for format stream fragments matching file stem (e.g. video.f137.mp4.part)
            if p.parent.exists() and len(stem) >= 3:
                for f in p.parent.glob(f"*{p.stem}*"):
                    if f.is_file() and any(f.name.lower().endswith(ext) for ext in [".part", ".ytdl", ".temp", ".part-Frag"]):
                        try:
                            f.unlink()
                        except Exception:
                            pass

        if d and d.exists():
            clean_title = re.sub(r'[\W_]+', ' ', title).strip().lower() if title else ""
            title_words = [w for w in clean_title.split() if len(w) >= 4] if clean_title else []

            # Check all .part, .ytdl, .temp files in download directory
            for f in list(d.glob("*.part")) + list(d.glob("*.ytdl")) + list(d.glob("*.temp")):
                if not f.is_file():
                    continue
                f_lower = f.name.lower()
                should_delete = False
                if not title:
                    should_delete = True
                elif clean_title and (clean_title in f_lower or f_lower in clean_title):
                    should_delete = True
                elif title_words and any(w in f_lower for w in title_words[:3]):
                    should_delete = True
                
                if should_delete:
                    try:
                        f.unlink()
                    except Exception:
                        pass
    except Exception as e:
        print(f"Error cleaning uncompleted download: {e}")

def get_local_ip():
    """Find local network IP address for mobile connections."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# --- Pending Downloads Persistence ---
def load_pending():
    """Load pending (interrupted) downloads from disk."""
    if PENDING_FILE.exists():
        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_pending(pending):
    """Save pending downloads to disk."""
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2)

def add_pending_download(task_id, url, options, title="", thumbnail=""):
    """Record a download as pending so it can be resumed after restart."""
    pending = load_pending()
    pending[task_id] = {
        "task_id": task_id,
        "url": url,
        "title": title or options.get("title", "Unknown"),
        "thumbnail": thumbnail or options.get("thumbnail", ""),
        "options": options,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_pending(pending)

def remove_pending_download(task_id):
    """Remove a download from pending (completed or permanently failed)."""
    pending = load_pending()
    if task_id in pending:
        del pending[task_id]
        save_pending(pending)

# Config helper
def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "download_dir": str(DEFAULT_DOWNLOAD_DIR),
        "preferred_quality": "1080",
        "preferred_audio": "mp3",
        "max_concurrent_downloads": 3,
    }

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# --- Concurrency Limiter & Queue System ---
DEFAULT_MAX_CONCURRENT = 3
_init_cfg = load_config()
_init_max = int(_init_cfg.get("max_concurrent_downloads", DEFAULT_MAX_CONCURRENT))
download_semaphore = threading.BoundedSemaphore(max(1, min(_init_max, 10)))
current_concurrency = _init_max
concurrency_lock = threading.Lock()

def set_concurrency_limit(new_limit):
    global download_semaphore, current_concurrency
    with concurrency_lock:
        new_limit = max(1, min(int(new_limit), 10))
        if new_limit != current_concurrency:
            current_concurrency = new_limit
            cfg = load_config()
            cfg["max_concurrent_downloads"] = new_limit
            save_config(cfg)
            download_semaphore = threading.BoundedSemaphore(new_limit)

# Universal Regex to detect & extract any video/media URLs (YouTube, TikTok, Instagram, Twitter/X, Facebook, etc.)
UNIVERSAL_URL_REGEX = re.compile(
    r'(https?://[^\s<>"\'{}|\\^`]+)',
    re.IGNORECASE
)

def extract_youtube_urls(text_or_list):
    """Extract, normalize, and de-duplicate valid URLs from text or a list of lines."""
    if isinstance(text_or_list, list):
        raw_text = "\n".join(str(x) for x in text_or_list)
    else:
        raw_text = str(text_or_list or "")

    matches = UNIVERSAL_URL_REGEX.findall(raw_text)
    seen = set()
    cleaned = []
    for u in matches:
        u_clean = u.strip().rstrip('.,;:!?"\'()[]{}<>')
        if u_clean and u_clean not in seen:
            seen.add(u_clean)
            cleaned.append(u_clean)

    # Fallback: line-by-line check for lines starting with http
    if not cleaned:
        for line in raw_text.splitlines():
            l = line.strip().rstrip('.,;:!?"\'()[]{}<>')
            if l.startswith("http://") or l.startswith("https://"):
                if l not in seen:
                    seen.add(l)
                    cleaned.append(l)

    return cleaned

# Backward compatibility alias
extract_media_urls = extract_youtube_urls

# History helper
def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def add_history_entry(entry):
    history = load_history()
    # Prepend newest
    history.insert(0, entry)
    # Keep last 100 entries
    history = history[:100]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

def get_ffmpeg_path():
    """Find ffmpeg.exe from project root, system PATH, or imageio-ffmpeg."""
    local_ffmpeg = BASE_DIR / "ffmpeg.exe"
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None

def is_ffmpeg_installed():
    return get_ffmpeg_path() is not None

def format_bytes(bytes_val):
    if not bytes_val or bytes_val <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"

def format_duration(seconds):
    if not seconds:
        return "Unknown"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

@app.route("/")
@app.route("/downloads")
def index():
    return render_template("index.html")

@app.route("/api/system-status")
def system_status():
    cfg = load_config()
    return jsonify({
        "ffmpeg_installed": is_ffmpeg_installed(),
        "download_dir": cfg.get("download_dir", str(DEFAULT_DOWNLOAD_DIR)),
        "download_dir_exists": Path(cfg.get("download_dir", "")).exists(),
        "max_concurrent_downloads": cfg.get("max_concurrent_downloads", DEFAULT_MAX_CONCURRENT),
        "local_ip": get_local_ip(),
    })

@app.route("/api/config", methods=["GET", "POST"])
def config_endpoint():
    if request.method == "POST":
        data = request.get_json() or {}
        new_dir = data.get("download_dir")
        if new_dir:
            try:
                Path(new_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return jsonify({"success": False, "error": f"Invalid directory: {str(e)}"}), 400
        new_concurrent = data.get("max_concurrent_downloads")
        if new_concurrent is not None:
            try:
                set_concurrency_limit(int(new_concurrent))
            except Exception:
                pass
        cfg = load_config()
        cfg.update(data)
        save_config(cfg)
        return jsonify({"success": True, "config": cfg})
    return jsonify(load_config())

@app.route("/api/history", methods=["GET", "DELETE"])
def history_endpoint():
    if request.method == "DELETE":
        if HISTORY_FILE.exists():
            try:
                HISTORY_FILE.unlink()
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500
        return jsonify({"success": True, "history": []})
    return jsonify({"history": load_history()})

@app.route("/api/info", methods=["POST"])
def get_video_info():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "extractor_args": DEFAULT_EXTRACTOR_ARGS,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({"error": "Failed to extract information."}), 404

            is_playlist = "entries" in info
            if is_playlist:
                raw_entries = list(info.get("entries", []))
                # Filter out any None entries (deleted/private videos)
                valid_entries = [e for e in raw_entries if e]
                sample_thumb = ""
                if valid_entries:
                    sample_thumb = valid_entries[0].get("thumbnail") or (
                        valid_entries[0].get("thumbnails")[-1]["url"]
                        if valid_entries[0].get("thumbnails")
                        else ""
                    )
                    if not sample_thumb and valid_entries[0].get("id"):
                        sample_thumb = f"https://i.ytimg.com/vi/{valid_entries[0]['id']}/mqdefault.jpg"

                formatted_entries = []
                for idx, e in enumerate(valid_entries, start=1):
                    v_id = e.get("id") or ""
                    v_url = e.get("url") or ""
                    if not v_url.startswith("http") and v_id:
                        v_url = f"https://www.youtube.com/watch?v={v_id}"

                    v_thumb = e.get("thumbnail") or ""
                    if not v_thumb and e.get("thumbnails"):
                        v_thumb = e["thumbnails"][-1].get("url", "")
                    if not v_thumb and v_id:
                        v_thumb = f"https://i.ytimg.com/vi/{v_id}/mqdefault.jpg"
                    if not v_thumb:
                        v_thumb = sample_thumb

                    formatted_entries.append({
                        "index": idx,
                        "id": v_id,
                        "title": e.get("title") or f"Video #{idx}",
                        "url": v_url,
                        "duration": format_duration(e.get("duration")),
                        "thumbnail": v_thumb,
                    })

                return jsonify({
                    "is_playlist": True,
                    "title": info.get("title", "Playlist"),
                    "item_count": len(valid_entries),
                    "thumbnail": sample_thumb,
                    "uploader": info.get("uploader") or info.get("channel") or "Unknown",
                    "url": url,
                    "resolutions": [1080, 720, 480, 360],
                    "entries": formatted_entries,
                })

            # Single Video extraction
            formats = info.get("formats", [])
            available_resolutions = set()
            has_video = False
            has_audio = False

            for f in formats:
                h = f.get("height")
                vcodec = f.get("vcodec")
                acodec = f.get("acodec")
                if vcodec and vcodec != "none" and h:
                    has_video = True
                    available_resolutions.add(h)
                if acodec and acodec != "none":
                    has_audio = True

            sorted_resolutions = sorted(list(available_resolutions), reverse=True)
            # Filter standard common resolutions
            common_resolutions = [r for r in sorted_resolutions if r in [2160, 1440, 1080, 720, 480, 360, 240, 144]]
            if not common_resolutions and sorted_resolutions:
                common_resolutions = sorted_resolutions

            thumbnails = info.get("thumbnails", [])
            best_thumb = info.get("thumbnail") or (thumbnails[-1]["url"] if thumbnails else "")

            return jsonify({
                "is_playlist": False,
                "id": info.get("id"),
                "title": info.get("title"),
                "uploader": info.get("uploader") or info.get("channel") or "Unknown",
                "duration": format_duration(info.get("duration")),
                "duration_raw": info.get("duration"),
                "views": info.get("view_count"),
                "thumbnail": best_thumb,
                "upload_date": info.get("upload_date"),
                "resolutions": common_resolutions,
                "has_audio": has_audio,
                "has_video": has_video,
                "webpage_url": info.get("webpage_url") or url,
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_download_thread(task_id, url, options):
    cfg = load_config()
    download_dir = Path(cfg.get("download_dir") or DEFAULT_DOWNLOAD_DIR)
    download_dir.mkdir(parents=True, exist_ok=True)

    is_audio_only = options.get("audio_only", False)
    resolution = options.get("resolution")
    audio_format = options.get("audio_format", "mp3")
    is_playlist = options.get("is_playlist", False)
    ffmpeg_exe = get_ffmpeg_path()
    ffmpeg_available = ffmpeg_exe is not None

    outtmpl = str(download_dir / "%(title)s.%(ext)s")
    if is_playlist:
        outtmpl = str(download_dir / "%(playlist)s" / "%(title)s.%(ext)s")

    def progress_hook(d):
        if is_task_cancelled(task_id):
            raise DownloadCancelledError("Download cancelled by user")

        # Block here if the task is paused (wait until event is set again)
        evt = pause_events.get(task_id)
        if evt:
            evt.wait()  # Blocks if cleared (paused), returns immediately if set (running)

        if is_task_cancelled(task_id):
            raise DownloadCancelledError("Download cancelled by user")

        with tasks_lock:
            if task_id not in tasks:
                return
            t = tasks[task_id]
            status = d.get("status")

            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                # Only update status to downloading if not paused
                if t["status"] != "paused":
                    t["status"] = "downloading"
                t["speed"] = d.get("_speed_str", "").strip() or "Calculating..."
                t["eta"] = d.get("_eta_str", "").strip() or "Unknown"
                t["total_bytes"] = total
                t["downloaded_bytes"] = downloaded
                t["percent"] = (
                    round((downloaded / total) * 100, 1)
                    if total > 0
                    else (float(d.get("_percent_str", "0").replace("%", "").strip()) if d.get("_percent_str") else 0.0)
                )
                t["filename"] = os.path.basename(d.get("filename", ""))

                # If playlist, update currently downloading item title
                info_dict = d.get("info_dict") or {}
                cur_title = info_dict.get("title")
                if cur_title:
                    t["current_item"] = cur_title

            elif status == "finished":
                t["status"] = "processing"
                t["percent"] = 100.0
                t["filename"] = os.path.basename(d.get("filename", ""))
                t["filepath"] = d.get("filename", "")

    ydl_opts = {
        "outtmpl": outtmpl,
        "progress_hooks": [progress_hook],
        "noplaylist": not is_playlist,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,  # Resume partially downloaded files
        "retries": 10,  # Auto-retry on temporary connection/server errors
        "fragment_retries": 10,
        "skip_unavailable_fragments": False,
        "socket_timeout": 30,
        "extractor_args": DEFAULT_EXTRACTOR_ARGS,
    }

    # Selective playlist items support (e.g. "1,3,5")
    playlist_items = options.get("playlist_items")
    if is_playlist and playlist_items:
        if isinstance(playlist_items, list):
            ydl_opts["playlist_items"] = ",".join(str(x) for x in playlist_items)
        else:
            ydl_opts["playlist_items"] = str(playlist_items)
        ydl_opts["noplaylist"] = False

    if ffmpeg_exe:
        ydl_opts["ffmpeg_location"] = ffmpeg_exe

    if is_audio_only:
        if ffmpeg_available:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "192",
            }]
        else:
            # Fallback when ffmpeg is not available: download best raw audio
            ydl_opts["format"] = "bestaudio/best"
    else:
        # Check resolution specification
        is_auto_res = not resolution or str(resolution).lower() in ("auto", "best")
        if ffmpeg_available:
            if not is_auto_res:
                # Fallback chain:
                # 1. Video <= requested height + best audio
                # 2. Single progressive format <= requested height
                # 3. Best video + best audio (auto-select best available if requested is unavailable)
                # 4. Best single format
                ydl_opts["format"] = (
                    f"bestvideo[height<={resolution}]+bestaudio/"
                    f"best[height<={resolution}]/"
                    f"bestvideo+bestaudio/"
                    f"best"
                )
            else:
                ydl_opts["format"] = "bestvideo+bestaudio/best"
        else:
            # When ffmpeg is not present, merge is not supported so we select progressive streams with fallback
            if not is_auto_res:
                ydl_opts["format"] = (
                    f"best[height<={resolution}]/"
                    f"best[height>={resolution}]/"
                    f"best"
                )
            else:
                ydl_opts["format"] = "best"

    # Wait for available concurrency slot
    if is_task_cancelled(task_id):
        delete_uncompleted_download(download_dir, options.get("title", ""), "")
        remove_pending_download(task_id)
        return

    download_semaphore.acquire()
    try:
        with tasks_lock:
            if task_id not in tasks or tasks[task_id].get("dismissed") or is_task_cancelled(task_id):
                return
            tasks[task_id]["status"] = "starting"
            tasks[task_id]["speed"] = "Connecting..."
            if not tasks[task_id].get("title") or tasks[task_id]["title"].startswith("Queued"):
                tasks[task_id]["title"] = "Connecting to source..."

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if not is_playlist:
                # Extract video info first to store metadata and detect actual resolution
                meta = ydl.extract_info(url, download=False)
                video_title = meta.get("title", "Video") if meta else "Video"
                thumb = meta.get("thumbnail") or "" if meta else ""

                # Detect actual resolution that will be downloaded
                actual_quality_label = "Best"
                if is_audio_only:
                    actual_quality_label = audio_format.upper()
                elif meta:
                    formats = meta.get("formats", [])
                    heights = sorted(list(set(f.get("height") for f in formats if f.get("height"))), reverse=True)
                    if not is_auto_res:
                        res_int = int(resolution)
                        if res_int in heights:
                            actual_quality_label = f"{res_int}p"
                        else:
                            smaller = [h for h in heights if h <= res_int]
                            chosen = smaller[0] if smaller else (heights[-1] if heights else res_int)
                            actual_quality_label = f"{chosen}p (Auto-fallback)"
                    else:
                        top_h = heights[0] if heights else None
                        actual_quality_label = f"{top_h}p (Auto)" if top_h else "Auto"
            else:
                # For playlists, fast initialize with passed metadata
                video_title = options.get("title") or "Playlist"
                thumb = options.get("thumbnail") or ""
                actual_quality_label = audio_format.upper() if is_audio_only else (f"{resolution}p" if resolution and resolution != "auto" else "Auto (Best)")

            with tasks_lock:
                tasks[task_id]["title"] = video_title
                tasks[task_id]["thumbnail"] = thumb
                tasks[task_id]["quality"] = actual_quality_label

            ydl.download([url])

        with tasks_lock:
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["percent"] = 100.0
            filepath = tasks[task_id].get("filepath") or str(download_dir / f"{video_title}")
            filename = tasks[task_id].get("filename") or os.path.basename(filepath)

            # Record to history
            add_history_entry({
                "id": str(uuid.uuid4()),
                "title": video_title,
                "url": url,
                "filename": filename,
                "filepath": filepath,
                "thumbnail": thumb,
                "type": "audio" if is_audio_only else "video",
                "format": audio_format if is_audio_only else f"{resolution}p" if resolution else "Best",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        # Remove from pending since download succeeded
        remove_pending_download(task_id)

    except DownloadCancelledError:
        with tasks_lock:
            if task_id in tasks and not tasks[task_id].get("dismissed"):
                tasks[task_id]["status"] = "cancelled"
                tasks[task_id]["speed"] = "Cancelled"
                tasks[task_id]["error"] = "Cancelled by user"
        delete_uncompleted_download(download_dir, video_title, tasks.get(task_id, {}).get("filepath"))
        remove_pending_download(task_id)

    except Exception as e:
        if is_task_cancelled(task_id) or "Download cancelled" in str(e):
            with tasks_lock:
                if task_id in tasks and not tasks[task_id].get("dismissed"):
                    tasks[task_id]["status"] = "cancelled"
                    tasks[task_id]["speed"] = "Cancelled"
                    tasks[task_id]["error"] = "Cancelled by user"
            delete_uncompleted_download(download_dir, video_title, tasks.get(task_id, {}).get("filepath"))
            remove_pending_download(task_id)
        else:
            with tasks_lock:
                if task_id in tasks and not tasks[task_id].get("dismissed"):
                    tasks[task_id]["status"] = "error"
                    tasks[task_id]["error"] = str(e)
    finally:
        clear_task_cancel(task_id)
        # Free slot for the next queued download
        download_semaphore.release()


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    task_id = str(uuid.uuid4())
    # Create pause event (set = running)
    evt = threading.Event()
    evt.set()
    pause_events[task_id] = evt

    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "url": url,
            "title": data.get("title") or "Fetching info...",
            "thumbnail": data.get("thumbnail") or "",
            "status": "starting",
            "percent": 0.0,
            "speed": "--",
            "eta": "--",
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "filename": "",
            "filepath": "",
            "error": None,
            "is_audio": bool(data.get("audio_only")),
            "quality": data.get("audio_format") if data.get("audio_only") else (f"{data.get('resolution')}p" if data.get("resolution") else "Best"),
            "start_time": time.time(),
            "is_playlist": bool(data.get("is_playlist")),
            "playlist_items": data.get("playlist_items"),
            "current_item": None,
            "options": data,
        }

    # Persist to pending file so it survives restarts
    add_pending_download(task_id, url, data, data.get("title", ""), data.get("thumbnail", ""))

    t = threading.Thread(
        target=run_download_thread,
        args=(task_id, url, data),
        daemon=True,
    )
    t.start()

    return jsonify({"success": True, "task_id": task_id})


@app.route("/api/parse-urls", methods=["POST"])
def parse_urls_endpoint():
    data = request.get_json() or {}
    text = data.get("text", "")
    urls = extract_youtube_urls(text)
    return jsonify({
        "urls": urls,
        "count": len(urls)
    })


@app.route("/api/batch-download", methods=["POST"])
def batch_download_endpoint():
    data = request.get_json() or {}
    raw_urls = data.get("urls", [])

    if isinstance(raw_urls, str):
        urls = extract_youtube_urls(raw_urls)
    elif isinstance(raw_urls, list):
        urls = []
        for item in raw_urls:
            extracted = extract_youtube_urls(item)
            if extracted:
                urls.extend(extracted)
            elif str(item).strip().startswith("http"):
                urls.append(str(item).strip())
        seen = set()
        deduped = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        urls = deduped
    else:
        urls = []

    if not urls:
        return jsonify({"error": "No valid video URLs found"}), 400

    # Optional custom concurrency passed for this batch
    custom_concurrency = data.get("concurrency")
    if custom_concurrency:
        try:
            set_concurrency_limit(int(custom_concurrency))
        except Exception:
            pass

    audio_only = bool(data.get("audio_only", False))
    audio_format = data.get("audio_format", "mp3")
    resolution = data.get("resolution", "auto")

    created_tasks = []

    for url in urls:
        task_id = str(uuid.uuid4())
        evt = threading.Event()
        evt.set()
        pause_events[task_id] = evt

        is_playlist = "playlist?list=" in url or "&list=" in url
        quality_label = audio_format.upper() if audio_only else (f"{resolution}p" if resolution != "auto" else "Auto (Best)")

        # Short placeholder title until yt-dlp fetches actual metadata
        initial_title = "Queued..."
        u_lower = url.lower()
        if "tiktok.com" in u_lower:
            initial_title = "Queued (TikTok)"
        elif "instagram.com" in u_lower:
            initial_title = "Queued (Instagram)"
        elif "twitter.com" in u_lower or "x.com" in u_lower:
            initial_title = "Queued (X/Twitter)"
        elif "facebook.com" in u_lower or "fb.watch" in u_lower:
            initial_title = "Queued (Facebook)"
        elif "reddit.com" in u_lower:
            initial_title = "Queued (Reddit)"
        elif "vimeo.com" in u_lower:
            initial_title = "Queued (Vimeo)"
        elif "watch?v=" in url:
            v_id = url.split("watch?v=")[-1].split("&")[0]
            initial_title = f"Queued (ID: {v_id[:8]})"
        elif "youtu.be/" in url:
            v_id = url.split("youtu.be/")[-1].split("?")[0]
            initial_title = f"Queued (ID: {v_id[:8]})"
        else:
            initial_title = "Queued (Media Link)"

        task_options = {
            "url": url,
            "title": initial_title,
            "thumbnail": "",
            "audio_only": audio_only,
            "audio_format": audio_format,
            "resolution": resolution,
            "is_playlist": is_playlist,
        }

        with tasks_lock:
            tasks[task_id] = {
                "id": task_id,
                "url": url,
                "title": initial_title,
                "thumbnail": "",
                "status": "queued",
                "percent": 0.0,
                "speed": "--",
                "eta": "--",
                "total_bytes": 0,
                "downloaded_bytes": 0,
                "filename": "",
                "filepath": "",
                "error": None,
                "is_audio": audio_only,
                "quality": quality_label,
                "start_time": time.time(),
                "is_playlist": is_playlist,
                "playlist_items": None,
                "current_item": None,
                "options": task_options,
            }

        add_pending_download(task_id, url, task_options, initial_title, "")

        t = threading.Thread(
            target=run_download_thread,
            args=(task_id, url, task_options),
            daemon=True,
        )
        t.start()

        created_tasks.append({
            "task_id": task_id,
            "url": url,
            "title": initial_title,
            "thumbnail": "",
            "audio_only": audio_only,
            "audio_format": audio_format,
            "resolution": resolution,
            "quality": quality_label,
            "status": "queued",
        })

    return jsonify({
        "success": True,
        "count": len(created_tasks),
        "tasks": created_tasks
    })


@app.route("/api/tasks/pause-all", methods=["POST"])
def pause_all_tasks():
    paused_count = 0
    with tasks_lock:
        for tid, task in tasks.items():
            if task["status"] in ("starting", "downloading"):
                evt = pause_events.get(tid)
                if evt:
                    evt.clear()
                task["status"] = "paused"
                task["speed"] = "Paused"
                paused_count += 1
    return jsonify({"success": True, "paused_count": paused_count})


@app.route("/api/tasks/resume-all", methods=["POST"])
def resume_all_tasks():
    resumed_count = 0
    with tasks_lock:
        for tid, task in tasks.items():
            if task["status"] == "paused":
                evt = pause_events.get(tid)
                if evt:
                    evt.set()
                task["status"] = "downloading"
                task["speed"] = "Resuming..."
                resumed_count += 1
    return jsonify({"success": True, "resumed_count": resumed_count})


@app.route("/api/tasks/clear-completed", methods=["POST"])
def clear_completed_tasks():
    cleared_ids = []
    with tasks_lock:
        for tid in list(tasks.keys()):
            if tasks[tid]["status"] in ("completed", "error"):
                cleared_ids.append(tid)
                del tasks[tid]
                if tid in pause_events:
                    del pause_events[tid]
    for tid in cleared_ids:
        remove_pending_download(tid)
    return jsonify({"success": True, "cleared_count": len(cleared_ids), "cleared_ids": cleared_ids})


@app.route("/api/tasks")
def list_tasks():
    with tasks_lock:
        return jsonify(list(tasks.values()))


@app.route("/api/pending")
def get_pending():
    """Return downloads that were interrupted (from previous sessions)."""
    pending = load_pending()
    # Filter out any that are currently active in this session
    with tasks_lock:
        active_ids = set(tasks.keys())
    result = [v for k, v in pending.items() if k not in active_ids]
    return jsonify({"pending": result})


@app.route("/api/resume", methods=["POST"])
def resume_pending_download():
    """Resume a previously interrupted download."""
    data = request.get_json() or {}
    pending_task_id = data.get("pending_task_id")

    if not pending_task_id:
        return jsonify({"error": "No pending_task_id provided"}), 400

    pending = load_pending()
    pending_item = pending.get(pending_task_id)
    if not pending_item:
        return jsonify({"error": "Pending download not found"}), 404

    # Remove the old pending entry
    remove_pending_download(pending_task_id)

    # Create a fresh task with a new ID
    url = pending_item["url"]
    options = pending_item.get("options", {})
    task_id = str(uuid.uuid4())

    # Create pause event (set = running)
    evt = threading.Event()
    evt.set()
    pause_events[task_id] = evt

    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "url": url,
            "title": pending_item.get("title") or "Resuming...",
            "thumbnail": pending_item.get("thumbnail") or "",
            "status": "starting",
            "percent": 0.0,
            "speed": "Resuming...",
            "eta": "--",
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "filename": "",
            "filepath": "",
            "error": None,
            "is_audio": bool(options.get("audio_only")),
            "quality": options.get("audio_format") if options.get("audio_only") else (f"{options.get('resolution')}p" if options.get("resolution") else "Best"),
            "start_time": time.time(),
            "resumed": True,
        }

    # Persist the new task as pending
    add_pending_download(task_id, url, options, pending_item.get("title", ""), pending_item.get("thumbnail", ""))

    t = threading.Thread(
        target=run_download_thread,
        args=(task_id, url, options),
        daemon=True,
    )
    t.start()

    return jsonify({
        "success": True,
        "task_id": task_id,
        "title": pending_item.get("title", ""),
        "thumbnail": pending_item.get("thumbnail", ""),
    })


@app.route("/api/pending/<pending_id>/dismiss", methods=["POST"])
def dismiss_pending(pending_id):
    """Remove a pending download without resuming it."""
    pending = load_pending()
    if pending_id not in pending:
        return jsonify({"error": "Not found"}), 404
    remove_pending_download(pending_id)
    return jsonify({"success": True})


@app.route("/api/task/<task_id>/pause", methods=["POST"])
def pause_task(task_id):
    """Pause an active download by clearing its threading.Event."""
    evt = pause_events.get(task_id)
    if not evt:
        return jsonify({"error": "Task not found"}), 404

    with tasks_lock:
        task = tasks.get(task_id)
        if not task or task["status"] not in ("starting", "downloading"):
            return jsonify({"error": "Task is not active"}), 400
        task["status"] = "paused"
        task["speed"] = "Paused"
        task["eta"] = "--"

    evt.clear()  # This will cause the progress_hook to block
    return jsonify({"success": True, "status": "paused"})


@app.route("/api/task/<task_id>/resume", methods=["POST"])
def resume_task(task_id):
    """Resume a paused download by setting its threading.Event."""
    evt = pause_events.get(task_id)
    if not evt:
        return jsonify({"error": "Task not found"}), 404

    with tasks_lock:
        task = tasks.get(task_id)
        if not task or task["status"] != "paused":
            return jsonify({"error": "Task is not paused"}), 400
        task["status"] = "downloading"
        task["speed"] = "Resuming..."

    evt.set()  # Unblock the progress_hook
    return jsonify({"success": True, "status": "downloading"})


@app.route("/api/task/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    """Cancel an active or queued download, delete any uncompleted files, and remove from queue."""
    request_task_cancel(task_id)

    # Unblock if paused so the thread wakes up and terminates
    if task_id in pause_events:
        pause_events[task_id].set()

    cfg = load_config()
    download_dir = Path(cfg.get("download_dir") or DEFAULT_DOWNLOAD_DIR)

    with tasks_lock:
        task = tasks.get(task_id)
        if task:
            title = task.get("title", "")
            filepath = task.get("filepath", "")
            task["status"] = "cancelled"
            task["speed"] = "Cancelled"
            task["error"] = "Cancelled by user"
            delete_uncompleted_download(download_dir, title, filepath)

    remove_pending_download(task_id)
    return jsonify({"success": True, "task_id": task_id})


@app.route("/api/tasks/cancel-all", methods=["POST"])
def cancel_all_tasks():
    """Cancel all active and queued download tasks and clean up incomplete files."""
    cfg = load_config()
    download_dir = Path(cfg.get("download_dir") or DEFAULT_DOWNLOAD_DIR)

    cancelled_count = 0
    with tasks_lock:
        for task_id, task in list(tasks.items()):
            if task["status"] in ("starting", "downloading", "paused", "queued"):
                request_task_cancel(task_id)
                if task_id in pause_events:
                    pause_events[task_id].set()
                task["status"] = "cancelled"
                task["speed"] = "Cancelled"
                task["error"] = "Cancelled by user"
                delete_uncompleted_download(download_dir, task.get("title", ""), task.get("filepath", ""))
                remove_pending_download(task_id)
                cancelled_count += 1

    return jsonify({"success": True, "cancelled_count": cancelled_count})


@app.route("/api/task/<task_id>/retry", methods=["POST"])
def retry_task(task_id):
    """Retry or continue a failed or interrupted download task."""
    with tasks_lock:
        task = tasks.get(task_id)
        if task:
            url = task.get("url")
            options = task.get("options") or {}
            title = task.get("title") or "Retrying..."
            thumbnail = task.get("thumbnail") or ""
        else:
            pending = load_pending()
            pending_item = pending.get(task_id)
            if not pending_item:
                return jsonify({"error": "Task not found"}), 404
            url = pending_item["url"]
            options = pending_item.get("options", {})
            title = pending_item.get("title") or "Retrying..."
            thumbnail = pending_item.get("thumbnail") or ""

    # Ensure pause event is reset to running state
    evt = threading.Event()
    evt.set()
    pause_events[task_id] = evt

    with tasks_lock:
        prev_percent = tasks.get(task_id, {}).get("percent", 0.0) if task else 0.0
        prev_total = tasks.get(task_id, {}).get("total_bytes", 0) if task else 0
        prev_dl = tasks.get(task_id, {}).get("downloaded_bytes", 0) if task else 0
        tasks[task_id] = {
            "id": task_id,
            "url": url,
            "title": title,
            "thumbnail": thumbnail,
            "status": "starting",
            "percent": prev_percent,
            "speed": "Reconnecting...",
            "eta": "--",
            "total_bytes": prev_total,
            "downloaded_bytes": prev_dl,
            "filename": "",
            "filepath": "",
            "error": None,
            "is_audio": bool(options.get("audio_only")),
            "quality": options.get("audio_format") if options.get("audio_only") else (f"{options.get('resolution')}p" if options.get("resolution") else "Best"),
            "start_time": time.time(),
            "is_playlist": bool(options.get("is_playlist")),
            "playlist_items": options.get("playlist_items"),
            "current_item": None,
            "options": options,
        }

    # Ensure task is in pending file
    add_pending_download(task_id, url, options, title, thumbnail)

    t = threading.Thread(
        target=run_download_thread,
        args=(task_id, url, options),
        daemon=True,
    )
    t.start()

    return jsonify({"success": True, "task_id": task_id, "title": title})


@app.route("/api/task/<task_id>/dismiss", methods=["POST"])
def dismiss_task(task_id):
    """Dismiss a failed, completed, or queued task from UI state."""
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id]["dismissed"] = True
            del tasks[task_id]
    remove_pending_download(task_id)
    if task_id in pause_events:
        evt = pause_events[task_id]
        evt.set()  # Unblock if paused so thread can exit cleanly
        del pause_events[task_id]
    return jsonify({"success": True})


@app.route("/api/progress/<task_id>")
def stream_progress(task_id):
    def event_generator():
        while True:
            with tasks_lock:
                task = tasks.get(task_id)
                if not task:
                    yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                    break

                data_payload = dict(task)

            yield f"data: {json.dumps(data_payload)}\n\n"

            if task["status"] in ["completed", "error"]:
                break

            time.sleep(0.4)

    return Response(event_generator(), mimetype="text/event-stream")


def format_file_size(num_bytes):
    """Format bytes into readable size."""
    if not num_bytes:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


@app.route("/api/files")
def list_download_files():
    """List all downloaded files and folders inside the configured download directory."""
    cfg = load_config()
    download_dir = Path(cfg.get("download_dir") or DEFAULT_DOWNLOAD_DIR).resolve()
    if not download_dir.exists():
        download_dir.mkdir(parents=True, exist_ok=True)

    items = []
    total_size = 0
    total_files = 0

    try:
        entries = sorted(download_dir.iterdir(), key=lambda e: e.stat().st_mtime if e.exists() else 0, reverse=True)
        for entry in entries:
            try:
                stat = entry.stat()
                is_dir = entry.is_dir()
                size = 0
                if is_dir:
                    for sub in entry.rglob("*"):
                        if sub.is_file():
                            try:
                                size += sub.stat().st_size
                            except Exception:
                                pass
                else:
                    size = stat.st_size
                    total_files += 1

                total_size += size
                mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

                suffix = entry.suffix.lower()
                if is_dir:
                    ftype = "folder"
                elif suffix in [".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv"]:
                    ftype = "video"
                elif suffix in [".mp3", ".m4a", ".wav", ".opus", ".aac", ".flac", ".ogg"]:
                    ftype = "audio"
                elif suffix in [".jpg", ".jpeg", ".png", ".webp"]:
                    ftype = "image"
                else:
                    ftype = "file"

                items.append({
                    "name": entry.name,
                    "relpath": entry.name,
                    "fullpath": str(entry),
                    "is_dir": is_dir,
                    "type": ftype,
                    "size": size,
                    "size_formatted": format_file_size(size),
                    "modified": mtime_str,
                    "timestamp": stat.st_mtime,
                    "ext": suffix,
                    "url": f"/api/files/serve/{entry.name}" if not is_dir else None,
                })
            except Exception:
                continue
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success": True,
        "download_dir": str(download_dir),
        "total_files": total_files,
        "total_size": total_size,
        "total_size_formatted": format_file_size(total_size),
        "files": items,
    })


@app.route("/api/files/serve/<path:filename>")
def serve_download_file(filename):
    """Stream or download a file directly from the downloads folder."""
    cfg = load_config()
    download_dir = Path(cfg.get("download_dir") or DEFAULT_DOWNLOAD_DIR).resolve()
    return send_from_directory(str(download_dir), filename, as_attachment=request.args.get("download") == "1")


@app.route("/api/files/delete", methods=["POST"])
def delete_download_file():
    """Delete a downloaded file or folder."""
    data = request.get_json() or {}
    relpath = data.get("relpath") or data.get("name")
    if not relpath:
        return jsonify({"error": "No file specified"}), 400

    cfg = load_config()
    download_dir = Path(cfg.get("download_dir") or DEFAULT_DOWNLOAD_DIR).resolve()
    target = (download_dir / relpath).resolve()

    # Security check: ensure target is within download_dir
    try:
        target.relative_to(download_dir)
    except ValueError:
        return jsonify({"error": "Invalid path"}), 403

    if not target.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data = request.get_json() or {}
    cfg = load_config()
    target = data.get("path") or cfg.get("download_dir") or str(DEFAULT_DOWNLOAD_DIR)
    target_path = Path(target).resolve()

    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    norm_path = os.path.normpath(str(target_path))
    try:
        if sys.platform == "win32":
            try:
                os.startfile(norm_path)
            except Exception:
                subprocess.Popen(["explorer.exe", norm_path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", norm_path])
        else:
            subprocess.Popen(["xdg-open", norm_path])
        return jsonify({"success": True, "path": norm_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/open-file", methods=["POST"])
def open_file():
    data = request.get_json() or {}
    filepath = (data.get("filepath") or "").strip()
    cfg = load_config()
    download_dir = Path(cfg.get("download_dir") or DEFAULT_DOWNLOAD_DIR).resolve()

    if not filepath:
        target = download_dir
    else:
        target = Path(filepath).resolve()
        if not target.exists():
            # Check relative to download_dir
            candidate = (download_dir / filepath).resolve()
            if candidate.exists():
                target = candidate
            else:
                # Fuzzy match extension
                found = None
                for ext in [".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".opus", ".wav"]:
                    cand = target.with_suffix(ext)
                    if cand.exists():
                        found = cand
                        break
                    cand2 = (download_dir / f"{target.name}{ext}").resolve()
                    if cand2.exists():
                        found = cand2
                        break
                if found:
                    target = found
                elif target.parent.exists():
                    target = target.parent
                else:
                    target = download_dir

    norm_path = os.path.normpath(str(target))
    try:
        if sys.platform == "win32":
            if target.is_file():
                # Launch explorer with /select,"path" directly as string
                subprocess.Popen(f'explorer.exe /select,"{norm_path}"')
            else:
                try:
                    os.startfile(norm_path)
                except Exception:
                    subprocess.Popen(f'explorer.exe "{norm_path}"')
        elif sys.platform == "darwin":
            if target.is_file():
                subprocess.Popen(["open", "-R", norm_path])
            else:
                subprocess.Popen(["open", norm_path])
        else:
            subprocess.Popen(["xdg-open", norm_path if target.is_dir() else str(target.parent)])
        return jsonify({"success": True, "path": norm_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    port = 5000
    local_ip = get_local_ip()
    print("\n========================================================")
    print(f"  [+] YouTube Downloader Studio UI is running!")
    print(f"  [*] Local:          http://127.0.0.1:{port}")
    print(f"  [*] Mobile/Network: http://{local_ip}:{port}")
    print("========================================================\n")
    
    # Auto open browser if running directly
    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="0.0.0.0", port=port, debug=False)
