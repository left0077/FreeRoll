import { useState, useEffect, useRef } from "react";
import { api, setBackendUrl, getBackendUrl } from "../utils/api";
import { useCookie } from "../hooks/useCookie";

export default function HomePage({ onEnterLobby, onWorldBuilder }) {
  const { nickname, setNickname, savePlayerId, getPlayerId, getLastGame, clearLastGame } = useCookie();
  const urlParams = new URLSearchParams(window.location.search);
  const urlRoom = urlParams.get("room") || "";
  const [roomCode, setRoomCode] = useState(urlRoom.toUpperCase());
  const [showSettings, setShowSettings] = useState(false);
  const [backendUrl, setBackendUrlState] = useState(getBackendUrl);
  const [loading, setLoading] = useState(false);
  const [autoJoining, setAutoJoining] = useState(!!urlRoom);
  const [error, setError] = useState("");

  // Check for saved game
  const lastGame = getLastGame();

  // Auto-join: if room in URL and nickname already saved (not freshly typed), join immediately
  const nicknameLoaded = useRef(false);
  useEffect(() => {
    if (urlRoom && nickname.trim() && !loading && !nicknameLoaded.current) {
      nicknameLoaded.current = true;
      // Small delay so user sees the page before redirect
      setTimeout(() => handleJoin(), 300);
    }
  }, [urlRoom, nickname]);

  const handleCreate = async () => {
    if (!nickname.trim()) return setError("请输入你的昵称");
    setLoading(true);
    setError("");
    try {
      const data = await api("/api/rooms", {
        method: "POST",
        body: JSON.stringify({ nickname: nickname.trim(), character_mode: "create" }),
      });
      savePlayerId(data.code, data.player_id);
      onEnterLobby(data.code, data.player_id, true);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleJoin = async () => {
    if (!nickname.trim()) return setError("请输入你的昵称");
    if (!roomCode.trim()) return setError("请输入房间码");
    setLoading(true);
    setError("");
    try {
      const code = roomCode.trim().toUpperCase();
      const existingPlayerId = getPlayerId(code); // check if we've been here before
      const body = { nickname: nickname.trim() };
      if (existingPlayerId) body.player_id = existingPlayerId;

      const data = await api(`/api/rooms/${code}/join`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      savePlayerId(code, data.player_id);
      onEnterLobby(code, data.player_id, false);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleResume = async () => {
    if (!lastGame || !nickname.trim()) return;
    setLoading(true); setError("");
    try {
      const data = await api(`/api/rooms/${lastGame.roomCode}/join`, {
        method: "POST",
        body: JSON.stringify({ nickname: nickname.trim(), player_id: lastGame.playerId }),
      });
      onEnterLobby(lastGame.roomCode, data.player_id, false);
    } catch (e) { setError("无法重新加入：" + e.message); }
    setLoading(false);
  };

  const handleSaveSettings = () => {
    setBackendUrl(backendUrl);
    setShowSettings(false);
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-4">
      <h1 className="text-4xl font-bold text-amber-400 mb-2">FreeRoll</h1>
      <p className="text-gray-400 mb-8">AI 主持的文字跑团冒险</p>

      <div className="w-full max-w-sm space-y-4">
        {urlRoom && (
          <p className="text-amber-400 text-sm bg-amber-900/20 px-4 py-2 rounded-lg">你被邀请加入房间 {urlRoom.toUpperCase()}，输入昵称加入</p>
        )}

        <input
          className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white placeholder-gray-500 focus:border-amber-500 focus:outline-none"
          placeholder="你的昵称"
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
        />

        <button
          onClick={handleCreate}
          disabled={loading}
          className="w-full py-3 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold disabled:opacity-50"
        >
          {loading ? "创建中..." : "创建房间"}
        </button>

        <div className="flex items-center gap-2">
          <div className="flex-1 h-px bg-gray-700" />
          <span className="text-gray-500 text-sm">或</span>
          <div className="flex-1 h-px bg-gray-700" />
        </div>

        <input
          className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white placeholder-gray-500 focus:border-amber-500 focus:outline-none uppercase"
          placeholder="输入 6 位房间码"
          value={roomCode}
          onChange={(e) => setRoomCode(e.target.value.slice(0, 6))}
          maxLength={6}
        />

        <button
          onClick={handleJoin}
          disabled={loading}
          className="w-full py-3 rounded-lg bg-gray-700 hover:bg-gray-600 text-white font-bold disabled:opacity-50"
        >
          {loading ? "加入中..." : "加入房间"}
        </button>

        {lastGame && nickname && (
          <button onClick={handleResume} disabled={loading}
            className="w-full py-3 rounded-lg bg-green-700 hover:bg-green-600 text-white font-bold disabled:opacity-50">
            {loading ? "重新加入中..." : `继续游戏 → 房间 ${lastGame.roomCode}`}
          </button>
        )}

        {error && <p className="text-red-400 text-sm text-center">{error}</p>}
      </div>

      <div className="flex gap-4 mt-8">
        <button onClick={onWorldBuilder} className="text-gray-600 hover:text-amber-400 text-sm">
          世界观构建器
        </button>
        <button onClick={() => setShowSettings(!showSettings)} className="text-gray-600 hover:text-gray-400 text-sm">
          后端设置
        </button>
      </div>

      {showSettings && (
        <div className="mt-2 w-full max-w-sm space-y-2">
          <input
            className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm focus:border-amber-500 focus:outline-none"
            placeholder="后端地址，如 http://localhost:8000"
            value={backendUrl}
            onChange={(e) => setBackendUrlState(e.target.value)}
          />
          <button
            onClick={handleSaveSettings}
            className="w-full py-2 rounded bg-gray-700 hover:bg-gray-600 text-white text-sm"
          >
            保存
          </button>
        </div>
      )}
    </div>
  );
}
