from __future__ import annotations

import re
import json
from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)

ROLL_DICE_TOOL = {
    "type": "function",
    "function": {
        "name": "roll_dice",
        "description": "当需要判定玩家行动结果时掷骰。rule-of-cool 原则下，有意义的行动才掷骰。",
        "parameters": {
            "type": "object",
            "properties": {
                "dice": {"type": "string", "description": "骰子表达式，如 d20, 2d6+3, d100"},
                "reason": {"type": "string", "description": "掷骰原因"},
                "difficulty": {"type": "integer", "description": "DC 难度等级，可选"},
                "character_name": {"type": "string", "description": "行动角色名"},
            },
            "required": ["dice", "reason", "character_name"],
        },
    },
}

UPDATE_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_state",
        "description": "当行动导致角色数值变化时调用。可修改任意数值条、增删物品/状态，甚至创建临时数值条。",
        "parameters": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string"},
                "bar_delta": {
                    "type": "object",
                    "description": "数值条变化，key是条名，value是变化量。如 {\"HP\": -3, \"SAN\": -5, \"好感度\": 10}",
                    "additionalProperties": {"type": "integer"},
                },
                "add_item": {"type": "string", "description": "获得物品"},
                "remove_item": {"type": "string", "description": "失去物品"},
                "add_status": {"type": "string", "description": "新增状态"},
                "remove_status": {"type": "string", "description": "移除状态"},
                "add_bar": {
                    "type": "object",
                    "description": "创建临时数值条，如倒计时。含current和max",
                    "properties": {
                        "name": {"type": "string"},
                        "current": {"type": "integer"},
                        "max": {"type": "integer"},
                    },
                },
                "remove_bar": {"type": "string", "description": "移除临时数值条（条名）"},
                "narrative": {"type": "string", "description": "状态变化的叙事描述"},
            },
            "required": ["character_name", "narrative"],
        },
    },
}

SYSTEM_PROMPT = """你是一个文字跑团的主持人（GM）。你的职责：

## 叙事原则
- 用生动的文字描述场景、NPC 和事件，让所有玩家沉浸在故事中
- 使用 rule-of-cool 原则：有趣 > 严格规则，鼓励玩家创造性行动
- 描述简洁有力，每次叙事控制在 2-4 段，不要写小说
- 不要在描述中替玩家做决定，不要假设玩家的反应
- **必须使用角色名而非"你""我"等代词**。例如"艾林举起火把，火光映亮了石壁上的符文"而非"你举起火把"。这是多人游戏，所有玩家都能看到叙事，"你"会让其他人困惑

## 裁决原则
- 当玩家尝试有风险/不确定的行动时，调用 roll_dice 进行判定
- 当玩家在描述中明确表达想掷骰、碰运气、赌一把、试试看等意图时，必须调用 roll_dice
- 当行动导致角色状态变化时，调用 update_state
- 不同世界观有不同的数值条（bars），不是只有HP。可能是 SAN、好感度、信用点等
- 可根据剧情需要创建临时数值条（add_bar），如"倒计时：3回合"、"考试压力：50/100"
- 临时数值条用完后记得 remove_bar 清理
- 普通对话、观察、移动等无风险行动不需要掷骰

## 回合管理
- 每次叙事末尾，根据故事走向指定下一个应该行动的玩家
- 格式：[NEXT:角色名]
- 让每个玩家都有参与机会，不要让一个人连续行动超过 2 回合

## 行动建议（最重要规则，每次叙事必须输出）
- 每次叙事末尾，你必须输出 [ACTIONS:...] 标记，为下一个行动的玩家提供 3 个贴合当前场景的具体建议
- 如果不输出这个标记，玩家将看不到任何行动提示，游戏无法继续！
- 格式：[ACTIONS:具体行动1|具体行动2|具体行动3]
- 行动建议必须基于你刚描述的叙事内容中的具体细节
  - 你刚描述了血迹→建议中应包含"检查血迹"
  - 你刚描述了NPC出现→建议中应包含"与NPC对话"
  - 你刚描述了奇怪的声音→建议中应包含"调查声音来源"
- 错误示范（太泛）："我检查房间"、"我搜索物品"、"我观察四周"
- 正确示范："蹲下用手指触碰地上的暗红色液体确认是否是血迹"、"朝声音传来的东北方向走廊轻声喊话试探"

## 世界书记录
- 当玩家发现重要的NPC、地点、物品或线索时，在叙事末尾用标记记录下来
- 格式：[NOTE:分类:内容]。分类：npc(人物)、location(地点)、clue(线索)、event(事件)
- 例如：[NOTE:npc:神秘的精灵商人艾隆，在废弃矿坑入口摆摊][NOTE:clue:矿坑深处传来有规律的敲击声]
- 只记录玩家新发现的事物，不要重复已有信息

## 剧情主线
- 游戏有主线剧情（storyline），分多个阶段。当玩家完成一个阶段时，推进主线
- 如果玩家发现了新的重要情报或剧情转折，可以更新后续阶段的内容
- 推进主线格式：[PLOT:阶段编号:阶段名称]。例如 [PLOT:1:发现暗门入口] 表示第1阶段完成，名称更新为"发现暗门入口"
- 阶段编号从0开始。先完成阶段0才能推进到阶段1
- 如果剧情发生重大转折，可以修改后续阶段名称：[PLOT:2:??] 表示将第2阶段重置为未知

## 游戏结束
- 当剧情自然收尾（任务完成、谜题解开、Boss击败等），输出 [ENDING:简短理由]
- 不要在剧情中途随意建议结束

## 玩家间对话
- 玩家可以用 (OOC) 标记进行场外对话，这些消息不需要你回应
"""


def build_messages(room: dict, player_input: str, player_character_name: str) -> list:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # World module
    wm = room.get("world_module")
    if wm:
        world_text = _format_world_module(wm)
        messages.append({"role": "system", "content": world_text})

    # Character roster
    chars_text = _format_characters(room["characters"])
    messages.append({"role": "system", "content": chars_text})

    # Full chat history
    for msg in room["messages"]:
        role = _msg_role(msg)
        content = msg["content"]
        if role:
            messages.append({"role": role, "content": content})

    # Current player input
    messages.append({"role": "user", "content": f"[{player_character_name}]: {player_input}"})

    return messages


def _format_world_module(wm: dict) -> str:
    c = wm.get("content", wm)
    parts = [f"## 世界观：{c.get('overview', '')}"]
    if c.get("factions"):
        parts.append(f"## 势力/种族：{json.dumps(c['factions'], ensure_ascii=False)}")
    if c.get("custom_rules"):
        parts.append(f"## 特色规则：{json.dumps(c['custom_rules'], ensure_ascii=False)}")
    if c.get("initial_scene"):
        parts.append(f"## 初始场景：{c['initial_scene']}")
    return "\n\n".join(parts)


def _format_characters(characters: list) -> str:
    lines = ["## 当前角色："]
    for c in characters:
        bar_strs = []
        for name, bar in c.bars.items():
            bar_strs.append(f"{name} {bar['current']}/{bar['max']}")
        tags_str = '/'.join(c.tags) if c.tags else '冒险者'
        lines.append(f"- {c.name}（{tags_str}）：{', '.join(bar_strs) if bar_strs else '无特殊数值'}")
    return "\n".join(lines)


def _msg_role(msg: dict) -> str | None:
    if msg["type"] in ("action", "ooc"):
        return "user"
    if msg["type"] in ("narrative", "dice", "system"):
        return "assistant"
    return None


async def process_action(room: dict, player_input: str, character_name: str,
                        on_chunk=None) -> dict:
    """Process a player action. If on_chunk is provided, streams text chunks."""
    messages = build_messages(room, player_input, character_name)

    result = {
        "narrative": "",
        "dice_result": None,
        "state_changes": [],
        "next_player": None,
        "ending_suggested": None,
        "tool_calls_made": [],
    }

    # First call always normal (may have tool calls, needs reasoning_content)
    extra_fields = {}
    narrative, tool_calls_data, extra_fields = await _normal_call(messages)

    # Process tool calls from first response
    tool_results = []
    if tool_calls_data:
        for tc in tool_calls_data:
            if tc["name"] == "roll_dice":
                # Defer roll — handler will ask player to roll, then resume
                result["pending_roll"] = tc
                result["tool_calls_made"].append("roll_dice")
            elif tc["name"] == "update_state":
                result["state_changes"].append(tc["args"])
                result["tool_calls_made"].append("update_state")
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": "状态已更新",
                })

        # Second call to get final narrative (streaming if callback)
        if tool_results:
            assistant_msg = {
                "role": "assistant",
                "content": narrative or "",
                "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)}}
                    for tc in tool_calls_data
                ],
            }
            # Preserve reasoning_content for DeepSeek thinking mode
            if extra_fields.get("reasoning_content"):
                assistant_msg["reasoning_content"] = extra_fields["reasoning_content"]
            messages.append(assistant_msg)
            messages.extend(tool_results)
            try:
                if on_chunk:
                    narrative2, _ = await _stream_call(messages, on_chunk)
                else:
                    narrative2, _, _ = await _normal_call(messages)
            except Exception:
                import traceback; traceback.print_exc()
                narrative2, _, _ = await _normal_call(messages)
            narrative = (narrative or "") + (narrative2 or "")

    # Parse markers
    next_match = re.search(r'\[NEXT:(.+?)\]', narrative or "")
    if next_match:
        result["next_player"] = next_match.group(1).strip()
        narrative = re.sub(r'\[NEXT:.+?\]', '', narrative or "").strip()

    ending_match = re.search(r'\[ENDING:(.+?)\]', narrative or "")
    if ending_match:
        result["ending_suggested"] = ending_match.group(1).strip()
        narrative = re.sub(r'\[ENDING:.+?\]', '', narrative or "").strip()

    # Parse action suggestions
    actions_match = re.search(r'\[ACTIONS:(.+?)\]', narrative or "")
    if actions_match:
        result["suggested_actions"] = [a.strip() for a in actions_match.group(1).split("|") if a.strip()]
        narrative = re.sub(r'\[ACTIONS:.+?\]', '', narrative or "").strip()

    # Parse plot progression
    plot_match = re.search(r'\[PLOT:(\d+):(.+?)\]', narrative or "")
    if plot_match:
        result["plot_update"] = {"stage": int(plot_match.group(1)), "name": plot_match.group(2).strip()}
        narrative = re.sub(r'\[PLOT:\d+:.+?\]', '', narrative or "").strip()

    # Parse world book notes
    notes = re.findall(r'\[NOTE:(\w+):(.+?)\]', narrative or "")
    if notes:
        result["world_notes"] = [{"category": c, "content": t.strip()} for c, t in notes]
        narrative = re.sub(r'\[NOTE:\w+:.+?\]', '', narrative or "").strip()

    # Store state for potential resume
    result["_messages"] = messages
    result["_tool_calls_data"] = tool_calls_data
    result["_tool_results"] = tool_results
    result["_extra"] = extra_fields
    result["_partial_narrative"] = narrative

    result["narrative"] = (narrative or "").strip()
    return result


def execute_pending_roll(prev_result: dict, dice_args: dict) -> dict:
    """Execute the dice roll immediately. Returns dice_result dict."""
    tool_calls_data = prev_result["_tool_calls_data"]
    for tc in tool_calls_data:
        if tc["name"] == "roll_dice":
            return _execute_dice(dice_args or tc["args"])
    return None


async def resume_with_roll(prev_result: dict, dice_args: dict, on_chunk=None) -> dict:
    """Resume AI after roll executed. Gets final narrative from AI."""
    messages = prev_result["_messages"]
    tool_calls_data = prev_result["_tool_calls_data"]
    tool_results = list(prev_result["_tool_results"])
    extra_fields = prev_result["_extra"]
    narrative = prev_result["_partial_narrative"] or ""

    # Build tool result for the already-executed roll
    for tc in tool_calls_data:
        if tc["name"] == "roll_dice":
            dr = _execute_dice(dice_args or tc["args"])
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps({"total": dr["total"], "rolls": dr["rolls"], "bonus": dr["bonus"]}, ensure_ascii=False),
            })
            break

    # Build assistant message with all tool calls
    assistant_msg = {
        "role": "assistant",
        "content": narrative,
        "tool_calls": [
            {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)}}
            for tc in tool_calls_data
        ],
    }
    if extra_fields.get("reasoning_content"):
        assistant_msg["reasoning_content"] = extra_fields["reasoning_content"]
    messages.append(assistant_msg)
    messages.extend(tool_results)

    # Final call to AI
    try:
        if on_chunk:
            narrative2, _ = await _stream_call(messages, on_chunk)
        else:
            narrative2, _, _ = await _normal_call(messages)
    except Exception:
        import traceback
        traceback.print_exc()
        narrative2, _, _ = await _normal_call(messages)

    full_narrative = (narrative or "") + (narrative2 or "")

    # Parse markers
    result = {
        "narrative": "",
        "state_changes": prev_result.get("state_changes", []),
        "next_player": None,
        "ending_suggested": None,
        "suggested_actions": [],
    }

    next_match = re.search(r'\[NEXT:(.+?)\]', full_narrative)
    if next_match:
        result["next_player"] = next_match.group(1).strip()
        full_narrative = re.sub(r'\[NEXT:.+?\]', '', full_narrative).strip()

    ending_match = re.search(r'\[ENDING:(.+?)\]', full_narrative)
    if ending_match:
        result["ending_suggested"] = ending_match.group(1).strip()
        full_narrative = re.sub(r'\[ENDING:.+?\]', '', full_narrative).strip()

    actions_match = re.search(r'\[ACTIONS:(.+?)\]', full_narrative)
    if actions_match:
        result["suggested_actions"] = [a.strip() for a in actions_match.group(1).split("|") if a.strip()]
        full_narrative = re.sub(r'\[ACTIONS:.+?\]', '', full_narrative).strip()

    plot_match = re.search(r'\[PLOT:(\d+):(.+?)\]', full_narrative)
    if plot_match:
        result["plot_update"] = {"stage": int(plot_match.group(1)), "name": plot_match.group(2).strip()}
        full_narrative = re.sub(r'\[PLOT:\d+:.+?\]', '', full_narrative).strip()

    notes = re.findall(r'\[NOTE:(\w+):(.+?)\]', full_narrative)
    if notes:
        result["world_notes"] = [{"category": c, "content": t.strip()} for c, t in notes]
        full_narrative = re.sub(r'\[NOTE:\w+:.+?\]', '', full_narrative).strip()

    result["narrative"] = full_narrative.strip()
    return result


async def _normal_call(messages):
    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=messages,
        tools=[ROLL_DICE_TOOL, UPDATE_STATE_TOOL],
        temperature=0.8, max_tokens=1024,
    )
    msg = resp.choices[0].message
    tools = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tools.append({"id": tc.id, "name": tc.function.name,
                          "args": json.loads(tc.function.arguments)})
    # Preserve reasoning_content for multi-turn thinking mode
    extra = {}
    if hasattr(msg, 'reasoning_content') and msg.reasoning_content:
        extra['reasoning_content'] = msg.reasoning_content
    return msg.content, tools, extra


async def _stream_call(messages, on_chunk):
    """Stream call: call on_chunk(text) for each token, return (full_text, tools)."""
    stream = await client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=messages,
        tools=[ROLL_DICE_TOOL, UPDATE_STATE_TOOL],
        temperature=0.8, max_tokens=1024,
        stream=True,
    )

    content = ""
    tool_calls_acc = {}  # {index: {id, name, args_str}}

    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            continue

        # Text content
        if delta.content:
            content += delta.content
            await on_chunk(delta.content)

        # Tool calls (accumulated across chunks)
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {"id": "", "name": "", "args_str": ""}
                if tc_delta.id:
                    tool_calls_acc[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_calls_acc[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_calls_acc[idx]["args_str"] += tc_delta.function.arguments

    # Parse accumulated tool calls
    tools = []
    for tc in tool_calls_acc.values():
        try:
            args = json.loads(tc["args_str"]) if tc["args_str"] else {}
        except json.JSONDecodeError:
            args = {}
        tools.append({"id": tc["id"], "name": tc["name"], "args": args})

    return content, tools


def _execute_dice(args: dict) -> dict:
    from services.dice import roll as do_roll, check_critical
    dice_expr = args.get("dice") or args.get("expression") or "d20"
    dice_result = do_roll(dice_expr)
    sides = _extract_sides(dice_expr)
    crit = check_critical(dice_result["rolls"], sides) if sides else None
    dc = args.get("difficulty")
    success = None
    if dc is not None:
        success = dice_result["total"] >= dc
    return {
        "character_name": args.get("character_name", "冒险者"),
        "expression": dice_expr,
        "total": dice_result["total"],
        "rolls": dice_result["rolls"],
        "bonus": dice_result["bonus"],
        "dc": dc,
        "success": success,
        "is_critical": crit,
        "reason": args.get("reason", args.get("dice", dice_expr)),
    }


def _extract_sides(expression: str) -> int:
    match = re.search(r'd(\d+)', expression)
    return int(match.group(1)) if match else 0
