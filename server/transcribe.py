"""Transcription with word timestamps, using gemini-3.5-transcribe.

Call shape verified against https://aistudio.google.com/docs/transcribe and the installed SDK:
- v1beta client, client.interactions.create(model, input, generation_config)
- input is an audio block: {"type": "audio", "data": <base64 string>, "mime_type": "audio/wav"}
- word timestamps need verbatim mode: {"transcription_config": {"mode": {"type": "verbatim",
  "timestamp_granularities": ["word"]}}}
- each word is an annotation with type "word_info", text, start_offset ("1.200s"), end_offset
"""

import base64
from pathlib import Path

from google import genai

from server.models import TRANSCRIBE_MODEL


def make_transcribe_client() -> genai.Client:
    return genai.Client(http_options={"api_version": "v1beta"})


def convert_offset_text_to_seconds(offset_text: str | None) -> float | None:
    """Turn "1.200s" or "3s" into 1.2 or 3.0."""
    if not offset_text:
        return None
    return float(offset_text.rstrip("s"))


def transcribe_clip_with_word_times(client: genai.Client, wav_path: Path) -> dict:
    """Return {"transcript": str, "words": [{"text", "start_s", "end_s"}, ...]}.

    Raises if the API call fails; the caller decides the fallback.
    """
    audio_base64 = base64.b64encode(Path(wav_path).read_bytes()).decode("utf-8")
    interaction = client.interactions.create(
        model=TRANSCRIBE_MODEL,
        input=[{"type": "audio", "data": audio_base64, "mime_type": "audio/wav"}],
        generation_config={
            "transcription_config": {
                "mode": {"type": "verbatim", "timestamp_granularities": ["word"]},
            },
        },
    )

    words = []
    for step in interaction.steps or []:
        for content_block in getattr(step, "content", None) or []:
            for annotation in getattr(content_block, "annotations", None) or []:
                if annotation.type != "word_info":
                    continue
                words.append(
                    {
                        "text": annotation.text,
                        "start_s": convert_offset_text_to_seconds(annotation.start_offset),
                        "end_s": convert_offset_text_to_seconds(annotation.end_offset),
                    }
                )

    return {"transcript": interaction.output_text or "", "words": words}
