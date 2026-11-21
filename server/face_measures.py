"""Face tells measured with MediaPipe Face Landmarker (blinks and gaze breaks).

API verified against the MediaPipe docs and the installed mediapipe 1.2.3:
FaceLandmarker in VIDEO mode, detect_for_video(mp.Image, timestamp_ms), blendshape
categories have .category_name and .score. Blendshape names checked on a real result.

Two steps, so stats can be recomputed after trimming without re-running the tracker:
1. track_face_frames(mp4) -> one entry per frame (blink and gaze scores, or no face)
2. compute_face_stats(frames, start_s) -> blink rate, gaze breaks, events from start_s on
"""

from pathlib import Path

import mediapipe

from server.media import read_video_frames_as_rgb
from server.paths import DATA_FOLDER

FACE_MODEL_FILE = DATA_FOLDER / "models" / "face_landmarker.task"
FACE_MODEL_URL = "https://huggingface.co/litert-community/MediaPipe-FaceLandmarker/resolve/main/face_landmarker.task"

# Every frame: clips are converted to 30 fps, and a blink (about 100-150 ms) can fall
# between frames at lower rates. 60 fps isn't possible because the source is 30 fps.
FRAMES_PER_SECOND = 30
FRAME_WIDTH = 480
# Blink scores differ a lot between people (one player's resting level was 0.15 with blinks
# at 0.75; another's blinks peaked near 0.5). So a blink is a jump above the clip's own
# resting level, with a floor so a squint or noise doesn't count.
BLINK_JUMP_ABOVE_RESTING = 0.25
BLINK_THRESHOLD_FLOOR = 0.35
GAZE_AWAY_THRESHOLD = 0.6
GAZE_BLENDSHAPE_NAMES = [
    "eyeLookOutLeft", "eyeLookOutRight",
    "eyeLookInLeft", "eyeLookInRight",
    "eyeLookUpLeft", "eyeLookUpRight",
    "eyeLookDownLeft", "eyeLookDownRight",
]


def download_face_model_if_missing() -> None:
    if FACE_MODEL_FILE.exists():
        return
    import urllib.request

    FACE_MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(FACE_MODEL_URL, FACE_MODEL_FILE)


def create_face_landmarker():
    """A new landmarker for each clip, so clips processed in parallel never share one."""
    download_face_model_if_missing()
    landmarker_options = mediapipe.tasks.vision.FaceLandmarkerOptions(
        base_options=mediapipe.tasks.BaseOptions(model_asset_path=str(FACE_MODEL_FILE)),
        running_mode=mediapipe.tasks.vision.RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,
    )
    return mediapipe.tasks.vision.FaceLandmarker.create_from_options(landmarker_options)


def track_face_frames(mp4_path: Path) -> list[dict]:
    """One entry per frame: {"t_s", "has_face", "blink_score", "gaze_away_score"}."""
    frames = []
    with create_face_landmarker() as face_landmarker:
        for timestamp_ms, rgb_frame in read_video_frames_as_rgb(mp4_path, FRAMES_PER_SECOND, FRAME_WIDTH):
            mediapipe_image = mediapipe.Image(image_format=mediapipe.ImageFormat.SRGB, data=rgb_frame)
            result = face_landmarker.detect_for_video(mediapipe_image, timestamp_ms)
            frame = {"t_s": timestamp_ms / 1000, "has_face": False, "blink_score": 0.0, "gaze_away_score": 0.0}
            if result.face_blendshapes:
                scores_by_name = {category.category_name: category.score for category in result.face_blendshapes[0]}
                frame["has_face"] = True
                frame["blink_score"] = (scores_by_name["eyeBlinkLeft"] + scores_by_name["eyeBlinkRight"]) / 2
                frame["gaze_away_score"] = max(scores_by_name[name] for name in GAZE_BLENDSHAPE_NAMES)
            frames.append(frame)
    return frames


def compute_face_stats(frames: list[dict], start_s: float = 0.0) -> dict:
    """Blink rate, gaze breaks, and timestamped events, using only frames from start_s on.

    Event times are relative to start_s, so they match a clip trimmed at start_s.
    """
    kept_frames = [frame for frame in frames if frame["t_s"] >= start_s]
    frames_with_face = [frame for frame in kept_frames if frame["has_face"]]
    if not frames_with_face:
        return {"blink_rate": None, "gaze_breaks": None, "face_found_fraction": 0.0, "events": []}

    blink_scores = sorted(frame["blink_score"] for frame in frames_with_face)
    resting_blink_score = blink_scores[len(blink_scores) // 2]  # the median: eyes open most of the time
    blink_threshold = max(BLINK_THRESHOLD_FLOOR, resting_blink_score + BLINK_JUMP_ABOVE_RESTING)

    events = []
    blink_count = 0
    gaze_break_count = 0
    eyes_were_closed = False
    gaze_was_away = False
    for frame in frames_with_face:
        # Count a blink when the eyes go from open to closed.
        eyes_are_closed = frame["blink_score"] > blink_threshold
        if eyes_are_closed and not eyes_were_closed:
            blink_count += 1
        eyes_were_closed = eyes_are_closed

        # Count a gaze break when the eyes move from the camera to looking away.
        # Skip frames where the eyes are closed: blinks also move the eyeLook scores.
        gaze_is_away = frame["gaze_away_score"] > GAZE_AWAY_THRESHOLD and not eyes_are_closed
        if gaze_is_away and not gaze_was_away:
            gaze_break_count += 1
            events.append({"t_s": round(frame["t_s"] - start_s, 1), "label": "gaze break"})
        gaze_was_away = gaze_is_away

    kept_minutes = len(kept_frames) / FRAMES_PER_SECOND / 60
    return {
        "blink_rate": round(blink_count / kept_minutes, 1) if kept_minutes > 0 else None,
        "gaze_breaks": gaze_break_count,
        "face_found_fraction": round(len(frames_with_face) / len(kept_frames), 2),
        "events": events,
    }


def measure_face(mp4_path: Path) -> dict:
    """Track the whole clip and compute stats over all of it (kept for scripts and tests)."""
    return compute_face_stats(track_face_frames(mp4_path))
