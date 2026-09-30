"""V0: raw audio (local path or HTTP(S) URL) -> timestamped transcript segments.

No LLM involved at this stage. Local ASR with faster-whisper large-v3-turbo (int8), the model
chosen in the ASR model-selection study (artifacts/asr_model_selection/,
evaluation/asr_model_selection/).

Whisper's word timestamps are merged into segments by word-count buffering (at least 8 words,
aiming for 15).
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

from minaret.schemas import Segment

MODEL_SIZE = "large-v3-turbo"
MIN_WORDS = 8
TARGET_WORDS = 15


def is_remote(source: str) -> bool:
    return urlsplit(source).scheme.lower() in {"http", "https"}


def resolve_audio(source: str, cache_dir: Path) -> Path:
    """Local path: used directly, never copied. HTTP(S) URL: streamed to a partial file, then
    published atomically."""
    if not is_remote(source):
        if "://" in source:
            raise ValueError("Only HTTP(S) URLs and local paths are supported")
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Audio not found: {path}")
        return path

    import httpx
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(unquote(urlsplit(source).path)).suffix.lower()
    if suffix not in {".mp3", ".wav", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".webm", ".aac"}:
        suffix = ".audio"
    dest = cache_dir / f"audio{suffix}"
    partial = cache_dir / "audio.part"
    try:
        with httpx.stream("GET", source, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type or "application/json" in content_type:
                raise ValueError(f"URL returned {content_type or 'non-audio content'} instead of audio")
            with partial.open("wb") as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
        if partial.stat().st_size == 0:
            raise ValueError("Empty download")
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    return dest


def _merge_words_by_count(words: list[dict], *, min_words: int = MIN_WORDS,
                           target_words: int = TARGET_WORDS) -> list[Segment]:
    """Group whole ASR words into segments by word count, no time constraint. A trailing group
    below min_words folds into the previous segment rather than standing alone."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        current.append(word)
        if len(current) >= target_words:
            groups.append(current)
            current = []
    if current:
        if groups and len(current) < min_words:
            groups[-1] = groups[-1] + current
        else:
            groups.append(current)

    segments = []
    for group in groups:
        text = "".join(w["text"] for w in group).strip()
        segments.append(Segment(id=str(uuid.uuid4()), start=group[0]["start"], end=group[-1]["end"], text=text))
    return segments


@dataclass
class TranscriptionResult:
    segments: list[Segment]
    words: list[dict]  # [{start, end, text}, ...] — kept for future re-segmentation, per this
                        # project's own resegment.py precedent: rebuilding a different merge from
                        # original word timestamps is possible; splitting already-merged text is not.
    language: str
    duration_seconds: float
    audio_sha256: str
    audio_path: str
    model: str = MODEL_SIZE
    backend: str = "faster_whisper"


def transcribe(source: str, *, language: Optional[str] = None, cache_dir: Optional[Path] = None,
                model=None) -> TranscriptionResult:
    """Transcribe one audio source (local path or URL) to V0 segments.

    `model` lets a caller pass an already-loaded faster_whisper.WhisperModel to reuse across
    multiple recordings in one process, avoiding a reload per file — this is a plain function,
    not a class, specifically so callers can compose it however they need (sequential batch,
    one-off script, or wrapped by a future job runner) without inheriting orchestration this
    package doesn't own.
    """
    cache_dir = cache_dir or Path.cwd() / ".minaret_cache" / hashlib.sha256(source.encode()).hexdigest()[:16]
    audio = resolve_audio(source, cache_dir)

    with audio.open("rb") as handle:
        audio_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()

    if model is None:
        from faster_whisper import WhisperModel
        model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

    stream, info = model.transcribe(str(audio), word_timestamps=True, language=language,
                                     task="transcribe", beam_size=5, vad_filter=False)
    words: list[dict] = []
    for segment in stream:
        for w in (segment.words or []):
            words.append({"start": float(w.start), "end": float(w.end), "text": w.word})

    if not words:
        raise ValueError("Empty ASR result or missing word alignment; nothing to segment")

    segments = _merge_words_by_count(words)

    return TranscriptionResult(
        segments=segments, words=words, language=info.language, duration_seconds=info.duration,
        audio_sha256=audio_sha256, audio_path=str(audio),
    )
