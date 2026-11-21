"""WebSocket hub: keeps track of who is connected to each room and sends messages.

Messages are JSON with a "type" field (see the contract in the PRD):
- server -> everyone: phase, suspicion, tell, scoreboard
- phone -> server: join {name, role}, vote {statement}
- server -> player phone only: secret {round_id, lie_index, statement, prompt}
"""

import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ConnectedPhone:
    websocket: WebSocket
    name: str = "anonymous"
    role: str = "voter"  # "eye", "voter", or "player"


@dataclass
class Room:
    connections: list[ConnectedPhone] = field(default_factory=list)
    current_phase: str = "lobby"


class RoomHub:
    def __init__(self):
        self.rooms: dict[str, Room] = {}

    def get_room(self, room_name: str) -> Room:
        if room_name not in self.rooms:
            self.rooms[room_name] = Room()
        return self.rooms[room_name]

    def add_connection(self, room_name: str, websocket: WebSocket) -> ConnectedPhone:
        connected_phone = ConnectedPhone(websocket=websocket)
        self.get_room(room_name).connections.append(connected_phone)
        return connected_phone

    def remove_connection(self, room_name: str, connected_phone: ConnectedPhone) -> None:
        room = self.get_room(room_name)
        if connected_phone in room.connections:
            room.connections.remove(connected_phone)

    async def send_to_one(self, connected_phone: ConnectedPhone, message: dict) -> None:
        try:
            await connected_phone.websocket.send_json(message)
        except Exception as send_error:
            logger.info("Could not send to %s: %s", connected_phone.name, send_error)

    async def send_to_everyone(self, room_name: str, message: dict) -> None:
        if message.get("type") == "phase":
            self.get_room(room_name).current_phase = message["phase"]
        for connected_phone in list(self.get_room(room_name).connections):
            await self.send_to_one(connected_phone, message)

    async def send_to_players(self, room_name: str, message: dict) -> None:
        """Only phones that joined with role "player" get this (used for the secret)."""
        for connected_phone in list(self.get_room(room_name).connections):
            if connected_phone.role == "player":
                await self.send_to_one(connected_phone, message)


room_hub = RoomHub()
