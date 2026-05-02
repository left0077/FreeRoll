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
- 描述简洁有力，每次叙事控制在 2-4 段
- 必须使用角色名而非"你""我"等代词
- 不要在描述中替玩家做决定

## ⚠️ 状态更新（最高优先级 — 每次叙事必须检查）
叙事中只要发生了以下任何情况，**必须**调用 update_state：
| 情况 | 参数 |
|------|------|
| 角色受伤 | bar_delta: {"HP": -具体数值} |
| 角色治疗 | bar_delta: {"HP": +具体数值} |
| 数值条变化 | bar_delta: {"条名": 变化量} |
| 获得物品 | add_item: "物品名" |
| 消耗物品 | remove_item: "物品名" |
| 新增状态 | add_status: "状态名" |
| 解除状态 | remove_status: "状态名" |

不要只在叙事中描述"他受伤了"就结束——必须实际调用 update_state 修改数值条。
例如叙事写了"金鬃王的利爪撕开了你的肩膀" → 必须 bar_delta: {"HP": -4} + 叙事描述"肩膀鲜血直流"。

## 输出格式（严格遵守）
所有回复分为两个部分，用 `[SYSTEM]` 分隔：

叙事部分（玩家可见）
[SYSTEM]
控制标记（玩家不可见）

例如：
走廊深处传来低沉的嘶吼，石壁上投下不安的阴影。金鬃王握紧长剑，手臂上被石像鬼抓出的伤口还在渗血。
[SYSTEM]
[NEXT:金鬃王]
[ACTIONS:举火把谨慎向前探查|退后到岔路口选择另一条路|包扎手臂上的伤口]
[BAR:金鬃王:HP:-3]
[NOTE:location:地下城第二层，有石像鬼出没]

状态变化标记格式（在 [SYSTEM] 块中使用）：
- [BAR:角色名:数值条名:变化量]  例：[BAR:金鬃王:HP:-5] [BAR:艾林:SAN:-10]
- [ITEM:角色名:+:物品名]  例：[ITEM:金鬃王:+:生锈的钥匙]
- [ITEM:角色名:-:物品名]  例：[ITEM:金鬃王:-:治疗药水]
- [STATUS:角色名:+:状态名]  例：[STATUS:金鬃王:+:中毒]
- [STATUS:角色名:-:状态名]  例：[STATUS:金鬃王:-:中毒]

注意：[SYSTEM] 前面的叙事部分是玩家看到的文字。[SYSTEM] 后面的标记是系统指令。
不要在叙事中使用 [SYSTEM] 这个词。

## 回合管理
- 根据故事走向指定下一个行动的玩家
- 让每个玩家都有参与机会，不要让一个人连续行动超过 2 回合

## 游戏结束
- 当剧情自然收尾时输出 [ENDING:简短理由]
- 不要在剧情中途随意建议结束

## 玩家间对话
- 玩家用 (OOC) 标记进行场外对话，你不需要回应
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
    """Split on [SYSTEM]: narrative before, control markers after."""
    if "[SYSTEM]" in text:
        parts = text.split("[SYSTEM]", 1)
        narrative_text = parts[0].strip()
        control_text = parts[1].strip() if len(parts) > 1 else ""
    else:
        narrative_text = text.strip()
        control_text = text  # Fallback: parse markers from full text, strip later

    # Parse controls from control_text first, fallback to narrative
    for source in [control_text, narrative_text]:
        if result.get("next_player") and result.get("suggested_actions"):
            break

        m = re.search(r'\[NEXT:(.+?)\]', source)
        if m and not result.get("next_player"):
            result["next_player"] = m.group(1).strip()

        m = re.search(r'\[ENDING:(.+?)\]', source)
        if m:
            result["ending_suggested"] = m.group(1).strip()

        m = re.search(r'\[ACTIONS:(.+?)\]', source)
        if m and not result.get("suggested_actions"):
            result["suggested_actions"] = [a.strip() for a in m.group(1).split("|") if a.strip()]

        m = re.search(r'\[PLOT:(\d+):(.+?)\]', source)
        if m and not result.get("plot_update"):
            result["plot_update"] = {"stage": int(m.group(1)), "name": m.group(2).strip()}

        notes = re.findall(r'\[NOTE:(\w+):(.+?)\]', source)
        if notes:
            existing = result.get("world_notes", [])
            for c, t in notes:
                if not any(d.get("content") == t.strip() for d in existing):
                    existing.append({"category": c, "content": t.strip()})
            result["world_notes"] = existing

        # Parse state changes from control markers
        for bar_match in re.finditer(r'\[BAR:([^:]+):([^:]+):([+-]?\d+)\]', source):
            delta = int(bar_match.group(3))
            existing_sc = next((s for s in result.get("state_changes", []) if s["character_name"] == bar_match.group(1)), None)
            if existing_sc:
                existing_sc.setdefault("bar_delta", {})[bar_match.group(2)] = existing_sc.get("bar_delta", {}).get(bar_match.group(2), 0) + delta
            else:
                result.setdefault("state_changes", []).append({
                    "character_name": bar_match.group(1),
                    "bar_delta": {bar_match.group(2): delta},
                    "narrative": "",
                })

        for item_match in re.finditer(r'\[ITEM:([^:]+):([+-]):(.+?)\]', source):
            name, op, item = item_match.group(1), item_match.group(2), item_match.group(3).strip()
            existing_sc = next((s for s in result.get("state_changes", []) if s["character_name"] == name), None)
            if existing_sc:
                if op == "+": existing_sc.setdefault("add_item", item)
                else: existing_sc.setdefault("remove_item", item)
            else:
                sc = {"character_name": name, "narrative": ""}
                if op == "+": sc["add_item"] = item
                else: sc["remove_item"] = item
                result.setdefault("state_changes", []).append(sc)

        for status_match in re.finditer(r'\[STATUS:([^:]+):([+-]):(.+?)\]', source):
            name, op, status = status_match.group(1), status_match.group(2), status_match.group(3).strip()
            existing_sc = next((s for s in result.get("state_changes", []) if s["character_name"] == name), None)
            if existing_sc:
                if op == "+": existing_sc.setdefault("add_status", status)
                else: existing_sc.setdefault("remove_status", status)
            else:
                sc = {"character_name": name, "narrative": ""}
                if op == "+": sc["add_status"] = status
                else: sc["remove_status"] = status
                result.setdefault("state_changes", []).append(sc)

    # Clean narrative: strip any remaining inline markers
    if "[SYSTEM]" not in text:
        narrative_text = re.sub(r'\[(?:NEXT|ACTIONS|ENDING|PLOT|NOTE):[^\]]*\]', '', narrative_text).strip()

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
