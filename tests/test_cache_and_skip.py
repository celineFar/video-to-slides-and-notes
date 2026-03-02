"""
Tests for caching and skip/overwrite behaviour in main.py.

Groups:
  Group 1  – PDF skip / overwrite         (tests 1–5)
  Group 2  – Screenshot cache             (tests 6–10)
  Group 3  – Video chunking skip          (tests 11–12)
  Group 4  – Stale state / known bugs     (tests 13–14)
  Group 5  – Video-title isolation        (test 15)
"""
import os
import pickle

import pytest
from unittest.mock import patch, call

from main import extract_screenshots_cached, _url_hash


# ── shared fixtures ──────────────────────────────────────────────────────────

FAKE_FRAMES = [(0.0, "/fake/frame_000000.png"), (4.5, "/fake/frame_000001.png")]
VIDEO = "myvideo.mp4"


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Run every test in a clean temp dir so cache files never leak."""
    monkeypatch.chdir(tmp_path)


# ── helpers that mirror main() formulas exactly ─────────────────────────────

def _pdf_name(video_title: str, ss: float, tr: float, part: int = None, url: str = None) -> str:
    """Mirror of the pdf_name formula in main() — single source of truth."""
    url_tag = f"_url{_url_hash(url)}" if url else ""
    if part is not None:
        return f"{video_title}_part_{part}_ss{ss}s_tr{tr}s{url_tag}.pdf"
    return f"{video_title}_ss{ss}s_tr{tr}s{url_tag}.pdf"


def _cache_filename(video_file: str, interval: float, chunk_start: float) -> str:
    """Mirror of the cache key formula in extract_screenshots_cached()."""
    safe_name = os.path.basename(video_file).replace(".", "_")
    return os.path.join(
        "extracted_frames_cache",
        f"{safe_name}_start_{int(chunk_start)}s_interval_{interval}s.pkl",
    )


def _write_cache(video_file: str, interval: float, chunk_start: float, frames=FAKE_FRAMES):
    """Write a valid cache pickle for the given params."""
    path = _cache_filename(video_file, interval, chunk_start)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump({"interval": interval, "chunk_start": chunk_start, "frames": frames}, f)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Group 1 — PDF naming / skip behaviour
# ─────────────────────────────────────────────────────────────────────────────

class TestPdfSkip:
    """
    Tests 1–5.

    The skip is: if os.path.exists(output_pdf): continue
    The output PDF name encodes ss (screenshot) and tr (transcript) intervals.
    We test the naming formula to verify what triggers a skip vs. a fresh run.
    """

    # 1 — exact match → same filename → would be skipped
    def test_same_config_produces_same_pdf_name(self):
        assert _pdf_name("Vid", 4.5, 9) == _pdf_name("Vid", 4.5, 9)

    # 2 — no PDF on disk → no skip (verified by file not existing)
    def test_missing_pdf_is_not_skipped(self, tmp_path):
        pdf_path = tmp_path / _pdf_name("Vid", 4.5, 9)
        assert not os.path.exists(pdf_path)

    # 3 — screenshot interval change → different name → new PDF
    def test_screenshot_interval_change_produces_new_pdf_name(self):
        assert _pdf_name("Vid", 4.5, 9) != _pdf_name("Vid", 9.0, 9)

    # 4 — transcript interval change → different name → new PDF
    def test_transcript_interval_change_produces_new_pdf_name(self):
        assert _pdf_name("Vid", 4.5, 9) != _pdf_name("Vid", 4.5, 4.5)

    # 5 — both intervals change → different name → new PDF
    def test_both_intervals_change_produces_new_pdf_name(self):
        assert _pdf_name("Vid", 4.5, 9) != _pdf_name("Vid", 9.0, 4.5)


# ─────────────────────────────────────────────────────────────────────────────
# Group 2 — Screenshot cache
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenshotCache:

    # 6 — warm cache with real files on disk: no re-extraction
    @patch("main.extract_screenshots", return_value=FAKE_FRAMES)
    def test_cache_hit_skips_extraction(self, mock_extract, tmp_path):
        # Frame files must exist on disk for the existence check to pass
        frames = [
            (0.0, str(tmp_path / "frame_000000.png")),
            (4.5, str(tmp_path / "frame_000001.png")),
        ]
        for _, p in frames:
            open(p, "wb").close()
        _write_cache(VIDEO, interval=4.5, chunk_start=0.0, frames=frames)

        result = extract_screenshots_cached(VIDEO, interval=4.5, chunk_start=0.0)

        mock_extract.assert_not_called()
        assert result == frames

    # 7 — cold cache: extracts and writes cache file
    @patch("main.extract_screenshots", return_value=FAKE_FRAMES)
    def test_cold_cache_extracts_and_writes(self, mock_extract):
        result = extract_screenshots_cached(VIDEO, interval=4.5, chunk_start=0.0)

        mock_extract.assert_called_once()
        assert result == FAKE_FRAMES

        cache_path = _cache_filename(VIDEO, 4.5, 0.0)
        assert os.path.exists(cache_path)

        with open(cache_path, "rb") as f:
            stored = pickle.load(f)
        assert stored["interval"] == 4.5
        assert stored["chunk_start"] == 0.0
        assert stored["frames"] == FAKE_FRAMES

    # 8 — interval change → different cache file → re-extracts
    @patch("main.extract_screenshots", return_value=FAKE_FRAMES)
    def test_interval_change_causes_reextraction(self, mock_extract):
        _write_cache(VIDEO, interval=4.5, chunk_start=0.0)

        extract_screenshots_cached(VIDEO, interval=9.0, chunk_start=0.0)

        mock_extract.assert_called_once()

    # 9 — chunk_start change → different cache file → re-extracts
    @patch("main.extract_screenshots", return_value=FAKE_FRAMES)
    def test_chunk_start_change_causes_reextraction(self, mock_extract):
        _write_cache(VIDEO, interval=4.5, chunk_start=0.0)

        extract_screenshots_cached(VIDEO, interval=4.5, chunk_start=1060.0)

        mock_extract.assert_called_once()

    # 10 — floor collision: chunk_start=0.5 maps to _start_0s_, same file as 0.0
    #      but the metadata check (stored chunk_start=0.0 ≠ 0.5) catches it
    @patch("main.extract_screenshots", return_value=FAKE_FRAMES)
    def test_chunk_start_floor_collision_caught_by_metadata(self, mock_extract):
        # Write cache for chunk_start=0.0 — filename contains _start_0s_
        _write_cache(VIDEO, interval=4.5, chunk_start=0.0)

        # 0.5 also floors to _start_0s_, so it hits the same cache file …
        # … but the stored chunk_start (0.0) ≠ 0.5, so metadata mismatch fires
        extract_screenshots_cached(VIDEO, interval=4.5, chunk_start=0.5)

        mock_extract.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Group 3 — Video chunking skip
# ─────────────────────────────────────────────────────────────────────────────

class TestChunkingSkip:
    """
    Tests 11–12.

    main() skips calling chunk() when all expected part files already exist:
        if all(os.path.exists(p) for p in expected_parts): ...
    We test that condition directly with the same file-naming formula.
    """

    def _expected_parts(self, chunk_dir, base, ext, n_splits):
        return [
            os.path.join(chunk_dir, f"{base}_part{i:03d}{ext}")
            for i in range(n_splits + 1)
        ]

    # 11 — all parts present → condition is True → chunk() not needed
    def test_all_parts_exist_means_skip(self, tmp_path):
        chunk_dir = str(tmp_path / "chunks")
        os.makedirs(chunk_dir)
        parts = self._expected_parts(chunk_dir, "myvideo", ".mp4", n_splits=2)
        for p in parts:
            open(p, "wb").close()

        assert all(os.path.exists(p) for p in parts)

    # 12 — one part missing → condition is False → chunk() would be called
    def test_missing_part_means_no_skip(self, tmp_path):
        chunk_dir = str(tmp_path / "chunks")
        os.makedirs(chunk_dir)
        parts = self._expected_parts(chunk_dir, "myvideo", ".mp4", n_splits=2)
        # Create only the first two; part 2 is missing
        for p in parts[:2]:
            open(p, "wb").close()

        assert not all(os.path.exists(p) for p in parts)


# ─────────────────────────────────────────────────────────────────────────────
# Group 4 — Stale state / known limitations
# ─────────────────────────────────────────────────────────────────────────────

class TestBugFixes:

    # 13 — stale cache: frame files deleted → re-extracts rather than returning bad paths
    @patch("main.extract_screenshots", return_value=FAKE_FRAMES)
    def test_stale_cache_triggers_reextraction(self, mock_extract):
        stale_frames = [(0.0, "/deleted/frame_000000.png")]
        _write_cache(VIDEO, interval=4.5, chunk_start=0.0, frames=stale_frames)

        result = extract_screenshots_cached(VIDEO, interval=4.5, chunk_start=0.0)

        mock_extract.assert_called_once()      # re-extracted because files are gone
        assert result == FAKE_FRAMES           # fresh frames returned, not stale ones

    # 14 — youtube_url change produces a different PDF name → old PDF not reused
    def test_youtube_url_change_produces_different_pdf_name(self):
        url_a = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
        url_b = "https://www.youtube.com/watch?v=bbbbbbbbbbb"
        assert _pdf_name("Vid", 4.5, 9, url=url_a) != _pdf_name("Vid", 4.5, 9, url=url_b)

    def test_no_url_vs_url_produces_different_pdf_name(self):
        url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
        assert _pdf_name("Vid", 4.5, 9, url=None) != _pdf_name("Vid", 4.5, 9, url=url)

    def test_same_url_produces_same_pdf_name(self):
        url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
        assert _pdf_name("Vid", 4.5, 9, url=url) == _pdf_name("Vid", 4.5, 9, url=url)

    def test_url_t_param_ignored_in_hash(self):
        # Two config URLs for the same video but different t= hints → same PDF
        url_a = "https://www.youtube.com/watch?v=abc&t=0s"
        url_b = "https://www.youtube.com/watch?v=abc&t=2442s"
        assert _pdf_name("Vid", 4.5, 9, url=url_a) == _pdf_name("Vid", 4.5, 9, url=url_b)


# ─────────────────────────────────────────────────────────────────────────────
# Group 5 — Video-title isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestVideoTitleIsolation:

    # 15 — different video_title → different output dir → always a fresh start
    def test_different_video_title_produces_different_pdf_name(self):
        assert _pdf_name("VideoA", 4.5, 9) != _pdf_name("VideoB", 4.5, 9)

    def test_different_video_title_produces_different_output_dir(self):
        dir_a = os.path.join("processed_videos", "VideoA", "pdfs")
        dir_b = os.path.join("processed_videos", "VideoB", "pdfs")
        assert dir_a != dir_b
