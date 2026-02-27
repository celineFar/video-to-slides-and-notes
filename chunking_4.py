#!/usr/bin/env python3
import os
import sys
import json
import subprocess
from shutil import which

def run(cmd):
    """Run a command, return (exitcode, stdout+stderr)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out, _ = p.communicate()
    return p.returncode, out

def parse_time(ts):
    """“HH:MM:SS”, a bare digit string, or a number → seconds (float)."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if ts.isdigit():
        return float(ts)
    parts = ts.split(":")
    if len(parts) == 3:
        hh, mm, ss = map(float, parts)
        return hh * 3600 + mm * 60 + ss
    raise ValueError(f"Bad time: {ts}")

def get_duration(path):
    """ffprobe → duration in seconds."""
    code, out = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", path
    ])
    if code != 0:
        raise RuntimeError(f"ffprobe failed:\n{out}")
    return float(json.loads(out)["format"]["duration"])

def fast_split(video, cuts, out_dir, base, ext):
    """Try ffmpeg -f segment to produce header-complete copies."""
    pts = ",".join(str(c) for c in cuts)
    pattern = os.path.join(out_dir, f"{base}_part%03d{ext}")
    cmd = [
        "ffmpeg", "-y",
        "-i", video,
        "-f", "segment",
        "-segment_times", pts,
        "-reset_timestamps", "1",
        "-c", "copy",
        "-movflags", "+faststart+frag_keyframe",
        pattern
    ]
    print("→ Attempting fast split with segment muxer…")
    code, out = run(cmd)
    if code == 0:
        return sorted(f for f in os.listdir(out_dir)
                      if f.startswith(base + "_part") and f.endswith(ext))
    print("⚠️  Fast split failed, ffmpeg said:\n", out)
    return []

def safe_transcode(video, cuts, out_dir, base, ext):
    """For each interval, re-encode to H.264/AAC so headers and codec data are fresh."""
    parts = []
    duration = get_duration(video)
    points = [0.0] + cuts + [duration]
    for i in range(len(points)-1):
        s, e = points[i], points[i+1]
        out_fn = f"{base}_part{i:03d}{ext}"
        out_path = os.path.join(out_dir, out_fn)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(s),
            "-to", str(e),
            "-i", video,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path
        ]
        print(f"→ Transcoding slice {i}: {s:.2f}s → {e:.2f}s")
        code, out = run(cmd)
        if code != 0:
            raise RuntimeError(f"Transcode failed for part {i}:\n{out}")
        parts.append(out_fn)
    return parts

def chunk(video_path, timestamps, output_dir=None):
    # 1) parse + clamp
    duration = get_duration(video_path)
    cuts = []
    for ts in timestamps:
        try:
            t = parse_time(ts)
        except ValueError:
            continue
        if 0 < t < duration:
            cuts.append(t)
    if not cuts:
        raise ValueError("No valid cut points found.")
    cuts = sorted(set(cuts))

    # 2) prep output
    if output_dir is None:
        output_dir = os.getcwd()
    os.makedirs(output_dir, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(video_path))

    # 3) fast split
    parts = fast_split(video_path, cuts, output_dir, base, ext)
    if parts:
        return [os.path.join(output_dir, p) for p in parts]

    # 4) fallback transcode
    print("→ Falling back to safe H.264 re-encode for each segment…")
    parts = safe_transcode(video_path, cuts, output_dir, base, ext)
    return [os.path.join(output_dir, p) for p in parts]


def main():
    video_file = "video.mp4"
    timestamps = ["00:18:35", "00:33:07", "00:44:29", "00:55:36", "01:14:14", "01:31:01","01:42:54","02:03:20","02:28:46", "02:52:09"]
    output_dir="segments_chunking_4"
    parts = chunk(video_file, timestamps, output_dir=output_dir)
    print("\nCreated segments:")
    for p in parts:
        print("  " + p)

if __name__ == "__main__":
    main()
