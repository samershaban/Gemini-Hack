"""Find talk before the real statement ("are you ready?", "ok go") so we can cut it off.

The rule is deliberately careful, because cutting too much would chop off the statement:
trim only when a few words (6 or fewer) come before a clear pause (0.8 s or more), the
pause ends in the first 40% of the clip, and at least 4 words come after it.
"""

MAX_CHATTER_WORDS = 6
MIN_PAUSE_SECONDS = 0.8
PAUSE_MUST_END_BEFORE_FRACTION = 0.4
MIN_WORDS_AFTER_PAUSE = 4
KEEP_BEFORE_SPEECH_SECONDS = 0.2


def find_chatter_end_seconds(words: list[dict], clip_duration_seconds: float) -> float | None:
    """Return where the real statement starts (seconds), or None if nothing should be cut.

    words: [{"text", "start_s", "end_s"}, ...] from transcribe.py
    """
    if not words or clip_duration_seconds <= 0:
        return None

    trim_at_seconds = None
    for word_number in range(1, min(MAX_CHATTER_WORDS, len(words) - 1) + 1):
        previous_word = words[word_number - 1]
        next_word = words[word_number]
        if previous_word["end_s"] is None or next_word["start_s"] is None:
            continue
        pause_seconds = next_word["start_s"] - previous_word["end_s"]
        pause_ends_early = next_word["start_s"] <= clip_duration_seconds * PAUSE_MUST_END_BEFORE_FRACTION
        words_after_pause = len(words) - word_number
        if pause_seconds >= MIN_PAUSE_SECONDS and pause_ends_early and words_after_pause >= MIN_WORDS_AFTER_PAUSE:
            # Keep looking: the latest qualifying pause is where the chatter ends.
            trim_at_seconds = max(next_word["start_s"] - KEEP_BEFORE_SPEECH_SECONDS, 0.0)
    return trim_at_seconds


def shift_words(words: list[dict], start_seconds: float) -> list[dict]:
    """Drop words before start_seconds and make the rest relative to it."""
    shifted_words = []
    reached_kept_speech = False
    for word in words:
        word_starts_before_cut = word["start_s"] is not None and word["start_s"] < start_seconds
        word_ends_before_cut = word["end_s"] is not None and word["end_s"] <= start_seconds
        if word_starts_before_cut or word_ends_before_cut:
            continue
        if word["start_s"] is None and not reached_kept_speech:
            continue  # no timestamp and nothing kept yet: it may belong to the cut chatter
        reached_kept_speech = True
        shifted_words.append({
            "text": word["text"],
            "start_s": round(word["start_s"] - start_seconds, 3) if word["start_s"] is not None else None,
            "end_s": round(word["end_s"] - start_seconds, 3) if word["end_s"] is not None else None,
        })
    return shifted_words
