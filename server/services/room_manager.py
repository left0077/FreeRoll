from __future__ import annotations

import uuid
import random
import string
from datetime import datetime, timezone
from dataclasses import dataclass, field

ROOMS: dict[str, dict] = {}  # {code: room_dict}


def generate_code() -> str:
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in ROOMS:
            return code


@dataclass
class Player:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nickname: str = ""
    is_owner: bool = False
    is_online: bool = True
    joined_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Character:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    player_id: str = ""
    name: str = ""
    is_preset: bool = False
    attributes: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    bars: dict = field(default_factory=lambda: {"HP": {"current": 20, "max": 20}})
    inventory: list = field(default_factory=list)
    statuses: list = field(default_factory=list)
    description: str = ""


def create_room(character_mode: str = "create") -> dict:
    code = generate_code()
    room = {
        "code": code,
        "status": "waiting",
        "character_mode": character_mode,
        "world_module": None,
        "players": [],
        "characters": [],
        "messages": [],
        "dice_logs": [],
        "turn_number": 0,
        "current_player_id": None,
        "snapshots": {},  # {turn_number: [character_states]}
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    ROOMS[code] = room
    return room


def get_room(code: str) -> dict | None:
    return ROOMS.get(code)


def delete_room(code: str):
    ROOMS.pop(code, None)


def find_player(code: str, player_id: str) -> Player | None:
    room = get_room(code)
    if not room:
        return None
    for p in room["players"]:
        if p.id == player_id:
            return p
    return None


def add_player(code: str, nickname: str, is_owner: bool = False, player_id: str | None = None) -> Player | None:
    room = get_room(code)
    if not room or room["status"] != "waiting":
        return None

    # Reconnect: same player_id returning
    if player_id:
        existing = find_player(code, player_id)
        if existing:
            existing.is_online = True
            existing.nickname = nickname  # allow name change
            return existing

    if len(room["players"]) >= 12:
        return None
    player = Player(nickname=nickname, is_owner=is_owner)
    if player_id:
        player.id = player_id
    room["players"].append(player)
    return player


def remove_player(code: str, player_id: str):
    room = get_room(code)
    if not room:
        return
    room["players"] = [p for p in room["players"] if p.id != player_id]
    room["characters"] = [c for c in room["characters"] if c.player_id != player_id]


def add_character(code: str, character: Character) -> Character:
    room = get_room(code)
    room["characters"].append(character)
    return character


def get_character(code: str, character_id: str) -> Character | None:
    room = get_room(code)
    for c in room["characters"]:
        if c.id == character_id:
            return c
    return None


def add_message(code: str, player_id: str | None, msg_type: str, content: str, metadata: dict = None) -> dict:
    room = get_room(code)
    msg = {
        "id": str(uuid.uuid4()),
        "player_id": player_id,
        "type": msg_type,
        "content": content,
        "metadata": metadata or {},
        "turn_number": room["turn_number"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    room["messages"].append(msg)
    return msg


def add_dice_log(code: str, character_id: str, expression: str, result: int,
                 detail: dict, dc: int = None, success: bool = None,
                 is_critical: bool = False) -> dict:
    room = get_room(code)
    log = {
        "id": str(uuid.uuid4()),
        "character_id": character_id,
        "expression": expression,
        "result": result,
        "detail": detail,
        "dc": dc,
        "success": success,
        "is_critical": is_critical,
        "turn_number": room["turn_number"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    room["dice_logs"].append(log)
    return log


def save_snapshot(code: str):
    """Save character states at the start of current turn for rollback."""
    room = get_room(code)
    turn = room["turn_number"]
    snap = {}
    for c in room["characters"]:
        snap[c.id] = {
            "bars": {k: dict(v) for k, v in c.bars.items()},
            "inventory": list(c.inventory),
            "statuses": list(c.statuses),
        }
    # Also snapshot storyline and discoveries
    wm = room.get("world_module")
    if wm and wm.get("content", {}).get("storyline"):
        snap["__storyline"] = list(wm["content"]["storyline"]["stages"])
    snap["__discoveries"] = list(room.get("discoveries", []))
    room["snapshots"][str(turn)] = snap


def restore_snapshot(code: str, to_turn: int):
    """Rollback to a previous turn's character states."""
    room = get_room(code)
    snap = room["snapshots"].get(str(to_turn))
    if not snap:
        return False
    for c in room["characters"]:
        if c.id in snap:
            s = snap[c.id]
            c.bars = {k: dict(v) for k, v in s["bars"].items()}
            c.inventory = list(s["inventory"])
            c.statuses = list(s["statuses"])
    # Restore storyline and discoveries
    if "__storyline" in snap:
        wm = room.get("world_module")
        if wm and wm.get("content", {}).get("storyline"):
            wm["content"]["storyline"]["stages"] = snap["__storyline"]
    if "__discoveries" in snap:
        room["discoveries"] = snap["__discoveries"]
    # Clear any in-flight flags
    room.pop("_processing", None)
    room.pop("_pending_roll", None)
    # Delete messages and dice logs after target turn
    room["messages"] = [m for m in room["messages"] if m["turn_number"] < to_turn]
    room["dice_logs"] = [d for d in room["dice_logs"] if d["turn_number"] < to_turn]
    # Clean up snapshots after target turn
    room["snapshots"] = {k: v for k, v in room["snapshots"].items() if int(k) < to_turn}
    room["turn_number"] = to_turn
    return True
