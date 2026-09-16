#!/usr/bin/env python3
"""
Desktop Window Launcher for YouTube Downloader
Uses pywebview for a clean, frameless/native desktop window experience.
"""

import sys
import threading
import time
from app import app

def start_server():
    app.run(host="127.0.0.1", port=5892, debug=False)

def main():
    try:
        import webview
    except ImportError:
        print("pywebview not installed. Running in web mode...")
        import subprocess
        subprocess.run([sys.executable, "app.py"])
        return

    # Start Flask in background thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(1)

    # Create native window
    window = webview.create_window(
        title="⚡ YouTube Downloader Studio",
        url="http://127.0.0.1:5892",
        width=1100,
        height=780,
        min_size=(800, 600),
        background_color="#0b0d13",
        text_select=True,
    )
    webview.start()

if __name__ == "__main__":
    main()
