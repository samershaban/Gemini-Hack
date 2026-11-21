"""Speech tells measured with plain code from the word timestamps (no model guessing)."""

import re

FILLER_WORDS = {"um", "uh", "er", "erm", "ah", "hmm", "mm", "uhm"}
FILLER_PHRASES = [("you", "know"), ("kind", "of"), ("sort", "of")]
SELF_CORRECTION_PHRASES = [("i", "mean"), ("no", "wait"), ("or", "rather")]
LONG_PAUSE_SECONDS = 0.7


def clean_word(word_text: str) -> str:
    """Lowercase and strip punctuation: "Um," -> "um"."""
    return re.sub(r"[^a-z']", "", word_text.lower())


def measure_speech(words: list[dict], speech_start_ms_fallback: int | None) -> dict:
    """Return speech measures plus a list of timestamped events for tell chips.

    words: [{"text", "start_s", "end_s"}, ...] from transcribe.py
    """
    clean_words = [clean_word(word["text"]) for word in words]
    events = []

    # Response delay: when the first word starts. Fall back to the silence detector.
    if words and words[0]["start_s"] is not None:
        delay_ms = int(words[0]["start_s"] * 1000)
    else:
        delay_ms = speech_start_ms_fallback

    filler_count = 0
    self_correction_count = 0
    long_pause_count = 0

    for word_number, word in enumerate(words):
        this_word = clean_words[word_number]
        next_word = clean_words[word_number + 1] if word_number + 1 < len(words) else ""
        word_pair = (this_word, next_word)

        if this_word in FILLER_WORDS or word_pair in FILLER_PHRASES:
            filler_count += 1
            events.append({"t_s": word["start_s"], "label": f"filler '{word['text'].strip(',.')}'"})

        if word_pair in SELF_CORRECTION_PHRASES:
            self_correction_count += 1
            events.append({"t_s": word["start_s"], "label": "self-correction"})
        elif this_word and this_word == next_word and this_word not in FILLER_WORDS:
            # Repeating a word ("I I went") counts as a restart.
            self_correction_count += 1
            events.append({"t_s": word["start_s"], "label": "restart"})

        if word_number > 0:
            previous_end = words[word_number - 1]["end_s"]
            if previous_end is not None and word["start_s"] is not None:
                gap_seconds = word["start_s"] - previous_end
                if gap_seconds >= LONG_PAUSE_SECONDS:
                    long_pause_count += 1
                    events.append({"t_s": previous_end, "label": f"{gap_seconds:.1f}s pause"})

    words_per_second = None
    if len(words) >= 2 and words[0]["start_s"] is not None and words[-1]["end_s"] is not None:
        speaking_seconds = words[-1]["end_s"] - words[0]["start_s"]
        if speaking_seconds > 0:
            words_per_second = round(len(words) / speaking_seconds, 2)

    # With no words (silent clip or transcription failed) we can't count anything: use None, not 0.
    no_words_heard = len(words) == 0
    return {
        "delay_ms": delay_ms,
        "fillers": None if no_words_heard else filler_count,
        "self_corrections": None if no_words_heard else self_correction_count,
        "long_pauses": None if no_words_heard else long_pause_count,
        "words_per_second": words_per_second,
        "events": events,
    }
