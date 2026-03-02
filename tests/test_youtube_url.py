import pytest
from main import make_youtube_url


# ── helpers ──────────────────────────────────────────────────────────────────

def qs(url: str) -> dict:
    """Parse query-string params from a URL into a dict."""
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    return {k: v[0] for k, v in parse_qs(parsed.query).items()}


# ── tests ─────────────────────────────────────────────────────────────────────

class TestMakeYoutubeUrl:

    def test_adds_timestamp_to_plain_url(self):
        url = "https://www.youtube.com/watch?v=abc123"
        result = make_youtube_url(url, 90)
        assert qs(result)["t"] == "90"
        assert qs(result)["v"] == "abc123"

    def test_float_seconds_are_truncated(self):
        url = "https://www.youtube.com/watch?v=abc123"
        result = make_youtube_url(url, 73.9)
        assert qs(result)["t"] == "73"

    def test_zero_seconds(self):
        url = "https://www.youtube.com/watch?v=abc123"
        result = make_youtube_url(url, 0)
        assert qs(result)["t"] == "0"

    def test_replaces_existing_t_param(self):
        url = "https://www.youtube.com/watch?v=abc123&t=999"
        result = make_youtube_url(url, 42)
        assert qs(result)["t"] == "42"
        # original t= must not survive
        assert result.count("t=") == 1

    def test_replaces_existing_t_param_with_s_suffix(self):
        url = "https://www.youtube.com/watch?v=abc123&t=2442s"
        result = make_youtube_url(url, 300)
        assert qs(result)["t"] == "300"
        assert result.count("t=") == 1

    def test_preserves_extra_params_around_t(self):
        # Real-world URL from config: extra pp= param after t=
        url = "https://www.youtube.com/watch?v=pTFZFxd4hOI&t=2442s&pp=ugUEEgJlbg%3D%3D"
        result = make_youtube_url(url, 120)
        params = qs(result)
        assert params["t"] == "120"
        assert params["v"] == "pTFZFxd4hOI"
        assert result.count("t=") == 1

    def test_youtu_be_short_url_no_existing_t(self):
        url = "https://youtu.be/abc123"
        result = make_youtube_url(url, 55)
        assert "t=55" in result
        assert result.count("t=") == 1

    def test_youtu_be_short_url_replaces_existing_t(self):
        url = "https://youtu.be/abc123?t=10"
        result = make_youtube_url(url, 55)
        assert qs(result)["t"] == "55"
        assert result.count("t=") == 1

    def test_large_timestamp(self):
        url = "https://www.youtube.com/watch?v=abc123"
        result = make_youtube_url(url, 7261.7)  # ~2 h 1 m 1.7 s
        assert qs(result)["t"] == "7261"
