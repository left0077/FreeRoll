const STORAGE_KEY = "freeroll_backend_url";

export function getBackendUrl() {
  return localStorage.getItem(STORAGE_KEY) || "http://frp-cat.com:59745";
}

export function setBackendUrl(url) {
  localStorage.setItem(STORAGE_KEY, url);
}

// WebSocket request function (set by App when WS connects)
let _wsRequest = null;
export function setWsTransport(requestFn) { _wsRequest = requestFn; }

// Maps API paths + methods to WebSocket message types
const PATH_MAP = {
  "POST /api/rooms": "create_room",
  "GET /api/rooms/": "get_room",
  "POST /api/rooms/ /join": "join_room",
  "POST /api/rooms/ /start": "start_game",
  "POST /api/rooms/ /end": "end_game",
  "POST /api/rooms/ /rollback": "rollback_game",
  "POST /api/worlds/generate": "generate_world",
  "DELETE /api/worlds/": "reset_world",
  "POST /api/characters/generate": "generate_character",
  "POST /api/characters/claim": "claim_character",
  "DELETE /api/characters/": "delete_character",
  "PUT /api/characters/": "edit_character",
};

function findMessageType(method, path) {
  // Exact match first
  const key = `${method} ${path}`;
  if (PATH_MAP[key]) return PATH_MAP[key];
  // Prefix match for parameterized paths
  for (const [k, v] of Object.entries(PATH_MAP)) {
    const [kMethod, kPath] = k.split(" ", 2);
    if (method !== kMethod) continue;
    // Match path prefix: "GET /api/rooms/" matches "GET /api/rooms/ABC123"
    if (kPath.endsWith("/") && path.startsWith(kPath)) return v;
    // Match middle param: "POST /api/rooms/ /join" matches "POST /api/rooms/ABC/join"
    if (kPath.includes(" /")) {
      const parts = kPath.split(" /");
      if (path.startsWith(parts[0]) && path.endsWith("/" + parts[1])) return v;
    }
    // Match ending param: "DELETE /api/characters/" matches "DELETE /api/characters/ID"
    if (kPath.endsWith("/") && path.startsWith(kPath)) return v;
  }
  return null;
}

export async function api(path, options = {}) {
  const method = options.method || "GET";
  const body = options.body ? JSON.parse(options.body) : {};

  // Try WebSocket first
  if (_wsRequest) {
    const msgType = findMessageType(method, path);
    if (msgType) {
      try {
        // Add player_id from URL search params
        if (path.includes("player_id=")) {
          body.player_id = new URLSearchParams(path.split("?")[1] || "").get("player_id");
        }
        // Add character_id from path for DELETE/PUT
        if (msgType === "delete_character" || msgType === "edit_character") {
          const parts = path.split("/");
          body.character_id = parts[parts.length - 1].split("?")[0];
        }
        // Add room_code from path
        const roomMatch = path.match(/\/api\/rooms\/([A-Z0-9]+)/);
        if (roomMatch) body.room_code = roomMatch[1];
        const worldMatch = path.match(/\/api\/worlds\/([A-Z0-9]+)/);
        if (worldMatch && msgType === "reset_world") body.room_code = worldMatch[1];

        const resp = await _wsRequest(msgType, body);
        if (resp._error) throw new Error(resp._error);
        return resp.payload || resp;
      } catch (e) {
        // WS failed, fall through to HTTP
        if (e.message === "WebSocket not connected") {
          // Fall through
        } else {
          throw e;
        }
      }
    }
  }

  // HTTP fallback
  const base = getBackendUrl();
  const url = `${base}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}
