from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from routers import rooms, worlds, characters
from ws.handler import handle_ws
from config import HOST, PORT

app = FastAPI(title="FreeRoll", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rooms.router)
app.include_router(worlds.router)
app.include_router(characters.router)


@app.websocket("/ws/{room_code}")
async def ws_endpoint(websocket: WebSocket, room_code: str, player_id: str = Query(...)):
    await websocket.accept()
    await handle_ws(websocket, room_code.upper(), player_id)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
