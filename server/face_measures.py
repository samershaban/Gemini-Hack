"""Face tells measured with MediaPipe Face Landmarker (blinks and gaze breaks).

API verified against the MediaPipe docs and the installed mediapipe 1.2.3:
FaceLandmarker in VIDEO mode, detect_for_video(mp.Image, timestamp_ms), blendshape
categories have .category_name and .score. Blendshape names checked on a real result.
"""

from pathlib import Path

import mediapipe

from server.media import read_video_frames_as_rgb
from server.paths import DATA_FOLDER

FACE_MODEL_FILE = DATA_FOLDER / "models" / "face_landmarker.task"
FACE_MODEL_URL = "https://huggingface.co/litert-community/MediaPipe-FaceLandmarker/resolve/main/face_landmarker.task"

FRAMES_PER_SECOND = 10
FRAME_WIDTH = 480
BLINK_THRESHOLD = 0.5
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


def measure_face(mp4_path: Path) -> dict:
    """Return blink rate, gaze breaks, how often a face was found, and timestamped events."""
    events = []
    frame_count = 0
    frames_with_face = 0
    blink_count = 0
    gaze_break_count = 0
    eyes_were_closed = False
    gaze_was_away = False

    with create_face_landmarker() as face_landmarker:
        for timestamp_ms, rgb_frame in read_video_frames_as_rgb(mp4_path, FRAMES_PER_SECOND, FRAME_WIDTH):
            frame_count += 1
            mediapipe_image = mediapipe.Image(image_format=mediapipe.ImageFormat.SRGB, data=rgb_frame)
            result = face_landmarker.detect_for_video(mediapipe_image, timestamp_ms)
            if not result.face_blendshapes:
                continue
            frames_with_face += 1

            scores_by_name = {category.category_name: category.score for category in result.face_blendshapes[0]}
            blink_score = (scores_by_name["eyeBlinkLeft"] + scores_by_name["eyeBlinkRight"]) / 2
            gaze_away_score = max(scores_by_name[name] for name in GAZE_BLENDSHAPE_NAMES)
            seconds = timestamp_ms / 1000

            # Count a blink when the eyes go from open to closed.
            eyes_are_closed = blink_score > BLINK_THRESHOLD
            if eyes_are_closed and not eyes_were_closed:
                blink_count += 1
            eyes_were_closed = eyes_are_closed

            # Count a gaze break when the eyes move from the camera to looking away.
            # Skip frames where the eyes are closed: blinks also move the eyeLook scores.
            gaze_is_away = gaze_away_score > GAZE_AWAY_THRESHOLD and not eyes_are_closed
            if gaze_is_away and not gaze_was_away:
                gaze_break_count += 1
                events.append({"t_s": round(seconds, 1), "label": "gaze break"})
            gaze_was_away = gaze_is_away

    clip_minutes = frame_count / FRAMES_PER_SECOND / 60
    blink_rate_per_minute = round(blink_count / clip_minutes, 1) if clip_minutes > 0 else None
    face_found_fraction = round(frames_with_face / frame_count, 2) if frame_count else 0.0

    if frames_with_face == 0:
        return {"blink_rate": None, "gaze_breaks": None, "face_found_fraction": 0.0, "events": []}

    return {
        "blink_rate": blink_rate_per_minute,
        "gaze_breaks": gaze_break_count,
        "face_found_fraction": face_found_fraction,
        "events": events,
    }
