#!/usr/bin/env python3
"""
YouTube Downloader Web Application Backend
Powered by Flask & yt-dlp
"""

import json
import os
import queue
import shutil
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

# Pause control: task_id -> threading.Event (set=running, clear=paused)
pause_events = {}

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
    }

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

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
def index():
    return render_template("index.html")

@app.route("/api/system-status")
def system_status():
    cfg = load_config()
    return jsonify({
        "ffmpeg_installed": is_ffmpeg_installed(),
        "download_dir": cfg.get("download_dir", str(DEFAULT_DOWNLOAD_DIR)),
        "download_dir_exists": Path(cfg.get("download_dir", "")).exists(),
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
        # Block here if the task is paused (wait until event is set again)
        evt = pause_events.get(task_id)
        if evt:
            evt.wait()  # Blocks if cleared (paused), returns immediately if set (running)

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

    try:
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

    except Exception as e:
        with tasks_lock:
            tasks[task_id]["status"] = "error"
            tasks[task_id]["error"] = str(e)


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
    """Dismiss a failed or completed task from UI state."""
    with tasks_lock:
        if task_id in tasks:
            del tasks[task_id]
    remove_pending_download(task_id)
    if task_id in pause_events:
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


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data = request.get_json() or {}
    cfg = load_config()
    target = data.get("path") or cfg.get("download_dir") or str(DEFAULT_DOWNLOAD_DIR)
    target_path = Path(target)

    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            os.startfile(str(target_path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target_path)])
        else:
            subprocess.Popen(["xdg-open", str(target_path)])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/open-file", methods=["POST"])
def open_file():
    data = request.get_json() or {}
    filepath = data.get("filepath")
    if not filepath:
        return jsonify({"error": "No file path provided"}), 400

    target = Path(filepath)
    if not target.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        if sys.platform == "win32":
            # Select the file in Windows Explorer
            subprocess.Popen(f'explorer /select,"{str(target)}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    port = 5000
    print(f"\n========================================================")
    print(f"  ⚡ YouTube Downloader Studio UI is running!")
    print(f"  🌐 Open in your browser: http://127.0.0.1:{port}")
    print(f"========================================================\n")
    
    # Auto open browser if running directly
    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="127.0.0.1", port=port, debug=False)
