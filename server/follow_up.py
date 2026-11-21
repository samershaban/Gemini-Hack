"""Gemini 4 Neon's two jobs in a round:

1. write_follow_up_question: the server picks which statement to press on; Neon watches
   that statement (and earlier answers about it) and writes one follow-up question.
2. read_lie_probabilities: on rounds that already had a follow-up, Neon gives a second
   opinion on which statement is the lie, blended with Decision 1 in pipeline.py.

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
LIVE_VIDEO_PROCESSING = "static"
LIVE_THINKING_LEVEL = "low"


class FollowUpQuestion(BaseModel):
    timestamp_s: float
    cue: str
    follow_up_question: str


class LieProbabilities(BaseModel):
    probability_statement_1_is_the_lie: float
    probability_statement_2_is_the_lie: float
    probability_statement_3_is_the_lie: float


def make_neon_client() -> genai.Client:
    return genai.Client()


def get_or_upload_file_uri(client: genai.Client, clip: dict) -> str:
    """Neon needs a Files API uri; reuse the one /clips uploaded if it's there."""
    if clip.get("gemini_file_uri"):
        return clip["gemini_file_uri"]
    uploaded_file = upload_clip_and_wait_until_active(client, Path(clip["mp4_path"]))
    return uploaded_file.uri


def build_neon_video_block(client: genai.Client, clip: dict) -> dict:
    return {
        "type": "video",
        "uri": get_or_upload_file_uri(client, clip),
        "mime_type": "video/mp4",
        "processing": LIVE_VIDEO_PROCESSING,
    }


def ask_neon_for_json(client: genai.Client, input_blocks: list[dict], answer_model: type[BaseModel]):
    interaction = client.interactions.create(
        model=NEON_MODEL,
        input=input_blocks,
        generation_config={"thinking_level": LIVE_THINKING_LEVEL},
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": answer_model.model_json_schema(),
        },
    )
    return answer_model.model_validate_json(interaction.output_text)


def write_follow_up_question(
    statement_number: int,
    statement_clip: dict,
    earlier_answer_clips: list[dict],
    prompt_text: str,
) -> dict:
    """Returns {"statement", "question", "t_s", "cue"}. Raises on failure (the caller has a template)."""
    client = make_neon_client()
    input_blocks = [
        build_neon_video_block(client, statement_clip),
        {"type": "text", "text": f"The video above is STATEMENT {statement_number}, about: {prompt_text}."},
    ]
    for answer_number, answer_clip in enumerate(earlier_answer_clips, start=1):
        input_blocks.append(build_neon_video_block(client, answer_clip))
        input_blocks.append({"type": "text", "text": f"The video above is follow-up answer {answer_number} about STATEMENT {statement_number}."})

    earlier_questions = [clip["follow_up_question"] for clip in earlier_answer_clips if clip.get("follow_up_question")]
    if earlier_questions:
        already_asked_text = (
            " We already asked: " + " | ".join(f'"{question}"' for question in earlier_questions)
            + ". Ask about a DIFFERENT detail; do not repeat or reword those questions."
        )
    elif earlier_answer_clips:
        already_asked_text = " Ask about a different detail than the earlier follow-up answers covered."
    else:
        already_asked_text = ""
    input_blocks.append({
        "type": "text",
        "text": (
            f"We are playing two truths and a lie, and we are not sure whether STATEMENT {statement_number} is the lie. "
            "Find the moment (seconds into the STATEMENT video) where the speaker shows a cue such as a pause, "
            "a gaze break, a filler word, or a mismatched smile, and name that cue in a few words. "
            "Then write ONE short, friendly follow-up question that asks for a concrete detail someone "
            f"would have to make up on the spot if they were lying. Under 20 words.{already_asked_text} "
            "Judge only the behavior in this moment, never the person."
        ),
    })
    answer = ask_neon_for_json(client, input_blocks, FollowUpQuestion)
    return {
        "statement": statement_number,
        "question": answer.follow_up_question,
        "t_s": answer.timestamp_s,
        "cue": answer.cue,
    }


def read_lie_probabilities(round_clips: dict, prompts: list[str]) -> list[float]:
    """Neon's second opinion: [p1, p2, p3], summing to 1. Raises on failure."""
    client = make_neon_client()
    input_blocks = []
    for baseline_number, baseline_clip in enumerate(round_clips["baselines"], start=1):
        input_blocks.append(build_neon_video_block(client, baseline_clip))
        input_blocks.append({"type": "text", "text": f"The video above is BASELINE {baseline_number}: the player telling the truth."})
    for statement_number, statement_clip in enumerate(round_clips["statements"], start=1):
        input_blocks.append(build_neon_video_block(client, statement_clip))
        input_blocks.append({"type": "text", "text": f"The video above is STATEMENT {statement_number}, about: {prompts[statement_number - 1]}."})
    for followup_clip in round_clips["followups"]:
        pressed_statement = followup_clip.get("pressed_statement")
        about_text = f"about STATEMENT {pressed_statement}" if pressed_statement else "about one of the statements"
        input_blocks.append(build_neon_video_block(client, followup_clip))
        input_blocks.append({"type": "text", "text": f"The video above is a FOLLOW-UP answer {about_text}."})
    input_blocks.append({
        "type": "text",
        "text": (
            "Two truths and a lie: exactly one of STATEMENT 1, 2, or 3 is a lie. Compare each statement and "
            "follow-up answer with how the player acts in the BASELINE videos. Give the probability that each "
            "statement is the lie. The three probabilities must add up to 1."
        ),
    })
    answer = ask_neon_for_json(client, input_blocks, LieProbabilities)
    raw_probabilities = [
        max(answer.probability_statement_1_is_the_lie, 0.0),
        max(answer.probability_statement_2_is_the_lie, 0.0),
        max(answer.probability_statement_3_is_the_lie, 0.0),
    ]
    total = sum(raw_probabilities)
    if total <= 0:
        raise ValueError("Neon gave all-zero probabilities")
    return [probability / total for probability in raw_probabilities]
