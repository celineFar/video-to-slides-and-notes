# Test Suite Overview

Three test files covering caching/skip behaviour, YouTube URL generation, and
chunked-video synchronisation. Run the full suite from the project root:

```
.venv/bin/pytest tests/ -v
```

---

## File map

| File | Tests | What it covers |
|------|------:|----------------|
| `test_cache_and_skip.py` | 19 | PDF skip logic, screenshot cache, video chunking skip, stale state, video-title isolation |
| `test_youtube_url.py` | 9 | `make_youtube_url` — timestamp injection and replacement |
| `test_chunking_and_sync.py` | 34 | Timestamp parsing, chunk-start mapping, abs_ts arithmetic, transcript matching edge cases, transcript/screenshot sync, PDF part naming, chunk file ordering |

Total: **62 tests**

---

## test_cache_and_skip.py

Shared helpers mirror the exact formulas used in `main()` so tests stay in
sync with production code without importing internal state:

- `_pdf_name(video_title, ss, tr, part, url)` — replicates the PDF filename formula
- `_cache_filename(video_file, interval, chunk_start)` — replicates the pickle cache key
- `_write_cache(...)` — writes a valid cache pickle to the temp dir

The `isolate` autouse fixture runs every test in a fresh `tmp_path` via
`monkeypatch.chdir` so cache files never leak between tests.

### Group 1 — PDF skip / overwrite (tests 1–5)

`main()` skips a chunk with `if os.path.exists(output_pdf): continue`. The
output filename encodes both intervals, so any config change produces a new
name and forces regeneration.

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Same config twice | Identical filename → would be skipped |
| 2 | PDF absent from disk | File does not exist → no skip |
| 3 | Screenshot interval changes | Different filename → new PDF generated |
| 4 | Transcript interval changes | Different filename → new PDF generated |
| 5 | Both intervals change | Different filename → new PDF generated |

### Group 2 — Screenshot cache (tests 6–10)

`extract_screenshots_cached` saves extracted frames to a pickle under
`extracted_frames_cache/`. On a cache hit it validates metadata **and** checks
that every frame file still exists on disk before serving the cache.

| # | Scenario | Expected |
|---|----------|----------|
| 6 | Cache warm, frame files on disk | `extract_screenshots` not called |
| 7 | Cold cache | Extracts, writes pickle, returns frames |
| 8 | Interval changed | Cache miss → re-extracts |
| 9 | `chunk_start` changed | Cache miss → re-extracts |
| 10 | `chunk_start=0.5` floors to same filename as `0.0` | Metadata mismatch catches it → re-extracts |

### Group 3 — Video chunking skip (tests 11–12)

`main()` skips calling `chunk()` when all expected part files exist:
`all(os.path.exists(p) for p in expected_parts)`.

| # | Scenario | Expected |
|---|----------|----------|
| 11 | All parts present | Condition `True` → chunk() not needed |
| 12 | One part missing | Condition `False` → chunk() would run |

### Group 4 — Stale state / bug fixes (tests 13–17)

Two bugs that were identified and fixed; these tests guard against regression.

| # | Scenario | Expected |
|---|----------|----------|
| 13 | Cache hit but frame files deleted from disk | Re-extracts rather than returning stale paths |
| 14 | `youtube_url` changes | Different PDF filename → old PDF not reused |
| 15 | No URL vs URL | Different PDF filename |
| 16 | Same URL | Same PDF filename |
| 17 | URL differs only in `t=` param | Same PDF filename (`t=` stripped before hashing) |

### Group 5 — Video-title isolation (tests 18–19)

| # | Scenario | Expected |
|---|----------|----------|
| 18 | Different `video_title` | Different PDF filename |
| 19 | Different `video_title` | Different output directory |

---

## test_youtube_url.py

Tests `make_youtube_url(base_url, seconds)` which injects a `t=` parameter
into a YouTube URL so each PDF slide links to the exact video timestamp.

| Test | Scenario |
|------|----------|
| `test_adds_timestamp_to_plain_url` | Plain URL — `t=` added |
| `test_float_seconds_are_truncated` | `73.9 s` → `t=73` (floor, no rounding) |
| `test_zero_seconds` | `t=0` is valid and emitted |
| `test_replaces_existing_t_param` | Old `t=999` replaced, appears exactly once |
| `test_replaces_existing_t_param_with_s_suffix` | `t=2442s` style also replaced |
| `test_preserves_extra_params_around_t` | `pp=` and `v=` survive the replacement |
| `test_youtu_be_short_url_no_existing_t` | `youtu.be` short URLs work |
| `test_youtu_be_short_url_replaces_existing_t` | `youtu.be` with existing `t=` replaced |
| `test_large_timestamp` | ~2 h timestamp handled correctly |

---

## test_chunking_and_sync.py

Shared helpers mirror `main()` formulas:

- `_cut_points(split_timestamps)` — replicates `[0.0] + [parse_ts(t) for t in ...]`
- `_part_pdf_name(...)` — replicates the chunked PDF name formula
- `_whole_pdf_name(...)` — replicates the unchunked PDF name formula

### Group A — `parse_ts` correctness (tests 1–6)

`parse_ts("HH:MM:SS")` converts a timestamp string to seconds.

| # | Input | Expected seconds |
|---|-------|-----------------|
| 1 | `"00:00:00"` | `0.0` |
| 2 | `"00:01:00"` | `60.0` |
| 3 | `"01:00:00"` | `3600.0` |
| 4 | `"00:17:45"` | `1065.0` |
| 5 | `"01:02:03"` | `3723.0` |
| 6 | `"00:00:01.5"` | `1.5` (fractional seconds preserved) |

### Group B — `cut_points` / chunk_start mapping (tests 7–10)

`cut_points = [0.0] + [parse_ts(t) for t in split_timestamps]` determines
which absolute time each video chunk starts at.

| # | Scenario | Expected |
|---|----------|----------|
| 7 | Empty `split_timestamps` | `[0.0]` |
| 8 | One split | `[0.0, 1065.0]` |
| 9 | Two splits | `[0.0, 1065.0, 2433.0]`, strictly increasing |
| 10 | Index mapping | `cut_points[0]=0.0`, `cut_points[1]=1065.0`, `cut_points[2]=2433.0` |

### Group C — `abs_ts = chunk_start + local_ts` (tests 11–14)

Every screenshot has a *local* timestamp within its chunk. Adding `chunk_start`
converts it to an *absolute* video timestamp for transcript matching.

| # | Scenario | Expected |
|---|----------|----------|
| 11 | First chunk, first frame | `0.0 + 0.0 = 0.0` |
| 12 | First chunk, mid-video | No offset applied |
| 13 | Second chunk at 1065 s, local 5 s | `abs_ts = 1070.0` |
| 14 | First frame of any chunk (`local_ts=0`) | `abs_ts == chunk_start` |

### Group D — `find_matching_chunk` edge cases (tests 15–21)

`find_matching_chunk(chunks, timestamp)` uses a two-pass strategy:
1. **Strict pass** — half-open interval `[start, end)` — handles exact
   boundaries correctly.
2. **Epsilon pass** — `[start − ε, end + ε]` — catches floating-point
   near-boundary cases (e.g. the very last frame of the last chunk).

| # | Scenario | Expected |
|---|----------|----------|
| 15 | `ts = start` of first chunk | Matched to that chunk |
| 16 | `ts` mid-interval | Matched to correct chunk |
| 17 | `ts` exactly at boundary between two chunks | Matched to the **next** chunk (strict pass wins) |
| 18 | `ts` just before end of chunk | Still matched to current chunk |
| 19 | `ts == end` of last chunk | Matched via epsilon pass |
| 20 | `ts` well past all chunks | Returns `""` |
| 21 | `ts` in a gap between non-contiguous chunks | Returns `""` |

> **Why two passes?** A single pass with `start − ε ≤ ts < end + ε` caused
> "boundary stealing": at `ts = 9.0` where chunk A ends at `9.0` and chunk B
> starts at `9.0`, the epsilon on `end` made chunk A match first. The two-pass
> approach gives priority to the strict interval so boundaries always belong to
> the next chunk.

### Group E — Transcript / screenshot sync (tests 22–28)

Verifies that `abs_ts = chunk_start + local_ts` produces captions that are
correctly aligned across chunk boundaries.

| # | Scenario | Expected caption |
|---|----------|-----------------|
| 22 | Chunk 0, `local_ts=3s` → `abs_ts=3s` | "Intro" |
| 23 | Chunk 1 (`start=9s`), `local_ts=3s` → `abs_ts=12s` | "Main content" |
| 24 | First frame of chunk 1, `local_ts=0` → `abs_ts=9s` | "Main content" (boundary → next) |
| 25 | `abs_ts` exactly at transcript boundary | Next chunk's caption |
| 26 | `abs_ts` in a gap between transcript chunks | `""` |
| 27 | Two frames with different intervals in the same chunk | Same caption (position, not interval, determines match) |
| 28 | Transcript chunk spans the video chunk boundary | Both sides match the same transcript chunk |

### Group F — PDF part naming (tests 29–32)

When `split_timestamps` is non-empty, each part gets a distinct PDF with
`_part_{idx}_` in the name.

| # | Scenario | Expected |
|---|----------|----------|
| 29 | Chunked video | `_part_0_` in filename |
| 30 | Unchunked video | No `_part_` in filename |
| 31 | Different part indices | All names distinct |
| 32 | Part numbering is zero-based | `_part_0_` present, `_part_1_` absent for idx=0 |

### Group G — `chunk_files` sort order (tests 33–34)

`main()` does `sorted(os.listdir(chunk_dir))`. The zero-padded `_partNNN`
naming ensures alphabetical order equals chronological order, so
`cut_points[idx]` stays aligned with the correct chunk.

| # | Scenario | Expected |
|---|----------|----------|
| 33 | Shuffled `_partNNN` filenames | `sorted()` restores chronological order |
| 34 | After sorting, `cut_points[idx]` alignment | Each chunk maps to its correct start time |
