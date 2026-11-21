"""Gemini Decision 1 (Decisions API) helpers.

Call shape verified against https://aistudio.google.com/docs/decisions-api and the
installed google-genai SDK (client.decisions.create(model, input, questions)):
- The client must use api_version v1beta.
- `input` is a list of content blocks: {"type": "text", ...} and {"type": "video", ...}.
- Inline media goes in "data" as a base64 *string* (up to 100 MB per request).
- Each question is {"type": "noul" | "choice" | "score", "instructions": ..., "criteria": ...}.
- Answers: result.answers[key] has .confidence plus .noul (P(yes)), .choice, or .score.
"""

import base64
import time
from pathlib import Path

from google import genai

from server.models import DECISION_MODEL

# Yes/no tell checks for one statement clip. Keys must match [A-Za-z0-9_-], max 64 characters.
# These score behavior in the moment, never the person.
TELL_QUESTIONS = {
    "long_pause_before_answering": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, is there a noticeably long pause before the speaker starts or continues talking?",
    },
    "gaze_breaks_away": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, does the speaker look away from the camera while talking?",
    },
    "hedging_words": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, does the speaker use hedging words like 'um', 'kind of', 'I think', or 'honestly'?",
    },
    "pitch_rises": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, does the speaker's voice pitch rise noticeably?",
    },
    "self_correction": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, does the speaker correct or restart what they were saying?",
    },
    "touches_face": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, does the speaker touch their face, mouth, or neck?",
    },
    "smile_does_not_match": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, does the speaker smile or laugh at a moment that doesn't fit what they are saying?",
    },
    "speech_speeds_up": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, does the speaker suddenly talk faster?",
    },
    "very_little_detail": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, is the story short on concrete details like names, places, or times?",
    },
    "cues_look_exaggerated": {
        "type": "noul",
        "instructions": "In the STATEMENT clip, do the speaker's nervous cues look exaggerated or put on, as if acting?",
    },
    "hesitation_level": {
        "type": "score",
        "instructions": "How much hesitation does the speaker show in the STATEMENT clip, in this moment?",
        "criteria": [
            "No hesitation: smooth and steady",
            "Some hesitation: a short pause or a filler word",
            "Clear hesitation: several pauses, fillers, or restarts",
            "Heavy hesitation: struggles to get the words out",
        ],
    },
}


def make_decisions_client() -> genai.Client:
    """The Decisions API is only on v1beta. The API key is read from GEMINI_API_KEY."""
    return genai.Client(http_options={"api_version": "v1beta"})


def build_text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def build_video_block_inline(mp4_path: Path, resolution: str | None = "low") -> dict:
    """Send the video bytes inside the request (base64 string). Best for short clips."""
    video_bytes = Path(mp4_path).read_bytes()
    video_block = {
        "type": "video",
        "data": base64.b64encode(video_bytes).decode("utf-8"),
        "mime_type": "video/mp4",
    }
    if resolution is not None:
        video_block["resolution"] = resolution
    return video_block


def build_video_block_from_upload(uploaded_file, resolution: str | None = "low") -> dict:
    """Point at a file already uploaded with the Files API."""
    video_block = {
        "type": "video",
        "uri": uploaded_file.uri,
        "mime_type": uploaded_file.mime_type,
    }
    if resolution is not None:
        video_block["resolution"] = resolution
    return video_block


def upload_clip_and_wait_until_active(client: genai.Client, mp4_path: Path, max_wait_seconds: float = 60):
    """Upload a clip with the Files API and wait until Gemini has finished processing it."""
    uploaded_file = client.files.upload(file=str(mp4_path))
    started_waiting_at = time.perf_counter()
    while uploaded_file.state is None or uploaded_file.state.name != "ACTIVE":
        if uploaded_file.state is not None and uploaded_file.state.name == "FAILED":
            raise RuntimeError(f"Gemini could not process {mp4_path}")
        if time.perf_counter() - started_waiting_at > max_wait_seconds:
            raise TimeoutError(f"{mp4_path} was not ACTIVE after {max_wait_seconds} seconds")
        time.sleep(0.5)
        uploaded_file = client.files.get(name=uploaded_file.name)
    return uploaded_file


def ask_decision_questions(client: genai.Client, input_blocks: list[dict], questions: dict):
    """One Decision 1 call: every question is answered against the same input."""
    return client.decisions.create(
        model=DECISION_MODEL,
        input=input_blocks,
        questions=questions,
    )
