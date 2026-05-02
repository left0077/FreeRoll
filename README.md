# FreeRoll

AI 驱动的多人在线自由跑团平台。AI 担任主持人，手机/电脑打开即玩。

## 技术栈

| 层 | 选型 |
|:---|:---|
| 前端 | React (Vite) + TailwindCSS |
| 后端 | Python FastAPI + uv |
| 存储 | 进程内存（无外部依赖） |
| AI | DeepSeek API |
| 实时 | WebSocket |

## 快速开始

```bash
# 后端
cd server
cp .env.example .env   # 填入 DEEPSEEK_API_KEY
uv run uvicorn main:app --reload

# 前端
cd client
npm install
npm run dev
```

## 项目结构

```
FreeRoll/
├── docs/
│   ├── architecture.md
│   ├── ai-engine.md
│   ├── data-model.md
│   └── api-design.md
├── server/
│   ├── main.py
│   ├── config.py
│   ├── routers/
│   ├── services/
│   └── ws/
└── client/
    └── src/
        ├── pages/
        ├── components/
        └── hooks/
```
