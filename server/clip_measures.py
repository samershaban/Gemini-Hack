"""The measure layer for one clip: transcript + speech tells + face tells.

Transcription (an API call) and face tracking (local CPU) run at the same time.
If the clip starts with chatter ("are you ready?"), the clip is trimmed and every
measure is recomputed on the kept part only. Every part has a fallback, so a
failure never stops a round.
"""

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from server.chatter_trim import find_chatter_end_seconds, shift_words
from server.face_measures import compute_face_stats, track_face_frames
from server.media import cut_clip, extract_audio_wav, find_speech_start_ms, get_video_duration_seconds
from server.speech_measures import measure_speech
from server.transcribe import make_transcribe_client, transcribe_clip_with_word_times

logger = logging.getLogger(__name__)


def transcribe_with_fallback(wav_path: Path) -> dict:
    try:
        return transcribe_clip_with_word_times(make_transcribe_client(), wav_path)
    except Exception as transcribe_error:
        logger.warning("Transcription failed for %s: %s", wav_path, transcribe_error)
        return {"transcript": "", "words": []}


def track_face_with_fallback(mp4_path: Path) -> list[dict]:
    try:
        return track_face_frames(mp4_path)
    except Exception as face_error:
        logger.warning("Face tracking failed for %s: %s", mp4_path, face_error)
        return []


def trim_chatter_if_any(mp4_path: Path, words: list[dict]) -> dict | None:
    """Cut chatter off the start of the clip. Returns {"trimmed_seconds", "untrimmed_mp4_path"} or None.

    The trimmed clip replaces mp4_path, so uploads, Decision 1, and the still frame all use it.
    The original is kept next to it as <clip_id>_untrimmed.mp4.
    """
    try:
        clip_duration_seconds = get_video_duration_seconds(mp4_path)
    except Exception as probe_error:
        logger.warning("Could not read the length of %s: %s", mp4_path, probe_error)
        return None

    chatter_end_seconds = find_chatter_end_seconds(words, clip_duration_seconds)
    if chatter_end_seconds is None or chatter_end_seconds <= 0:
        return None

    untrimmed_mp4_path = mp4_path.with_name(mp4_path.stem + "_untrimmed.mp4")
    shutil.move(mp4_path, untrimmed_mp4_path)
    try:
        cut_clip(untrimmed_mp4_path, mp4_path, chatter_end_seconds, clip_duration_seconds - chatter_end_seconds)
    except Exception as cut_error:
        logger.warning("Trimming %s failed, keeping the full clip: %s", mp4_path, cut_error)
        shutil.move(untrimmed_mp4_path, mp4_path)
        return None
    return {"trimmed_seconds": round(chatter_end_seconds, 2), "untrimmed_mp4_path": str(untrimmed_mp4_path)}


def measure_clip(mp4_path: Path) -> dict:
    """Return {"transcript", "words", "measures", "events", "trim"} for one MP4 clip.

    "measures" holds every number we measured. The /clips response only sends the
    four contract fields (delay_ms, fillers, blink_rate, gaze_breaks).
    """
    wav_path = mp4_path.with_suffix(".wav")
    speech_start_ms = None
    try:
        extract_audio_wav(mp4_path, wav_path)
        speech_start_ms = find_speech_start_ms(wav_path)
        has_audio = True
    except Exception as audio_error:
        logger.warning("No usable audio in %s: %s", mp4_path, audio_error)
        has_audio = False

    with ThreadPoolExecutor(max_workers=2) as worker_pool:
        face_future = worker_pool.submit(track_face_with_fallback, mp4_path)
        if has_audio:
            transcription = transcribe_with_fallback(wav_path)
        else:
            transcription = {"transcript": "", "words": []}
        face_frames = face_future.result()

    words = transcription["words"]
    transcript = transcription["transcript"]
    start_seconds = 0.0
    trim = trim_chatter_if_any(mp4_path, words)
    if trim is not None:
        start_seconds = trim["trimmed_seconds"]
        words = shift_words(words, start_seconds)
        transcript = " ".join(word["text"] for word in words)
        speech_start_ms = None  # the silence detector ran on the untrimmed audio

    speech_result = measure_speech(words, speech_start_ms)
    face_result = compute_face_stats(face_frames, start_seconds)

    measures = {
        "delay_ms": speech_result["delay_ms"],
        "fillers": speech_result["fillers"],
        "blink_rate": face_result["blink_rate"],
        "gaze_breaks": face_result["gaze_breaks"],
        "self_corrections": speech_result["self_corrections"],
        "long_pauses": speech_result["long_pauses"],
        "words_per_second": speech_result["words_per_second"],
        "face_found_fraction": face_result["face_found_fraction"],
    }
    all_events = sorted(speech_result["events"] + face_result["events"], key=lambda event: event["t_s"] or 0)

    return {
        "transcript": transcript,
        "words": words,
        "measures": measures,
        "events": all_events,
        "trim": trim,
    }
