#!/usr/bin/env python3
import os
import re
import pickle
import tempfile
from typing import List, Tuple
from collections import defaultdict
from datetime import datetime

from chunking_4 import chunk
import pdf_api
from youtube_screenshot_script import run_extraction
from tqdm.auto import tqdm

VIDEO_INTERVAL = 2

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
def extract_screenshots(video_url: str, interval: int) -> List[Tuple[float, str]]:
    output_dir = tempfile.mkdtemp(prefix="screenshots_")

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
        verbose=True,
        thumbnail=True
    )

    folder = raw_results["output_folder"]
    return get_timestamped_frames(folder, interval)   # ✅ FIX


# ---------------------------
# ✅ STRICT TRANSCRIPT MATCHING
# ---------------------------
def find_matching_chunk(chunks, timestamp, eps=0.0001):
    for start, end, text in chunks:
        if start - eps <= timestamp < end + eps:
            return text.strip()
    return ""


# ---------------------------
# ✅ FIXED CACHING
# ---------------------------
def extract_screenshots_cached(video_file_path: str, interval: int, chunk_start: float):
    cache_dir = "screenshot_cache"
    os.makedirs(cache_dir, exist_ok=True)

    safe_name = os.path.basename(video_file_path).replace(".", "_")

    cache_file = os.path.join(
        cache_dir,
        f"{safe_name}_start_{int(chunk_start)}_screenshots.pkl"
    )

    if os.path.exists(cache_file):
        print(f"⚡ Loaded cached screenshots: {cache_file}")
        with open(cache_file, "rb") as f:
            return pickle.load(f)

    screenshots = extract_screenshots(video_file_path, interval)

    with open(cache_file, "wb") as f:
        pickle.dump(screenshots, f)

    print(f"💾 Cached screenshots saved to: {cache_file}")
    return screenshots


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

    base_dir = os.path.join("uploaded_videos", video_title)
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
    # --- Create video chunks ---
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


if __name__ == "__main__":
    main()
