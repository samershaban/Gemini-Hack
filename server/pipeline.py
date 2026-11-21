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
from server.follow_up import read_lie_probabilities, write_follow_up_question
from server.media import save_still_frame
from server.paths import get_round_folder

logger = logging.getLogger(__name__)

CONFIDENT_ENOUGH_TO_CALL = 0.70  # below this, ask another follow-up question
MAX_FOLLOW_UPS = 3  # so a round never runs forever
TELL_PROBABILITY_TO_SHOW = 0.6
NEON_TIMEOUT_SECONDS = 12  # after this, skip Neon (template question / Decision 1 alone)
NEON_WEIGHT = 0.25  # Neon's share of the blended lie probabilities, on rounds with follow-ups

# Numbers we compare against the player's own baseline ("difference from baseline", PRD v2).
# delay_ms is left out: it starts when the operator taps record, so it mostly measures the operator.
MEASURE_NAMES_TO_COMPARE = [
    "fillers", "blink_rate", "gaze_breaks",
    "self_corrections", "long_pauses", "words_per_second",
]
ALL_STATEMENTS_IN_ORDER = [1, 2, 3]
ALL_STATEMENTS_REVERSED = [3, 2, 1]

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
    statement_order: list[int] = ALL_STATEMENTS_IN_ORDER,
) -> list[dict]:
    """Labeled clips for Decision 1. statement_order changes only the order of the blocks
    (labels stay the same), which lets us cancel out any bias toward the first or last one."""
    input_blocks = []
    for baseline_number, baseline_clip in enumerate(round_clips["baselines"], start=1):
        input_blocks.append(build_text_block(f"BASELINE {baseline_number} (the player telling the truth, to learn how they normally act):"))
        input_blocks.append(build_video_block_for_clip(baseline_clip))
    for statement_number in statement_order:
        input_blocks.append(build_text_block(f"STATEMENT {statement_number}:"))
        input_blocks.append(build_video_block_for_clip(round_clips["statements"][statement_number - 1]))
    for followup_clip in round_clips["followups"]:
        # /clips saved which statement each follow-up question was about.
        pressed_statement = followup_clip.get("pressed_statement")
        if pressed_statement is not None:
            followup_label = f"FOLLOW-UP answer, after being pressed about STATEMENT {pressed_statement}:"
        else:
            followup_label = "FOLLOW-UP answer, after being pressed with one more question:"
        input_blocks.append(build_text_block(followup_label))
        input_blocks.append(build_video_block_for_clip(followup_clip))

    measured_lines = [
        describe_measured_differences(statement_number, differences_by_statement[statement_number])
        for statement_number in statement_order
    ]
    input_blocks.append(build_text_block(
        "Measured by code (counts per clip, blink rate per minute, words per second):\n" + "\n".join(measured_lines)
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


def run_with_timeout(timeout_seconds: float, function, *arguments):
    """Run function(*arguments) in a thread; raise TimeoutError if it takes too long."""
    worker_pool = ThreadPoolExecutor(max_workers=1)
    future = worker_pool.submit(function, *arguments)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        raise TimeoutError(f"{function.__name__} took over {timeout_seconds} s")
    finally:
        worker_pool.shutdown(wait=False)


def read_choice_probabilities(decision_answers) -> list[float]:
    """Decision 1's probability for statements 1-3, rescaled to add up to 1 (without "other")."""
    lie_choice = decision_answers["which_statement_is_the_lie"]
    raw_probabilities = [lie_choice.probabilities.get(f"statement_{number}", 0.0) for number in ALL_STATEMENTS_IN_ORDER]
    probability_total = sum(raw_probabilities) or 1.0
    return [probability / probability_total for probability in raw_probabilities]


def ask_decision_in_order(round_clips: dict, differences_by_statement: dict, statement_order: list[int], questions: dict):
    return ask_decision_questions(
        make_decisions_client(),
        build_decision_input(round_clips, differences_by_statement, statement_order),
        questions,
    ).answers


def analyze_round(round_id: str) -> dict:
    """Score the round. Returns the /analyze contract shape and saves the full analysis.

    Three calls run at the same time:
    - Decision 1 with every question, statements in order 1-2-3
    - Decision 1 with only the lie question, statements in order 3-2-1 (cancels order bias)
    - Neon's second opinion, only when the round already has follow-up answers
    """
    round_clips = load_round_clips(round_id)
    prompts = db.get_round(round_id)["prompts"]
    baseline_averages = average_baseline_measures(round_clips["baselines"])
    differences_by_statement = {
        statement_number: compute_differences_from_baseline(statement_clip, baseline_averages)
        for statement_number, statement_clip in enumerate(round_clips["statements"], start=1)
    }
    all_questions = build_decision_questions()
    lie_question_only = {"which_statement_is_the_lie": all_questions["which_statement_is_the_lie"]}
    ask_neon = len(round_clips["followups"]) > 0

    # Not a `with` block: leaving one waits for every call, and a slow Neon call would hold up the round.
    worker_pool = ThreadPoolExecutor(max_workers=3)
    in_order_future = worker_pool.submit(
        ask_decision_in_order, round_clips, differences_by_statement, ALL_STATEMENTS_IN_ORDER, all_questions)
    reversed_future = worker_pool.submit(
        ask_decision_in_order, round_clips, differences_by_statement, ALL_STATEMENTS_REVERSED, lie_question_only)
    neon_future = worker_pool.submit(read_lie_probabilities, round_clips, prompts) if ask_neon else None

    decision_answers = None
    decision_probabilities_by_order = {}
    try:
        decision_answers = in_order_future.result()
        decision_probabilities_by_order["1-2-3"] = read_choice_probabilities(decision_answers)
    except Exception as decision_error:
        logger.warning("Decision 1 (in order) failed for round %s: %s", round_id, decision_error)
    try:
        decision_probabilities_by_order["3-2-1"] = read_choice_probabilities(reversed_future.result())
    except Exception as decision_error:
        logger.warning("Decision 1 (reversed) failed for round %s: %s", round_id, decision_error)

    if decision_probabilities_by_order:
        # Average the two orders so neither the first nor the last statement gets an edge.
        decision_probabilities = [
            sum(probabilities[position] for probabilities in decision_probabilities_by_order.values()) / len(decision_probabilities_by_order)
            for position in range(3)
        ]
        source = "decision_1"
    else:
        decision_probabilities = guess_lie_from_measures_only(differences_by_statement)
        source = "measures_fallback"

    # If Decision 1 alone isn't confident, start writing the follow-up question now, at the
    # same time as Neon's second opinion, instead of one after the other.
    can_ask_more = len(round_clips["followups"]) < MAX_FOLLOW_UPS
    question_future = None
    if can_ask_more and max(decision_probabilities) < CONFIDENT_ENOUGH_TO_CALL:
        question_future = worker_pool.submit(choose_follow_up, round_id, round_clips, decision_probabilities, prompts)

    neon_probabilities = None
    if neon_future is not None:
        try:
            neon_probabilities = neon_future.result(timeout=NEON_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            logger.warning("Neon second opinion took over %s s for round %s, skipping it", NEON_TIMEOUT_SECONDS, round_id)
        except Exception as neon_error:
            logger.warning("Neon second opinion failed for round %s: %s", round_id, neon_error)

    if neon_probabilities is not None and source == "decision_1":
        blended_probabilities = [
            (1 - NEON_WEIGHT) * decision_probability + NEON_WEIGHT * neon_probability
            for decision_probability, neon_probability in zip(decision_probabilities, neon_probabilities)
        ]
        source = "decision_1_plus_neon"
    else:
        blended_probabilities = decision_probabilities

    lie_probs = [round(probability, 3) for probability in blended_probabilities]
    confidence = max(lie_probs)
    top_statement = lie_probs.index(confidence) + 1
    escalate = confidence < CONFIDENT_ENOUGH_TO_CALL and can_ask_more

    analysis = {
        "lie_probs": lie_probs,
        "confidence": confidence,
        "tells": collect_tells(round_clips, decision_answers),
        "escalate": escalate,
    }
    follow_up_detail = None
    if escalate:
        if question_future is not None:
            follow_up_detail = question_future.result()  # choose_follow_up has its own timeout and template
        else:
            follow_up_detail = choose_follow_up(round_id, round_clips, lie_probs, prompts)
        analysis["follow_up"] = {"statement": follow_up_detail["statement"], "question": follow_up_detail["question"]}

    # Save more than we return, for the eval and the call.
    saved_analysis = dict(analysis)
    saved_analysis["follow_up_detail"] = follow_up_detail
    saved_analysis["follow_ups_so_far"] = len(round_clips["followups"])
    saved_analysis["source"] = source
    saved_analysis["top_statement"] = top_statement
    saved_analysis["decision_probabilities_by_order"] = {
        order_name: [round(probability, 3) for probability in probabilities]
        for order_name, probabilities in decision_probabilities_by_order.items()
    }
    saved_analysis["neon_probabilities"] = [round(probability, 3) for probability in neon_probabilities] if neon_probabilities else None
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
    worker_pool.shutdown(wait=False)
    return analysis


def choose_statement_to_press(lie_probs: list[float], followup_clips: list[dict]) -> int:
    """Press on the statements we're unsure about, taking turns between the top two.

    Among the two most suspicious statements, pick the one asked about fewer times;
    on a tie, pick the more suspicious one.
    """
    statements_by_suspicion = sorted(ALL_STATEMENTS_IN_ORDER, key=lambda number: lie_probs[number - 1], reverse=True)
    top_two_statements = statements_by_suspicion[:2]
    times_pressed = {
        statement_number: sum(1 for clip in followup_clips if clip.get("pressed_statement") == statement_number)
        for statement_number in top_two_statements
    }
    return min(top_two_statements, key=lambda number: (times_pressed[number], -lie_probs[number - 1]))


def choose_follow_up(round_id: str, round_clips: dict, lie_probs: list[float], prompts: list[str]) -> dict:
    """The server picks the statement; Neon writes the question (template if it fails or is slow)."""
    statement_number = choose_statement_to_press(lie_probs, round_clips["followups"])
    statement_clip = round_clips["statements"][statement_number - 1]
    earlier_answer_clips = [
        clip for clip in round_clips["followups"] if clip.get("pressed_statement") == statement_number
    ]
    prompt_text = prompts[statement_number - 1]
    try:
        return run_with_timeout(
            NEON_TIMEOUT_SECONDS, write_follow_up_question,
            statement_number, statement_clip, earlier_answer_clips, prompt_text,
        )
    except Exception as neon_error:
        logger.warning("Neon follow-up question failed for round %s, using the template: %s", round_id, neon_error)

    template_questions = [
        "What exactly happened, and when?",
        "Who else was there, and what did they say?",
        "Where were you, and what did it look like?",
    ]
    question_ending = template_questions[min(len(earlier_answer_clips), len(template_questions) - 1)]
    return {
        "statement": statement_number,
        "question": f"Tell me more about statement {statement_number} ({prompt_text.lower()}). {question_ending}",
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
