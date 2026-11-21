"""The measure layer for one clip: transcript + speech tells + face tells.

Transcription (an API call) and face tracking (local CPU) run at the same time.
Every part has a fallback, so a failure never stops a round.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from server.face_measures import measure_face
from server.media import extract_audio_wav, find_speech_start_ms
from server.speech_measures import measure_speech
from server.transcribe import make_transcribe_client, transcribe_clip_with_word_times

logger = logging.getLogger(__name__)


def transcribe_with_fallback(wav_path: Path) -> dict:
    try:
        return transcribe_clip_with_word_times(make_transcribe_client(), wav_path)
    except Exception as transcribe_error:
        logger.warning("Transcription failed for %s: %s", wav_path, transcribe_error)
        return {"transcript": "", "words": []}


def measure_face_with_fallback(mp4_path: Path) -> dict:
    try:
        return measure_face(mp4_path)
    except Exception as face_error:
        logger.warning("Face measuring failed for %s: %s", mp4_path, face_error)
        return {"blink_rate": None, "gaze_breaks": None, "face_found_fraction": None, "events": []}


def measure_clip(mp4_path: Path) -> dict:
    """Return {"transcript", "words", "measures", "events"} for one MP4 clip.

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
        face_future = worker_pool.submit(measure_face_with_fallback, mp4_path)
        if has_audio:
            transcription = transcribe_with_fallback(wav_path)
        else:
            transcription = {"transcript": "", "words": []}
        face_result = face_future.result()

    speech_result = measure_speech(transcription["words"], speech_start_ms)

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
        "transcript": transcription["transcript"],
        "words": transcription["words"],
        "measures": measures,
        "events": all_events,
    }
