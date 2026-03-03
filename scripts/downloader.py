"""YouTube video downloader module using yt-dlp."""

import json
import os
import re
import sys
import yt_dlp

try:
    import yaml
except ImportError:
    yaml = None


def progress_hook(d):
    """Print download progress to stdout."""
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "N/A")
        speed = d.get("_speed_str", "N/A")
        eta = d.get("_eta_str", "N/A")
        print(f"\r  {pct} | Speed: {speed} | ETA: {eta}", end="", flush=True)
    elif d["status"] == "finished":
        print("\n  Download complete, processing...")


def _seconds_to_hhmmss(seconds):
    """Convert seconds to HH:MM:SS."""
    total = int(round(float(seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _extract_chapter_starts(info):
    """
    Extract chapter start timestamps from yt-dlp info.

    Returns a sorted list of HH:MM:SS strings, excluding 00:00:00.
    """
    chapters = info.get("chapters") or []
    starts = set()
    for ch in chapters:
        start = ch.get("start_time")
        if start is None:
            continue
        start = int(round(float(start)))
        if start > 0:
            starts.add(start)
    return [_seconds_to_hhmmss(v) for v in sorted(starts)]


def _video_id_from_url(url):
    m = re.search(r"(?:v=|/v/|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def download_video(url, output_dir=".", max_resolution=None, cookies=None):
    """
    Download a YouTube video using yt-dlp.

    Returns (video_title, path_to_mp4, chapter_start_timestamps).
    """
    # Fast path: if we have a cached metadata sidecar and the mp4 exists,
    # skip all network calls entirely.
    video_id = _video_id_from_url(url)
    meta_path = os.path.join(output_dir, f"{video_id}.meta.json") if video_id else None

    if meta_path and os.path.isfile(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        title = meta["title"]
        chapter_starts = meta["chapter_starts"]
        safe_title = yt_dlp.utils.sanitize_filename(title, restricted=True)
        video_path = os.path.join(output_dir, f"{safe_title}.mp4")
        if os.path.isfile(video_path):
            print(f"Title: {title}")
            print(f"Duration: {meta.get('duration', 'N/A')}")
            print(f"Uploader: {meta.get('uploader', 'N/A')}")
            if chapter_starts:
                print(f"Chapter starts: {', '.join(chapter_starts)}")
            else:
                print("Chapter starts: none found")
            print("  Video already exists, skipping download.")
            print("Done!")
            return title, video_path, chapter_starts

    # Slow path: fetch info from YouTube.
    fmt = "best[ext=mp4]/best"
    extra_opts = {}
    if max_resolution:
        fmt = f"bestvideo[height<={max_resolution}]+bestaudio/best[height<={max_resolution}]"
        extra_opts["merge_output_format"] = "mp4"

    ydl_opts = {
        "format": fmt,
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "restrictfilenames": True,
        "continuedl": True,
        "progress_hooks": [progress_hook],
        "noplaylist": True,
        **extra_opts,
    }

    if cookies and os.path.isfile(cookies):
        ydl_opts["cookiefile"] = cookies

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        print(f"Fetching info for: {url}")
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "video")
        chapter_starts = _extract_chapter_starts(info)
        print(f"Title: {title}")
        print(f"Duration: {info.get('duration_string', 'N/A')}")
        print(f"Uploader: {info.get('uploader', 'N/A')}")
        if chapter_starts:
            print(f"Chapter starts: {', '.join(chapter_starts)}")
        else:
            print("Chapter starts: none found")

        safe_title = yt_dlp.utils.sanitize_filename(title, restricted=True)
        video_path = os.path.join(output_dir, f"{safe_title}.mp4")

        if os.path.isfile(video_path):
            print("  Video already exists, skipping download.")
        else:
            print("Starting download...")
            ydl.download([url])
            if not os.path.isfile(video_path):
                for f in os.listdir(output_dir):
                    if f.endswith(".mp4"):
                        video_path = os.path.join(output_dir, f)
                        break

        # Save metadata so future runs skip the network call.
        if meta_path:
            with open(meta_path, "w") as f:
                json.dump({
                    "title": title,
                    "chapter_starts": chapter_starts,
                    "duration": info.get("duration_string", "N/A"),
                    "uploader": info.get("uploader", "N/A"),
                }, f)

        print("Done!")
        return title, video_path, chapter_starts


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--config":
        if yaml is None:
            sys.exit("ERROR: PyYAML is not installed.  Run:  pip install pyyaml")
        with open(sys.argv[2]) as f:
            cfg = yaml.safe_load(f) or {}
        video_url = cfg.get("url") or sys.exit("ERROR: 'url' not set in config.")
        output_dir = cfg.get("output_dir", ".")
        max_resolution = cfg.get("max_resolution")
        cookies = cfg.get("cookies")
    else:
        video_url = sys.argv[1] if len(sys.argv) > 1 else input("Enter YouTube URL: ")
        output_dir = "."
        max_resolution = None
        cookies = None

    os.makedirs(output_dir, exist_ok=True)
    download_video(video_url, output_dir=output_dir, max_resolution=max_resolution, cookies=cookies)
