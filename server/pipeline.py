"""The round pipeline: analyze (fused Decision 1 call), then the call.

Numbering used in every response: `statement` is 1, 2, or 3. `lie_probs` is a list in
statement order, and `lie_index` (in /reveal) is 0, 1, or 2, the position in that list.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

from server import db
from server.decisions import (
    ask_decision_questions,
    build_text_block,
    build_video_block_from_uri,
    build_video_block_inline,
    make_decisions_client,
)
from server.follow_up import ask_neon_for_follow_up
from server.media import save_still_frame
from server.paths import get_round_folder

logger = logging.getLogger(__name__)

CONFIDENT_ENOUGH_TO_CALL = 0.75
TELL_PROBABILITY_TO_SHOW = 0.6
MAX_FOLLOW_UPS = 1
NEON_TIMEOUT_SECONDS = 12  # after this, the host asks the template question instead

# Numbers we compare against the player's own baseline ("difference from baseline", PRD v2).
MEASURE_NAMES_TO_COMPARE = [
    "delay_ms", "fillers", "blink_rate", "gaze_breaks",
    "self_corrections", "long_pauses", "words_per_second",
]

# Per-statement yes/no tells. "{label}" is replaced by "STATEMENT 1" and so on.
PER_STATEMENT_TELLS = {
    "long_pause": ("long pause", "In {label}, is there a longer pause before or during the answer than in the BASELINE clips?"),
    "gaze_break": ("gaze break", "In {label}, does the speaker look away from the camera more than in the BASELINE clips?"),
    "hedging": ("hedging words", "In {label}, does the speaker use more hedging or filler words than in the BASELINE clips?"),
    "pitch_rise": ("pitch rise", "In {label}, does the speaker's voice pitch rise compared with the BASELINE clips?"),
    "self_correction": ("self-correction", "In {label}, does the speaker correct or restart what they were saying?"),
    "exaggerated": ("acting nervous", "In {label}, do the speaker's nervous cues look exaggerated or put on, compared with the BASELINE clips?"),
}


class RoundNotReadyError(Exception):
    """Raised when a round is missing clips it needs."""


def pick_latest_clip_per_index(clips: list[dict]) -> list[dict]:
    """If the operator re-recorded a clip, keep only the newest one for each index."""
    latest_by_index = {}
    for clip in clips:  # clips are oldest first, so later ones replace earlier ones
        latest_by_index[clip["statement_index"]] = clip
    return [latest_by_index[index] for index in sorted(latest_by_index)]


def load_round_clips(round_id: str) -> dict:
    """Return {"baselines": [...], "statements": [3 clips], "followups": [...]}."""
    all_clips = db.get_clips_for_round(round_id)
    baselines = pick_latest_clip_per_index([clip for clip in all_clips if clip["kind"] == "baseline"])
    statements = pick_latest_clip_per_index([clip for clip in all_clips if clip["kind"] == "statement"])
    followups = [clip for clip in all_clips if clip["kind"] == "followup"]
    if len(statements) != 3:
        raise RoundNotReadyError(f"Need 3 statement clips, have {len(statements)}")
    return {"baselines": baselines, "statements": statements, "followups": followups}


def average_baseline_measures(baseline_clips: list[dict]) -> dict:
    averages = {}
    for measure_name in MEASURE_NAMES_TO_COMPARE:
        values = [
            clip["measures"][measure_name]
            for clip in baseline_clips
            if clip["measures"] and clip["measures"].get(measure_name) is not None
        ]
        averages[measure_name] = sum(values) / len(values) if values else None
    return averages


def compute_differences_from_baseline(statement_clip: dict, baseline_averages: dict) -> dict:
    differences = {}
    statement_measures = statement_clip["measures"] or {}
    for measure_name in MEASURE_NAMES_TO_COMPARE:
        statement_value = statement_measures.get(measure_name)
        baseline_value = baseline_averages.get(measure_name)
        if statement_value is None or baseline_value is None:
            differences[measure_name] = None
        else:
            differences[measure_name] = round(statement_value - baseline_value, 2)
    return differences


def build_video_block_for_clip(clip: dict) -> dict:
    """Use the Files API upload when it's ready (faster); otherwise send the video inline."""
    if clip.get("gemini_file_uri"):
        return build_video_block_from_uri(clip["gemini_file_uri"])
    return build_video_block_inline(Path(clip["mp4_path"]))


def describe_measured_differences(statement_number: int, differences: dict) -> str:
    readable_parts = []
    for measure_name, difference in differences.items():
        if difference is not None:
            readable_parts.append(f"{measure_name} {difference:+g}")
    if not readable_parts:
        return f"STATEMENT {statement_number}: no measurements."
    return f"STATEMENT {statement_number} measured difference from BASELINE: " + ", ".join(readable_parts) + "."


def build_decision_input(
    round_clips: dict,
    differences_by_statement: dict,
    pressed_statement: int | None = None,
) -> list[dict]:
    """pressed_statement: which statement the follow-up question was about (from the last analysis)."""
    input_blocks = []
    for baseline_number, baseline_clip in enumerate(round_clips["baselines"], start=1):
        input_blocks.append(build_text_block(f"BASELINE {baseline_number} (the player telling the truth, to learn how they normally act):"))
        input_blocks.append(build_video_block_for_clip(baseline_clip))
    for statement_number, statement_clip in enumerate(round_clips["statements"], start=1):
        input_blocks.append(build_text_block(f"STATEMENT {statement_number}:"))
        input_blocks.append(build_video_block_for_clip(statement_clip))
    for followup_clip in round_clips["followups"][-MAX_FOLLOW_UPS:]:
        # The stage always sends the follow-up clip with index 1, so the statement it was
        # about comes from the follow-up question we asked, not from the clip's index.
        if pressed_statement is not None:
            followup_label = f"FOLLOW-UP answer, after being pressed about STATEMENT {pressed_statement}:"
        else:
            followup_label = "FOLLOW-UP answer, after being pressed with one more question:"
        input_blocks.append(build_text_block(followup_label))
        input_blocks.append(build_video_block_for_clip(followup_clip))

    measured_lines = [
        describe_measured_differences(statement_number, differences)
        for statement_number, differences in differences_by_statement.items()
    ]
    input_blocks.append(build_text_block(
        "Measured by code (delay in ms, counts per clip, blink rate per minute):\n" + "\n".join(measured_lines)
    ))
    return input_blocks


def build_decision_questions() -> dict:
    questions = {
        "which_statement_is_the_lie": {
            "type": "choice",
            "instructions": "This is a two truths and a lie game. Exactly one of STATEMENT 1, 2, or 3 is a lie. Which one is the lie?",
            "criteria": {
                "statement_1": "STATEMENT 1 is the lie",
                "statement_2": "STATEMENT 2 is the lie",
                "statement_3": "STATEMENT 3 is the lie",
                "other": "Impossible to tell",
            },
        },
        "speech_is_clear": {
            "type": "noul",
            "instructions": "Is the speaker's voice clear enough to understand in the STATEMENT clips?",
        },
        "player_in_frame": {
            "type": "noul",
            "instructions": "Is the speaker's face clearly visible in the STATEMENT clips?",
        },
    }
    for statement_number in [1, 2, 3]:
        label = f"STATEMENT {statement_number}"
        for tell_key, (_, instructions_template) in PER_STATEMENT_TELLS.items():
            questions[f"s{statement_number}_{tell_key}"] = {
                "type": "noul",
                "instructions": instructions_template.format(label=label),
            }
        questions[f"s{statement_number}_hesitation"] = {
            "type": "score",
            "instructions": f"How much hesitation does the speaker show in {label}, in that moment, compared with the BASELINE clips?",
            "criteria": ["Less than baseline", "Same as baseline", "A bit more than baseline", "Much more than baseline"],
        }
    return questions


def guess_lie_from_measures_only(differences_by_statement: dict) -> list[float]:
    """Fallback when Decision 1 fails: more tells than baseline means more suspicious."""
    suspicion_points = []
    for statement_number in [1, 2, 3]:
        differences = differences_by_statement[statement_number]
        points = 1.0
        if differences["delay_ms"] is not None:
            points += max(differences["delay_ms"], 0) / 1000
        for count_name in ["fillers", "gaze_breaks", "self_corrections", "long_pauses"]:
            if differences[count_name] is not None:
                points += max(differences[count_name], 0)
        suspicion_points.append(points)
    total_points = sum(suspicion_points)
    return [round(points / total_points, 3) for points in suspicion_points]


def collect_tells(round_clips: dict, decision_answers: dict | None) -> list[dict]:
    """Tell chips: measured events (with exact times) plus strong Decision 1 tells."""
    tells = []
    for statement_number, statement_clip in enumerate(round_clips["statements"], start=1):
        for event in statement_clip["events"] or []:
            tells.append({"statement": statement_number, "t_s": event["t_s"], "label": event["label"]})
        if decision_answers:
            for tell_key, (tell_label, _) in PER_STATEMENT_TELLS.items():
                answer = decision_answers.get(f"s{statement_number}_{tell_key}")
                if answer is not None and answer.noul >= TELL_PROBABILITY_TO_SHOW:
                    tells.append({"statement": statement_number, "t_s": None, "label": tell_label})
    return tells


def analyze_round(round_id: str) -> dict:
    """Score the round. Returns the /analyze contract shape and saves the full analysis."""
    round_clips = load_round_clips(round_id)
    baseline_averages = average_baseline_measures(round_clips["baselines"])
    differences_by_statement = {
        statement_number: compute_differences_from_baseline(statement_clip, baseline_averages)
        for statement_number, statement_clip in enumerate(round_clips["statements"], start=1)
    }

    # If we already asked a follow-up question, remember which statement it was about.
    previous_analysis = db.get_round(round_id)["analysis"]
    pressed_statement = None
    if previous_analysis and previous_analysis.get("follow_up"):
        pressed_statement = previous_analysis["follow_up"]["statement"]

    decision_answers = None
    source = "decision_1"
    try:
        decision_result = ask_decision_questions(
            make_decisions_client(),
            build_decision_input(round_clips, differences_by_statement, pressed_statement),
            build_decision_questions(),
        )
        decision_answers = decision_result.answers
        lie_choice = decision_answers["which_statement_is_the_lie"]
        raw_probabilities = [lie_choice.probabilities.get(f"statement_{number}", 0.0) for number in [1, 2, 3]]
        probability_total = sum(raw_probabilities) or 1.0
        lie_probs = [round(probability / probability_total, 3) for probability in raw_probabilities]
    except Exception as decision_error:
        logger.warning("Decision 1 failed for round %s, using measures only: %s", round_id, decision_error)
        lie_probs = guess_lie_from_measures_only(differences_by_statement)
        source = "measures_fallback"

    confidence = max(lie_probs)
    top_statement = lie_probs.index(confidence) + 1
    already_followed_up = len(round_clips["followups"]) >= MAX_FOLLOW_UPS
    escalate = confidence < CONFIDENT_ENOUGH_TO_CALL and not already_followed_up

    analysis = {
        "lie_probs": lie_probs,
        "confidence": confidence,
        "tells": collect_tells(round_clips, decision_answers),
        "escalate": escalate,
    }
    follow_up_detail = None
    if escalate:
        follow_up_detail = choose_follow_up(round_id, round_clips, lie_probs)
        analysis["follow_up"] = {"statement": follow_up_detail["statement"], "question": follow_up_detail["question"]}

    # Save more than we return, for the eval and the call.
    saved_analysis = dict(analysis)
    saved_analysis["follow_up_detail"] = follow_up_detail
    saved_analysis["source"] = source
    saved_analysis["top_statement"] = top_statement
    # JSON keys are always text, so save statement numbers as "1", "2", "3".
    saved_analysis["differences_by_statement"] = {
        str(statement_number): differences for statement_number, differences in differences_by_statement.items()
    }
    if decision_answers:
        saved_analysis["gates"] = {
            "speech_is_clear": decision_answers["speech_is_clear"].noul,
            "player_in_frame": decision_answers["player_in_frame"].noul,
        }
        saved_analysis["tell_probabilities"] = {
            question_key: answer.noul
            for question_key, answer in decision_answers.items()
            if answer.type == "noul"
        }
    db.save_round_json(round_id, "analysis_json", saved_analysis)
    return analysis


def choose_follow_up(round_id: str, round_clips: dict, lie_probs: list[float]) -> dict:
    """Pick the statement to press on and one question about it.

    Neon watches the two most suspicious statements. If it fails or is too slow,
    we ask a template question about the most suspicious statement.
    """
    round_info = db.get_round(round_id)
    prompts = round_info["prompts"]
    statements_by_suspicion = sorted([1, 2, 3], key=lambda number: lie_probs[number - 1], reverse=True)
    two_closest_statements = statements_by_suspicion[:2]
    clips_to_send = {number: round_clips["statements"][number - 1] for number in sorted(two_closest_statements)}

    worker_pool = ThreadPoolExecutor(max_workers=1)
    neon_future = worker_pool.submit(ask_neon_for_follow_up, clips_to_send, prompts)
    try:
        return neon_future.result(timeout=NEON_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        logger.warning("Neon follow-up took over %s s for round %s, using the template", NEON_TIMEOUT_SECONDS, round_id)
    except Exception as neon_error:
        logger.warning("Neon follow-up failed for round %s, using the template: %s", round_id, neon_error)
    finally:
        worker_pool.shutdown(wait=False)

    top_statement = statements_by_suspicion[0]
    prompt_text = prompts[top_statement - 1]
    return {
        "statement": top_statement,
        "question": f"Tell me more about statement {top_statement} ({prompt_text.lower()}). What exactly happened, and when?",
        "t_s": None,
        "cue": None,
    }


def pick_strongest_cue(round_clips: dict, statement_number: int, analysis: dict) -> tuple[str, float]:
    """Return (cue text, time in seconds) for the BUSTED screen."""
    statement_clip = round_clips["statements"][statement_number - 1]
    timed_events = [event for event in statement_clip["events"] or [] if event["t_s"] is not None]

    # Prefer the measured tell we have the most of compared with the baseline.
    differences = analysis.get("differences_by_statement", {}).get(str(statement_number)) or {}
    preferred_labels = []
    if (differences.get("gaze_breaks") or 0) > 0:
        preferred_labels.append("gaze break")
    if (differences.get("long_pauses") or 0) > 0:
        preferred_labels.append("pause")
    if (differences.get("fillers") or 0) > 0:
        preferred_labels.append("filler")
    if (differences.get("self_corrections") or 0) > 0:
        preferred_labels.extend(["self-correction", "restart"])
    for preferred_label in preferred_labels:
        for event in timed_events:
            if preferred_label in event["label"]:
                return event["label"], event["t_s"]
    if timed_events:
        return timed_events[0]["label"], timed_events[0]["t_s"]

    # No timed event: use the strongest Decision 1 tell and the delay before speaking.
    tell_probabilities = analysis.get("tell_probabilities", {})
    best_tell_label = "something felt off"
    best_probability = 0.0
    for tell_key, (tell_label, _) in PER_STATEMENT_TELLS.items():
        probability = tell_probabilities.get(f"s{statement_number}_{tell_key}", 0.0)
        if probability > best_probability:
            best_tell_label, best_probability = tell_label, probability
    delay_ms = (statement_clip["measures"] or {}).get("delay_ms") or 0
    return best_tell_label, round(delay_ms / 1000, 1)


def make_call(round_id: str) -> dict:
    """The final call. Returns the /call contract shape and saves it."""
    round_info = db.get_round(round_id)
    if round_info["analysis"] is None:
        analyze_round(round_id)
        round_info = db.get_round(round_id)
    analysis = round_info["analysis"]
    round_clips = load_round_clips(round_id)

    statement_number = analysis["top_statement"]
    confidence = analysis["confidence"]
    cue, cue_time_seconds = pick_strongest_cue(round_clips, statement_number, analysis)
    confidence_percent = round(confidence * 100)
    line = f"Statement {statement_number}. {cue.capitalize()} at {cue_time_seconds:.1f} seconds. I'm {confidence_percent}% sure."

    frame_url = None
    statement_clip = round_clips["statements"][statement_number - 1]
    frame_path = get_round_folder(round_id) / "frame.jpg"
    try:
        save_still_frame(Path(statement_clip["mp4_path"]), frame_path, cue_time_seconds)
        frame_url = f"/rounds/{round_id}/frame.jpg"
    except Exception as frame_error:
        logger.warning("Could not save the still frame for round %s: %s", round_id, frame_error)

    call = {
        "statement": statement_number,
        "confidence": confidence,
        "t_s": cue_time_seconds,
        "cue": cue,
        "line": line,
        "frame_url": frame_url,
    }
    db.save_round_json(round_id, "call_json", call)
    return call
