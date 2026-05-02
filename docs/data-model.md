# 数据模型

## 核心实体

```
Room ──┬── Player (2-6)
       ├── Character (每个玩家一个)
       ├── WorldModule
       ├── ChatMessage[]
       └── DiceLog[]
```

## 表结构

### room
| 列 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID PK | |
| code | VARCHAR(6) UNIQUE | 6 位房间码 |
| status | ENUM(waiting, playing, ended) | |
| world_module_id | UUID FK → world_module | nullable |
| character_mode | ENUM(create, preset, both) | 角色创建模式 |
| turn_number | INTEGER DEFAULT 0 | |
| current_player_id | UUID FK → player | 当前回合玩家，nullable |
| created_at | TIMESTAMP | |
| finished_at | TIMESTAMP | nullable |

### player
| 列 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID PK | |
| room_id | UUID FK → room | |
| nickname | VARCHAR(50) | |
| is_owner | BOOLEAN | |
| is_online | BOOLEAN | |
| joined_at | TIMESTAMP | |

### character
| 列 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID PK | |
| player_id | UUID FK → player | 一对一 |
| room_id | UUID FK → room | |
| name | VARCHAR(100) | |
| is_preset | BOOLEAN DEFAULT false | 是否为预设角色 |
| attributes | JSONB | {"力量": 14, "敏捷": 16} |
| tags | JSONB | ["精灵","弓箭手"] |
| hp_current | INTEGER | |
| hp_max | INTEGER | |
| inventory | JSONB | ["短剑","药水×2"] |
| statuses | JSONB | ["中毒"] |
| description | TEXT | 角色背景故事 |

### world_module
| 列 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID PK | |
| room_id | UUID FK → room | |
| source_type | ENUM(template, web_search, txt_upload) | |
| source_ref | VARCHAR(500) | |
| content | JSONB | {overview, factions, rules, initial_scene} |
| preset_characters | JSONB | 预设角色列表，可为空 |
| created_at | TIMESTAMP | |

### chat_message
| 列 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID PK | |
| room_id | UUID FK → room | |
| player_id | UUID FK → player (nullable) | NULL = AI |
| type | ENUM(narrative, action, dice, system, ooc) | |
| content | TEXT | |
| metadata | JSONB | 骰子结果、状态变更 |
| turn_number | INTEGER | |
| created_at | TIMESTAMP (INDEXED) | |

### dice_log
| 列 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID PK | |
| room_id | UUID FK → room | |
| character_id | UUID FK → character | |
| expression | VARCHAR(50) | |
| result | INTEGER | |
| detail | JSONB | {rolls: [15], bonus: 3} |
| dc | INTEGER | nullable |
| success | BOOLEAN | nullable |
| is_critical | BOOLEAN | |
| turn_number | INTEGER | |
| created_at | TIMESTAMP | |

## Redis 键设计

```
room:{code}:players         → HASH   {player_id: socket_id}
room:{code}:online_count    → INT
room:{code}:typing           → SET   正在输入的玩家 ID
room:{code}:snapshot:{turn}  → JSON  该回合开始时的角色状态快照（用于回溯）
```

### 回溯快照格式
```json
{
  "turn": 15,
  "characters": {
    "uuid-1": {"hp_current": 20, "hp_max": 24, "inventory": [...], "statuses": [...]},
    "uuid-2": {...}
  }
}
```

回溯时：
1. 从 Redis 读取目标回合快照
2. 恢复所有角色状态到该快照
3. 删除 `chat_message` 中 `turn_number >= 目标回合` 的记录
4. 删除 `dice_log` 中 `turn_number >= 目标回合` 的记录
5. 更新 `room.current_player_id` 和 `room.turn_number`
6. 广播状态重置，下一玩家从回溯点重新行动

## 待确认

`[ ]` 已结束房间数据保留多久？建议 7 天自动清理或手动删除。
`[ ]` message 列表加载时是否需要分页（预计 200-500 条）？
