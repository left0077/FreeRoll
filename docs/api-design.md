# API 设计

## HTTP 端点

### 房间
```
POST   /api/rooms                   创建房间 {
                                      character_mode: "create"|"preset"|"both",
                                      world_source?: "template"|"web_search"|"txt_upload",
                                      source_ref?: "classic_dungeon"
                                    }
GET    /api/rooms/:code             获取房间信息
POST   /api/rooms/:code/join        加入房间 {nickname: "阿拉贡"}
POST   /api/rooms/:code/start       开始游戏（房主，需 ≥ 2 人）
POST   /api/rooms/:code/end         结束游戏（房主）
POST   /api/rooms/:code/rollback    回溯 {to_turn: 15}（房主）
```

### 世界模组
```
POST   /api/worlds/generate         生成模组 {type, ref}
GET    /api/worlds/:id              获取模组详情
POST   /api/worlds/upload-txt       上传 TXT（multipart/form-data）
```

### 角色
```
POST   /api/characters/generate     AI 辅助车卡 {room_code, description: "精灵弓箭手"}
POST   /api/characters/claim        认领预设角色 {room_code, player_id, character_id}
GET    /api/characters/:id          获取角色卡
PUT    /api/characters/:id          编辑角色卡
```

### 战报
```
POST   /api/rooms/:code/report      生成战报
GET    /api/rooms/:code/report      获取战报
```

## WebSocket 消息

连接：`ws://<host>/ws/:room_code?player_id=<id>`

### 客户端 → 服务端

| type | payload | 说明 |
|:---|:---|:---|
| player_action | {content} | 玩家行动 |
| player_chat | {content} | 玩家间对话 |
| dice_roll | {expression} | 快捷掷骰 |
| typing_start | {} | 正在输入 |
| typing_end | {} | 输入结束 |

### 服务端 → 客户端

| type | payload | 说明 |
|:---|:---|:---|
| gm_narrative | {content, turn_number} | AI 叙事 |
| gm_dice_result | {character_name, expression, result, is_critical, dc, success, narrative} | 骰子结果 |
| state_update | {character_id, changes, narrative} | 状态变更 |
| turn_change | {current_player_id, player_name, turn_number} | AI 指定下一玩家 |
| game_ending_prompt | {reason} | AI 建议结束，提示房主 |
| player_joined | {player_id, nickname, online_count} | |
| player_left | {player_id, online_count} | |
| typing_indicator | {player_id, nickname, is_typing} | |
| game_started | {initial_scene} | |
| game_ended | {report_url} | |
| room_rollback | {to_turn} | 房间已回溯 |
| error | {message, code} | |

## 完整回合时序

```
Client                     Server                        DeepSeek
   │── player_action ──────►│
   │                        │── 构建 messages:           │
   │                        │   system + world +         │
   │                        │   全部历史 + action         │
   │                        │                            │
   │                        │── chat.completions ────────►│
   │                        │   tools: [roll_dice,        │
   │                        │     update_state]          │
   │                        │                            │
   │                        │◄── 响应（可能含 tool_calls）│
   │                        │                            │
   │                        │── 服务端处理：              │
   │                        │   · 执行掷骰（如有）        │
   │                        │   · 更新状态（如有）        │
   │                        │   · 保存回合快照            │
   │                        │   · 解析 [NEXT:角色名]     │
   │                        │   · 检测 [ENDING] 标记     │
   │                        │                            │
   │                        │── 如需要，二次调用 AI ─────►│
   │                        │   （反馈 tool 结果）        │
   │                        │◄── 最终叙事                 │
   │                        │                            │
   │◄── gm_dice_result ────│  (如有掷骰)
   │◄── state_update ──────│  (如有状态变更)
   │◄── gm_narrative ──────│  (叙事文本)
   │◄── turn_change ───────│  (切换回合)
   │◄── game_ending_prompt │  (仅当 AI 建议结束时)
```

## 回溯流程

```
房主 Client                  Server                          DB/Redis
   │── HTTP POST /rollback ──►│
   │    {to_turn: 15}         │
   │                          │── 读取快照 room:X:snapshot:15
   │                          │◄── 获取角色状态
   │                          │── UPDATE character 恢复所有角色状态
   │                          │── DELETE chat_message WHERE turn >= 15
   │                          │── DELETE dice_log WHERE turn >= 15
   │                          │── UPDATE room SET turn_number=15
   │                          │
   │◄── 200 OK ──────────────│
   │                          │── WebSocket 广播 room_rollback {to_turn: 15}
   │                          │   所有玩家看到叙事回到第 15 回合
```

回溯后，玩家从第 15 回合的叙事点开始重新输入行动，如同该点之后的一切从未发生。
