"""Score every finished round against the baselines and the modality ablation.

Run from the repo root:
    .venv/bin/python -m eval.run_eval

- Reads every revealed round from SQLite (each has the true lie from the server).
- The first 15 rounds are the locked holdout, reported separately.
- Model calls are cached in data/eval_cache.json, so re-running is cheap.
- Writes docs/results.json, docs/accuracy_by_condition.png, docs/calibration.png.
"""

import json
import logging
import random
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from eval.charts import draw_accuracy_chart, draw_calibration_chart
from eval.eval_conditions import CONDITION_RUNNERS
from server import db
from server.paths import DATA_FOLDER, REPO_ROOT_FOLDER
from server.pipeline import RoundNotReadyError, load_round_clips

logger = logging.getLogger(__name__)

HOLDOUT_ROUND_COUNT = 15
CACHE_FILE = DATA_FOLDER / "eval_cache.json"
DOCS_FOLDER = REPO_ROOT_FOLDER / "docs"
CALIBRATION_BUCKETS = [(0.33, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
PARALLEL_ROUNDS = 4

CONDITION_LABELS = {
    "random": "Random guess",
    "room_votes": "The room (phone votes)",
    "single_hydrogen_call": "Single Hydrogen call",
    "decision_transcript_only": "Transcript only",
    "decision_audio_only": "Audio only",
    "decision_video_only": "Video only",
    "decision_all_media": "All media",
    "decision_all_media_plus_measures": "All media + measures",
    "live_system": "Live Poker Face (with follow-up)",
}


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=1))


def run_model_conditions_for_round(round_info: dict, cache: dict) -> dict:
    """Run every model condition on one round (using the cache when we can)."""
    round_id = round_info["round_id"]
    try:
        round_clips = load_round_clips(round_id)
    except RoundNotReadyError as not_ready_error:
        logger.warning("Skipping round %s: %s", round_id, not_ready_error)
        return {}
    # The eval leaves out the follow-up clip, except in the live system result.
    round_clips["followups"] = []

    results = {}
    for condition_name, run_condition in CONDITION_RUNNERS.items():
        cache_key = f"{round_id}:{condition_name}"
        if cache_key in cache:
            results[condition_name] = cache[cache_key]
            continue
        try:
            results[condition_name] = run_condition(round_clips)
            cache[cache_key] = results[condition_name]
        except Exception as condition_error:
            logger.warning("Condition %s failed on round %s: %s", condition_name, round_id, condition_error)
            results[condition_name] = {"statement": None, "confidence": None, "error": str(condition_error)}
    return results


def score_round(round_info: dict, model_results: dict) -> dict:
    """One row per round: which statement each condition picked, and whether it was right."""
    lie_statement = round_info["lie_index"] + 1
    result = round_info["result"]
    random_generator = random.Random(round_info["round_id"])

    picks = {"random": {"statement": random_generator.choice([1, 2, 3]), "confidence": 1 / 3}}

    votes = result["votes"]
    if votes:
        vote_counts = {statement: 0 for statement in [1, 2, 3]}
        for vote in votes:
            vote_counts[vote["statement"]] += 1
        majority_statement = max(vote_counts, key=vote_counts.get)
        picks["room_votes"] = {"statement": majority_statement, "confidence": result["room_accuracy"]}

    call = round_info["call"]
    if call:
        picks["live_system"] = {"statement": call["statement"], "confidence": call["confidence"]}

    picks.update(model_results)

    for pick in picks.values():
        pick["correct"] = pick["statement"] == lie_statement if pick.get("statement") else None

    return {
        "round_id": round_info["round_id"],
        "lie_statement": lie_statement,
        "tried_to_trick": bool(round_info.get("tried_to_trick")),
        "tags": json.loads(round_info["tags_json"]) if round_info.get("tags_json") else [],
        "picks": picks,
    }


def summarize_accuracy(scored_rounds: list[dict]) -> dict:
    summary = {}
    for condition_name in CONDITION_LABELS:
        outcomes = [
            scored["picks"][condition_name]["correct"]
            for scored in scored_rounds
            if condition_name in scored["picks"] and scored["picks"][condition_name]["correct"] is not None
        ]
        summary[condition_name] = {
            "label": CONDITION_LABELS[condition_name],
            "rounds": len(outcomes),
            "accuracy": round(sum(outcomes) / len(outcomes), 3) if outcomes else None,
        }
    return summary


def summarize_by_tag(scored_rounds: list[dict], condition_name: str) -> dict:
    """Accuracy of one condition on each hard-input tag (poker_face, loud_room, ...)."""
    outcomes_by_tag = {}
    for scored in scored_rounds:
        pick = scored["picks"].get(condition_name)
        if not pick or pick["correct"] is None:
            continue
        for tag in scored["tags"] or ["untagged"]:
            outcomes_by_tag.setdefault(tag, []).append(pick["correct"])
    return {
        tag: {"rounds": len(outcomes), "accuracy": round(sum(outcomes) / len(outcomes), 3)}
        for tag, outcomes in outcomes_by_tag.items()
    }


def summarize_calibration(scored_rounds: list[dict], condition_name: str) -> list[dict]:
    """When Gemini says 70% sure, is it right about 70% of the time?"""
    buckets = []
    for bucket_low, bucket_high in CALIBRATION_BUCKETS:
        outcomes = []
        confidences = []
        for scored in scored_rounds:
            pick = scored["picks"].get(condition_name)
            if not pick or pick.get("confidence") is None or pick["correct"] is None:
                continue
            if bucket_low <= pick["confidence"] < bucket_high:
                outcomes.append(pick["correct"])
                confidences.append(pick["confidence"])
        buckets.append({
            "bucket": f"{bucket_low:.2f}-{min(bucket_high, 1.0):.2f}",
            "rounds": len(outcomes),
            "mean_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
            "accuracy": round(sum(outcomes) / len(outcomes), 3) if outcomes else None,
        })
    return buckets


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    db.create_tables()
    revealed_rounds = db.get_all_revealed_rounds()
    print(f"{len(revealed_rounds)} finished rounds")

    cache = load_cache()
    with ThreadPoolExecutor(max_workers=PARALLEL_ROUNDS) as worker_pool:
        model_results_per_round = list(worker_pool.map(
            lambda round_info: run_model_conditions_for_round(round_info, cache), revealed_rounds
        ))
    save_cache(cache)

    scored_rounds = [
        score_round(round_info, model_results)
        for round_info, model_results in zip(revealed_rounds, model_results_per_round)
    ]
    holdout_rounds = scored_rounds[:HOLDOUT_ROUND_COUNT]
    later_rounds = scored_rounds[HOLDOUT_ROUND_COUNT:]

    results = {
        "total_rounds": len(scored_rounds),
        "accuracy_all_rounds": summarize_accuracy(scored_rounds),
        "accuracy_holdout_first_15": summarize_accuracy(holdout_rounds),
        "accuracy_after_holdout": summarize_accuracy(later_rounds),
        "accuracy_by_tag_live_system": summarize_by_tag(scored_rounds, "live_system"),
        "calibration_live_system": summarize_calibration(scored_rounds, "live_system"),
        "calibration_all_media_plus_measures": summarize_calibration(scored_rounds, "decision_all_media_plus_measures"),
        "rounds": scored_rounds,
    }
    DOCS_FOLDER.mkdir(exist_ok=True)
    (DOCS_FOLDER / "results.json").write_text(json.dumps(results, indent=2))

    print(f"\n{'Condition':<36} {'Rounds':>6} {'Accuracy':>9}")
    for condition_summary in results["accuracy_all_rounds"].values():
        accuracy_text = f"{condition_summary['accuracy']:.0%}" if condition_summary["accuracy"] is not None else "-"
        print(f"{condition_summary['label']:<36} {condition_summary['rounds']:>6} {accuracy_text:>9}")

    draw_accuracy_chart(results["accuracy_all_rounds"], DOCS_FOLDER / "accuracy_by_condition.png")
    draw_calibration_chart(results["calibration_live_system"], DOCS_FOLDER / "calibration.png")
    print(f"\nWrote {DOCS_FOLDER / 'results.json'} and the charts in {DOCS_FOLDER}")


if __name__ == "__main__":
    main()
