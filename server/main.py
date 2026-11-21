"""Poker Face: Room Edition, Part A (the brain).

Run from the repo root:
    .venv/bin/uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

Endpoints follow the contract in "Poker Face Room Edition PRD.md". Do not change a
request or response shape without telling the Part B (web/) owner first.
"""

import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server import db
from server.clip_measures import measure_clip
from server.decisions import make_decisions_client, upload_clip_and_wait_until_active
from server.media import ClipConversionError, convert_clip_to_mp4
from server.paths import get_round_folder
from server.round_prompts import pick_lie_index, pick_three_prompts

load_dotenv()

ALLOWED_CLIP_KINDS = ["baseline", "statement", "followup", "angle"]
CONTRACT_MEASURE_NAMES = ["delay_ms", "fillers", "blink_rate", "gaze_breaks"]

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.create_tables()
    yield


app = FastAPI(title="Poker Face Brain", lifespan=lifespan)

# Phones and the Vite dev server load the web app from other origins, so allow them all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateRoundRequest(BaseModel):
    room: str


@app.get("/health")
def health_check():
    return {"ok": True}


@app.post("/rounds")
def create_round(request_body: CreateRoundRequest):
    round_id = uuid.uuid4().hex[:12]
    prompts = pick_three_prompts()
    lie_index = pick_lie_index()

    db.insert_round(round_id=round_id, room=request_body.room, prompts=prompts, lie_index=lie_index)

    # The lie index stays secret: it is only sent to the player's phone over the WebSocket later.
    return {"round_id": round_id, "prompts": prompts}


@app.post("/rounds/{round_id}/clips")
def upload_clip(
    round_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    kind: str = Form(...),
    index: int = Form(...),
    camera_id: str = Form("stage"),
):
    # Plain `def` (not `async def`) so FastAPI runs the slow ffmpeg call in a worker thread.
    if db.get_round(round_id) is None:
        raise HTTPException(status_code=404, detail=f"No round with id {round_id}")

    if kind not in ALLOWED_CLIP_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"kind must be one of {ALLOWED_CLIP_KINDS}, got '{kind}'",
        )

    clip_id = uuid.uuid4().hex[:12]
    round_folder = get_round_folder(round_id)

    # Keep the original file exactly as the browser sent it.
    original_extension = Path(file.filename or "").suffix or ".webm"
    original_path = round_folder / f"{clip_id}_original{original_extension}"
    with open(original_path, "wb") as original_file:
        shutil.copyfileobj(file.file, original_file)

    mp4_path = round_folder / f"{clip_id}.mp4"
    try:
        convert_clip_to_mp4(original_path, mp4_path)
    except ClipConversionError as conversion_error:
        raise HTTPException(status_code=422, detail=str(conversion_error))

    db.insert_clip(
        clip_id=clip_id,
        round_id=round_id,
        kind=kind,
        statement_index=index,
        camera_id=camera_id,
        original_path=str(original_path),
        mp4_path=str(mp4_path),
    )

    clip_measurements = measure_clip(mp4_path)
    db.save_clip_measurements(
        clip_id=clip_id,
        transcript=clip_measurements["transcript"],
        words=clip_measurements["words"],
        measures=clip_measurements["measures"],
        events=clip_measurements["events"],
    )

    # Upload to the Gemini Files API after responding. Decision 1 answers faster on an
    # uploaded file (635 ms median) than on inline video (about 1.6 s), see docs/timing_decision_1.json.
    background_tasks.add_task(upload_clip_to_gemini, clip_id, mp4_path)

    contract_measures = {name: clip_measurements["measures"][name] for name in CONTRACT_MEASURE_NAMES}
    return {
        "clip_id": clip_id,
        "transcript": clip_measurements["transcript"],
        "measures": contract_measures,
    }


def upload_clip_to_gemini(clip_id: str, mp4_path: Path) -> None:
    """Runs in the background. If it fails, /analyze falls back to sending the video inline."""
    try:
        uploaded_file = upload_clip_and_wait_until_active(make_decisions_client(), mp4_path)
        db.save_clip_gemini_file_uri(clip_id, uploaded_file.uri)
    except Exception as upload_error:
        logger.warning("Gemini upload failed for clip %s: %s", clip_id, upload_error)
