"""ffmpeg helpers: convert browser clips to MP4 and cut short test clips."""

import subprocess
from pathlib import Path


class ClipConversionError(Exception):
    """Raised when ffmpeg cannot read or convert a clip."""


def run_ffmpeg(ffmpeg_arguments: list[str]) -> None:
    """Run ffmpeg and raise ClipConversionError with the end of its error output if it fails."""
    full_command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + ffmpeg_arguments
    finished_process = subprocess.run(full_command, capture_output=True, text=True)
    if finished_process.returncode != 0:
        error_text = finished_process.stderr.strip()
        last_error_lines = "\n".join(error_text.splitlines()[-5:])
        raise ClipConversionError(f"ffmpeg failed: {last_error_lines}")


def convert_clip_to_mp4(input_path: Path, output_path: Path) -> None:
    """Convert a WebM (or any) clip from MediaRecorder into an H.264/AAC MP4.

    MediaRecorder writes variable frame rate video, so we force a steady 30 fps.
    """
    run_ffmpeg(
        [
            "-i", str(input_path),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-fps_mode", "cfr",
            "-r", "30",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ]
    )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ClipConversionError("ffmpeg finished but the MP4 is empty")


def cut_clip(input_path: Path, output_path: Path, start_seconds: float, length_seconds: float) -> None:
    """Cut a piece out of a longer video and re-encode it as MP4."""
    run_ffmpeg(
        [
            "-ss", str(start_seconds),
            "-i", str(input_path),
            "-t", str(length_seconds),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ]
    )


def extract_audio_wav(input_path: Path, output_path: Path) -> None:
    """Pull the audio out of a clip as 16 kHz mono WAV (what speech models like best)."""
    run_ffmpeg(["-i", str(input_path), "-vn", "-ac", "1", "-ar", "16000", str(output_path)])


def find_speech_start_ms(wav_path: Path) -> int | None:
    """Find when the speaker starts talking, using ffmpeg's silence detector.

    This needs no API call, so it is the fallback for delay_ms when transcription fails.
    Returns None if the clip has no clear speech.
    """
    detector_command = [
        "ffmpeg", "-hide_banner", "-i", str(wav_path),
        "-af", "silencedetect=noise=-35dB:d=0.2",
        "-f", "null", "-",
    ]
    finished_process = subprocess.run(detector_command, capture_output=True, text=True)
    detector_lines = finished_process.stderr.splitlines()

    first_silence_start = None
    first_silence_end = None
    for line in detector_lines:
        if "silence_start:" in line and first_silence_start is None:
            first_silence_start = float(line.split("silence_start:")[1].strip())
        if "silence_end:" in line and first_silence_end is None:
            first_silence_end = float(line.split("silence_end:")[1].split("|")[0].strip())

    if first_silence_start is None:
        return 0  # no silence at all: speech starts right away
    if first_silence_start > 0.05:
        return 0  # the clip starts with sound, so speech starts at 0
    if first_silence_end is None:
        return None  # the whole clip is silent
    return int(first_silence_end * 1000)


def get_video_size(video_path: Path) -> tuple[int, int]:
    """Return (width, height) of the first video stream."""
    probe_command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video_path),
    ]
    probe_output = subprocess.run(probe_command, capture_output=True, text=True, check=True).stdout
    width_text, height_text = probe_output.strip().split(",")[:2]
    return int(width_text), int(height_text)


def read_video_frames_as_rgb(video_path: Path, frames_per_second: int, frame_width: int):
    """Yield (timestamp_ms, rgb_frame) pairs, decoded by ffmpeg into numpy arrays.

    Frames are scaled down to frame_width to keep face tracking fast.
    """
    import numpy

    original_width, original_height = get_video_size(video_path)
    frame_height = int(round(original_height * frame_width / original_width / 2) * 2)
    decode_command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video_path),
        "-vf", f"fps={frames_per_second},scale={frame_width}:{frame_height}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    bytes_per_frame = frame_width * frame_height * 3
    decoder_process = subprocess.Popen(decode_command, stdout=subprocess.PIPE)
    frame_number = 0
    try:
        while True:
            frame_bytes = decoder_process.stdout.read(bytes_per_frame)
            if len(frame_bytes) < bytes_per_frame:
                break
            rgb_frame = numpy.frombuffer(frame_bytes, dtype=numpy.uint8).reshape(frame_height, frame_width, 3)
            timestamp_ms = int(frame_number * 1000 / frames_per_second)
            yield timestamp_ms, rgb_frame
            frame_number += 1
    finally:
        decoder_process.stdout.close()
        decoder_process.wait()


def save_still_frame(video_path: Path, output_path: Path, at_seconds: float) -> None:
    """Save one JPEG frame from the video at the given time (for the BUSTED screen)."""
    run_ffmpeg(["-ss", str(at_seconds), "-i", str(video_path), "-frames:v", "1", "-q:v", "3", str(output_path)])


def get_video_duration_seconds(video_path: Path) -> float:
    probe_command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path),
    ]
    probe_output = subprocess.run(probe_command, capture_output=True, text=True, check=True).stdout
    return float(probe_output.strip())
