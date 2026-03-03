#!/usr/bin/env python3
"""
fetch_and_upload.py  –  Run on your LOCAL machine.

Downloads a YouTube video + transcript, then uploads both to the remote
server via rsync/SSH so the main pipeline can process them.

Usage:
    python3 scripts/fetch_and_upload.py "https://www.youtube.com/watch?v=VIDEO_ID"

    # Override defaults:
    python3 scripts/fetch_and_upload.py "URL" \
        --max-resolution 720 \
        --transcript-interval 9 \
        --languages en zh-Hant ja \
        --server ubuntu@YOUR_SERVER_IP \
        --remote-dir /home/ubuntu/youtube-project/uploads

    # With cookies (needed when YouTube blocks your IP):
    python3 scripts/fetch_and_upload.py "URL" --cookies cookies.txt

    # Using a config file (URL and all options read from it):
    python3 scripts/fetch_and_upload.py --config scripts/fetch_config.yaml

    # Config file + CLI override (CLI wins):
    python3 scripts/fetch_and_upload.py --config scripts/fetch_config.yaml --max-resolution 720

Requirements (install locally):
    pip install yt-dlp youtube-transcript-api

By default no Google-account cookies are used. yt-dlp falls back to the
public (non-authenticated) innertube API. If YouTube blocks your requests,
use --cookies with a Netscape-format cookies.txt file exported from your
browser (see https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp).
"""

import argparse
import os
import pickle
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    yaml = None

from downloader import download_video


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    """Make a string safe for filenames."""
    return re.sub(r"[^\w\-_.]", "_", name)


def _extract_video_id(url: str) -> str:
    """Pull the 11-char video ID out of various YouTube URL formats."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:embed/)([A-Za-z0-9_-]{11})",
        r"(?:shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    sys.exit(f"ERROR: Could not extract video ID from URL: {url}")


# ---------------------------------------------------------------------------
# Download transcript
# ---------------------------------------------------------------------------

def download_transcript(url: str, languages: list[str] | None = None) -> list[dict]:
    """
    Fetch the transcript using youtube_transcript_api (no cookies needed).

    Returns a list of {'text', 'start', 'duration'} dicts.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        sys.exit(
            "ERROR: youtube-transcript-api is not installed.  "
            "Run:  pip install youtube-transcript-api"
        )

    if languages is None:
        languages = ["en", "zh-Hant", "zh-Hans", "ja"]

    video_id = _extract_video_id(url)

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=languages)
        return [
            {"text": snippet.text, "start": snippet.start, "duration": snippet.duration}
            for snippet in transcript
        ]
    except Exception as e:
        print(f"WARNING: Could not fetch transcript: {e}")
        return []


# ---------------------------------------------------------------------------
# Chunk transcript into (start, end, text) tuples  –  same format main.py expects
# ---------------------------------------------------------------------------

def _chunk_transcript(raw: list[dict], interval: int) -> list[tuple[float, float, str]]:
    if not raw:
        return []

    chunks: list[tuple[float, float, str]] = []
    current_start = 0.0
    current_end = float(interval)
    current_texts: list[str] = []

    for entry in raw:
        seg_start = entry["start"]
        seg_text = entry["text"]

        while seg_start >= current_end:
            if current_texts:
                chunks.append((current_start, current_end, " ".join(current_texts)))
                current_texts = []
            current_start = current_end
            current_end = current_start + interval

        current_texts.append(seg_text)

    if current_texts:
        chunks.append((current_start, current_end, " ".join(current_texts)))

    return chunks


# ---------------------------------------------------------------------------
# Upload to server
# ---------------------------------------------------------------------------

def upload_files(files: list[str], server: str, remote_dir: str) -> None:
    """scp files to the remote server."""
    for f in files:
        basename = os.path.basename(f)
        print(f"  Uploading {basename} -> {server}:{remote_dir}/")
        result = subprocess.run(
            ["scp", "-c", "aes128-ctr", "-o", "Compression=no", f, f"{server}:{remote_dir}/"],
        )
        if result.returncode != 0:
            print(f"  FAILED to upload {basename}")
        else:
            print(f"  Done: {basename}")


def upload_file_to_remote_path(local_path: str, server: str, remote_path: str) -> bool:
    """Upload one file to an explicit remote path (including filename)."""
    basename = os.path.basename(local_path)
    print(f"  Uploading {basename} -> {server}:{remote_path}")
    result = subprocess.run(
        ["scp", "-c", "aes128-ctr", "-o", "Compression=no", local_path, f"{server}:{remote_path}"],
    )
    if result.returncode != 0:
        print(f"  FAILED to upload {basename}")
        return False
    print(f"  Done: {basename}")
    return True


def build_runtime_config(
    title: str,
    source_url: str,
    video_filename: str,
    transcript_filename: str | None,
    split_timestamps: list[str],
) -> dict:
    """
    Build a main.py config that points to uploaded artifacts.

    Starts from repo config.yaml if present, then overrides key runtime fields.
    """
    cfg: dict = {}
    if yaml is not None and os.path.isfile("config.yaml"):
        with open("config.yaml") as f:
            cfg = yaml.safe_load(f) or {}

    cfg["video_path"] = f"uploads/{video_filename}"
    cfg["video_title"] = sanitize(title)
    cfg["youtube_url"] = source_url
    cfg["split_timestamps"] = split_timestamps

    if transcript_filename:
        cfg["transcript_path"] = f"uploads/{transcript_filename}"
    else:
        cfg["transcript_path"] = None

    return cfg


def write_yaml(path: str, data: dict) -> None:
    if yaml is None:
        sys.exit("ERROR: PyYAML is not installed.  Run:  pip install pyyaml")
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    """Load a YAML config file and return its contents as a dict."""
    if yaml is None:
        sys.exit("ERROR: PyYAML is not installed.  Run:  pip install pyyaml")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def main():
    # Pre-parse just --config so we can load it before setting argparse defaults.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    pre_args, _ = pre.parse_known_args()

    cfg: dict = {}
    if pre_args.config:
        cfg = _load_config(pre_args.config)

    parser = argparse.ArgumentParser(
        description="Download a YouTube video + transcript locally, then upload to the server.",
    )
    parser.add_argument("--config", default=None,
        help="Path to a YAML config file. CLI flags override config values.",
    )
    parser.add_argument("url", nargs="?", default=cfg.get("url"),
        help="YouTube video URL",
    )
    parser.add_argument(
        "--max-resolution", type=int, default=cfg.get("max_resolution"),
        help="Cap video resolution (e.g. 720, 1080). Default: best available.",
    )
    parser.add_argument(
        "--transcript-interval", type=int, default=cfg.get("transcript_interval", 9),
        help="Chunk size in seconds for the transcript (default: 9).",
    )
    parser.add_argument(
        "--languages", nargs="+", default=cfg.get("languages", ["en", "zh-Hant", "zh-Hans", "ja"]),
        help="Language preference order for the transcript.",
    )
    parser.add_argument(
        "--server", default=cfg.get("server", "ubuntu@YOUR_SERVER_IP_OR_HOSTNAME"),
        help="SSH destination (user@host or SSH alias).",
    )
    parser.add_argument(
        "--remote-dir", default=cfg.get("remote_dir", "/home/ubuntu/youtube-project/uploads"),
        help="Remote directory to upload files into.",
    )
    parser.add_argument(
        "--cookies", default=cfg.get("cookies"),
        help="Path to a Netscape-format cookies.txt file for yt-dlp authentication.",
    )
    parser.add_argument(
        "--skip-upload", action="store_true", default=cfg.get("skip_upload", False),
        help="Download only; do not upload to the server.",
    )
    parser.add_argument(
        "--output-dir", default=cfg.get("output_dir") or "downloads",
        help="Local directory for downloads. Default: downloads/",
    )
    parser.add_argument(
        "--remote-config-path",
        default=cfg.get("remote_config_path", "/home/ubuntu/youtube-project/config.yaml"),
        help="Remote config.yaml destination path to upload (default: /home/ubuntu/youtube-project/config.yaml).",
    )

    args = parser.parse_args()

    if not args.url:
        parser.error("A YouTube URL is required — either as a positional argument or via 'url:' in the config file.")

    # -- Prepare output dir --------------------------------------------------
    if args.output_dir:
        out_dir = args.output_dir
        os.makedirs(out_dir, exist_ok=True)
        cleanup = False
    else:
        out_dir = tempfile.mkdtemp(prefix="yt_fetch_")
        cleanup = True

    print(f"Working directory: {out_dir}\n")

    files_to_upload: list[str] = []

    # -- 1. Download video ---------------------------------------------------
    print("=" * 60)
    print("STEP 1: Downloading video ...")
    print("=" * 60)

    title, video_path, chapter_starts = download_video(
        args.url,
        output_dir=out_dir,
        max_resolution=args.max_resolution,
        cookies=args.cookies,
    )
    print(f"\n  Video saved: {video_path}")
    if chapter_starts:
        print(f"  Chapter starts for split_timestamps: {chapter_starts}")
    else:
        print("  No chapter starts found; split_timestamps will be empty.")
    files_to_upload.append(video_path)

    # -- 2. Download transcript ----------------------------------------------
    print()
    print("=" * 60)
    print("STEP 2: Downloading transcript ...")
    print("=" * 60)

    safe_title = sanitize(title)
    pkl_name = f"{safe_title}_transcript_{args.transcript_interval}s.pkl"
    pkl_path = os.path.join(out_dir, pkl_name)

    if os.path.isfile(pkl_path):
        print("  Transcript already exists, skipping.")
        files_to_upload.append(pkl_path)
    else:
        raw_transcript = download_transcript(args.url, languages=args.languages)
        if raw_transcript:
            chunks = _chunk_transcript(raw_transcript, args.transcript_interval)
            with open(pkl_path, "wb") as f:
                pickle.dump(chunks, f)
            print(f"  Transcript saved: {pkl_path}  ({len(chunks)} chunks)")
            files_to_upload.append(pkl_path)
        else:
            pkl_name = None
            print("  No transcript available -- skipping.")

    # -- 3. Build runtime config --------------------------------------------
    print()
    print("=" * 60)
    print("STEP 3: Building config.yaml ...")
    print("=" * 60)
    runtime_cfg = build_runtime_config(
        title=title,
        source_url=args.url,
        video_filename=os.path.basename(video_path),
        transcript_filename=pkl_name,
        split_timestamps=chapter_starts,
    )
    generated_cfg_path = os.path.join(out_dir, "config.yaml")
    write_yaml(generated_cfg_path, runtime_cfg)
    print(f"  Generated config: {generated_cfg_path}")
    print(f"  split_timestamps entries: {len(chapter_starts)}")

    # -- 4. Upload -----------------------------------------------------------
    if not args.skip_upload:
        print()
        print("=" * 60)
        print("STEP 4: Uploading to server ...")
        print("=" * 60)
        upload_files(files_to_upload, args.server, args.remote_dir)
        upload_file_to_remote_path(generated_cfg_path, args.server, args.remote_config_path)
    else:
        print("\n  --skip-upload: skipping upload step.")

    # -- Summary -------------------------------------------------------------
    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"  Video title : {title}")
    print(f"  Video file  : {os.path.basename(video_path)}")
    if pkl_name:
        print(f"  Transcript  : {pkl_name}")
    if chapter_starts:
        print(f"  split_timestamps: {chapter_starts}")
    else:
        print("  split_timestamps: []")
    print(f"  Config file : {generated_cfg_path}")
    print()

    if not args.skip_upload:
        print("Next steps on the server:")
        print(f"  1. Verify {args.remote_config_path}")
        print("  2. Run:  python3 main.py --config config.yaml")

    if cleanup and args.skip_upload:
        print(f"\nFiles are in: {out_dir}")
    elif cleanup and not args.skip_upload:
        shutil.rmtree(out_dir, ignore_errors=True)
        print("  (temp files cleaned up)")


if __name__ == "__main__":
    main()
