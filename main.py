#!/usr/bin/env python3
import argparse
import hashlib
import os
import re
import pickle
import shutil
import tempfile
import yaml
from typing import List, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from chunking_utils import chunk
import pdf_api
from youtube_screenshot_script import run_extraction, sanitize_filename, download_video
from tqdm.auto import tqdm
import transcript_api

SCREENSHOT_INTERVAL = 2
TIMESTAMPS = ['00:21:56']
VIDEO_PATH = "https://www.youtube.com/watch?v=HG6yIjZapSA"
TRANSCRIPT_INTERVAL = 8

def download_timestamped_transcript(
    source: str,
    transcript_interval: int = TRANSCRIPT_INTERVAL,
    video_dir: str = "videos",
    languages: List[str] | None = None,
    verbose: bool = False,
) -> List[Tuple[float, float, str]] | None:
    """
    Download a video if needed and return a timestamped transcript.

    Returns:
        List of (start_time, end_time, text) tuples, or None on failure.
    """

    # Case 1: source is NOT a URL — caller must supply a transcript_path instead
    if not source.startswith(("http://", "https://", "www.")):
        return None

    # Case 2: source IS a URL
    video_url = source

    # Optional: download the video locally if you need it for other steps
    os.makedirs(video_dir, exist_ok=True)

    if verbose:
        print(f"Fetching transcript for: {video_url}")
        print(f"Transcript chunk interval: {transcript_interval}s")

    try:
        transcript_chunks = transcript_api.get_chunked_transcript(
            video_url,
            transcript_interval,
            languages=languages,
        )
    except Exception as e:
        if verbose:
            print(f"Failed to fetch transcript: {e}")
        return None

    return transcript_chunks


def download_if_needed(
    source: str = VIDEO_PATH,
    max_resolution: int | None = None,
    video_dir: str = "videos",
    verbose: bool = False,
    ) -> str | None:
    """
    Download a video if the source is a URL and return a sanitized title.
    """
    if not source.startswith(("http://", "https://", "www.")):
        path = Path(source)
        return path.stem, str(path)

    os.makedirs(video_dir, exist_ok=True)

    title = download_video(
        url=source,
        output_dir=video_dir,
        max_resolution=max_resolution,
        verbose=verbose,
    )

    return title, os.path.join(video_dir, sanitize_filename(title))




def get_timestamped_frames(
    folder_path: str,
    interval: float,
    max_allowed_gap: int = 1,
) -> List[Tuple[float, str]]:
    """
    Safely generate timestamps for extracted frames.

    - Uses filename index * interval IF and ONLY IF:
        1. Indices are strictly increasing
        2. No large gaps exist
        3. Order matches sorted order
    - Otherwise FALLS BACK to reconstructed time via enumeration.
    """

    pattern = re.compile(r'frame_(\d{6})_q\d+_b\d+.*\.(?:png|jpg)')

    frames = []

    # ----------------------------
    # 1. Collect filenames + indices
    # ----------------------------
    for filename in os.listdir(folder_path):
        match = pattern.match(filename)
        if match:
            index = int(match.group(1))
            frames.append((filename, index))

    if not frames:
        return []

    # ----------------------------
    # 2. Sort by filename (true order)
    # ----------------------------
    frames.sort(key=lambda x: x[0])

    indices = [idx for _, idx in frames]

    # ----------------------------
    # 3. Sanity checks
    # ----------------------------
    is_strictly_increasing = all(
        earlier < later for earlier, later in zip(indices, indices[1:])
    )

    gaps = [
        indices[i + 1] - indices[i]
        for i in range(len(indices) - 1)
    ]

    has_large_gaps = any(gap > max_allowed_gap for gap in gaps)

    use_filename_time = is_strictly_increasing and not has_large_gaps

    # ----------------------------
    # 4. Build timestamps
    # ----------------------------
    timestamped_files = []

    if use_filename_time:
        # ✅ Safe to use index-based timestamps
        for filename, index in frames:
            timestamp = index * interval
            full_path = os.path.join(folder_path, filename)
            timestamped_files.append((timestamp, full_path))
    else:
        # ⚠️ Fallback to reconstructed timestamps
        print("⚠️ WARNING: Unreliable filename indices detected. Falling back to reconstructed timestamps.")

        for i, (filename, _) in enumerate(frames):
            timestamp = i * interval
            full_path = os.path.join(folder_path, filename)
            timestamped_files.append((timestamp, full_path))

    return timestamped_files


# ---------------------------
# ✅ SCREENSHOT EXTRACTION
# ✅ FIX: pass interval into get_timestamped_frames
# ---------------------------
def extract_screenshots(video_url: str, interval: int, screenshots_dir: str = "screenshots", verbose: bool = False) -> List[Tuple[float, str]]:
    os.makedirs(screenshots_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    video_name = Path(video_url).stem
    folder_name = f"{video_name}_interval{interval}s_{timestamp}"
    output_dir = os.path.join(screenshots_dir, folder_name)
    os.makedirs(output_dir, exist_ok=True)

    raw_results = run_extraction(
        video_url,
        output=output_dir,
        method="interval",
        interval=interval,
        # quality=20.0,
        quality=0,
        # blur=15.0,
        blur=0,
        detect_watermarks=False,
        png=True,
        verbose=verbose,
        thumbnail=True
    )

    folder = raw_results["output_folder"]
    return get_timestamped_frames(folder, interval)   # ✅ FIX


# ---------------------------
# ✅ STRICT TRANSCRIPT MATCHING
# ---------------------------
def find_matching_chunk(chunks, timestamp, eps=0.0001):
    # First pass: strict half-open intervals [start, end) — handles exact
    # boundaries correctly so contiguous chunks never steal each other's frames.
    for start, end, text in chunks:
        if start <= timestamp < end:
            return text.strip()
    # Second pass: epsilon fallback for floating-point near-boundary cases
    # (e.g. the last frame of the last transcript chunk).
    for start, end, text in chunks:
        if start - eps <= timestamp <= end + eps:
            return text.strip()
    return ""


# ---------------------------
# ✅ FIXED CACHING
# ---------------------------
def extract_screenshots_cached(video_file_path: str, interval: int, chunk_start: float, verbose: bool = False):
    cache_dir = "extracted_frames_cache"
    os.makedirs(cache_dir, exist_ok=True)

    safe_name = os.path.basename(video_file_path).replace(".", "_")

    cache_file = os.path.join(
        cache_dir,
        f"{safe_name}_start_{int(chunk_start)}s_interval_{interval}s.pkl"
    )

    if os.path.exists(cache_file):
        with open(cache_file, "rb") as f:
            cached = pickle.load(f)
        if cached["interval"] == interval and cached["chunk_start"] == chunk_start:
            frames = cached["frames"]
            if all(os.path.exists(p) for _, p in frames):
                print(f"⚡ Loaded cached frames: {cache_file}")
                return frames
            print(f"⚠️  Cached frame files missing from disk, re-extracting.")
        else:
            print(f"⚠️  Cache metadata mismatch, re-extracting.")

    frames = extract_screenshots(video_file_path, interval, verbose=verbose)

    with open(cache_file, "wb") as f:
        pickle.dump({"interval": interval, "chunk_start": chunk_start, "frames": frames}, f)

    print(f"💾 Cached frames saved to: {cache_file}")
    return frames

# ---------------------------
# ✅ TRANSCRIPT GAP + OVERLAP SCAN
# ---------------------------
def scan_transcript_continuity(chunks):
    results = []
    gaps = 0
    overlaps = 0

    for i in range(1, len(chunks)):
        prev_end = chunks[i - 1][1]
        curr_start = chunks[i][0]
        delta = curr_start - prev_end

        if delta > 0.001:
            results.append(("GAP", prev_end, curr_start, delta))
            gaps += 1
        elif delta < -0.001:
            results.append(("OVERLAP", prev_end, curr_start, delta))
            overlaps += 1
        else:
            results.append(("OK", prev_end, curr_start, delta))

    return results, gaps, overlaps


# ---------------------------
# ✅ DEBUG FILE WRITER
# ---------------------------
def write_match_debug_file(
    video_title,
    chunk_file,
    chunk_index,
    chunk_start,
    screenshots,
    transcript_chunks,
    used_matches,
    interval
):
    os.makedirs("debug_logs", exist_ok=True)

    debug_path = os.path.join(
        "debug_logs",
        f"match_debug_{video_title}_part_{chunk_index}.txt"
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(debug_path, "w", encoding="utf-8") as f:
        f.write("=" * 50 + "\n")
        f.write("MATCH DEBUG REPORT\n")
        f.write(f"Video Title : {video_title}\n")
        f.write(f"Chunk File  : {chunk_file}\n")
        f.write(f"Chunk Index : {chunk_index}\n")
        f.write(f"Chunk Start : {chunk_start:.2f}\n")
        f.write(f"Screenshot Interval : {interval}\n")
        f.write(f"Generated : {now}\n")
        f.write("=" * 50 + "\n\n")

        # ---- CONTINUITY CHECK ----
        f.write("TRANSCRIPT CONTINUITY CHECK\n\n")
        continuity, gaps, overlaps = scan_transcript_continuity(transcript_chunks)
        for tag, a, b, d in continuity:
            f.write(f"[{tag}] {a:.2f} → {b:.2f} ({d:.2f})\n")

        f.write(f"\nGaps     : {gaps}\n")
        f.write(f"Overlaps : {overlaps}\n\n")

        # ---- SCREENSHOT MATCHES ----
        f.write("SCREENSHOT → TRANSCRIPT MATCHING\n\n")

        matched_ranges = set()

        for i, (local_ts, abs_ts, match) in enumerate(used_matches, 1):
            f.write(f"#{i:03d} Local {local_ts:.2f}s | Abs {abs_ts:.2f}s\n")
            if match:
                s, e, t = match
                matched_ranges.add((s, e))
                f.write(f"  Transcript: [{s:.2f} → {e:.2f}]\n")
                f.write(f"  Text: {t}\n\n")
            else:
                f.write("  ❌ NO MATCH FOUND\n\n")

        # ---- UNMATCHED TRANSCRIPTS ----
        f.write("UNMATCHED TRANSCRIPT CHUNKS\n\n")

        unmatched = [c for c in transcript_chunks if (c[0], c[1]) not in matched_ranges]

        for i, (s, e, t) in enumerate(unmatched, 1):
            f.write(f"[{i:03d}] {s:.2f} → {e:.2f} ({e - s:.2f}s)\n")
            f.write(f"{t}\n\n")

        # ---- SUMMARY ----
        f.write("FINAL SUMMARY\n\n")
        f.write(f"Screenshots processed : {len(used_matches)}\n")
        f.write(f"Matched screenshots   : {sum(1 for x in used_matches if x[2])}\n")
        f.write(f"Unmatched screenshots : {sum(1 for x in used_matches if not x[2])}\n")
        f.write(f"Transcript chunks     : {len(transcript_chunks)}\n")
        f.write(f"Unmatched transcripts : {len(unmatched)}\n")

    print(f"📝 Debug log saved: {debug_path}")


# ---------------------------
# ✅ MAIN PIPELINE
# ---------------------------
def create_slides():
    timestamps = ['00:17:45', '00:40:33']
    video_title = 'docker_video'

    base_dir = os.path.join("processed_videos", video_title)
    chunk_dir = os.path.join(base_dir, "chunks")
    pdf_dir = os.path.join(base_dir, "pdfs")

    # transcript_path = "docker_transcript.pkl"
    video_path = "downloaded_video_20251205_003252.mp4"
    transcript_path = "docker_transcript_8seconds.pkl"

    os.makedirs(chunk_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)

    def parse_ts(ts: str) -> float:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    cut_points = [0.0] + [parse_ts(t) for t in timestamps]
    # --- Create video chunks (skip if outputs already exist) ---
    base, ext = os.path.splitext(os.path.basename(video_path))
    expected_parts = [
        os.path.join(chunk_dir, f"{base}_part{i:03d}{ext}")
        for i in range(len(timestamps) + 1)
    ]
    if all(os.path.exists(p) for p in expected_parts):
        print("⚡ Video segments already exist, skipping chunking.")
    else:
        chunk(video_path=video_path, timestamps=timestamps, output_dir=chunk_dir)
        print("\n✅ Video segments created.")

    with open(transcript_path, "rb") as f:
        transcript_chunks = pickle.load(f)

    chunk_files = sorted(os.listdir(chunk_dir))

    for idx, file in enumerate(chunk_files):
        chunk_start = cut_points[idx]
        video_file_path = os.path.join(chunk_dir, file)
        output_pdf = os.path.join(pdf_dir, f"{video_title}_part_{idx}.pdf")

        screenshots = extract_screenshots_cached(video_file_path, VIDEO_INTERVAL, chunk_start)

        used_matches = []
        page_pdfs = []

        with tempfile.TemporaryDirectory() as tempdir:
            for i, (local_ts, img_path) in tqdm(
                enumerate(screenshots, start=1),
                total=len(screenshots)
            ):
                abs_ts = chunk_start + local_ts
                caption = find_matching_chunk(transcript_chunks, abs_ts)

                match_obj = next(
                    (c for c in transcript_chunks if c[0] <= abs_ts < c[1]),
                    None
                )

                used_matches.append((local_ts, abs_ts, match_obj))

                page_pdf = os.path.join(tempdir, f"page_{i:03d}.pdf")
                pdf_api.image_to_pdf(img_path, caption, page_pdf)
                page_pdfs.append(page_pdf)

            write_match_debug_file(
                video_title,
                file,
                idx,
                chunk_start,
                screenshots,
                transcript_chunks,
                used_matches,
                interval=VIDEO_INTERVAL
            )

            pdf_api.merge_pdfs(page_pdfs, output_pdf)
            print(f"✅ PDF created: {output_pdf}")



def parse_ts(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def _url_hash(url: str) -> str:
    """8-char hash of a YouTube base URL (t= stripped) for use in PDF filenames."""
    clean = re.sub(r'[&?]t=\d+s?', '', url)
    return hashlib.md5(clean.encode()).hexdigest()[:8]


def make_youtube_url(base_url: str, seconds: float) -> str:
    """Return base_url with a t= timestamp parameter set to the given seconds."""
    t = int(seconds)
    # Strip any existing t= parameter
    clean = re.sub(r'[&?]t=\d+s?', '', base_url)
    sep = '&' if '?' in clean else '?'
    return f"{clean}{sep}t={t}"


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Generate slide PDFs from a video + transcript."
    )
    parser.add_argument("--config", default="config.yaml", help="Path to YAML config file (default: config.yaml)")
    parser.add_argument("--video-path", help="Override video_path from config")
    parser.add_argument("--video-title", help="Override video_title from config")
    parser.add_argument("--screenshot-interval", type=float, help="Override screenshot_interval")
    parser.add_argument("--transcript-interval", type=float, help="Override transcript_interval")
    parser.add_argument("--max-resolution", type=int, help="Override max_resolution")
    parser.add_argument("--verbose", action="store_true", help="Override verbose to True")
    parser.add_argument("--youtube-url", help="YouTube URL to embed as a timestamped footnote in each slide")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # CLI overrides (only when explicitly provided)
    if args.video_path:          cfg["video_path"] = args.video_path
    if args.video_title:         cfg["video_title"] = args.video_title
    if args.screenshot_interval: cfg["screenshot_interval"] = args.screenshot_interval
    if args.transcript_interval: cfg["transcript_interval"] = args.transcript_interval
    if args.max_resolution:      cfg["max_resolution"] = args.max_resolution
    if args.verbose:             cfg["verbose"] = True
    if args.youtube_url:         cfg["youtube_url"] = args.youtube_url

    # Resolve config values
    video_path_raw      = cfg["video_path"]
    video_title         = cfg["video_title"]
    split_timestamps    = cfg.get("split_timestamps") or []
    screenshot_interval = cfg.get("screenshot_interval", SCREENSHOT_INTERVAL)
    transcript_interval = cfg.get("transcript_interval", TRANSCRIPT_INTERVAL)
    max_resolution      = cfg.get("max_resolution", None)
    verbose                = cfg.get("verbose", False)
    screenshots_dir        = cfg.get("screenshots_dir", "screenshots")
    transcript_path        = cfg.get("transcript_path", None)
    video_dir              = cfg.get("video_dir", "videos")
    transcript_languages   = cfg.get("transcript_languages", None)

    # YouTube URL for per-slide footnote links (with timestamp)
    if _is_youtube(video_path_raw):
        youtube_base_url: Optional[str] = video_path_raw
    else:
        youtube_base_url = cfg.get("youtube_url") or None

    # 1. Download video if URL, otherwise use local path
    result = download_if_needed(video_path_raw, max_resolution=max_resolution, video_dir=video_dir, verbose=verbose)
    if result is None:
        print("ERROR: Could not resolve video path.")
        return
    _title, video_path = result

    # 2. Load or fetch transcript
    if transcript_path:
        with open(transcript_path, "rb") as f:
            transcript_chunks = pickle.load(f)
        if verbose:
            print(f"Loaded transcript from: {transcript_path}")
    else:
        transcript_chunks = download_timestamped_transcript(
            video_path_raw, transcript_interval=transcript_interval,
            video_dir=video_dir, languages=transcript_languages, verbose=verbose
        )
        if transcript_chunks is None:
            print("ERROR: Could not fetch transcript. For local videos, set transcript_path in config.yaml.")
            return

    # 3. Set up output dirs
    base_dir  = os.path.join("processed_videos", video_title)
    chunk_dir = os.path.join(base_dir, "chunks")
    pdf_dir   = os.path.join(base_dir, "pdfs")
    os.makedirs(chunk_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)

    # 4. Chunk video at timestamps (skip if none provided)
    if split_timestamps:
        cut_points  = [0.0] + [parse_ts(t) for t in split_timestamps]
        base, ext = os.path.splitext(os.path.basename(video_path))
        expected_parts = [
            os.path.join(chunk_dir, f"{base}_part{i:03d}{ext}")
            for i in range(len(split_timestamps) + 1)
        ]
        if all(os.path.exists(p) for p in expected_parts):
            print("⚡ Video segments already exist, skipping chunking.")
        else:
            chunk(video_path=video_path, timestamps=split_timestamps, output_dir=chunk_dir)
            print("✅ Video segments created.")
        chunk_files = sorted(os.listdir(chunk_dir))
    else:
        # No chunking — treat the whole video as one segment
        single_chunk = os.path.join(chunk_dir, os.path.basename(video_path))
        shutil.copy2(video_path, single_chunk)
        cut_points  = [0.0]
        chunk_files = [os.path.basename(video_path)]

    # 5. Process each chunk → screenshots → PDF
    for idx, file in enumerate(chunk_files):
        chunk_start     = cut_points[idx]
        video_file_path = os.path.join(chunk_dir, file)
        url_tag = f"_url{_url_hash(youtube_base_url)}" if youtube_base_url else ""
        if split_timestamps:
            pdf_name = f"{video_title}_part_{idx}_ss{screenshot_interval}s_tr{transcript_interval}s{url_tag}.pdf"
        else:
            pdf_name = f"{video_title}_ss{screenshot_interval}s_tr{transcript_interval}s{url_tag}.pdf"
        output_pdf = os.path.join(pdf_dir, pdf_name)

        if os.path.exists(output_pdf):
            print(f"⚡ PDF already exists, skipping: {output_pdf}")
            continue

        screenshots = extract_screenshots_cached(video_file_path, screenshot_interval, chunk_start, verbose=verbose)

        used_matches = []
        page_pdfs    = []

        with tempfile.TemporaryDirectory() as tempdir:
            for i, (local_ts, img_path) in tqdm(
                enumerate(screenshots, start=1), total=len(screenshots)
            ):
                abs_ts    = chunk_start + local_ts
                match_obj = next((c for c in transcript_chunks if c[0] <= abs_ts < c[1]), None)
                caption   = match_obj[2].strip() if match_obj else ""
                used_matches.append((local_ts, abs_ts, match_obj))
                page_pdf = os.path.join(tempdir, f"page_{i:03d}.pdf")
                footnote = make_youtube_url(youtube_base_url, abs_ts) if youtube_base_url else None
                pdf_api.image_to_pdf(img_path, caption, page_pdf, footnote_url=footnote)
                page_pdfs.append(page_pdf)

            write_match_debug_file(
                video_title, file, idx, chunk_start,
                screenshots, transcript_chunks, used_matches,
                interval=screenshot_interval,
            )
            pdf_api.merge_pdfs(page_pdfs, output_pdf)
            print(f"✅ PDF created: {output_pdf}")


if __name__ == "__main__":
    main()
