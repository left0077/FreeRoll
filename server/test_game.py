"""Full integration test: create room, 3 players, 3 rounds via WebSocket."""
import asyncio
import json
import websockets
import httpx

BASE = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient(timeout=60.0) as http:
        # 1. Create room
        r = await http.post(f"{BASE}/api/rooms", json={"nickname": "苹果", "character_mode": "create"})
        room = r.json()
        code = room["code"]
        pid1 = room["player_id"]
        print(f"1. Room {code} created, host: 苹果")

        # 2. Generate world
        await http.post(f"{BASE}/api/worlds/generate", json={"type": "template", "ref": "classic_dungeon", "room_code": code})
        print("2. World generated")

        # 3. Join 2 more players
        r = await http.post(f"{BASE}/api/rooms/{code}/join", json={"nickname": "香蕉"})
        pid2 = r.json()["player_id"]
        r = await http.post(f"{BASE}/api/rooms/{code}/join", json={"nickname": "橙子"})
        pid3 = r.json()["player_id"]
        print("3. Players joined: 苹果, 香蕉, 橙子")

        # 4. Create characters
        chars = {}
        for pid, desc in [
            (pid1, "人类战士，勇敢正义，队长型人物"),
            (pid2, "精灵法师，博学但有些胆小"),
            (pid3, "矮人盗贼，贪财但忠诚"),
        ]:
            r = await http.post(f"{BASE}/api/characters/generate", json={
                "room_code": code, "player_id": pid, "description": desc,
            }, timeout=120.0)
            if r.status_code != 200:
                print(f"  ERROR: char gen returned {r.status_code}: {r.text[:200]}")
                return
            chars[pid] = r.json()["name"]
        print(f"4. Characters: {chars[pid1]}, {chars[pid2]}, {chars[pid3]}")

    # Actions for each player
    player_actions = {
        pid1: (chars[pid1], "我高举火把仔细观察前方黑暗的走廊，寻找陷阱和敌人的踪迹"),
        pid2: (chars[pid2], "我在队伍后方轻声念诵侦测魔法的咒语，检查周围是否有魔法能量波动"),
        pid3: (chars[pid3], "我蹲下来用盗贼的直觉检查石板地面和两侧墙壁，寻找暗门或隐藏机关"),
    }

    # 5. Connect WebSocket first, THEN start game
    print("5. Connecting WebSocket clients...")
    ws_tasks = []
    start_event = asyncio.Event()
    done_event = asyncio.Event()

    for pid, (name, action) in player_actions.items():
        task = asyncio.create_task(player_ws(code, pid, name, action, start_event, done_event))
        ws_tasks.append(task)

    await asyncio.sleep(1)  # Let all connections establish

    # 6. Start game
    async with httpx.AsyncClient(timeout=60.0) as http:
        await http.post(f"{BASE}/api/rooms/{code}/start?player_id={pid1}")
    print("6. Game started!")

    # Wait for 3 rounds or 3 minutes
    try:
        await asyncio.wait_for(done_event.wait(), timeout=180)
    except asyncio.TimeoutError:
        print("\n⏰ 整体超时(3分钟)")

    for t in ws_tasks:
        t.cancel()

    print("\n=== 测试完成 ===")

async def player_ws(code, pid, char_name, action, start_event, done_event):
    url = f"ws://localhost:8000/ws/{code}?player_id={pid}"
    acted = False
    turns_completed = 0

    try:
        async with websockets.connect(url) as ws:
            print(f"  [{char_name}] WebSocket connected, waiting for game start...")

            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=120)
                data = json.loads(msg)
                t = data["type"]
                p = data.get("payload", {})

                if t == "game_started":
                    print(f"  [{char_name}] 游戏开始! 初场景: {p.get('initial_scene','')[:80]}...")
                    start_event.set()
                    if p.get("first_player_id") == pid and not acted:
                        await asyncio.sleep(0.5)
                        print(f"\n[{char_name}] 🎯 回合0: {action[:50]}...")
                        await ws.send(json.dumps({"type": "player_action", "payload": {"content": action}}))
                        acted = True

                elif t == "turn_change":
                    tn = p.get("turn_number", 0)
                    if tn > turns_completed:
                        turns_completed = tn
                    if p.get("current_player_id") == pid and not acted:
                        await asyncio.sleep(0.5)
                        print(f"\n[{char_name}] 🎯 回合{tn}: {action[:50]}...")
                        await ws.send(json.dumps({"type": "player_action", "payload": {"content": action}}))
                        acted = True
                    print(f"  [{char_name}] 轮到: {p.get('player_name')} (回合{tn})")

                elif t == "gm_narrative":
                    text = p['content'][:200].replace('\n', ' ')
                    print(f"  📜 [{char_name}看到] {text}")

                elif t == "gm_dice_result":
                    crit = ""
                    if p.get("is_critical") == "critical_success": crit = " 🎉大成功!"
                    elif p.get("is_critical") == "critical_failure": crit = " 💀大失败!"
                    print(f"  🎲 {p['character_name']} {p['expression']}={p['total']}{crit}")

                elif t == "state_update":
                    hp = p.get("hp_delta", 0)
                    hp_s = f"HP{hp:+d} " if hp else ""
                    print(f"  ⚡ {p['character_name']} {hp_s}| {p.get('narrative','')[:80]}")

                elif t == "game_ending_prompt":
                    print(f"  🏁 AI建议结束: {p.get('reason')}")

                elif t == "game_ended":
                    print(f"  [{char_name}] 游戏结束")
                    done_event.set()
                    return

                elif t == "typing_indicator":
                    pass  # skip

                if turns_completed >= 3:
                    print(f"  [{char_name}] 已完成3轮")
                    done_event.set()
                    return

    except asyncio.TimeoutError:
        print(f"  [{char_name}] ⏰ 超时")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"  [{char_name}] ❌ {type(e).__name__}: {e}")

asyncio.run(main())
