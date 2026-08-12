#!/usr/bin/env python3
"""
yt_downloader.py — a small CLI tool for downloading YouTube videos/audio.

Usage examples:
    python yt_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"
    python yt_downloader.py URL1 URL2 URL3
    python yt_downloader.py URL --audio-only
    python yt_downloader.py URL --resolution 720
    python yt_downloader.py URL --output ~/Videos
    python yt_downloader.py --from-file urls.txt
    python yt_downloader.py PLAYLIST_URL --playlist
"""

import argparse
import sys

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Install it with: pip install yt-dlp")


def build_ydl_opts(args):
    """Construct yt-dlp options based on parsed CLI arguments."""
    output_template = f"{args.output}/%(title)s.%(ext)s"
    if args.playlist:
        output_template = f"{args.output}/%(playlist)s/%(title)s.%(ext)s"

    opts = {
        "outtmpl": output_template,
        "progress_hooks": [progress_hook],
        "noplaylist": not args.playlist,
        "quiet": False,
        "no_warnings": False,
    }

    if args.audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": args.audio_format,
            "preferredquality": "192",
        }]
    elif args.resolution:
        opts["format"] = (
            f"bestvideo[height<={args.resolution}]+bestaudio/"
            f"best[height<={args.resolution}]"
        )
    else:
        opts["format"] = "bestvideo+bestaudio/best"

    return opts


def progress_hook(d):
    """Print a simple progress indicator during download."""
    if d["status"] == "downloading":
        percent = d.get("_percent_str", "").strip()
        speed = d.get("_speed_str", "").strip()
        eta = d.get("_eta_str", "").strip()
        print(f"\r  {percent} at {speed}, ETA {eta}   ", end="", flush=True)
    elif d["status"] == "finished":
        print(f"\n  Done: {d.get('filename', '')}")


def read_urls_from_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def download(urls, args):
    ydl_opts = build_ydl_opts(args)
    failures = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            print(f"\nDownloading: {url}")
            try:
                ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                print(f"  Failed: {e}")
                failures.append(url)

    if failures:
        print(f"\n{len(failures)} download(s) failed:")
        for url in failures:
            print(f"  - {url}")
        sys.exit(1)
    else:
        print("\nAll downloads completed successfully.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download YouTube videos or audio to local storage using yt-dlp."
    )
    parser.add_argument(
        "urls", nargs="*", help="One or more YouTube video/playlist URLs"
    )
    parser.add_argument(
        "--from-file", metavar="FILE",
        help="Read URLs from a text file (one URL per line, '#' for comments)"
    )
    parser.add_argument(
        "-o", "--output", default="downloads",
        help="Output directory (default: ./downloads)"
    )
    parser.add_argument(
        "--audio-only", action="store_true",
        help="Download audio only instead of video"
    )
    parser.add_argument(
        "--audio-format", default="mp3", choices=["mp3", "m4a", "wav", "opus"],
        help="Audio format when using --audio-only (default: mp3)"
    )
    parser.add_argument(
        "--resolution", type=int, metavar="HEIGHT",
        help="Max video resolution height, e.g. 720 or 1080"
    )
    parser.add_argument(
        "--playlist", action="store_true",
        help="Download the entire playlist instead of a single video"
    )

    args = parser.parse_args()

    urls = list(args.urls)
    if args.from_file:
        urls.extend(read_urls_from_file(args.from_file))

    if not urls:
        parser.error("No URLs provided. Pass URLs directly or use --from-file.")

    args.urls = urls
    return args


def main():
    args = parse_args()
    download(args.urls, args)


if __name__ == "__main__":
    main()