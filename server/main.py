import os
from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
    try:
        await websocket.accept()
    except Exception:
        return  # Client already disconnected
    await handle_ws(websocket, room_code.upper(), player_id)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve frontend static files
dist_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")


@app.on_event("startup")
async def start_cleanup():
    import asyncio
    from services.room_manager import cleanup_idle_rooms
    async def cleanup_loop():
        while True:
            await asyncio.sleep(600)  # Every 10 minutes
            removed = cleanup_idle_rooms(60)
            if removed > 0:
                print(f"[CLEANUP] Removed {removed} idle rooms", flush=True)
    asyncio.create_task(cleanup_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
