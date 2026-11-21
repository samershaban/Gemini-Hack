"""Time one Decision 1 call on a 5-second clip.

Run from the repo root:
    .venv/bin/python -m eval.time_decision_call
    .venv/bin/python -m eval.time_decision_call --clip test_clips/my_clip.mp4

With no --clip, it downloads the sample video used in Google's Decisions API docs and
cuts the first 5 seconds. No license is stated for that video, so it stays local only
(test_clips/ is gitignored) and is never committed, shown, or used in the eval. It is not
a person talking, so the answers mean nothing; we only measure latency here. Prefer
--clip with a short recording of a consenting teammate.

Three ways of sending the clip are timed:
  A. inline base64, resolution "low"
  B. inline base64, default resolution
  C. Files API upload (timed once), then the call with the file's uri
"""

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from server.decisions import (
    TELL_QUESTIONS,
    ask_decision_questions,
    build_text_block,
    build_video_block_from_upload,
    build_video_block_inline,
    make_decisions_client,
    upload_clip_and_wait_until_active,
)
from server.media import cut_clip
from server.models import DECISION_MODEL
from server.paths import REPO_ROOT_FOLDER

SAMPLE_VIDEO_URL = "https://storage.googleapis.com/generativeai-downloads/videos/ForBiggerBlazes.mp4"
TEST_CLIPS_FOLDER = REPO_ROOT_FOLDER / "test_clips"
RESULTS_FILE = REPO_ROOT_FOLDER / "docs" / "timing_decision_1.json"
RUNS_PER_VARIANT = 5
CLIP_LENGTH_SECONDS = 5


def get_default_five_second_clip() -> Path:
    """Download the Google sample video once and cut it to 5 seconds."""
    TEST_CLIPS_FOLDER.mkdir(exist_ok=True)
    full_video_path = TEST_CLIPS_FOLDER / "ForBiggerBlazes.mp4"
    short_clip_path = TEST_CLIPS_FOLDER / "ForBiggerBlazes_5s.mp4"
    if not full_video_path.exists():
        print(f"Downloading {SAMPLE_VIDEO_URL} ...")
        urllib.request.urlretrieve(SAMPLE_VIDEO_URL, full_video_path)
    if not short_clip_path.exists():
        cut_clip(full_video_path, short_clip_path, start_seconds=0, length_seconds=CLIP_LENGTH_SECONDS)
    return short_clip_path


def time_one_variant(client, variant_name: str, input_blocks: list[dict]) -> dict:
    """Make the same call several times and collect the latency of each one."""
    latencies_ms = []
    last_result = None
    for run_number in range(1, RUNS_PER_VARIANT + 1):
        started_at = time.perf_counter()
        last_result = ask_decision_questions(client, input_blocks, TELL_QUESTIONS)
        latency_ms = (time.perf_counter() - started_at) * 1000
        latencies_ms.append(round(latency_ms, 1))
        print(f"  {variant_name} run {run_number}: {latency_ms:.0f} ms")

    input_tokens = None
    if last_result.usage is not None:
        input_tokens = last_result.usage.total_input_tokens

    # Keep one set of answers so we can check every question came back with a confidence.
    example_answers = {}
    for question_key, answer in (last_result.answers or {}).items():
        example_answers[question_key] = {
            "type": answer.type,
            "value": getattr(answer, answer.type),
            "confidence": round(answer.confidence, 3),
        }
    missing_question_keys = sorted(set(TELL_QUESTIONS) - set(example_answers))

    return {
        "variant": variant_name,
        "latencies_ms": latencies_ms,
        "min_ms": min(latencies_ms),
        "median_ms": statistics.median(latencies_ms),
        "max_ms": max(latencies_ms),
        "input_tokens": input_tokens,
        "missing_question_keys": missing_question_keys,
        "example_answers": example_answers,
    }


def main() -> None:
    load_dotenv()
    argument_parser = argparse.ArgumentParser(description="Time Decision 1 on a 5-second clip")
    argument_parser.add_argument("--clip", type=Path, help="Path to a 5-second MP4 clip")
    arguments = argument_parser.parse_args()

    clip_path = arguments.clip if arguments.clip else get_default_five_second_clip()
    print(f"Clip: {clip_path} ({clip_path.stat().st_size / 1024:.0f} KB)")
    print(f"Model: {DECISION_MODEL}, {len(TELL_QUESTIONS)} questions per call, {RUNS_PER_VARIANT} runs each\n")

    client = make_decisions_client()
    label_block = build_text_block("STATEMENT clip:")
    all_variant_results = []

    print("A. inline, resolution low")
    inline_low_blocks = [label_block, build_video_block_inline(clip_path, resolution="low")]
    all_variant_results.append(time_one_variant(client, "A_inline_low", inline_low_blocks))

    print("B. inline, default resolution")
    inline_default_blocks = [label_block, build_video_block_inline(clip_path, resolution=None)]
    all_variant_results.append(time_one_variant(client, "B_inline_default", inline_default_blocks))

    print("C. Files API upload, then uri")
    upload_started_at = time.perf_counter()
    uploaded_file = upload_clip_and_wait_until_active(client, clip_path)
    upload_ms = round((time.perf_counter() - upload_started_at) * 1000, 1)
    print(f"  upload + wait until ACTIVE: {upload_ms:.0f} ms")
    files_api_blocks = [label_block, build_video_block_from_upload(uploaded_file, resolution="low")]
    files_api_result = time_one_variant(client, "C_files_api_low", files_api_blocks)
    files_api_result["upload_and_wait_ms"] = upload_ms
    all_variant_results.append(files_api_result)

    print("\nVariant              min    median    max   input tokens   missing answers")
    for variant_result in all_variant_results:
        print(
            f"{variant_result['variant']:<18} {variant_result['min_ms']:>6.0f} {variant_result['median_ms']:>8.0f} "
            f"{variant_result['max_ms']:>6.0f}   {str(variant_result['input_tokens']):>12}   "
            f"{variant_result['missing_question_keys'] or 'none'}"
        )
    print(f"(Files API upload + wait until ACTIVE, one time: {upload_ms:.0f} ms)")

    RESULTS_FILE.parent.mkdir(exist_ok=True)
    results_to_save = {
        "model": DECISION_MODEL,
        "clip": clip_path.name,
        "clip_size_kb": round(clip_path.stat().st_size / 1024),
        "questions_per_call": len(TELL_QUESTIONS),
        "runs_per_variant": RUNS_PER_VARIANT,
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "variants": all_variant_results,
    }
    RESULTS_FILE.write_text(json.dumps(results_to_save, indent=2))
    print(f"\nSaved {RESULTS_FILE}")


if __name__ == "__main__":
    main()
