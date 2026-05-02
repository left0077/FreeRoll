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

SYSTEM_PROMPT = """你是一个文字跑团的主持人（GM）。

## 核心规则
1. 掷骰必须调用 roll_dice 函数——绝不在叙事中写骰子结果
2. 数值变化写在 <controls> 块里——绝不在叙事中写"HP:15→12"
3. 叙事只写故事，不写任何游戏机制

## 输出格式
<response>
<narrative>纯故事文本，2-4段，用角色名而非你/我。禁止出现骰子、HP、状态标记等游戏术语。</narrative>
<controls>
<next>下一个行动的角色名</next>
<actions>建议1|建议2|建议3</actions>
<bar character="角色名" name="HP" delta="-3"/>
<item character="角色名" action="add">物品名</item>
<status character="角色名" action="add">状态名</status>
<note category="npc">内容</note>
</controls>
</response>

## 回合规则
- 指定下一个行动的玩家，每个玩家都有参与机会
- 剧情自然收尾时加 <ending>理由</ending>

## 玩家对话
- (OOC) 开头的消息是玩家场外对话，不需要你回应
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

    # First call (streaming if callback, captures reasoning_content from stream)
    extra_fields = {}
    if on_chunk:
        try:
            narrative, tool_calls_data, extra_fields = await _stream_call(messages, on_chunk)
        except Exception:
            import traceback; traceback.print_exc()
            narrative, tool_calls_data, extra_fields = await _normal_call(messages)
    else:
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
                print(f"[AI] update_state called: {json.dumps(tc['args'], ensure_ascii=False)[:200]}", flush=True)
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
                    narrative2, _, _ = await _stream_call(messages, on_chunk)
                else:
                    narrative2, _, _ = await _normal_call(messages)
            except Exception:
                import traceback; traceback.print_exc()
                narrative2, _, _ = await _normal_call(messages)
            narrative = (narrative or "") + (narrative2 or "")

    # Split on --- : before is narrative, after is control markers
    _parse_mixed_response(narrative or "", result)
    narrative = result["narrative"]

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
            narrative2, _, _ = await _stream_call(messages, on_chunk)
        else:
            narrative2, _, _ = await _normal_call(messages)
    except Exception:
        import traceback; traceback.print_exc()
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

    _parse_mixed_response(full_narrative, result)
    return result


def _parse_mixed_response(text: str, result: dict):
    """Extract <narrative> for players, <controls> for system."""
    narrative_text = ""
    control_text = ""

    m = re.search(r'<narrative>(.+?)</narrative>', text, re.DOTALL)
    if m:
        narrative_text = m.group(1).strip()

    m = re.search(r'<controls>(.+?)</controls>', text, re.DOTALL)
    if m:
        control_text = m.group(1).strip()

    if not narrative_text and not control_text:
        # Fallback: old format
        if "<system>" in text:
            parts = text.split("<system>", 1)
            narrative_text = parts[0].strip()
            control_text = parts[1].strip() if len(parts) > 1 else ""
        else:
            narrative_text = text.strip()

    # Parse XML controls
    if control_text:
        m = re.search(r'<next>(.+?)</next>', control_text)
        if m: result["next_player"] = m.group(1).strip()

        m = re.search(r'<ending>(.+?)</ending>', control_text)
        if m: result["ending_suggested"] = m.group(1).strip()

        m = re.search(r'<actions>(.+?)</actions>', control_text)
        if m: result["suggested_actions"] = [a.strip() for a in m.group(1).split("|") if a.strip()]

        m = re.search(r'<plot\s+stage="(\d+)">(.+?)</plot>', control_text)
        if m: result["plot_update"] = {"stage": int(m.group(1)), "name": m.group(2).strip()}

        for m in re.finditer(r'<note\s+category="(\w+)">(.+?)</note>', control_text):
            existing = result.setdefault("world_notes", [])
            if not any(d.get("content") == m.group(2).strip() for d in existing):
                existing.append({"category": m.group(1), "content": m.group(2).strip()})

        for m in re.finditer(r'<bar\s+character="([^"]+)"\s+name="([^"]+)"\s+delta="([+-]?\d+)"', control_text):
            delta = int(m.group(3))
            existing_sc = next((s for s in result.setdefault("state_changes", []) if s["character_name"] == m.group(1)), None)
            if existing_sc:
                existing_sc.setdefault("bar_delta", {})[m.group(2)] = existing_sc.get("bar_delta", {}).get(m.group(2), 0) + delta
            else:
                result["state_changes"].append({"character_name": m.group(1), "bar_delta": {m.group(2): delta}, "narrative": ""})

        for m in re.finditer(r'<item\s+character="([^"]+)"\s+action="(add|remove)">(.+?)</item>', control_text):
            name, action, item = m.group(1), m.group(2), m.group(3).strip()
            existing_sc = next((s for s in result.setdefault("state_changes", []) if s["character_name"] == name), None)
            if existing_sc:
                if action == "add": existing_sc["add_item"] = item
                else: existing_sc["remove_item"] = item
            else:
                sc = {"character_name": name, "narrative": ""}
                if action == "add": sc["add_item"] = item
                else: sc["remove_item"] = item
                result["state_changes"].append(sc)

        for m in re.finditer(r'<status\s+character="([^"]+)"\s+action="(add|remove)">(.+?)</status>', control_text):
            name, action, status = m.group(1), m.group(2), m.group(3).strip()
            existing_sc = next((s for s in result.setdefault("state_changes", []) if s["character_name"] == name), None)
            if existing_sc:
                if action == "add": existing_sc["add_status"] = status
                else: existing_sc["remove_status"] = status
            else:
                sc = {"character_name": name, "narrative": ""}
                if action == "add": sc["add_status"] = status
                else: sc["remove_status"] = status
                result["state_changes"].append(sc)

    # Fallback: parse old bracket markers from narrative
    if not result.get("next_player"):
        for source in [control_text, narrative_text]:
            m = re.search(r'\[NEXT:(.+?)\]', source)
            if m: result["next_player"] = m.group(1).strip(); break
    if not result.get("suggested_actions"):
        m = re.search(r'\[ACTIONS:(.+?)\]', narrative_text)
        if m: result["suggested_actions"] = [a.strip() for a in m.group(1).split("|") if a.strip()]

    # Clean narrative
    if "<system>" not in text:
        narrative_text = re.sub(r'<(next|actions|bar|item|status|note|plot|ending|system)[^>]*>.*?</\1>', '', narrative_text, flags=re.DOTALL).strip()
        narrative_text = re.sub(r'\[(?:NEXT|ACTIONS|BAR|ITEM|STATUS|NOTE|PLOT|ENDING):[^\]]*\]', '', narrative_text).strip()

    result["narrative"] = narrative_text


async def _normal_call(messages):
    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=messages,
        tools=[ROLL_DICE_TOOL],  # Only dice — state changes via [BAR:...] text markers
        temperature=0.8, max_tokens=1024,
        extra_body={"thinking": {"type": "enabled"}},
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
    # Return the full message dict to preserve all fields (reasoning_content etc.)
    return msg.content, tools, msg.model_dump()


async def _stream_call(messages, on_chunk):
    """Stream call: call on_chunk(text) for each token. Returns (full_text, tools, extra_fields)."""
    stream = await client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=messages,
        tools=[ROLL_DICE_TOOL],
        temperature=0.8, max_tokens=1024,
        stream=True,
        extra_body={"thinking": {"type": "enabled"}},
    )

    content = ""
    reasoning = ""
    tool_calls_acc = {}

    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            continue

        if delta.content:
            content += delta.content
            await on_chunk(delta.content)

        # Capture reasoning_content from thinking chunks
        if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
            reasoning += delta.reasoning_content

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

    tools = []
    for tc in tool_calls_acc.values():
        try:
            args = json.loads(tc["args_str"]) if tc["args_str"] else {}
        except json.JSONDecodeError:
            args = {}
        tools.append({"id": tc["id"], "name": tc["name"], "args": args})

    extra = {}
    if reasoning:
        extra["reasoning_content"] = reasoning
    return content, tools, extra


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
        "character_name": args.get("character_name") or args.get("name") or "",
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
