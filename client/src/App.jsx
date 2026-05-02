import { useState, useCallback, useEffect } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import HomePage from "./pages/HomePage";
import LobbyPage from "./pages/LobbyPage";
import GamePage from "./pages/GamePage";
import WorldBuilder from "./pages/WorldBuilder";

export default function App() {
  const [page, setPage] = useState("home");
  const [roomCode, setRoomCode] = useState("");
  const [playerId, setPlayerId] = useState("");
  const [isOwner, setIsOwner] = useState(false);

  // Shared WebSocket — connects when room is active, stays connected across pages
  const { connect, disconnect, send, on, off, status } = useWebSocket(roomCode, playerId);

  useEffect(() => {
    if (roomCode && playerId) connect();
    return () => {};
  }, [roomCode, playerId, connect]);

  const enterLobby = useCallback((code, pid, owner) => {
    setRoomCode(code);
    setPlayerId(pid);
    setIsOwner(owner);
    setPage("lobby");
  }, []);

  const enterGame = useCallback(() => setPage("game"), []);

  const backToHome = useCallback(() => {
    disconnect();
    setPage("home");
    setRoomCode("");
    setPlayerId("");
    setIsOwner(false);
  }, [disconnect]);

  const goToWorldBuilder = useCallback(() => setPage("worldbuilder"), []);

  const ws = { send, on, off, connected: status === "connected", status };

  if (page === "home") return <HomePage onEnterLobby={enterLobby} onWorldBuilder={goToWorldBuilder} />;
  if (page === "worldbuilder") return <WorldBuilder onBack={backToHome} />;
  if (page === "lobby") return <LobbyPage roomCode={roomCode} playerId={playerId} isOwner={isOwner} ws={ws} onGameStart={enterGame} onLeave={backToHome} />;
  return <GamePage roomCode={roomCode} playerId={playerId} isOwner={isOwner} ws={ws} onLeave={backToHome} />;
}
