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

import anyio.from_thread
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server import db
from server.clip_measures import measure_clip
from server.decisions import make_decisions_client, upload_clip_and_wait_until_active
from server.media import ClipConversionError, convert_clip_to_mp4
from server.paths import get_round_folder
from server.pipeline import RoundNotReadyError, analyze_round, make_call
from server.room_hub import room_hub
from server.round_prompts import pick_lie_index, pick_three_prompts
from server.scoring import build_scoreboard, reveal_round

load_dotenv()

ALLOWED_CLIP_KINDS = ["baseline", "statement", "followup", "angle"]
CONTRACT_MEASURE_NAMES = ["delay_ms", "fillers", "blink_rate", "gaze_breaks"]
PHASE_FOR_CLIP_KIND = {"baseline": "baseline", "statement": "statements", "followup": "followup"}

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


class RevealRequest(BaseModel):
    tried_to_trick: bool = False
    # Optional: the stage can say which statement was really the lie (1-3).
    # Otherwise we use the player's phone confirmation, then the secret.
    lie_statement: int | None = None


def send_to_room_from_worker_thread(room_name: str, message: dict) -> None:
    """Plain `def` endpoints run in worker threads; this hands the WebSocket send to the event loop."""
    try:
        anyio.from_thread.run(room_hub.send_to_everyone, room_name, message)
    except Exception as send_error:
        logger.warning("Could not send %s to room %s: %s", message.get("type"), room_name, send_error)


def build_secret_message(round_info: dict) -> dict:
    lie_index = round_info["lie_index"]
    return {
        "type": "secret",
        "round_id": round_info["round_id"],
        "lie_index": lie_index,
        "statement": lie_index + 1,
        "prompt": round_info["prompts"][lie_index],
    }


def get_round_or_404(round_id: str) -> dict:
    round_info = db.get_round(round_id)
    if round_info is None:
        raise HTTPException(status_code=404, detail=f"No round with id {round_id}")
    return round_info


@app.get("/health")
def health_check():
    return {"ok": True}


@app.post("/rounds")
def create_round(request_body: CreateRoundRequest):
    round_id = uuid.uuid4().hex[:12]
    prompts = pick_three_prompts()
    lie_index = pick_lie_index()

    db.insert_round(round_id=round_id, room=request_body.room, prompts=prompts, lie_index=lie_index)

    # The lie index stays secret: it only goes to the player's phone over the WebSocket.
    round_info = db.get_round(round_id)
    try:
        anyio.from_thread.run(room_hub.send_to_players, request_body.room, build_secret_message(round_info))
    except Exception as send_error:
        logger.warning("Could not send the secret: %s", send_error)
    send_to_room_from_worker_thread(request_body.room, {"type": "phase", "phase": "baseline"})

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
    round_info = get_round_or_404(round_id)

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

    # The stage always sends follow-up clips with index 1, so remember which statement
    # the follow-up question was about (from the latest analysis).
    pressed_statement = None
    follow_up_question = None
    if kind == "followup" and round_info["analysis"] and round_info["analysis"].get("follow_up"):
        pressed_statement = round_info["analysis"]["follow_up"]["statement"]
        follow_up_question = round_info["analysis"]["follow_up"]["question"]

    db.insert_clip(
        clip_id=clip_id,
        round_id=round_id,
        kind=kind,
        statement_index=index,
        camera_id=camera_id,
        original_path=str(original_path),
        mp4_path=str(mp4_path),
        pressed_statement=pressed_statement,
        follow_up_question=follow_up_question,
    )

    clip_measurements = measure_clip(mp4_path)
    db.save_clip_measurements(
        clip_id=clip_id,
        transcript=clip_measurements["transcript"],
        words=clip_measurements["words"],
        measures=clip_measurements["measures"],
        events=clip_measurements["events"],
    )
    if clip_measurements["trim"] is not None:
        db.save_clip_trim(
            clip_id,
            clip_measurements["trim"]["trimmed_seconds"],
            clip_measurements["trim"]["untrimmed_mp4_path"],
        )

    # Upload to the Gemini Files API after responding. Decision 1 answers faster on an
    # uploaded file (635 ms median) than on inline video (about 1.6 s), see docs/timing_decision_1.json.
    background_tasks.add_task(upload_clip_to_gemini, clip_id, mp4_path)

    if kind in PHASE_FOR_CLIP_KIND:
        send_to_room_from_worker_thread(round_info["room"], {"type": "phase", "phase": PHASE_FOR_CLIP_KIND[kind]})

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


@app.post("/rounds/{round_id}/analyze")
def analyze(round_id: str):
    round_info = get_round_or_404(round_id)
    room_name = round_info["room"]
    send_to_room_from_worker_thread(room_name, {"type": "phase", "phase": "thinking"})
    try:
        analysis = analyze_round(round_id)
    except RoundNotReadyError as not_ready_error:
        raise HTTPException(status_code=409, detail=str(not_ready_error))

    send_to_room_from_worker_thread(room_name, {"type": "suspicion", "value": analysis["confidence"]})
    for tell in analysis["tells"]:
        send_to_room_from_worker_thread(room_name, {"type": "tell", **tell})
    if analysis["escalate"]:
        send_to_room_from_worker_thread(room_name, {"type": "phase", "phase": "followup"})
    return analysis


@app.post("/rounds/{round_id}/call")
def call(round_id: str):
    round_info = get_round_or_404(round_id)
    try:
        final_call = make_call(round_id)
    except RoundNotReadyError as not_ready_error:
        raise HTTPException(status_code=409, detail=str(not_ready_error))
    send_to_room_from_worker_thread(round_info["room"], {"type": "phase", "phase": "call"})
    return final_call


@app.post("/rounds/{round_id}/reveal")
def reveal(round_id: str, request_body: RevealRequest):
    round_info = get_round_or_404(round_id)
    reveal_result = reveal_round(round_id, request_body.tried_to_trick, request_body.lie_statement)
    send_to_room_from_worker_thread(round_info["room"], {"type": "phase", "phase": "reveal"})
    send_to_room_from_worker_thread(round_info["room"], {"type": "scoreboard", **reveal_result["scoreboard"]})
    return reveal_result


@app.get("/rounds/{round_id}/frame.jpg")
def get_still_frame(round_id: str):
    get_round_or_404(round_id)
    frame_path = get_round_folder(round_id) / "frame.jpg"
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="No still frame yet; call /call first")
    return FileResponse(frame_path, media_type="image/jpeg")


@app.websocket("/ws/{room_name}")
async def room_websocket(websocket: WebSocket, room_name: str):
    await websocket.accept()
    connected_phone = room_hub.add_connection(room_name, websocket)
    room = room_hub.get_room(room_name)
    await room_hub.send_to_one(connected_phone, {"type": "phase", "phase": room.current_phase})
    await room_hub.send_to_one(connected_phone, {"type": "scoreboard", **build_scoreboard(room_name)})
    await room_hub.send_to_one(connected_phone, room_hub.build_roster_message(room_name))
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "join":
                connected_phone.name = str(message.get("name") or "anonymous")[:40]
                connected_phone.role = message.get("role") if message.get("role") in ["voter", "player"] else "voter"
                connected_phone.has_joined = True
                await room_hub.send_player_list(room_name)
                # A player who joins after the round started still gets the secret.
                latest_round = db.get_latest_round_in_room(room_name)
                if connected_phone.role == "player" and latest_round and latest_round["result"] is None:
                    await room_hub.send_to_one(connected_phone, build_secret_message(latest_round))

            elif message_type == "confirm_lie":
                # The player says which statement was really their lie (they don't always
                # lie on the one the server picked).
                latest_round = db.get_latest_round_in_room(room_name)
                statement = message.get("statement")
                if connected_phone.role != "player":
                    await room_hub.send_to_one(connected_phone, {"type": "error", "detail": "Only the player can confirm the lie"})
                elif latest_round is None or statement not in [1, 2, 3]:
                    await room_hub.send_to_one(connected_phone, {"type": "error", "detail": "statement must be 1, 2, or 3"})
                elif latest_round["call"] is not None:
                    # Locked once Gemini has made its call, so nobody can switch after seeing the guess.
                    await room_hub.send_to_one(connected_phone, {"type": "error", "detail": "Too late: Gemini already made its call"})
                else:
                    db.save_confirmed_lie(latest_round["round_id"], statement)
                    await room_hub.send_to_one(connected_phone, {"type": "lie_confirmed", "statement": statement})

            elif message_type == "vote":
                latest_round = db.get_latest_round_in_room(room_name)
                statement = message.get("statement")
                if latest_round is None or latest_round["result"] is not None:
                    await room_hub.send_to_one(connected_phone, {"type": "error", "detail": "No open round to vote on"})
                elif statement not in [1, 2, 3]:
                    await room_hub.send_to_one(connected_phone, {"type": "error", "detail": "statement must be 1, 2, or 3"})
                else:
                    db.save_vote(latest_round["round_id"], connected_phone.name, statement)
                    await room_hub.send_to_one(connected_phone, {"type": "vote_locked", "statement": statement})
    except WebSocketDisconnect:
        pass
    finally:
        room_hub.remove_connection(room_name, connected_phone)
        await room_hub.send_player_list(room_name)
