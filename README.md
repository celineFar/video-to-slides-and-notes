<p align="center">
  <img src="Logo.png" alt="Video to Slides" width="280"/>
</p>

<h1 align="center">Video to Slides</h1>

<p align="center">
  <strong>Automatically convert YouTube videos into beautiful PDF slide decks</strong>
</p>

<p align="center">
  <a href="#features">Features</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#usage">Usage</a> &bull;
  <a href="#configuration">Configuration</a> &bull;
  <a href="#project-structure">Project Structure</a> &bull;
  <a href="#testing">Testing</a>
</p>

---

**Video to Slides** extracts frames and transcripts from YouTube videos (or local video files) and generates captioned PDF slide decks — perfect for turning lectures, tutorials, and presentations into study materials.

## Features

- **YouTube & local video support** — provide a URL to auto-download, or point to a local file
- **Automatic transcript fetching** — pulls captions from YouTube with multi-language fallback (English, Chinese, Japanese)
- **Intelligent frame extraction** — captures screenshots at configurable intervals with quality and blur filtering
- **Clickable timestamp links** — each PDF slide includes a footnote linking to the exact moment in the video
- **Video chunking** — split long videos at specific timestamps for multi-part slide decks
- **Smart caching** — pickle-based caching avoids re-processing the same video segments
- **YAML configuration** — simple config file with full CLI override support

## Quick Start

### Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and available in your PATH

### Installation

```bash
git clone <repo-url> && cd youtube-project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Generate your first slides

```bash
# Edit config.yaml with your video URL or path
python3 main.py --config config.yaml
```

Output PDFs will be saved to `processed_videos/<video_title>/pdfs/`.

## Usage

### From a YouTube URL

Set `video_path` in `config.yaml` to a YouTube URL:

```yaml
video_path: "https://www.youtube.com/watch?v=VIDEO_ID"
video_title: "My-Lecture"
```

```bash
python3 main.py --config config.yaml
```

The video and transcript will be downloaded automatically.

### From a local video file

```yaml
video_path: "uploads/my-video.mp4"
video_title: "My-Lecture"
transcript_path: "uploads/my_transcript.pkl"
youtube_url: "https://www.youtube.com/watch?v=VIDEO_ID"  # optional, for timestamp links
```

### Using the fetch scripts

**Download directly on the server:**

```bash
python3 scripts/fetch_local.py "https://www.youtube.com/watch?v=VIDEO_ID"
python3 main.py --config config.yaml
```

**Download locally and upload to a remote server:**

```bash
python3 scripts/fetch_and_upload.py --config scripts/fetch_config.yaml
```

### CLI overrides

Any config option can be overridden from the command line:

```bash
python3 main.py --config config.yaml \
  --video-path "path/to/video.mp4" \
  --screenshot-interval 2.0 \
  --transcript-interval 12 \
  --verbose
```

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `video_path` | *required* | YouTube URL or path to a local video file |
| `video_title` | *required* | Label used for output folder naming |
| `video_dir` | `"videos"` | Directory for downloaded YouTube videos |
| `screenshot_interval` | `4.5` | Seconds between captured frames |
| `transcript_interval` | `9` | Seconds per transcript chunk |
| `max_resolution` | `null` | Cap video download quality (e.g. `720`, `1080`) |
| `split_timestamps` | `[]` | `HH:MM:SS` timestamps to split video into parts |
| `transcript_path` | `null` | Path to a pre-saved transcript pickle |
| `transcript_languages` | `["en", "zh-Hant", ...]` | Language fallback order for YouTube captions |
| `screenshots_dir` | `"screenshots"` | Root folder for extracted frames |
| `youtube_url` | `null` | YouTube link for PDF timestamp footnotes (local videos only) |
| `verbose` | `false` | Enable detailed progress logging |

## Project Structure

```
youtube-project/
├── main.py                        # Pipeline orchestrator
├── youtube_screenshot_script.py   # Frame extraction engine
├── pdf_api.py                     # PDF generation utilities
├── transcript_api.py              # Transcript fetching
├── chunking_utils.py              # Video segmentation with FFmpeg
├── config.yaml                    # Runtime configuration
├── requirements.txt               # Python dependencies
│
├── scripts/
│   ├── fetch_and_upload.py        # Download & upload via SSH/rsync
│   ├── fetch_local.py             # Download directly on server
│   └── fetch_config.yaml          # Config template for fetch scripts
│
├── tests/                         # 62 pytest tests
│   ├── test_cache_and_skip.py     # Caching & skip logic
│   ├── test_youtube_url.py        # Timestamp URL generation
│   └── test_chunking_and_sync.py  # Timestamp alignment & sync
│
├── processed_videos/              # Output PDFs
├── screenshots/                   # Extracted frames
├── extracted_frames_cache/        # Frame cache (pickle)
├── uploads/                       # Input staging area
└── debug_logs/                    # Match debug reports
```

## How It Works

```
Config + CLI args
       ↓
 Download video & transcript (or load from disk)
       ↓
 Split into chunks (optional, via FFmpeg)
       ↓
 For each chunk:
   → Extract frames at regular intervals (with caching)
   → Match each frame to its transcript segment by timestamp
   → Generate a PDF page per frame with caption + timestamp link
   → Merge pages into a final PDF
```

## Testing

Run the full test suite:

```bash
.venv/bin/pytest tests/ -v
```

The suite covers caching logic, URL timestamp injection, transcript-to-frame matching, chunk boundary handling, and PDF naming conventions — all without requiring live YouTube calls.

## Acknowledgements

This project is a fork of [youtube-screenshot-extractor](https://github.com/EnragedAntelope/youtube-screenshot-extractor) by EnragedAntelope, extended with transcript matching, PDF slide generation, video chunking, and smart caching.
