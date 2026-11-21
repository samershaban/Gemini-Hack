"""WebSocket hub: keeps track of who is connected to each room and sends messages.

Messages are JSON with a "type" field (see the contract in the PRD):
- server -> everyone: phase, suspicion, tell, scoreboard
- phone -> server: join {name, role}, vote {statement}
- server -> everyone: roster {players: [{name, role}]} whenever someone joins or leaves,
  and to each new connection right away (so the stage gets the current list)
"""

import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ConnectedPhone:
    websocket: WebSocket
    name: str = "anonymous"
    role: str = "voter"  # phones only vote; the player is on stage
    has_joined: bool = False  # True after the phone sends its join message (the stage never does)


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

    def make_name_unique(self, room_name: str, wanted_name: str, connected_phone: "ConnectedPhone") -> str:
        """Votes are saved by name, so two phones named "Sam" become "Sam" and "Sam 2"."""
        taken_names = {
            other_phone.name for other_phone in self.get_room(room_name).connections
            if other_phone is not connected_phone and other_phone.has_joined
        }
        unique_name = wanted_name
        number = 2
        while unique_name in taken_names:
            unique_name = f"{wanted_name} {number}"
            number += 1
        return unique_name

    def build_roster_message(self, room_name: str) -> dict:
        """Everyone who has joined (sent a join message), for the stage's player list."""
        joined_phones = [
            {"name": connected_phone.name, "role": connected_phone.role}
            for connected_phone in self.get_room(room_name).connections
            if connected_phone.has_joined
        ]
        return {"type": "roster", "players": joined_phones}

    async def send_player_list(self, room_name: str) -> None:
        await self.send_to_everyone(room_name, self.build_roster_message(room_name))


room_hub = RoomHub()
