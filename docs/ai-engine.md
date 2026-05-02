# AI 主持人引擎设计

## 核心理念

DeepSeek 1M 上下文足够容纳整场游戏。**全文保留，不裁剪。**

## 核心循环

```
玩家输入 → AI 裁决 + 叙事 + 判定 → 提取 Function Call → 执行 → 广播 → AI 指定下一玩家
```

## Prompt 架构

每轮发送给 DeepSeek 的三层结构：

### 1. System Prompt（固定，约 500 tokens）
- 主持人身份：叙事风格、语气、裁决原则（rule-of-cool）
- 禁止行为：不能替玩家做决定、不能泄露隐藏信息
- Function Calling 使用规则
- **回合分配规则**：在每次叙事末尾，用 `[NEXT:角色名]` 标记你认为下一个应该行动的玩家

### 2. 世界模组 + 角色卡（开局注入，约 4,000 tokens）
- 世界观、势力、规则、初始场景
- 所有角色卡摘要

### 3. 完整对话历史（动态增长，上限 ~50K tokens）
- 整场游戏的完整消息

## Function Calling 设计

### roll_dice — 骰子裁决
```json
{
  "name": "roll_dice",
  "parameters": {
    "dice": "d20 / 2d6+3 / d100",
    "reason": "为什么掷骰",
    "difficulty": "DC（可选）",
    "character_name": "角色名"
  }
}
```

### update_state — 状态变更
```json
{
  "name": "update_state",
  "parameters": {
    "character_name": "角色名",
    "hp_delta": "生命变化",
    "add_item": "获得物品（可选）",
    "remove_item": "失去物品（可选）",
    "add_status": "新增状态（可选）",
    "remove_status": "移除状态（可选）",
    "narrative": "叙事描述"
  }
}
```

## 单次行动处理流程

```
1. 服务端收到 player_action
2. 构建 messages = [system_prompt, world_module, ...完整历史, 当前行动]
3. 调用 DeepSeek API（tools: [roll_dice, update_state]）
4. 如果 AI 调用了 roll_dice：
   → 服务端执行掷骰，将 tool_result 回传给 AI
   → AI 根据结果生成叙事
5. 如果 AI 调用了 update_state：
   → 服务端执行状态变更
6. 从 AI 最终回复中解析 [NEXT:角色名]
   → 广播 turn_change，切换到该玩家
   → 如未找到标记，按加入顺序轮转到下一人
7. 广播 gm_narrative / gm_dice_result / state_update
```

## AI 回复格式要求

System Prompt 中要求 AI 在每次叙事末尾包含：
```
[NEXT:角色名]
```

服务端解析此标记，验证角色名有效后切换回合。

## 游戏结束判定

AI 在剧情自然收尾时应输出：
```
[ENDING]建议结束理由[/ENDING]
```

服务端检测到此标记后，向房主发送提示"AI 建议结束游戏，是否结束？"，房主确认后结束。

## Token 预算

单局游戏约 50K tokens，1M 上下文下使用率 5%，余量极大。
