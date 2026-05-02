from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.room_manager import create_room, get_room, delete_room, add_player, add_message, restore_snapshot
from services.ai_engine import process_action
from ws.handler import _broadcast, _build_room_state

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class CreateRoomRequest(BaseModel):
    nickname: str
    character_mode: str = "create"
    world_source: str | None = None
    source_ref: str | None = None


class JoinRequest(BaseModel):
    nickname: str
    player_id: str | None = None  # 重连时传入，避免创建新玩家


class RollbackRequest(BaseModel):
    to_turn: int


@router.post("")
async def api_create_room(req: CreateRoomRequest):
    room = create_room(character_mode=req.character_mode)
    player = add_player(room["code"], req.nickname, is_owner=True)
    return {
        "code": room["code"],
        "player_id": player.id,
        "status": room["status"],
    }


@router.get("/{code}")
async def api_get_room(code: str):
    room = get_room(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    return {
        "code": room["code"],
        "status": room["status"],
        "character_mode": room["character_mode"],
        "turn_number": room["turn_number"],
        "current_player_id": room["current_player_id"],
        "players": [
            {"id": p.id, "nickname": p.nickname, "is_owner": p.is_owner, "is_online": p.is_online}
            for p in room["players"]
        ],
        "characters": [
            {
                "id": c.id, "player_id": c.player_id, "name": c.name,
                "is_preset": c.is_preset, "tags": c.tags,
                "bars": c.bars,
                "attributes": c.attributes, "description": c.description,
                "inventory": c.inventory, "statuses": c.statuses,
            }
            for c in room["characters"]
        ],
        "messages": [
            {"id": m["id"], "player_id": m["player_id"], "type": m["type"],
             "content": m["content"], "metadata": m.get("metadata"),
             "turn_number": m.get("turn_number")}
            for m in room["messages"]
        ],
        "world_module": room["world_module"],
    }


@router.post("/{code}/join")
async def api_join_room(code: str, req: JoinRequest):
    player = add_player(code.upper(), req.nickname, player_id=req.player_id)
    if not player:
        raise HTTPException(status_code=400, detail="无法加入房间（房间不存在/已开始/已满）")
    return {"player_id": player.id, "code": code.upper(), "reconnected": req.player_id is not None and player.id == req.player_id}


def _require_owner(room, player_id: str):
    owner = next((p for p in room["players"] if p.is_owner), None)
    if not owner or owner.id != player_id:
        raise HTTPException(status_code=403, detail="仅房主可执行此操作")


@router.post("/{code}/start")
async def api_start_game(code: str, player_id: str):
    room = get_room(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    _require_owner(room, player_id)
    players = room["players"]
    if len(players) < 1:
        raise HTTPException(status_code=400, detail="至少需要1名玩家")
    if not room["characters"]:
        raise HTTPException(status_code=400, detail="还没有角色")
    if not room.get("world_module"):
        raise HTTPException(status_code=400, detail="还没有生成世界模组")

    room["status"] = "playing"
    room["turn_number"] = 0
    room["current_player_id"] = room["characters"][0].player_id

    # Initial scene narration
    initial_scene = room["world_module"].get("content", {}).get("initial_scene", "冒险开始了...")

    await _broadcast(code.upper(), {
        "type": "game_started",
        "payload": {
            **{k: v for k, v in _build_room_state(room).items() if k != "world_module"},
            "initial_scene": initial_scene,
            "first_player_name": room["characters"][0].name if room["characters"] else "",
        },
    })

    add_message(code.upper(), None, "narrative", initial_scene)
    return {"status": "playing"}


@router.post("/{code}/end")
async def api_end_game(code: str, player_id: str):
    room = get_room(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    _require_owner(room, player_id)
    room["status"] = "ended"

    await _broadcast(code.upper(), {
        "type": "game_ended",
        "payload": {"message": "游戏结束！希望你们玩得开心。"},
    })

    # Clean up
    delete_room(code.upper())
    return {"status": "ended"}


@router.post("/{code}/rollback")
async def api_rollback(code: str, req: RollbackRequest, player_id: str):
    room = get_room(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    _require_owner(room, player_id)
    ok = restore_snapshot(code.upper(), req.to_turn)
    if not ok:
        raise HTTPException(status_code=400, detail="回溯失败，该回合快照不存在")

    await _broadcast(code.upper(), {
        "type": "room_rollback",
        "payload": {"to_turn": req.to_turn},
    })
    return {"status": "rolled_back", "to_turn": req.to_turn}


@router.post("/{code}/report")
async def api_generate_report(code: str):
    room = get_room(code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    # Simple summary: just return key stats
    messages = room["messages"]
    narrative_msgs = [m for m in messages if m["type"] == "narrative"]
    return {
        "total_turns": room["turn_number"],
        "total_messages": len(messages),
        "narrative_count": len(narrative_msgs),
        "players": [p.nickname for p in room["players"]],
        "messages": [{"type": m["type"], "content": m["content"], "turn": m.get("turn_number")}
                      for m in messages],
    }
