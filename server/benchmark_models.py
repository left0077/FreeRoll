"""Benchmark deepseek-v4-pro vs deepseek-v4-flash on speed and quality."""
import asyncio
import time
from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# Test prompts representing real game scenarios
TESTS = [
    ("世界生成", """为一个奇幻地下城冒险写一段120字的初始场景描述，要有氛围感。"""),
    ("车卡", """为"沉默寡言的精灵弓箭手，背负灭族之仇"生成跑团角色卡JSON。
{"name":"名字","attributes":{"力量":14,"敏捷":17,"智力":12,"魅力":8},"tags":["标签1","标签2","标签3"],"hp":20,"inventory":["物品1","物品2"],"description":"50字简介"}"""),
    ("玩家行动", """你是跑团主持人。玩家行动："我高举火把仔细观察前方黑暗的走廊，寻找陷阱和敌人踪迹"。请叙事描述结果，如需掷骰调用 roll_dice。末尾标记 [NEXT:艾林·星语]"""),
]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "roll_dice",
        "description": "掷骰判定",
        "parameters": {
            "type": "object",
            "properties": {
                "dice": {"type": "string"},
                "reason": {"type": "string"},
                "character_name": {"type": "string"},
            },
            "required": ["dice", "reason", "character_name"],
        },
    },
}]


async def test_model(model: str, name: str, prompt: str, use_tools: bool = False):
    start = time.time()
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8,
        "max_tokens": 1024,
    }
    if use_tools:
        kwargs["tools"] = TOOLS

    resp = await client.chat.completions.create(**kwargs)
    elapsed = time.time() - start
    msg = resp.choices[0].message
    content = msg.content or ""
    tool_calls = len(msg.tool_calls) if msg.tool_calls else 0

    return {
        "model": name,
        "time": round(elapsed, 2),
        "tokens_in": resp.usage.prompt_tokens,
        "tokens_out": resp.usage.completion_tokens,
        "content_preview": content[:120].replace('\n', ' '),
        "tool_calls": tool_calls,
    }


async def main():
    models = [
        ("deepseek-v4-flash", "Flash"),
        ("deepseek-v4-pro", "Pro"),
    ]

    print("=" * 70)
    print("DeepSeek v4-flash vs v4-pro 速度对比")
    print("=" * 70)

    for test_name, prompt in TESTS:
        use_tools = test_name == "玩家行动"
        print(f"\n--- {test_name} ---")
        print(f"Prompt: {prompt[:80]}...")

        results = []
        for model_id, label in models:
            print(f"  测试 {label}...", end=" ", flush=True)
            try:
                r = await test_model(model_id, label, prompt, use_tools)
                results.append(r)
                print(f"{r['time']}s | {r['tokens_in']}→{r['tokens_out']} tokens | {r['content_preview'][:80]}...")
            except Exception as e:
                print(f"ERROR: {e}")

        if len(results) == 2:
            f, p = results[0], results[1]
            speedup = round(p['time'] / f['time'], 1) if f['time'] > 0 else 0
            print(f"  ⚡ Flash 比 Pro 快 {speedup}x | Flash: {f['time']}s | Pro: {p['time']}s")

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)

asyncio.run(main())
