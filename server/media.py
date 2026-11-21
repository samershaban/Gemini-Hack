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
