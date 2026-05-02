import json
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from services.room_manager import get_room

router = APIRouter(prefix="/api/worlds", tags=["worlds"])

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)

TEMPLATES = {
    "classic_dungeon": {
        "name": "经典地城",
        "overview": "一个古老的地下城中埋藏着失落的宝藏。黑暗的走廊中回荡着未知生物的嘶吼。",
        "factions": ["冒险者公会", "地城守卫者", "暗影教团"],
        "rules": ["D&D 5e 基础规则", "地城中每探索一个新房间需要掷察觉检定"],
        "bar_schema": {
            "HP": {"default": 20, "description": "生命值，归零则昏迷"},
        },
    },
    "cthulhu_investigation": {
        "name": "克苏鲁调查",
        "overview": "1920年代的新英格兰，一系列离奇事件指向某个不可名状的存在。理智是比生命更珍贵的资源。",
        "factions": ["调查员", "密斯卡托尼克大学", "深潜者教派"],
        "rules": ["COC 7e 简化规则", "目睹恐怖事物需掷 SAN CHECK", "SAN 归零则角色陷入疯狂"],
        "bar_schema": {
            "HP": {"default": 12, "description": "生命值"},
            "SAN": {"default": 60, "description": "理智值，归零陷入疯狂"},
        },
    },
    "cyberpunk_bar": {
        "name": "赛博朋克酒吧",
        "overview": "2077年，霓虹灯下的夜之城。一间名为'自由落体'的酒吧里，佣兵、黑客和公司特工在此交汇。",
        "factions": ["街头佣兵", "荒坂公司", "网络黑客", "漩涡帮"],
        "rules": ["赛博朋克简易规则", "黑客行为需掷技术检定", "植入体可提供加成"],
        "bar_schema": {
            "HP": {"default": 20, "description": "生命值"},
            "信用点": {"default": 500, "description": "电子货币，用于购买装备和信息"},
        },
    },
}


class GenerateRequest(BaseModel):
    type: str  # "template", "web_search", "txt_upload"
    ref: str = ""  # template name, search keyword, or filename
    room_code: str = ""


class UploadTxtResponse(BaseModel):
    filename: str
    content_preview: str
    char_count: int


@router.delete("/{room_code}")
async def api_reset_world(room_code: str):
    room = get_room(room_code.upper())
    if not room:
        raise HTTPException(status_code=404, detail="房间不存在")
    room["world_module"] = None
    from ws.handler import _broadcast
    await _broadcast(room_code.upper(), {"type": "world_updated", "payload": {"reset": True}})
    return {"status": "reset"}


@router.post("/generate")
async def api_generate_world(req: GenerateRequest):
    if req.type == "template":
        template = TEMPLATES.get(req.ref)
        if not template:
            available = list(TEMPLATES.keys())
            raise HTTPException(status_code=400, detail=f"模板不存在，可用：{available}")
        initial_scene = await _generate_initial_scene(template)
        world = {
            "source_type": "template",
            "source_ref": req.ref,
            "content": {
                "overview": template["overview"],
                "factions": template["factions"],
                "custom_rules": template["rules"],
                "bar_schema": template.get("bar_schema", {}),
                "initial_scene": initial_scene,
            },
            "preset_characters": [],
        }

    elif req.type == "web_search":
        if not req.ref:
            raise HTTPException(status_code=400, detail="请输入要搜索的作品名")
        world = await _generate_from_search(req.ref)

    elif req.type == "txt_upload":
        raise HTTPException(status_code=400, detail="请先使用 /api/worlds/upload-txt 上传文件")

    else:
        raise HTTPException(status_code=400, detail="type 必须为 template / web_search / txt_upload")

    # Attach to room and notify players
    if req.room_code:
        room = get_room(req.room_code.upper())
        if room:
            room["world_module"] = world
            # Broadcast world update so all clients refresh
            from ws.handler import _broadcast
            await _broadcast(req.room_code.upper(), {
                "type": "world_updated",
                "payload": {"source_ref": world.get("source_ref", ""), "has_presets": len(world.get("preset_characters", [])) > 0},
            })

    return world


async def _generate_initial_scene(template: dict) -> str:
    prompt = f"""为以下世界观写一段 150 字以内的初始场景描述，作为跑团冒险的开场：

世界观：{template['name']}
概述：{template['overview']}
势力：{', '.join(template['factions'])}

直接写叙事文本，不要加标题或前缀。"""
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return f"欢迎来到{template['name']}。{template['overview']}"


async def _generate_from_search(query: str) -> dict:
    prompt = f"""请基于作品《{query}》构建一个跑团世界模组。你需要输出一个 JSON 对象，包含以下字段：

{{
  "overview": "世界概述（200字以内）",
  "factions": ["势力1", "势力2", "势力3"],
  "custom_rules": ["特色规则1", "特色规则2"],
  "bar_schema": {{"HP": {{"default": 20, "description": "生命值"}} }},
  "initial_scene": "初始场景描述（150字以内）",
  "preset_characters": [
    {{"name": "角色名", "description": "简介", "tags": ["标签1", "标签2"], "bars": {{"HP": {{"current": 20, "max": 20}} }}, "attributes": {{}} }}
  ]
}}

bar_schema 定义这个世界使用哪些数值条。战斗团用HP，校园团用"好感度""成绩"，克苏鲁用HP+SAN。根据作品风格选择合适的数值条。

请确保输出是合法的 JSON，不要加额外说明文字。"""

    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    content = json.loads(resp.choices[0].message.content)
    return {
        "source_type": "web_search",
        "source_ref": query,
        "content": content,
        "preset_characters": content.get("preset_characters", []),
    }


@router.post("/upload-txt")
async def api_upload_txt(file: UploadFile = File(...)):
    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="仅支持 TXT 文件")
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    if len(text) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 2MB")

    # Truncate to first 50K chars for analysis
    analysis_text = text[:50000]

    prompt = f"""请分析以下小说片段，构建一个跑团世界模组。输出 JSON：

{{
  "overview": "世界概述（200字以内）",
  "factions": ["势力1", "势力2"],
  "custom_rules": ["特色规则1"],
  "bar_schema": {{"HP": {{"default": 20, "description": "生命值"}} }},
  "initial_scene": "初始场景描述（150字以内）",
  "preset_characters": [
    {{"name": "角色名", "description": "简介", "tags": ["标签"], "bars": {{"HP": {{"current": 20, "max": 20}} }}, "attributes": {{}} }}
  ]
}}

bar_schema 根据小说风格定义合适的数值条。

小说片段：
{analysis_text}

请确保输出是合法的 JSON。"""

    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    world_content = json.loads(resp.choices[0].message.content)

    return {
        "filename": file.filename,
        "content_preview": text[:200] + "..." if len(text) > 200 else text,
        "char_count": len(text),
        "world": {
            "source_type": "txt_upload",
            "source_ref": file.filename,
            "content": world_content,
            "preset_characters": world_content.get("preset_characters", []),
        },
    }
