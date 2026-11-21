"""One function per eval condition. Each returns {"statement": 1-3 or None, "confidence": float or None}.

Modality ablation (what does raw media add over text?), all with Decision 1 and the
same single choice question, so only the input changes:
  transcript_only, audio_only, video_only, all_media, all_media_plus_measures
Baseline: one Hydrogen call that sees the whole round and names the lie.
"""

import base64
from pathlib import Path

from google import genai
from pydantic import BaseModel

from server.decisions import ask_decision_questions, build_text_block, make_decisions_client
from server.media import run_ffmpeg
from server.models import HYDROGEN_MODEL
from server.pipeline import (
    average_baseline_measures,
    build_decision_questions,
    compute_differences_from_baseline,
    describe_measured_differences,
)

LIE_QUESTION_KEY = "which_statement_is_the_lie"


def get_lie_question_only() -> dict:
    return {LIE_QUESTION_KEY: build_decision_questions()[LIE_QUESTION_KEY]}


def make_audio_only_copy(mp4_path: Path) -> Path:
    """ffmpeg -vn: drop the video, keep the sound."""
    audio_path = mp4_path.with_name(mp4_path.stem + "_audio_only.wav")
    if not audio_path.exists():
        run_ffmpeg(["-i", str(mp4_path), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)])
    return audio_path


def make_video_only_copy(mp4_path: Path) -> Path:
    """ffmpeg -an: drop the sound, keep the picture."""
    video_path = mp4_path.with_name(mp4_path.stem + "_video_only.mp4")
    if not video_path.exists():
        run_ffmpeg(["-i", str(mp4_path), "-an", "-c:v", "copy", str(video_path)])
    return video_path


def encode_file_as_base64(file_path: Path) -> str:
    return base64.b64encode(file_path.read_bytes()).decode("utf-8")


def build_media_block(clip: dict, modality: str) -> dict:
    mp4_path = Path(clip["mp4_path"])
    if modality == "transcript":
        transcript = clip["transcript"] or "(no words heard)"
        return build_text_block(f'Transcript: "{transcript}"')
    if modality == "audio":
        return {"type": "audio", "data": encode_file_as_base64(make_audio_only_copy(mp4_path)), "mime_type": "audio/wav"}
    if modality == "video":
        return {"type": "video", "data": encode_file_as_base64(make_video_only_copy(mp4_path)),
                "mime_type": "video/mp4", "resolution": "low"}
    if modality == "all":
        return {"type": "video", "data": encode_file_as_base64(mp4_path), "mime_type": "video/mp4", "resolution": "low"}
    raise ValueError(f"Unknown modality {modality}")


def build_labeled_round_input(round_clips: dict, modality: str) -> list[dict]:
    input_blocks = []
    for baseline_number, baseline_clip in enumerate(round_clips["baselines"], start=1):
        input_blocks.append(build_text_block(f"BASELINE {baseline_number} (the player telling the truth):"))
        input_blocks.append(build_media_block(baseline_clip, modality))
    for statement_number, statement_clip in enumerate(round_clips["statements"], start=1):
        input_blocks.append(build_text_block(f"STATEMENT {statement_number}:"))
        input_blocks.append(build_media_block(statement_clip, modality))
    return input_blocks


def read_lie_choice(decision_result) -> dict:
    lie_choice = decision_result.answers[LIE_QUESTION_KEY]
    probabilities = [lie_choice.probabilities.get(f"statement_{number}", 0.0) for number in [1, 2, 3]]
    total = sum(probabilities) or 1.0
    normalized = [probability / total for probability in probabilities]
    best_probability = max(normalized)
    return {"statement": normalized.index(best_probability) + 1, "confidence": round(best_probability, 3)}


def run_decision_condition(round_clips: dict, modality: str, add_measures: bool = False) -> dict:
    input_blocks = build_labeled_round_input(round_clips, modality)
    if add_measures:
        baseline_averages = average_baseline_measures(round_clips["baselines"])
        measured_lines = [
            describe_measured_differences(number, compute_differences_from_baseline(clip, baseline_averages))
            for number, clip in enumerate(round_clips["statements"], start=1)
        ]
        input_blocks.append(build_text_block("Measured by code:\n" + "\n".join(measured_lines)))
    decision_result = ask_decision_questions(make_decisions_client(), input_blocks, get_lie_question_only())
    return read_lie_choice(decision_result)


class SingleCallAnswer(BaseModel):
    lie_statement: int


def run_single_hydrogen_call(round_clips: dict) -> dict:
    """Baseline: one plain Hydrogen call on the whole round, no tells, no measures."""
    input_blocks = build_labeled_round_input(round_clips, "all")
    input_blocks.append(build_text_block(
        "This is a game of two truths and a lie. Exactly one of STATEMENT 1, 2, or 3 is a lie. Which one?"
    ))
    # Keep the client in a variable: a client created inline gets closed before the request is sent.
    hydrogen_client = genai.Client()
    interaction = hydrogen_client.interactions.create(
        model=HYDROGEN_MODEL,
        input=input_blocks,
        generation_config={"thinking_level": "low"},
        response_format={"type": "text", "mime_type": "application/json", "schema": SingleCallAnswer.model_json_schema()},
    )
    answer = SingleCallAnswer.model_validate_json(interaction.output_text)
    statement = answer.lie_statement if answer.lie_statement in [1, 2, 3] else None
    return {"statement": statement, "confidence": None}


CONDITION_RUNNERS = {
    "single_hydrogen_call": run_single_hydrogen_call,
    "decision_transcript_only": lambda round_clips: run_decision_condition(round_clips, "transcript"),
    "decision_audio_only": lambda round_clips: run_decision_condition(round_clips, "audio"),
    "decision_video_only": lambda round_clips: run_decision_condition(round_clips, "video"),
    "decision_all_media": lambda round_clips: run_decision_condition(round_clips, "all"),
    "decision_all_media_plus_measures": lambda round_clips: run_decision_condition(round_clips, "all", add_measures=True),
}

