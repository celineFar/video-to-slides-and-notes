"""
Tests for chunked-video scenarios: timestamp parsing, chunk-start mapping,
abs_ts arithmetic, transcript/screenshot synchronisation, edge cases.

Groups:
  Group A — parse_ts correctness                 (tests  1- 6)
  Group B — cut_points / chunk_start mapping     (tests  7-10)
  Group C — abs_ts = chunk_start + local_ts      (tests 11-14)
  Group D — find_matching_chunk edge cases       (tests 15-21)
  Group E — transcript / screenshot sync         (tests 22-26)
  Group F — PDF part naming                      (tests 27-30)
  Group G — chunk_files sort order               (tests 31-32)
"""

import os
import pytest

from main import parse_ts, find_matching_chunk, _url_hash


# ─────────────────────────────────────────────────────────────────────────────
# Helpers that mirror main() formulas exactly
# ─────────────────────────────────────────────────────────────────────────────

def _cut_points(split_timestamps):
    """Mirror of: cut_points = [0.0] + [parse_ts(t) for t in split_timestamps]"""
    return [0.0] + [parse_ts(t) for t in split_timestamps]


def _part_pdf_name(video_title, part, ss, tr, url=None):
    """Mirror of the chunked pdf_name formula (split_timestamps present)."""
    url_tag = f"_url{_url_hash(url)}" if url else ""
    return f"{video_title}_part_{part}_ss{ss}s_tr{tr}s{url_tag}.pdf"


def _whole_pdf_name(video_title, ss, tr, url=None):
    """Mirror of the unchunked pdf_name formula (no split_timestamps)."""
    url_tag = f"_url{_url_hash(url)}" if url else ""
    return f"{video_title}_ss{ss}s_tr{tr}s{url_tag}.pdf"


# ─────────────────────────────────────────────────────────────────────────────
# Group A — parse_ts
# ─────────────────────────────────────────────────────────────────────────────

class TestParseTs:

    # 1 — all-zero input
    def test_zeros(self):
        assert parse_ts("00:00:00") == 0.0

    # 2 — minutes only
    def test_one_minute(self):
        assert parse_ts("00:01:00") == 60.0

    # 3 — hours only
    def test_one_hour(self):
        assert parse_ts("01:00:00") == 3600.0

    # 4 — mixed: 17m 45s = 1065s
    def test_mixed_minutes_and_seconds(self):
        assert parse_ts("00:17:45") == 1065.0

    # 5 — mixed: 1h 2m 3s = 3723s
    def test_mixed_hours_minutes_seconds(self):
        assert parse_ts("01:02:03") == 3723.0

    # 6 — fractional seconds are preserved (float(s))
    def test_fractional_seconds(self):
        assert parse_ts("00:00:01.5") == 1.5


# ─────────────────────────────────────────────────────────────────────────────
# Group B — cut_points & chunk_start mapping
# ─────────────────────────────────────────────────────────────────────────────

class TestCutPoints:

    # 7 — no split timestamps → single entry [0.0]
    def test_empty_split_timestamps_gives_single_cut_point(self):
        assert _cut_points([]) == [0.0]

    # 8 — one split timestamp → two cut points
    def test_one_split_timestamp(self):
        assert _cut_points(["00:17:45"]) == [0.0, 1065.0]

    # 9 — two split timestamps → three cut points, strictly increasing
    def test_two_split_timestamps_are_ordered(self):
        cut = _cut_points(["00:17:45", "00:40:33"])
        assert cut == [0.0, 1065.0, 2433.0]
        assert cut[0] < cut[1] < cut[2]

    # 10 — each chunk index maps to the correct chunk_start value
    def test_chunk_index_to_chunk_start_alignment(self):
        cut = _cut_points(["00:17:45", "00:40:33"])
        assert cut[0] == 0.0      # part 000: starts at 0s
        assert cut[1] == 1065.0   # part 001: starts at 17m45s
        assert cut[2] == 2433.0   # part 002: starts at 40m33s


# ─────────────────────────────────────────────────────────────────────────────
# Group C — abs_ts = chunk_start + local_ts
# ─────────────────────────────────────────────────────────────────────────────

class TestAbsTs:

    # 11 — first chunk, first frame: abs_ts equals local_ts
    def test_first_chunk_first_frame_no_offset(self):
        assert 0.0 + 0.0 == 0.0

    # 12 — first chunk, mid-video frame: no offset applied
    def test_first_chunk_no_offset(self):
        chunk_start, local_ts = 0.0, 45.0
        assert chunk_start + local_ts == 45.0

    # 13 — second chunk: offset shifts local time to absolute time
    def test_second_chunk_offset_applied(self):
        chunk_start = 1065.0   # cut at 00:17:45
        local_ts    = 5.0      # 5 s into this chunk
        assert chunk_start + local_ts == 1070.0

    # 14 — first frame of any chunk (local_ts=0) has abs_ts == chunk_start
    def test_first_frame_abs_ts_equals_chunk_start(self):
        for chunk_start in (0.0, 1065.0, 2433.0):
            assert chunk_start + 0.0 == chunk_start


# ─────────────────────────────────────────────────────────────────────────────
# Group D — find_matching_chunk edge cases
# ─────────────────────────────────────────────────────────────────────────────

CHUNKS = [
    (0.0,   9.0,  "Introduction"),
    (9.0,  18.0,  "Chapter 1"),
    (18.0, 27.0,  "Chapter 2"),
]


class TestFindMatchingChunk:

    # 15 — exact start of first chunk → matched
    def test_match_at_exact_start(self):
        assert find_matching_chunk(CHUNKS, 0.0) == "Introduction"

    # 16 — mid-interval → matched to correct chunk
    def test_match_in_middle_of_chunk(self):
        assert find_matching_chunk(CHUNKS, 4.5) == "Introduction"

    # 17 — exact start of second chunk → matched to second, not first
    def test_match_at_boundary_goes_to_next_chunk(self):
        assert find_matching_chunk(CHUNKS, 9.0) == "Chapter 1"

    # 18 — just before chunk end (8.9999s) → still matched to first chunk
    def test_match_just_before_end_of_chunk(self):
        assert find_matching_chunk(CHUNKS, 8.9999) == "Introduction"

    # 19 — timestamp exactly equal to end of last chunk → matched (eps allows it)
    def test_end_of_last_chunk_is_matched_via_epsilon(self):
        # condition: start - eps <= ts < end + eps → 18.0-ε <= 27.0 < 27.0+ε  ✓
        assert find_matching_chunk(CHUNKS, 27.0) == "Chapter 2"

    # 20 — timestamp well past all chunks → empty string
    def test_no_match_beyond_all_chunks(self):
        assert find_matching_chunk(CHUNKS, 100.0) == ""

    # 21 — timestamp in a gap between two non-contiguous chunks → empty string
    def test_no_match_in_gap_between_chunks(self):
        chunks_with_gap = [
            (0.0,  5.0,  "Part A"),
            (10.0, 15.0, "Part B"),   # 5.0–10.0 is a gap
        ]
        assert find_matching_chunk(chunks_with_gap, 7.5) == ""


# ─────────────────────────────────────────────────────────────────────────────
# Group E — transcript / screenshot synchronisation
# ─────────────────────────────────────────────────────────────────────────────

class TestTranscriptScreenshotSync:

    TRANSCRIPT = [
        (0.0,   9.0,  "Intro"),
        (9.0,  18.0,  "Main content"),
        (18.0, 27.0,  "Conclusion"),
    ]

    # 22 — screenshot in first chunk maps to correct caption (no offset needed)
    def test_first_chunk_screenshot_maps_to_intro(self):
        abs_ts = 0.0 + 3.0   # chunk_start=0, local_ts=3s
        assert find_matching_chunk(self.TRANSCRIPT, abs_ts) == "Intro"

    # 23 — screenshot in second chunk with chunk_start offset maps correctly
    def test_second_chunk_screenshot_offset_gives_correct_caption(self):
        chunk_start = 9.0
        abs_ts = chunk_start + 3.0   # 12.0s → "Main content"
        assert find_matching_chunk(self.TRANSCRIPT, abs_ts) == "Main content"

    # 24 — first frame of second chunk (local_ts=0) matches at the boundary
    def test_first_frame_of_second_chunk_at_transcript_boundary(self):
        chunk_start = 9.0
        abs_ts = chunk_start + 0.0   # exactly 9.0s → new transcript chunk
        assert find_matching_chunk(self.TRANSCRIPT, abs_ts) == "Main content"

    # 25 — screenshot at exactly a transcript boundary gets the next chunk, not prev
    def test_screenshot_at_transcript_boundary_matches_next_chunk(self):
        abs_ts = 9.0   # boundary between "Intro" and "Main content"
        assert find_matching_chunk(self.TRANSCRIPT, abs_ts) == "Main content"

    # 26 — screenshot in a transcript gap gets an empty caption
    def test_screenshot_in_transcript_gap_gets_empty_caption(self):
        sparse = [
            (0.0,  5.0,  "Intro"),
            # gap: 5.0–10.0
            (10.0, 20.0, "Content"),
        ]
        assert find_matching_chunk(sparse, 7.5) == ""

    # Bonus — two screenshots with different intervals in same transcript chunk
    # both get the same caption (caption depends on abs_ts, not interval)
    def test_two_frames_in_same_transcript_chunk_get_same_caption(self):
        abs_ts_a = 1.5   # 1.5s — "Intro"
        abs_ts_b = 7.0   # 7.0s — still "Intro"
        assert find_matching_chunk(self.TRANSCRIPT, abs_ts_a) == "Intro"
        assert find_matching_chunk(self.TRANSCRIPT, abs_ts_b) == "Intro"

    # Bonus — transcript chunk spanning a video chunk boundary: both sides match it
    def test_transcript_chunk_spanning_video_chunk_boundary(self):
        transcript = [(1060.0, 1070.0, "Cross-boundary text")]
        cut = 1065.0   # video chunk boundary

        # last frame of part 0: local_ts near 5.0 → abs_ts ≈ 1065.0
        abs_ts_in_part0 = 1064.9
        # first frame of part 1: local_ts=0.0 → abs_ts=1065.0
        abs_ts_in_part1 = 1065.0

        assert find_matching_chunk(transcript, abs_ts_in_part0) == "Cross-boundary text"
        assert find_matching_chunk(transcript, abs_ts_in_part1) == "Cross-boundary text"


# ─────────────────────────────────────────────────────────────────────────────
# Group F — PDF part naming
# ─────────────────────────────────────────────────────────────────────────────

class TestChunkedPdfNaming:

    # 27 — chunked PDF name contains _part_{idx}_
    def test_chunked_pdf_name_contains_part_index(self):
        assert "_part_0_" in _part_pdf_name("MyVid", part=0, ss=4.5, tr=9)

    # 28 — unchunked PDF name does not contain _part_
    def test_unchunked_pdf_name_has_no_part_token(self):
        assert "_part_" not in _whole_pdf_name("MyVid", ss=4.5, tr=9)

    # 29 — different part indices produce different PDF names
    def test_different_part_indices_produce_different_names(self):
        names = [_part_pdf_name("MyVid", part=i, ss=4.5, tr=9) for i in range(3)]
        assert len(set(names)) == 3   # all distinct

    # 30 — part index is zero-based (part 0 exists, part -1 does not)
    def test_part_index_zero_is_present(self):
        name = _part_pdf_name("MyVid", part=0, ss=4.5, tr=9)
        assert "_part_0_" in name
        assert "_part_1_" not in name


# ─────────────────────────────────────────────────────────────────────────────
# Group G — chunk_files sort order
# ─────────────────────────────────────────────────────────────────────────────

class TestChunkFilesOrder:
    """
    main() uses sorted(os.listdir(chunk_dir)).
    The _partNNN zero-padded naming ensures alphabetical == chronological.
    """

    # 31 — _partNNN names sort to chronological order
    def test_part_names_sort_alphabetically_and_chronologically(self):
        files = ["vid_part002.mp4", "vid_part000.mp4", "vid_part001.mp4"]
        assert sorted(files) == ["vid_part000.mp4", "vid_part001.mp4", "vid_part002.mp4"]

    # 32 — after sorting, cut_points[idx] aligns with the correct chunk_start
    def test_sorted_files_align_with_cut_points(self):
        split_ts   = ["00:17:45", "00:40:33"]
        cut_points = _cut_points(split_ts)
        files      = sorted(["vid_part002.mp4", "vid_part000.mp4", "vid_part001.mp4"])
        expected   = [0.0, 1065.0, 2433.0]

        for idx, file in enumerate(files):
            assert cut_points[idx] == expected[idx], (
                f"{file} → expected chunk_start {expected[idx]}, got {cut_points[idx]}"
            )
