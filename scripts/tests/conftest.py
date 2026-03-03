"""Shared fixtures and constants for interrupt/resume tests."""

import json
import os
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_ID = "dQw4w9WgXcQ"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
VIDEO_TITLE = "Test Video Title"

# What yt_dlp.utils.sanitize_filename(VIDEO_TITLE, restricted=True) produces
YDL_SAFE_TITLE = "Test_Video_Title"

# What fetch_and_upload.sanitize(VIDEO_TITLE) produces (re.sub based)
FETCH_SAFE_TITLE = "Test_Video_Title"

CHAPTER_STARTS = ["00:01:00", "00:05:00"]
TRANSCRIPT_INTERVAL = 9

FAKE_INFO = {
    "title": VIDEO_TITLE,
    "duration_string": "10:00",
    "uploader": "TestUploader",
    "chapters": [
        {"start_time": 0, "title": "Intro"},
        {"start_time": 60, "title": "Chapter 1"},
        {"start_time": 300, "title": "Chapter 2"},
    ],
}

FAKE_META = {
    "title": VIDEO_TITLE,
    "chapter_starts": CHAPTER_STARTS,
    "duration": "10:00",
    "uploader": "TestUploader",
}


@dataclass
class FakeSnippet:
    text: str
    start: float
    duration: float


FAKE_TRANSCRIPT_SNIPPETS = [
    FakeSnippet(text="Hello world", start=0.0, duration=3.0),
    FakeSnippet(text="This is a test", start=3.0, duration=4.0),
    FakeSnippet(text="Another segment", start=10.0, duration=3.0),
]

FAKE_TRANSCRIPT_RAW = [
    {"text": s.text, "start": s.start, "duration": s.duration}
    for s in FAKE_TRANSCRIPT_SNIPPETS
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def work_dir(tmp_path):
    """A clean temp directory for downloads."""
    return tmp_path


@pytest.fixture
def meta_json_path(work_dir):
    return work_dir / f"{VIDEO_ID}.meta.json"


@pytest.fixture
def video_path(work_dir):
    return work_dir / f"{YDL_SAFE_TITLE}.mp4"


@pytest.fixture
def pkl_path(work_dir):
    return work_dir / f"{FETCH_SAFE_TITLE}_transcript_{TRANSCRIPT_INTERVAL}s.pkl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_meta_json(work_dir, meta=None):
    """Write a .meta.json sidecar file."""
    path = work_dir / f"{VIDEO_ID}.meta.json"
    path.write_text(json.dumps(meta or FAKE_META))
    return path


def create_fake_video(work_dir):
    """Write a fake .mp4 file."""
    path = work_dir / f"{YDL_SAFE_TITLE}.mp4"
    path.write_bytes(b"fake mp4 data")
    return path


def create_fake_pkl(work_dir):
    """Write a fake transcript .pkl file."""
    path = work_dir / f"{FETCH_SAFE_TITLE}_transcript_{TRANSCRIPT_INTERVAL}s.pkl"
    chunks = [(0.0, 9.0, "Hello world This is a test"), (9.0, 18.0, "Another segment")]
    with open(path, "wb") as f:
        pickle.dump(chunks, f)
    return path


def make_ydl_mock(work_dir):
    """Create a mock YoutubeDL instance whose download() creates a fake .mp4."""
    mock_ydl = mock.MagicMock()
    mock_ydl.extract_info.return_value = FAKE_INFO

    def create_mp4(urls):
        (work_dir / f"{YDL_SAFE_TITLE}.mp4").write_bytes(b"fake mp4 data")

    mock_ydl.download.side_effect = create_mp4
    return mock_ydl
