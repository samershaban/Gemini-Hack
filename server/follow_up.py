"""Escalation: Gemini 4 Neon watches the two most suspicious statements and writes one
follow-up question.

Call shape verified against https://aistudio.google.com/docs/video-understanding,
/docs/structured-output, /docs/thinking and the installed SDK:
- client.interactions.create(model, input, generation_config, response_format)
- video block {"type": "video", "uri", "mime_type", "processing": "static" | "agentic"}; text goes after the video
- response_format={"type": "text", "mime_type": "application/json", "schema": <JSON schema>}
- read the JSON from interaction.output_text
"""

import logging
from pathlib import Path

from google import genai
from pydantic import BaseModel

from server.decisions import upload_clip_and_wait_until_active
from server.models import NEON_MODEL

logger = logging.getLogger(__name__)

# Measured on two 5-second statement clips (same answer every time):
#   agentic + medium thinking 21.6 s, agentic + low 16.7 s, static + low 6.0 s.
# A live round can't wait 17+ seconds, so live rounds use static processing.
# The eval compares static vs. agentic on the same clips.
LIVE_VIDEO_PROCESSING = "static"
LIVE_THINKING_LEVEL = "low"


class FollowUpPlan(BaseModel):
    suspect_statement: int
    timestamp_s: float
    cue: str
    follow_up_question: str


def make_neon_client() -> genai.Client:
    return genai.Client()


def get_or_upload_file_uri(client: genai.Client, clip: dict) -> str:
    """Agentic video needs a Files API uri; reuse the one /clips uploaded if it's there."""
    if clip.get("gemini_file_uri"):
        return clip["gemini_file_uri"]
    uploaded_file = upload_clip_and_wait_until_active(client, Path(clip["mp4_path"]))
    return uploaded_file.uri


def ask_neon_for_follow_up(
    statement_clips_by_number: dict[int, dict],
    prompts: list[str],
    video_processing: str = LIVE_VIDEO_PROCESSING,
    thinking_level: str = LIVE_THINKING_LEVEL,
) -> dict:
    """statement_clips_by_number: the two closest statements, e.g. {2: clip, 3: clip}.

    Returns {"statement": int, "question": str, "t_s": float, "cue": str}. Raises on failure;
    the caller keeps the template question as the fallback.
    """
    client = make_neon_client()
    input_blocks = []
    for statement_number, clip in statement_clips_by_number.items():
        input_blocks.append({
            "type": "video",
            "uri": get_or_upload_file_uri(client, clip),
            "mime_type": "video/mp4",
            "processing": video_processing,
        })
        input_blocks.append({
            "type": "text",
            "text": f"The video above is STATEMENT {statement_number}, about: {prompts[statement_number - 1]}.",
        })

    statement_numbers = sorted(statement_clips_by_number)
    input_blocks.append({
        "type": "text",
        "text": (
            "We are playing two truths and a lie. One of these statements might be the lie. "
            f"Watch STATEMENT {statement_numbers[0]} and STATEMENT {statement_numbers[1]} closely. "
            "Pick the one that looks more like a lie, find the exact moment (seconds into that video) "
            "where the speaker shows a cue such as a pause, a gaze break, a filler word, or a mismatched smile, "
            "and name that cue in a few words. Then write ONE short, friendly follow-up question that asks "
            "for a concrete detail a liar would have to make up on the spot. Under 20 words. "
            "Judge only the behavior in this moment, never the person."
        ),
    })

    interaction = client.interactions.create(
        model=NEON_MODEL,
        input=input_blocks,
        generation_config={"thinking_level": thinking_level},
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": FollowUpPlan.model_json_schema(),
        },
    )
    follow_up_plan = FollowUpPlan.model_validate_json(interaction.output_text)

    if follow_up_plan.suspect_statement not in statement_clips_by_number:
        raise ValueError(f"Neon picked statement {follow_up_plan.suspect_statement}, not one we sent")

    return {
        "statement": follow_up_plan.suspect_statement,
        "question": follow_up_plan.follow_up_question,
        "t_s": follow_up_plan.timestamp_s,
        "cue": follow_up_plan.cue,
    }
