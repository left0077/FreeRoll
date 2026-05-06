import json
import uuid
from fastapi import WebSocket, WebSocketDisconnect
from services.room_manager import (
    get_room, add_player, remove_player, add_message, add_dice_log,
    save_snapshot, restore_snapshot, touch_room
)
from services.ai_engine import process_action, resume_with_roll, execute_pending_roll
from services.dice import roll as do_roll
from services.room_manager import (
    create_room, get_room, delete_room, add_player,
    add_character, get_character, Character, restore_snapshot,
)

CONNECTIONS: dict[str, list[WebSocket]] = {}  # {room_code: [ws, ...]}


async def handle_ws(ws: WebSocket, room_code: str, player_id: str):
    room = get_room(room_code)
    if not room:
        await ws.close(code=4004, reason="Room not found")
        return

    # Find player
    player = next((p for p in room["players"] if p.id == player_id), None)
    if not player:
        await ws.close(code=4004, reason="Player not found")
        return

    player.is_online = True
    # Remove old connection for same player (prevents duplicates)
    sockets = CONNECTIONS.setdefault(room_code, [])
    sockets[:] = [w for w in sockets if getattr(w, '_freeroll_pid', None) != player_id]
    ws._freeroll_pid = player_id
    sockets.append(ws)
    # Clear in-flight flags if this player was the one stuck
    if room.get("_processing") and room.get("_pending_roll", {}).get("player_id") == player_id:
        pass  # Keep pending roll — they might be reconnecting to confirm it
    elif room.get("_processing"):
        room.pop("_processing", None)

    # Send full room state immediately — no HTTP GET needed
    await ws.send_json({
        "type": "room_state",
        "payload": _build_room_state(room),
    })

    await _broadcast(room_code, {
        "type": "player_joined",
        "payload": {
            "player_id": player.id,
            "nickname": player.nickname,
            "online_count": len(CONNECTIONS.get(room_code, [])),
        },
    }, exclude=ws)

    try:
        while True:
            try:
                raw = await ws.receive_text()
            except RuntimeError:
                # WebSocket was closed before receiving (Starlette 1.0 compatibility)
                break
            data = json.loads(raw)
            msg_type = data.get("type")
            payload = data.get("payload", {})

            if msg_type == "player_action":
                print(f"[WS] player_action from {player.nickname} ({player.id[:8]}), turn={room.get('current_player_id','')[:8]}, status={room.get('status')}", flush=True)
                await _handle_action(room, player, payload)
            elif msg_type == "roll_confirm":
                await _handle_roll_confirm(room, player)
            elif msg_type == "player_chat":
                await _handle_chat(room, player, payload)
            elif msg_type == "dice_roll":
                await _handle_manual_roll(room, player, payload)
            elif msg_type == "typing_start":
                await _broadcast(room_code, {
                    "type": "typing_indicator",
                    "payload": {"player_id": player.id, "nickname": player.nickname, "is_typing": True},
                }, exclude=ws)
            elif msg_type == "typing_end":
                await _broadcast(room_code, {
                    "type": "typing_indicator",
                    "payload": {"player_id": player.id, "nickname": player.nickname, "is_typing": False},
                }, exclude=ws)

            # -- CRUD operations via WebSocket --
            elif msg_type == "get_room":
                await _reply(ws, _build_room_state(room), data.get("_rid"))
            elif msg_type == "join_room":
                p, err = add_player(room_code, payload.get("nickname", "玩家"), player_id=payload.get("player_id"))
                await _reply(ws, {"player_id": p.id if p else "", "code": room_code, "error": err if not p else None}, data.get("_rid"))
                if p:
                    await _broadcast(room_code, {"type": "player_joined", "payload": {"player_id": p.id, "nickname": p.nickname, "online_count": len(CONNECTIONS.get(room_code, []))}}, exclude=ws)
            elif msg_type == "start_game":
                await _handle_start_game(room, player, payload, ws, data.get("_rid"))
            elif msg_type == "end_game":
                await _handle_end_game(room, player, payload, ws, data.get("_rid"))
            elif msg_type == "rollback_game":
                await _handle_rollback(room, player, payload, ws, data.get("_rid"))
            elif msg_type == "generate_world":
                await _handle_generate_world(room, player, payload, ws, data.get("_rid"))
            elif msg_type == "reset_world":
                room["world_module"] = None
                await _reply(ws, {"status": "reset"}, data.get("_rid"))
                await _broadcast(room_code, {"type": "world_updated", "payload": {"reset": True}})
            elif msg_type == "generate_character":
                await _handle_generate_character(room, player, payload, ws, data.get("_rid"))
            elif msg_type == "claim_character":
                await _handle_claim_character(room, player, payload, ws, data.get("_rid"))
            elif msg_type == "delete_character":
                cid = payload.get("character_id", "")
                room["characters"] = [c for c in room["characters"] if c.id != cid]
                await _reply(ws, {"status": "deleted"}, data.get("_rid"))
                await _broadcast(room_code, {"type": "character_updated"})

    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass  # Starlette 1.0 WebSocket state issue
    finally:
        player.is_online = False
        CONNECTIONS[room_code] = [w for w in CONNECTIONS.get(room_code, []) if w != ws]
        await _broadcast(room_code, {
            "type": "player_left",
            "payload": {
                "player_id": player.id,
                "online_count": len(CONNECTIONS.get(room_code, [])),
            },
        })
        if not CONNECTIONS.get(room_code):
            CONNECTIONS.pop(room_code, None)


async def _handle_action(room, player, payload):
    code = room["code"]
    content = payload.get("content", "").strip()
    if not content:
        return

    # Prevent concurrent AI calls (double-click protection)
    if room.get("_processing"):
        await _send_error_single(code, player.id, "AI 正在处理上一个行动，请稍候")
        return
    room["_processing"] = True

    try:
        await _do_handle_action(room, player, payload)
    finally:
        room.pop("_processing", None)


async def _do_handle_action(room, player, payload):
    code = room["code"]
    content = payload.get("content", "").strip()

    # Validate game state
    if room["status"] != "playing":
        await _send_error_single(code, player.id, "游戏尚未开始或已结束")
        return

    # Validate it's this player's turn
    if player.id != room.get("current_player_id"):
        await _send_error_single(code, player.id, "还没轮到你行动")
        return

    # Find character
    char = next((c for c in room["characters"] if c.player_id == player.id), None)
    if not char:
        await _send_error_single(code, player.id, "你还没有角色")
        return

    # Broadcast typing stop
    await _broadcast(code, {
        "type": "typing_indicator",
        "payload": {"player_id": player.id, "nickname": player.nickname, "is_typing": False},
    })

    # Save action message and broadcast to all players
    touch_room(code)
    msg = add_message(code, player.id, "action", content)
    await _broadcast(code, {
        "type": "player_action_broadcast",
        "payload": {"id": msg["id"], "player_id": player.id, "content": content, "turn_number": room["turn_number"]},
    })
    save_snapshot(code)

    # Process through AI with streaming — extract <narrative>...</narrative> char by char
    _buf = ""
    _state = "seek"  # seek | stream | done

    async def on_chunk(text: str):
        nonlocal _buf, _state
        for ch in text:
            _buf += ch
            if _state == "seek":
                if _buf.endswith("<narrative>"):
                    _buf = ""
                    _state = "stream"
                elif len(_buf) > 20:
                    _buf = _buf[-20:]
            elif _state == "stream":
                if _buf.endswith("</narrative>"):
                    content = _buf[:-len("</narrative>")]
                    if content:
                        await _broadcast(code, {"type": "gm_narrative_chunk", "payload": {"content": content, "turn_number": room["turn_number"]}})
                    _buf = ""
                    _state = "done"
                elif len(_buf) > 14:  # Send all but keep last 13 chars to detect </narrative>
                    await _broadcast(code, {"type": "gm_narrative_chunk", "payload": {"content": _buf[:-13], "turn_number": room["turn_number"]}})
                    _buf = _buf[-13:]

    try:
        ai_result = await process_action(room, content, char.name, on_chunk=on_chunk)
        # Signal streaming is complete
        await _broadcast(code, {"type": "gm_narrative_chunk_done", "payload": {"turn_number": room["turn_number"]}})
        # Flush any remaining buffered text
        if _buf and _state == "stream":
            await _broadcast(code, {"type": "gm_narrative_chunk", "payload": {"content": _buf, "turn_number": room["turn_number"]}})
    except Exception as e:
        import traceback
        print(f"ERROR in _do_handle_action: {e}", flush=True)
        traceback.print_exc()
        room["messages"] = [m for m in room["messages"] if m.get("content") != content or m.get("type") != "action"]
        await _send_error_single(code, player.id, "命运之神暂时走神了，请重试")
        return

    # If AI wants a dice roll, pause and ask the player
    if ai_result.get("pending_roll"):
        roll_args = ai_result["pending_roll"]
        # Store pending state and start auto-roll timeout
        room["_pending_roll"] = {"player_id": player.id, "ai_result": ai_result, "roll_args": roll_args}
        await _send_to_player(code, player.id, {
            "type": "roll_request",
            "payload": {
                "dice": roll_args.get("dice", "d20"),
                "reason": roll_args.get("reason", "判定"),
                "character_name": roll_args.get("character_name", char.name),
            },
        })
        await _broadcast(code, {
            "type": "gm_narrative_chunk",
            "payload": {"content": f"（等待 {char.name} 掷骰...）", "turn_number": room["turn_number"]},
        }, exclude=None)

        # Auto-roll timeout: if player doesn't respond in 30s, roll automatically
        import asyncio
        async def auto_roll():
            await asyncio.sleep(30)
            if room.get("status") != "playing":
                return
            # Skip auto-roll if no one is connected — dead game
            if not CONNECTIONS.get(code):
                return
            # Skip if the acting player is offline
            next_p = next((p for p in room["players"] if p.id == player.id), None)
            if not next_p or not next_p.is_online:
                return
            pending = room.get("_pending_roll")
            if pending and pending["player_id"] == player.id:
                try:
                    ai_result2 = await resume_with_roll(ai_result, roll_args)
                    room.pop("_pending_roll", None)
                    await _process_ai_result(room, code, ai_result2, player, ai_result.get("state_changes", []))
                    await _broadcast(code, {"type": "gm_narrative_chunk", "payload": {"content": "（自动掷骰）", "turn_number": room["turn_number"]}})
                except Exception:
                    pass
        asyncio.create_task(auto_roll())
        return  # Stop here, wait for roll_confirm or auto-roll

    # Handle dice result (from deferred roll or direct)
    if ai_result["dice_result"]:
        dr = ai_result["dice_result"]
        # Find character by name (from AI) then map to ID
        dice_char = next((c for c in room["characters"] if c.name == dr["character_name"]), char)
        add_dice_log(
            code, dice_char.id, dr["expression"], dr["total"],
            {"rolls": dr["rolls"], "bonus": dr["bonus"]},
            dc=dr.get("dc"), success=dr.get("success"),
            is_critical=bool(dr.get("is_critical")),
        )
        add_message(code, None, "dice",
                    f"{dr['character_name']} {dr['expression']} = {dr['total']}",
                    metadata=dr)
        # Include character_id in broadcast so frontend can match
        dr["character_id"] = dice_char.id
        await _broadcast(code, {
            "type": "gm_dice_result",
            "payload": dr,
        })

    # Handle state changes
    for sc in ai_result["state_changes"]:
        sc_char = next((c for c in room["characters"] if c.name == sc["character_name"]), None)
        if sc_char:
            # Apply bar deltas
            bar_delta = sc.get("bar_delta") or {}
            for bar_name, delta in bar_delta.items():
                if bar_name in sc_char.bars:
                    bar = sc_char.bars[bar_name]
                    bar["current"] = max(0, min(bar["current"] + delta, bar["max"]))
            # Add/remove bars
            if sc.get("add_bar"):
                ab = sc["add_bar"]
                sc_char.bars[ab["name"]] = {"current": ab.get("current", 0), "max": ab.get("max", 0)}
            if sc.get("remove_bar") and sc["remove_bar"] in sc_char.bars:
                del sc_char.bars[sc["remove_bar"]]
            # Items
            if sc.get("add_item"):
                sc_char.inventory.append(sc["add_item"])
            if sc.get("remove_item") and sc["remove_item"] in sc_char.inventory:
                sc_char.inventory.remove(sc["remove_item"])
            # Statuses
            if sc.get("add_status") and sc["add_status"] not in sc_char.statuses:
                sc_char.statuses.append(sc["add_status"])
            if sc.get("remove_status") and sc["remove_status"] in sc_char.statuses:
                sc_char.statuses.remove(sc["remove_status"])

        await _broadcast(code, {
            "type": "state_update",
            "payload": {
                "character_id": sc_char.id if sc_char else "",
                "character_name": sc["character_name"],
                "bar_delta": sc.get("bar_delta", {}),
                "add_bar": sc.get("add_bar"),
                "remove_bar": sc.get("remove_bar"),
                "add_item": sc.get("add_item"),
                "remove_item": sc.get("remove_item"),
                "add_status": sc.get("add_status"),
                "remove_status": sc.get("remove_status"),
                "narrative": sc["narrative"],
            },
        })

    # Narrative
    if ai_result["narrative"]:
        add_message(code, None, "narrative", ai_result["narrative"])
        # Always send the full narrative so the frontend can display it
        await _broadcast(code, {
            "type": "gm_narrative",
            "payload": {
                "content": ai_result["narrative"],
                "turn_number": room["turn_number"],
                "suggested_actions": ai_result.get("suggested_actions", []),
            },
        })

    # Next player
    room["turn_number"] += 1
    next_name = ai_result.get("next_player")
    next_char = None
    if next_name:
        next_char = next((c for c in room["characters"] if c.name == next_name), None)
    if not next_char and room["characters"]:
        cur_idx = next((i for i, c in enumerate(room["characters"]) if c.id == char.id), 0)
        next_idx = (cur_idx + 1) % len(room["characters"])
        next_char = room["characters"][next_idx]

    if next_char:
        room["current_player_id"] = next_char.player_id
        await _broadcast(code, {
            "type": "turn_change",
            "payload": {
                "current_player_id": next_char.player_id,
                "player_name": next_char.name,
                "turn_number": room["turn_number"],
            },
        })
        # Start auto-skip timer if next player is disconnected
        import asyncio
        next_pid = next_char.player_id
        current_turn = room["turn_number"]
        async def auto_skip():
            await asyncio.sleep(60)
            if room.get("status") != "playing":
                return
            if room.get("current_player_id") != next_pid:
                return  # Player already acted or turn changed
            if room.get("turn_number") != current_turn:
                return  # Turn already advanced
            next_p = next((p for p in room["players"] if p.id == next_pid), None)
            if next_p and next_p.is_online:
                return  # Player reconnected
            # Auto-skip: send a generic skip action
            skip_char = next((c for c in room["characters"] if c.player_id == next_pid), None)
            if skip_char:
                add_message(code, next_pid, "action", "（因断线自动跳过回合）")
                await _broadcast(code, {"type": "player_action_broadcast", "payload": {"id": str(uuid.uuid4()), "player_id": next_pid, "content": "（因断线自动跳过回合）", "turn_number": room["turn_number"]}})
                add_message(code, None, "narrative", f"{skip_char.name} 因断线未能行动。")
                await _broadcast(code, {"type": "gm_narrative", "payload": {"content": f"{skip_char.name} 因断线未能行动，回合自动跳过。", "turn_number": room["turn_number"], "suggested_actions": []}})
                # Advance to next player
                cur_idx = next((i for i, c in enumerate(room["characters"]) if c.player_id == next_pid), 0)
                next_idx = (cur_idx + 1) % len(room["characters"])
                nn_char = room["characters"][next_idx]
                room["turn_number"] += 1
                room["current_player_id"] = nn_char.player_id
                await _broadcast(code, {"type": "turn_change", "payload": {"current_player_id": nn_char.player_id, "player_name": nn_char.name, "turn_number": room["turn_number"]}})
        asyncio.create_task(auto_skip())

    # World book notes
    notes = ai_result.get("world_notes", [])
    if notes:
        room.setdefault("discoveries", [])
        for note in notes:
            if not any(d.get("content") == note["content"] for d in room["discoveries"]):
                room["discoveries"].append({"category": note["category"], "content": note["content"], "turn": room["turn_number"]})
        if notes:
            await _broadcast(code, {"type": "discoveries_updated", "payload": {"discoveries": room["discoveries"]}})

    # Plot progression
    plot = ai_result.get("plot_update")
    if plot:
        wm = room.get("world_module")
        if wm and wm.get("content", {}).get("storyline"):
            stages = wm["content"]["storyline"]["stages"]
            idx = plot["stage"]
            if 0 <= idx < len(stages):
                stages[idx] = plot["name"]
                await _broadcast(code, {"type": "plot_updated", "payload": {"storyline": wm["content"]["storyline"]}})

    # Ending suggestion
    if ai_result.get("ending_suggested"):
        await _broadcast(code, {
            "type": "game_ending_prompt",
            "payload": {"reason": ai_result["ending_suggested"]},
        })


async def _handle_chat(room, player, payload):
    content = payload.get("content", "").strip()
    if not content:
        return
    msg = add_message(room["code"], player.id, "ooc", content)
    await _broadcast(room["code"], {
        "type": "player_chat",
        "payload": {
            "player_id": player.id,
            "nickname": player.nickname,
            "content": content,
        },
    })


async def _handle_manual_roll(room, player, payload):
    expression = payload.get("expression", "d20")
    result = do_roll(expression)
    char = next((c for c in room["characters"] if c.player_id == player.id), None)
    await _broadcast(room["code"], {
        "type": "gm_dice_result",
        "payload": {
            "character_name": char.name if char else player.nickname,
            "expression": expression,
            "total": result["total"],
            "rolls": result["rolls"],
            "bonus": result["bonus"],
            "is_critical": None,
        },
    })


async def _broadcast(room_code: str, message: dict, exclude: WebSocket = None):
    sockets = CONNECTIONS.get(room_code, [])
    dead = []
    for ws in sockets:
        if ws == exclude:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in sockets:
            sockets.remove(ws)


async def _send_error(room_code: str, message: str):
    for ws in CONNECTIONS.get(room_code, []):
        try:
            await ws.send_json({"type": "error", "payload": {"message": message}})
        except Exception:
            pass


async def _handle_roll_confirm(room, player):
    code = room["code"]
    print(f"[ROLL_CONFIRM] from {player.nickname} ({player.id[:8]})", flush=True)
    pending = room.get("_pending_roll")
    if not pending or pending["player_id"] != player.id:
        await _send_error_single(code, player.id, "没有待掷骰的请求")
        return

    # Pop FIRST to prevent auto-roll from also firing
    room.pop("_pending_roll", None)
    ai_result = pending["ai_result"]
    roll_args = pending["roll_args"]

    # Phase 1: Execute dice immediately → broadcast result with animation
    char = next((c for c in room["characters"] if c.player_id == player.id), None)
    dr = execute_pending_roll(ai_result, roll_args)
    if dr:
        dr["character_name"] = char.name if char else dr.get("character_name", "冒险者")
        dice_char = char
        add_dice_log(code, dice_char.id if dice_char else "", dr["expression"], dr["total"],
                    {"rolls": dr["rolls"], "bonus": dr["bonus"]},
                    dc=dr.get("dc"), success=dr.get("success"),
                    is_critical=bool(dr.get("is_critical")))
        add_message(code, None, "dice", f"{dr['character_name']} {dr['expression']} = {dr['total']}", metadata=dr)
        dr["character_id"] = dice_char.id if dice_char else ""
        await _broadcast(code, {"type": "gm_dice_result", "payload": dr})

    # Phase 2: Resume AI to get narrative (runs in background)
    try:
        ai_result2 = await resume_with_roll(ai_result, roll_args)
        await _process_ai_result(room, code, ai_result2, player, ai_result.get("state_changes", []))
    except Exception:
        import traceback
        traceback.print_exc()
        await _send_error_single(code, player.id, "掷骰判定失败，请重试")


async def _process_ai_result(room, code, ai_result, player, prev_state_changes=None):
    """Process dice result, state changes, narrative from AI result."""
    char = next((c for c in room["characters"] if c.player_id == player.id), None)

    # Handle dice result
    if ai_result.get("dice_result"):
        dr = ai_result["dice_result"]
        dr["character_name"] = char.name if char else dr.get("character_name", "冒险者")
        dice_char = char
        add_dice_log(code, dice_char.id if dice_char else "", dr["expression"], dr["total"],
                    {"rolls": dr["rolls"], "bonus": dr["bonus"]},
                    dc=dr.get("dc"), success=dr.get("success"),
                    is_critical=bool(dr.get("is_critical")))
        add_message(code, None, "dice",
                    f"{dr['character_name']} {dr['expression']} = {dr['total']}", metadata=dr)
        dr["character_id"] = dice_char.id
        await _broadcast(code, {"type": "gm_dice_result", "payload": dr})

    # Handle state changes (both from first call and resume call)
    all_state_changes = (prev_state_changes or []) + ai_result.get("state_changes", [])
    for sc in all_state_changes:
        sc_char = next((c for c in room["characters"] if c.name == sc["character_name"]), None)
        if sc_char:
            bar_delta = sc.get("bar_delta") or {}
            for bar_name, delta in bar_delta.items():
                if bar_name in sc_char.bars:
                    bar = sc_char.bars[bar_name]
                    bar["current"] = max(0, min(bar["current"] + delta, bar["max"]))
            if sc.get("add_bar"):
                ab = sc["add_bar"]
                sc_char.bars[ab["name"]] = {"current": ab.get("current", 0), "max": ab.get("max", 0)}
            if sc.get("remove_bar") and sc["remove_bar"] in sc_char.bars:
                del sc_char.bars[sc["remove_bar"]]
            if sc.get("add_item"):
                sc_char.inventory.append(sc["add_item"])
            if sc.get("remove_item") and sc["remove_item"] in sc_char.inventory:
                sc_char.inventory.remove(sc["remove_item"])
            if sc.get("add_status") and sc["add_status"] not in sc_char.statuses:
                sc_char.statuses.append(sc["add_status"])
            if sc.get("remove_status") and sc["remove_status"] in sc_char.statuses:
                sc_char.statuses.remove(sc["remove_status"])

        await _broadcast(code, {"type": "state_update", "payload": {
            "character_id": sc_char.id if sc_char else "",
            "character_name": sc["character_name"],
            "bar_delta": sc.get("bar_delta", {}),
            "add_bar": sc.get("add_bar"),
            "remove_bar": sc.get("remove_bar"),
            "add_item": sc.get("add_item"),
            "remove_item": sc.get("remove_item"),
            "add_status": sc.get("add_status"),
            "remove_status": sc.get("remove_status"),
            "narrative": sc["narrative"],
        }})

    # Narrative — always send, even if empty, to clear frontend processing state
    narrative_text = ai_result.get("narrative", "")
    if narrative_text:
        add_message(code, None, "narrative", narrative_text)
    await _broadcast(code, {"type": "gm_narrative", "payload": {
        "content": narrative_text,
        "turn_number": room["turn_number"],
        "suggested_actions": ai_result.get("suggested_actions", []),
    }})

    # Next player
    room["turn_number"] += 1
    next_name = ai_result.get("next_player")
    next_char = None
    if next_name:
        next_char = next((c for c in room["characters"] if c.name == next_name), None)
    if not next_char and room["characters"]:
        cur_idx = next((i for i, c in enumerate(room["characters"]) if c.id == char.id), 0) if char else 0
        next_idx = (cur_idx + 1) % len(room["characters"])
        next_char = room["characters"][next_idx]

    if next_char:
        room["current_player_id"] = next_char.player_id
        await _broadcast(code, {"type": "turn_change", "payload": {
            "current_player_id": next_char.player_id,
            "player_name": next_char.name,
            "turn_number": room["turn_number"],
        }})

    # World book notes
    notes = ai_result.get("world_notes", [])
    if notes:
        room.setdefault("discoveries", [])
        for note in notes:
            if not any(d.get("content") == note["content"] for d in room["discoveries"]):
                room["discoveries"].append({"category": note["category"], "content": note["content"], "turn": room["turn_number"]})
        if notes:
            await _broadcast(code, {"type": "discoveries_updated", "payload": {"discoveries": room["discoveries"]}})

    # Plot progression
    plot = ai_result.get("plot_update")
    if plot:
        wm = room.get("world_module")
        if wm and wm.get("content", {}).get("storyline"):
            stages = wm["content"]["storyline"]["stages"]
            idx = plot["stage"]
            if 0 <= idx < len(stages):
                stages[idx] = plot["name"]
                await _broadcast(code, {"type": "plot_updated", "payload": {"storyline": wm["content"]["storyline"]}})

    if ai_result.get("ending_suggested"):
        await _broadcast(code, {"type": "game_ending_prompt", "payload": {"reason": ai_result["ending_suggested"]}})


async def _send_to_player(room_code: str, player_id: str, message: dict):
    """Send a message to a specific player only."""
    for ws in CONNECTIONS.get(room_code, []):
        if getattr(ws, '_freeroll_pid', None) != player_id:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            pass


async def _reply(ws, payload, rid=None):
    """Send a response. If rid is provided, client will match it to a pending request."""
    msg = {"type": "ok", "payload": payload}
    if rid:
        msg["_rid"] = rid
    try:
        await ws.send_json(msg)
    except Exception:
        pass


async def _handle_start_game(room, player, payload, ws, rid):
    if not next((p for p in room["players"] if p.is_owner and p.id == player.id), None):
        await _reply(ws, {"_error": "仅房主可执行此操作"}, rid); return
    if len(room["players"]) < 1:
        await _reply(ws, {"_error": "至少需要1名玩家"}, rid); return
    if not room["characters"]:
        await _reply(ws, {"_error": "还没有角色"}, rid); return
    if not room.get("world_module"):
        await _reply(ws, {"_error": "还没有生成世界模组"}, rid); return

    room["status"] = "playing"
    room["turn_number"] = 0
    room["current_player_id"] = room["characters"][0].player_id
    wm = room.get("world_module") or {}
    initial_scene = wm.get("content", {}).get("initial_scene", "冒险开始了...")
    add_message(room["code"], None, "narrative", initial_scene)

    await _reply(ws, {"status": "playing"}, rid)
    await _broadcast(room["code"], {
        "type": "game_started",
        "payload": {**_build_room_state(room), "initial_scene": initial_scene, "first_player_name": room["characters"][0].name},
    })


async def _handle_end_game(room, player, payload, ws, rid):
    if not next((p for p in room["players"] if p.is_owner and p.id == player.id), None):
        await _reply(ws, {"_error": "仅房主可执行此操作"}, rid); return
    room["status"] = "ended"

    # Generate brief summary
    summary = f"冒险结束！共 {room['turn_number']} 回合，{len(room['players'])} 名冒险者参与。"
    try:
        msgs = [m["content"][:200] for m in room.get("messages", []) if m["type"] == "narrative"][-3:]
        if msgs:
            from openai import AsyncOpenAI
            from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
            ai = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=15.0)
            prompt = f"用两句话为这次跑团冒险写一个精彩的战报总结。最后几段叙事：{'; '.join(msgs)}"
            resp = await ai.chat.completions.create(model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=150)
            summary = resp.choices[0].message.content.strip()
    except Exception:
        pass

    await _broadcast(room["code"], {"type": "game_ended", "payload": {"message": "游戏结束！", "summary": summary}})
    await _reply(ws, {"status": "ended", "summary": summary}, rid)
    delete_room(room["code"])


async def _handle_rollback(room, player, payload, ws, rid):
    if not next((p for p in room["players"] if p.is_owner and p.id == player.id), None):
        await _reply(ws, {"_error": "仅房主可执行此操作"}, rid); return
    to_turn = payload.get("to_turn", 0)
    ok = restore_snapshot(room["code"], to_turn)
    if not ok:
        await _reply(ws, {"_error": "回溯失败"}, rid); return
    await _broadcast(room["code"], {"type": "room_rollback", "payload": {"to_turn": to_turn}})
    await _reply(ws, {"status": "rolled_back"}, rid)


async def _handle_generate_world(room, player, payload, ws, rid):
    import json as _json
    from openai import AsyncOpenAI
    from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    wtype = payload.get("type", "template")
    ref = payload.get("ref", "classic_dungeon")

    if wtype == "template":
        from routers.worlds import TEMPLATES
        template = TEMPLATES.get(ref)
        if not template:
            await _reply(ws, {"_error": "模板不存在"}, rid); return
        ai_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)
        prompt = f"为以下世界观写一段150字以内的初始场景描述：世界观：{template['name']} 概述：{template['overview']} 势力：{', '.join(template['factions'])} 直接写叙事文本。"
        try:
            resp = await ai_client.chat.completions.create(model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.9, max_tokens=300)
            scene = resp.choices[0].message.content.strip()
        except Exception:
            scene = f"欢迎来到{template['name']}。{template['overview']}"
        from routers.worlds import _generate_presets_for_template
        presets = await _generate_presets_for_template(template, scene, max(2, len(room["players"])))
        world = {
            "source_type": "template", "source_ref": ref,
            "content": {"overview": template["overview"], "factions": template["factions"], "custom_rules": template["rules"], "bar_schema": template.get("bar_schema", {}), "storyline": template.get("storyline", {"title": "冒险", "stages": ["??", "??"]}), "initial_scene": scene},
            "preset_characters": presets,
        }
    else:
        await _reply(ws, {"_error": "仅支持 template 类型"}, rid); return

    room["world_module"] = world
    await _reply(ws, world, rid)
    await _broadcast(room["code"], {"type": "world_updated", "payload": {"source_ref": ref, "has_presets": False}})


async def _handle_generate_character(room, player, payload, ws, rid):
    import json as _json
    from openai import AsyncOpenAI
    from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    desc = payload.get("description", "")
    if not desc:
        await _reply(ws, {"_error": "请输入角色描述"}, rid); return

    existing_names = [c.name for c in room["characters"]]
    world_context = ""
    bar_info = ""
    if room.get("world_module"):
        c = (room.get("world_module") or {}).get("content", {})
        world_context = f"世界观：{c.get('overview', '')}"
        if c.get("bar_schema"):
            bar_info = f"数值条定义：{_json.dumps(c['bar_schema'], ensure_ascii=False)}"

    prompt = f"""{world_context}
{bar_info}
已有角色名：{existing_names}。新角色名不能重复。

玩家描述："{desc}"

生成一个符合世界观的角色卡，输出 JSON：
{{"name":"独特角色名","bars":{{"HP":{{"current":20,"max":20}}}},"attributes":{{}},"tags":["标签"],"inventory":["物品"],"description":"50字简介"}}
输出合法 JSON，不要加额外文字。"""

    ai_client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=30.0)
    try:
        resp = await ai_client.chat.completions.create(model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.9, max_tokens=1024, response_format={"type": "json_object"})
        char_data = _json.loads(resp.choices[0].message.content)
    except Exception as e:
        await _reply(ws, {"_error": f"AI生成失败: {e}"}, rid); return

    char_name = char_data.get("name", "未命名")
    if char_name in existing_names:
        char_name += "_2"

    character = Character(
        player_id=player.id, name=char_name,
        attributes=char_data.get("attributes", {}), tags=char_data.get("tags", []),
        bars=char_data.get("bars", {"HP": {"current": 20, "max": 20}}),
        inventory=char_data.get("inventory", []), description=char_data.get("description", ""),
    )
    add_character(room["code"], character)

    await _reply(ws, {
        "id": character.id, "player_id": character.player_id, "name": character.name,
        "bars": character.bars, "attributes": character.attributes, "tags": character.tags,
        "inventory": character.inventory, "statuses": character.statuses, "description": character.description,
    }, rid)
    await _broadcast(room["code"], {"type": "character_updated"})


async def _handle_claim_character(room, player, payload, ws, rid):
    wm = room.get("world_module")
    if not wm:
        await _reply(ws, {"_error": "世界模组尚未生成"}, rid); return
    presets = wm.get("preset_characters", [])
    idx = payload.get("preset_index", 0)
    if idx >= len(presets):
        await _reply(ws, {"_error": "预设角色不存在"}, rid); return

    preset = presets[idx]
    preset_name = preset.get("name", "未命名")
    if any(c.name == preset_name for c in room["characters"]):
        await _reply(ws, {"_error": f"角色「{preset_name}」已被认领"}, rid); return
    character = Character(
        player_id=player.id, name=preset_name, is_preset=True,
        attributes=preset.get("attributes", {}), tags=preset.get("tags", []),
        bars=preset.get("bars", {"HP": {"current": 20, "max": 20}}),
        inventory=preset.get("inventory", []), description=preset.get("description", ""),
    )
    add_character(room["code"], character)

    await _reply(ws, {"id": character.id, "player_id": character.player_id, "name": character.name, "is_preset": True, "bars": character.bars}, rid)
    await _broadcast(room["code"], {"type": "character_updated"})


def _build_room_state(room: dict) -> dict:
    """Build a serializable room state for the initial WebSocket push."""
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
                "bars": c.bars, "attributes": c.attributes,
                "description": c.description, "inventory": c.inventory, "statuses": c.statuses,
            }
            for c in room["characters"]
        ],
        "world_module": room.get("world_module"),
        "discoveries": room.get("discoveries", []),
        "messages": [
            {"id": m["id"], "player_id": m["player_id"], "type": m["type"],
             "content": m["content"], "metadata": m.get("metadata"),
             "turn_number": m.get("turn_number")}
            for m in room.get("messages", [])
        ],
    }


async def _send_error_single(room_code: str, player_id: str, message: str):
    """Send error to a specific player only."""
    for ws in CONNECTIONS.get(room_code, []):
        if getattr(ws, '_freeroll_pid', None) != player_id:
            continue
        try:
            await ws.send_json({"type": "error", "payload": {"message": message, "player_id": player_id}})
        except Exception:
            pass
