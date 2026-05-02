from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from services.room_manager import get_room, add_character, get_character, Character

router = APIRouter(prefix="/api/characters", tags=["characters"])

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)


class GenerateRequest(BaseModel):
    room_code: str
    player_id: str
    description: str  # Natural language description


class ClaimRequest(BaseModel):
    room_code: str
    player_id: str
    preset_index: int  # Index in preset_characters list


class EditRequest(BaseModel):
    name: str | None = None
    bars: dict | None = None
    attributes: dict | None = None
    tags: list | None = None
    inventory: list | None = None
    statuses: list | None = None
    description: str | None = None


@router.post("/generate")
async def api_generate_character(req: GenerateRequest):
    room = get_room(req.room_code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")

    # Get world context and existing names
    world_context = ""
    bar_info = ""
    if room.get("world_module"):
        wm = room["world_module"]
        c = wm.get("content", wm)
        world_context = f"世界观：{c.get('overview', '')}"
        if c.get("bar_schema"):
            bar_info = f"这个世界的数值条定义：{json.dumps(c['bar_schema'], ensure_ascii=False)}"
        if c.get("factions"):
            world_context += f"\n势力：{json.dumps(c['factions'], ensure_ascii=False)}"

    # Existing character names to avoid duplicates
    existing_names = [char.name for char in room["characters"]]
    name_constraint = ""
    if existing_names:
        name_constraint = f"\n已有角色名：{existing_names}。你的角色名必须与这些不同。"

    prompt = f"""{world_context}
{bar_info}
{name_constraint}

玩家描述："{req.description}"

请根据玩家描述和世界观设定生成角色卡。角色必须符合这个世界——如果是奇幻世界观，不要出现科幻元素；如果是现代校园，不要出现魔法。

输出 JSON：
{{
  "name": "一个符合世界观的独特角色名（不要与已有角色名重复）",
  "bars": {{"HP": {{"current": 20, "max": 20}} }},
  "attributes": {{}},
  "tags": ["标签1", "标签2", "标签3"],
  "inventory": ["符合世界观的初始物品"],
  "description": "角色背景简介（50字），说明ta为何出现在这个世界"
}}

注意：
- 角色名必须是新的，不能与已有角色重名
- bars 根据 bar_schema 使用正确的数值条和默认值
- 角色背景要与世界观一致
- 输出合法 JSON，不要加额外文字。"""

    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )

    char_data = json.loads(resp.choices[0].message.content)
    char_name = char_data.get("name", "未命名")

    # Check for duplicate name - retry once if needed
    existing_names = [c.name for c in room["characters"]]
    if char_name in existing_names:
        retry_prompt = f"""你刚才生成的角色名"{char_name}"与已有角色重名。请换一个不同的名字，其他保持不变。输出 JSON。"""
        resp2 = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": resp.choices[0].message.content},
                {"role": "user", "content": retry_prompt},
            ],
            temperature=1.0,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        char_data = json.loads(resp2.choices[0].message.content)
        char_name = char_data.get("name", char_name + "_2")

    bars = char_data.get("bars", {"HP": {"current": 20, "max": 20}})

    character = Character(
        player_id=req.player_id,
        name=char_data.get("name", "未命名"),
        attributes=char_data.get("attributes", {}),
        tags=char_data.get("tags", []),
        bars=bars,
        inventory=char_data.get("inventory", []),
        description=char_data.get("description", ""),
    )
    add_character(req.room_code.upper(), character)
    from ws.handler import _broadcast as _bc1
    await _bc1(req.room_code.upper(), {"type": "character_updated"})

    return {
        "id": character.id,
        "player_id": character.player_id,
        "name": character.name,
        "attributes": character.attributes,
        "tags": character.tags,
        "bars": character.bars,
        "inventory": character.inventory,
        "statuses": character.statuses,
        "description": character.description,
    }


@router.post("/claim")
async def api_claim_preset(req: ClaimRequest):
    room = get_room(req.room_code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")

    wm = room.get("world_module")
    if not wm:
        raise HTTPException(status_code=400, detail="世界模组尚未生成")

    presets = wm.get("preset_characters", [])
    if req.preset_index >= len(presets):
        raise HTTPException(status_code=400, detail="预设角色不存在")

    preset = presets[req.preset_index]
    bars = preset.get("bars", {"HP": {"current": 20, "max": 20}})
    character = Character(
        player_id=req.player_id,
        name=preset.get("name", "未命名"),
        is_preset=True,
        attributes=preset.get("attributes", {}),
        tags=preset.get("tags", []),
        bars=bars,
        inventory=preset.get("inventory", []),
        description=preset.get("description", ""),
    )
    add_character(req.room_code.upper(), character)
    from ws.handler import _broadcast as _bc2
    await _bc2(req.room_code.upper(), {"type": "character_updated"})

    return {
        "id": character.id,
        "player_id": character.player_id,
        "name": character.name,
        "is_preset": True,
        "attributes": character.attributes,
        "tags": character.tags,
        "bars": character.bars,
        "inventory": character.inventory,
        "description": character.description,
    }


@router.delete("/{character_id}")
async def api_delete_character(character_id: str, room_code: str):
    room = get_room(room_code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    room["characters"] = [c for c in room["characters"] if c.id != character_id]
    from ws.handler import _broadcast as _bc3
    await _bc3(room_code.upper(), {"type": "character_updated"})
    return {"status": "deleted"}


@router.get("/{character_id}")
async def api_get_character(character_id: str, room_code: str):
    character = get_character(room_code.upper(), character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return {
        "id": character.id,
        "player_id": character.player_id,
        "name": character.name,
        "is_preset": character.is_preset,
        "attributes": character.attributes,
        "tags": character.tags,
        "bars": character.bars,
        "inventory": character.inventory,
        "statuses": character.statuses,
        "description": character.description,
    }


@router.put("/{character_id}")
async def api_edit_character(character_id: str, room_code: str, req: EditRequest):
    character = get_character(room_code.upper(), character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    if req.name is not None:
        character.name = req.name
    if req.bars is not None:
        character.bars = req.bars
    if req.attributes is not None:
        character.attributes = req.attributes
    if req.tags is not None:
        character.tags = req.tags
    if req.inventory is not None:
        character.inventory = req.inventory
    if req.statuses is not None:
        character.statuses = req.statuses
    if req.description is not None:
        character.description = req.description

    return {"status": "ok"}
