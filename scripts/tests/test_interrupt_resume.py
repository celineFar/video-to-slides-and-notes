"""
Tests for interrupt/resume behavior.

Verifies that re-running the pipeline after an interruption at any stage
correctly skips completed work and resumes from where it left off.
"""

import json
import os
import pickle
import subprocess
from pathlib import Path
from unittest import mock

import pytest

# Ensure project root is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import (
    VIDEO_ID,
    VIDEO_URL,
    VIDEO_TITLE,
    YDL_SAFE_TITLE,
    FETCH_SAFE_TITLE,
    CHAPTER_STARTS,
    TRANSCRIPT_INTERVAL,
    FAKE_INFO,
    FAKE_META,
    FAKE_TRANSCRIPT_SNIPPETS,
    FAKE_TRANSCRIPT_RAW,
    create_meta_json,
    create_fake_video,
    create_fake_pkl,
    make_ydl_mock,
)


# ===================================================================
# Group 1: download_video() unit tests
# ===================================================================

class TestDownloadVideoCache:
    """Tests for download_video() caching and resume logic."""

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    def test_full_cache_hit_skips_all_network(
        self, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """When both .meta.json and .mp4 exist, no yt-dlp calls are made."""
        from downloader import download_video

        create_meta_json(work_dir)
        create_fake_video(work_dir)

        title, video_path, chapter_starts = download_video(
            VIDEO_URL, output_dir=str(work_dir)
        )

        assert title == VIDEO_TITLE
        assert chapter_starts == CHAPTER_STARTS
        assert os.path.basename(video_path) == f"{YDL_SAFE_TITLE}.mp4"
        # YoutubeDL should never have been instantiated
        mock_ydl_cls.assert_not_called()

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    def test_meta_missing_mp4_exists_skips_download(
        self, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """When .mp4 exists but no .meta.json, fetches info but skips download."""
        from downloader import download_video

        create_fake_video(work_dir)
        # No meta.json

        mock_ydl = make_ydl_mock(work_dir)
        mock_ydl_cls.return_value.__enter__ = mock.Mock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = mock.Mock(return_value=False)

        title, video_path, chapter_starts = download_video(
            VIDEO_URL, output_dir=str(work_dir)
        )

        assert title == VIDEO_TITLE
        # extract_info was called (to get metadata)
        mock_ydl.extract_info.assert_called_once()
        # download was NOT called (mp4 already exists)
        mock_ydl.download.assert_not_called()
        # meta.json was written for future runs
        meta_path = work_dir / f"{VIDEO_ID}.meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["title"] == VIDEO_TITLE

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    def test_nothing_cached_does_full_download(
        self, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """When nothing is cached, does full download and creates both files."""
        from downloader import download_video

        mock_ydl = make_ydl_mock(work_dir)
        mock_ydl_cls.return_value.__enter__ = mock.Mock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = mock.Mock(return_value=False)

        title, video_path, chapter_starts = download_video(
            VIDEO_URL, output_dir=str(work_dir)
        )

        assert title == VIDEO_TITLE
        mock_ydl.extract_info.assert_called_once()
        mock_ydl.download.assert_called_once()
        # Both files should now exist
        assert (work_dir / f"{YDL_SAFE_TITLE}.mp4").exists()
        assert (work_dir / f"{VIDEO_ID}.meta.json").exists()

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    def test_continuedl_is_enabled(
        self, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """Verify continuedl: True is passed to yt-dlp options."""
        from downloader import download_video

        mock_ydl = make_ydl_mock(work_dir)
        mock_ydl_cls.return_value.__enter__ = mock.Mock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = mock.Mock(return_value=False)

        download_video(VIDEO_URL, output_dir=str(work_dir))

        # Check the opts passed to YoutubeDL constructor
        call_args = mock_ydl_cls.call_args
        opts = call_args[0][0] if call_args[0] else call_args[1]
        assert opts.get("continuedl") is True


# ===================================================================
# Group 2: Pipeline interrupt/resume integration tests
# ===================================================================

class TestPipelineInterruptResume:
    """
    Integration tests that call main() twice to simulate interrupt-then-resume.
    Mocks yt-dlp and transcript API at the lowest level so the real caching
    logic in download_video() and main() is exercised.
    """

    def _base_argv(self, work_dir, skip_upload=True):
        argv = [
            "fetch_and_upload.py",
            VIDEO_URL,
            "--output-dir", str(work_dir),
            "--transcript-interval", str(TRANSCRIPT_INTERVAL),
        ]
        if skip_upload:
            argv.append("--skip-upload")
        return argv

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    @mock.patch("youtube_transcript_api.YouTubeTranscriptApi")
    def test_interrupt_after_video__resumes_without_redownload(
        self, mock_transcript_cls, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """
        Run 1: Video downloads OK, transcript raises KeyboardInterrupt.
        Run 2: Video is skipped entirely (cached), transcript succeeds.
        """
        from fetch_and_upload import main

        mock_ydl = make_ydl_mock(work_dir)
        mock_ydl_cls.return_value.__enter__ = mock.Mock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = mock.Mock(return_value=False)

        # Run 1: transcript fetch raises KeyboardInterrupt
        mock_api = mock.MagicMock()
        mock_transcript_cls.return_value = mock_api
        mock_api.fetch.side_effect = KeyboardInterrupt("simulated interrupt")

        with mock.patch("sys.argv", self._base_argv(work_dir)):
            with pytest.raises(KeyboardInterrupt):
                main()

        # After run 1: video + meta exist, but no pkl
        assert (work_dir / f"{YDL_SAFE_TITLE}.mp4").exists()
        assert (work_dir / f"{VIDEO_ID}.meta.json").exists()
        pkl = work_dir / f"{FETCH_SAFE_TITLE}_transcript_{TRANSCRIPT_INTERVAL}s.pkl"
        assert not pkl.exists()

        # Run 2: transcript succeeds
        mock_api.fetch.side_effect = None
        mock_api.fetch.return_value = FAKE_TRANSCRIPT_SNIPPETS
        mock_ydl_cls.reset_mock()

        with mock.patch("sys.argv", self._base_argv(work_dir)):
            main()

        # On run 2, YoutubeDL should NOT have been instantiated (full cache hit)
        mock_ydl_cls.assert_not_called()
        # Transcript pkl should now exist
        assert pkl.exists()

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    @mock.patch("youtube_transcript_api.YouTubeTranscriptApi")
    def test_interrupt_after_transcript__resumes_without_redownload(
        self, mock_transcript_cls, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """
        Run 1: Video + transcript complete, config write raises.
        Run 2: Both video and transcript are skipped, config + rest succeeds.
        """
        from fetch_and_upload import main

        mock_ydl = make_ydl_mock(work_dir)
        mock_ydl_cls.return_value.__enter__ = mock.Mock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = mock.Mock(return_value=False)

        mock_api = mock.MagicMock()
        mock_transcript_cls.return_value = mock_api
        mock_api.fetch.return_value = FAKE_TRANSCRIPT_SNIPPETS

        # Run 1: interrupt during config write
        with mock.patch("sys.argv", self._base_argv(work_dir)):
            with mock.patch("fetch_and_upload.write_yaml", side_effect=KeyboardInterrupt):
                with pytest.raises(KeyboardInterrupt):
                    main()

        # After run 1: video, meta, and pkl all exist
        assert (work_dir / f"{YDL_SAFE_TITLE}.mp4").exists()
        assert (work_dir / f"{VIDEO_ID}.meta.json").exists()
        pkl = work_dir / f"{FETCH_SAFE_TITLE}_transcript_{TRANSCRIPT_INTERVAL}s.pkl"
        assert pkl.exists()

        # Run 2: everything resumes
        mock_ydl_cls.reset_mock()
        mock_api.fetch.reset_mock()

        with mock.patch("sys.argv", self._base_argv(work_dir)):
            main()

        # Video: YoutubeDL not called (full cache hit)
        mock_ydl_cls.assert_not_called()
        # Transcript: download_transcript not called (pkl exists)
        mock_api.fetch.assert_not_called()
        # Config should now exist
        assert (work_dir / "config.yaml").exists()

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    @mock.patch("youtube_transcript_api.YouTubeTranscriptApi")
    @mock.patch("fetch_and_upload.subprocess.run")
    def test_interrupt_during_upload__retries_upload(
        self, mock_run, mock_transcript_cls, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """
        Run 1: All local work done, upload (scp) fails.
        Run 2: Local work skipped, upload retried and succeeds.
        """
        from fetch_and_upload import main

        mock_ydl = make_ydl_mock(work_dir)
        mock_ydl_cls.return_value.__enter__ = mock.Mock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = mock.Mock(return_value=False)

        mock_api = mock.MagicMock()
        mock_transcript_cls.return_value = mock_api
        mock_api.fetch.return_value = FAKE_TRANSCRIPT_SNIPPETS

        # Run 1: scp fails
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

        with mock.patch("sys.argv", self._base_argv(work_dir, skip_upload=False)):
            main()

        # All local files exist
        assert (work_dir / f"{YDL_SAFE_TITLE}.mp4").exists()
        assert (work_dir / f"{VIDEO_ID}.meta.json").exists()
        pkl = work_dir / f"{FETCH_SAFE_TITLE}_transcript_{TRANSCRIPT_INTERVAL}s.pkl"
        assert pkl.exists()
        assert (work_dir / "config.yaml").exists()
        # scp was called but failed
        assert mock_run.called

        # Run 2: scp succeeds
        mock_ydl_cls.reset_mock()
        mock_api.fetch.reset_mock()
        mock_run.reset_mock()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

        with mock.patch("sys.argv", self._base_argv(work_dir, skip_upload=False)):
            main()

        # Local work was skipped
        mock_ydl_cls.assert_not_called()
        mock_api.fetch.assert_not_called()
        # Upload was retried
        assert mock_run.called


# ===================================================================
# Group 3: Edge cases
# ===================================================================

class TestEdgeCases:

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    def test_meta_exists_but_mp4_deleted_redownloads(
        self, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """If .meta.json exists but .mp4 is gone, falls to slow path and re-downloads."""
        from downloader import download_video

        create_meta_json(work_dir)
        # Do NOT create .mp4

        mock_ydl = make_ydl_mock(work_dir)
        mock_ydl_cls.return_value.__enter__ = mock.Mock(return_value=mock_ydl)
        mock_ydl_cls.return_value.__exit__ = mock.Mock(return_value=False)

        title, video_path, chapter_starts = download_video(
            VIDEO_URL, output_dir=str(work_dir)
        )

        # Should have fallen through to the slow path
        mock_ydl_cls.assert_called_once()
        mock_ydl.extract_info.assert_called_once()
        mock_ydl.download.assert_called_once()

    @mock.patch("downloader.yt_dlp.utils.sanitize_filename", return_value=YDL_SAFE_TITLE)
    @mock.patch("downloader.yt_dlp.YoutubeDL")
    @mock.patch("youtube_transcript_api.YouTubeTranscriptApi")
    def test_empty_transcript_creates_no_pkl(
        self, mock_transcript_cls, mock_ydl_cls, mock_sanitize, work_dir
    ):
        """When download_transcript returns [], no .pkl is created."""
        from fetch_and_upload import main

        # Setup: video is cached
        create_meta_json(work_dir)
        create_fake_video(work_dir)

        mock_api = mock.MagicMock()
        mock_transcript_cls.return_value = mock_api
        mock_api.fetch.return_value = []  # empty transcript

        with mock.patch("sys.argv", self._base_argv(work_dir)):
            main()

        pkl = work_dir / f"{FETCH_SAFE_TITLE}_transcript_{TRANSCRIPT_INTERVAL}s.pkl"
        assert not pkl.exists()

    def _base_argv(self, work_dir):
        return [
            "fetch_and_upload.py",
            VIDEO_URL,
            "--output-dir", str(work_dir),
            "--transcript-interval", str(TRANSCRIPT_INTERVAL),
            "--skip-upload",
        ]
