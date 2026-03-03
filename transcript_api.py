# transcript_api.py

from typing import List, Tuple, Optional
from langchain_community.document_loaders import YoutubeLoader
from langchain_community.document_loaders.youtube import TranscriptFormat

def get_chunked_transcript(
    video_url: str,
    chunk_length: int,
    languages: Optional[List[str]] = None,
    add_video_info: bool = False
) -> List[Tuple[float, float, str]]:
    """
    Download and chunk a YouTube transcript into fixed‐length segments.

    Args:
        video_url:     Full URL of the YouTube video.
        chunk_length:  Desired size of each chunk in seconds.
        languages:     List of language codes to try (default ["zh-Hant","zh-Hans","ja","en"]).
        add_video_info:
                       If True, will fetch extra video metadata (slower).

    Returns:
        A list of (start_time, end_time, text) tuples for each chunk.
    """
    if languages is None:
        languages = ["zh-Hant", "zh-Hans", "ja", "en"]

    loader = YoutubeLoader.from_youtube_url(
        video_url,
        add_video_info=add_video_info,
        transcript_format=TranscriptFormat.CHUNKS,
        chunk_size_seconds=chunk_length,
        language=languages,
    )
    docs = loader.load()

    # Pull all the start times first
    starts: List[float] = []
    for doc in docs:
        md = doc.metadata
        raw = md.get("start_seconds") or md.get("start") or md.get("start_time")
        try:
            starts.append(float(raw))
        except (TypeError, ValueError):
            starts.append(0.0)

    chunks: List[Tuple[float, float, str]] = []
    for i, doc in enumerate(docs):
        start = starts[i]
        # end is next chunk’s start, or start+chunk_length for the last one
        if i < len(docs) - 1:
            end = starts[i+1]
        else:
            end = start + chunk_length

        chunks.append((start, end, doc.page_content))

    return chunks
