import json
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from services.room_manager import get_room

router = APIRouter(prefix="/api/worlds", tags=["worlds"])

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)

TEMPLATES = {
    "isekai_adventure": {
        "name": "异世界冒险",
        "overview": "你被召唤到了剑与魔法的异世界。王国正面临魔王军的威胁，冒险者公会在各地招募勇者。魔法、龙与古老的遗迹等待探索。",
        "factions": ["冒险者公会", "魔王军", "王国骑士团", "精灵聯邦"],
        "rules": ["经典奇幻规则", "咏唱魔法需消耗魔力", "击败敌人可获得经验成长"],
        "bar_schema": {
            "HP": {"default": 20, "description": "生命值"},
            "MP": {"default": 30, "description": "魔力值，用于释放魔法"},
        },
        "storyline": {"title": "击败魔王", "stages": ["??", "??", "??", "??"]},
    },
    "japanese_high_school": {
        "name": "日式校园高中",
        "overview": "樱花飘落的四月，县立橘花高中的新学期开始了。这里没有剑与魔法，只有青春、恋爱、友情和数不清的社团活动。你的选择将改变与你有关的一切。",
        "factions": ["学生会", "运动社团", "文艺部", "归宅部"],
        "rules": ["好感度系统：与角色互动影响关系", "社团活动每两周有特殊事件", "考试季有学业压力事件", "放学后的自由时间可自由行动"],
        "bar_schema": {
            "好感度": {"default": 0, "description": "与重要角色的好感度，影响关系发展"},
            "成绩": {"default": 50, "description": "学业成绩，低于30会被强制补习"},
            "体力": {"default": 100, "description": "精力值，社团活动和打工消耗体力"},
        },
        "storyline": {"title": "学园祭的约定", "stages": ["??", "??", "??"]},
    },
    "rainbow_six": {
        "name": "彩虹六号",
        "overview": "这里是彩虹小队，全球最精锐的反恐部队。每一次任务都可能是最后一次——情报是关键，团队配合是生命，一个错误的决定将导致不可挽回的后果。准备好了吗，干员？",
        "factions": ["彩虹小队", "白面具恐怖组织", "当地警方", "情报局"],
        "rules": ["战术射击规则：战斗高度致命", "情报收集影响任务难度", "队友状态影响团队行动", "每次任务前可规划战术"],
        "bar_schema": {
            "HP": {"default": 100, "description": "生命值，归零则重伤倒地"},
            "弹药": {"default": 120, "description": "弹药储备，耗尽无法射击"},
            "情报值": {"default": 0, "description": "任务情报完整度，越高越容易发现陷阱"},
        },
        "storyline": {"title": "化解危机", "stages": ["??", "??", "??", "??"]},
    },
    "animal_world": {
        "name": "动物世界",
        "overview": "非洲大草原上，万物遵循着古老的自然法则。狮群统治着领地，鬣狗在暗处窥伺，象群穿越干涸的河床。生存、家族、荣耀——这就是动物的世界。",
        "factions": ["狮群", "鬣狗群", "象群", "人类猎人"],
        "rules": ["动物本能规则：每个物种有独特能力", "领地争夺战影响生存资源", "季节更替影响食物和水源", "幼崽的成长是族群的未来"],
        "bar_schema": {
            "HP": {"default": 20, "description": "生命值"},
            "食物储备": {"default": 30, "description": "族群的食物存量，耗尽会饥饿"},
            "声望": {"default": 10, "description": "在草原上的威望，影响其他动物的态度"},
        },
        "storyline": {"title": "草原之王", "stages": ["??", "??", "??"]},
    },
    "nailong_vs_laoda": {
        "name": "奶龙大战劳大",
        "overview": "在奶龙大陆上，正义的奶龙军团与邪恶的劳大势力展开了终极对决。奶龙们喷吐棉花糖火焰，劳大手下的薯条兵挥舞着番茄酱利剑。这是一场关乎零食自由与沙发主权的史诗战争！",
        "factions": ["奶龙军团", "劳大帝国", "薯条雇佣兵", "中立甜品店"],
        "rules": ["搞笑战斗规则：创意越大伤害越高", "奶龙喷火消耗棉花糖能量", "劳大的可乐炸弹可以摧毁奶龙堡垒", "中立甜品店可以补充体力但价格很坑"],
        "bar_schema": {
            "HP": {"default": 25, "description": "生命值"},
            "棉花糖能量": {"default": 50, "description": "奶龙喷火消耗的能量"},
            "搞笑值": {"default": 0, "description": "搞笑创意分，越高伤害越大"},
        },
        "storyline": {"title": "零食自由之战", "stages": ["??", "??", "??"]},
    },
    "gambler_king": {
        "name": "赌王争霸",
        "overview": "澳门金光大道，霓虹不夜城。世界扑克大赛即将开幕，全球顶尖赌徒云集于此。牌桌之上，筹码如山，一个眼神、一次加注，就可能改变命运。这里赌的不只是钱，更是胆识、心理与运气。",
        "factions": ["职业赌徒联盟", "赌场寡头", "出千团伙", "国际刑警"],
        "rules": ["牌技对抗：关键赌局需要掷牌技判定", "心理博弈：察言观色和虚张声势可以扭转局势", "筹码即生命：输光筹码则出局", "出千有风险：被抓住直接淘汰"],
        "bar_schema": {
            "筹码": {"default": 1000, "description": "赌局筹码，输光则出局"},
            "声望": {"default": 0, "description": "赌坛地位，影响对手心理"},
            "心理值": {"default": 50, "description": "心态稳定度，低于20容易冲动下注"},
        },
        "storyline": {"title": "赌王争霸赛", "stages": ["??", "??", "??", "??"]},
    },
}


class GenerateRequest(BaseModel):
    type: str  # "template", "web_search", "txt_upload"
    ref: str = ""
    room_code: str = ""
    style: str = ""
    tone: str = ""
    custom_style: str = ""


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
        initial_scene = await _generate_initial_scene(template, req.style, req.tone, req.custom_style)
        player_count = 2
        if req.room_code:
            room = get_room(req.room_code.upper())
            if room:
                player_count = max(2, len(room["players"]))
        presets = await _generate_presets_for_template(template, initial_scene, player_count, req.style, req.tone, req.custom_style)
        world = {
            "source_type": "template",
            "source_ref": req.ref,
            "content": {
                "overview": template["overview"],
                "factions": template["factions"],
                "custom_rules": template["rules"],
                "bar_schema": template.get("bar_schema", {}),
                "storyline": template.get("storyline", {"title": "冒险", "stages": ["??", "??"]}),
                "initial_scene": initial_scene,
                "style": req.style,
                "tone": req.tone,
                "custom_style": req.custom_style,
            },
            "preset_characters": presets,
        }

    elif req.type == "web_search":
        if not req.ref:
            raise HTTPException(status_code=400, detail="请输入要搜索的作品名")
        world = await _generate_from_search(req.ref, req.style, req.tone, req.custom_style)

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


async def _generate_presets_for_template(template: dict, scene: str, player_count: int = 2, style: str = "", tone: str = "", custom_style: str = "") -> list:
    """Generate preset characters scaled to room size."""
    count = max(3, min(player_count + 2, 6))
    bar_schema = template.get("bar_schema", {"HP": {"default": 20, "description": "生命值"}})
    bar_info = ", ".join([f"{k}({v['description']})" for k, v in bar_schema.items()])

    style_note = ""
    if style: style_note += f" 角色描述必须使用{style}风格。"
    if tone: style_note += f" 主线紧密度：{tone}。"
    if custom_style: style_note += f" 额外：{custom_style}。"

    prompt = f"""世界观：{template['name']} — {template['overview']}
势力：{', '.join(template.get('factions', []))}
可用数值条：{bar_info}
{style_note}
初始场景：{scene}

为这个世界观生成恰好 {count} 个预设角色卡，输出 JSON 数组。角色要来自不同势力、性格互补、能力各异。格式：
[
  {{"name": "角色名", "bars": {{"HP": {{"current": 20, "max": 20}} }}, "tags": ["标签"], "attributes": {{}}, "inventory": ["物品"], "description": "角色简介"}}
]
输出合法 JSON。"""
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9, max_tokens=1536,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        chars = data if isinstance(data, list) else data.get("characters", data.get("preset_characters", []))
        return chars if isinstance(chars, list) else []
    except Exception:
        return []


async def _generate_initial_scene(template: dict, style: str = "", tone: str = "", custom_style: str = "") -> str:
    style_note = ""
    if style: style_note += f" 文风：必须使用{style}风格。"
    if tone: style_note += f" 主线：{tone}。"
    if custom_style: style_note += f" {custom_style}。"

    prompt = f"""为以下世界观写一段 150 字以内的初始场景描述，作为跑团冒险的开场：
{style_note}
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
        scene = (resp.choices[0].message.content or "").strip()
        return scene or f"欢迎来到{template['name']}。{template['overview']}"
    except Exception:
        return f"欢迎来到{template['name']}。{template['overview']}"


async def _generate_from_search(query: str, style: str = "", tone: str = "", custom_style: str = "") -> dict:
    style_note = ""
    if style: style_note += f" 文风：所有叙事文本必须严格使用{style}风格写作。这不是建议，是强制要求。如果{style}是诗歌体，就用诗歌写；如果是喷子体，就用粗俗吐槽写。"
    if tone:
        tightness = {"strict": "请严格围绕主线展开剧情。", "free": "请放任玩家自由探索世界，不必急于推进主线。"}.get(tone, "")
        style_note += f" 主线紧密度：{tightness}"
    if custom_style: style_note += f" 额外要求：{custom_style}。"
    if style_note: style_note = f"\n创作要求：{style_note}\n"

    prompt = f"""请基于作品《{query}》构建一个跑团世界模组。{style_note}你需要输出一个 JSON 对象，包含以下字段：

{{
  "overview": "世界概述（200字以内）",
  "factions": ["势力1", "势力2", "势力3"],
  "custom_rules": ["特色规则1", "特色规则2"],
  "bar_schema": {{"HP": {{"default": 20, "description": "生命值"}} }},
  "storyline": {{"title": "主线任务名", "stages": ["??", "??", "??"]}},
  "initial_scene": "初始场景描述（150字以内）",
  "preset_characters": [
    {{"name": "角色名", "description": "简介", "tags": ["标签1", "标签2"], "bars": {{"HP": {{"current": 20, "max": 20}} }}, "attributes": {{}} }}
  ]
}}

bar_schema 根据作品风格选择数值条。storyline 设计3-4个剧情阶段，所有阶段初始为"??"。

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
