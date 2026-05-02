import { useState, useCallback } from "react";
import HomePage from "./pages/HomePage";
import LobbyPage from "./pages/LobbyPage";
import GamePage from "./pages/GamePage";
import WorldBuilder from "./pages/WorldBuilder";

export default function App() {
  const [page, setPage] = useState("home");
  const [roomCode, setRoomCode] = useState("");
  const [playerId, setPlayerId] = useState("");
  const [isOwner, setIsOwner] = useState(false);

  const enterLobby = useCallback((code, pid, owner) => {
    setRoomCode(code);
    setPlayerId(pid);
    setIsOwner(owner);
    setPage("lobby");
  }, []);

  const enterGame = useCallback(() => setPage("game"), []);

  const backToHome = useCallback(() => {
    setPage("home");
    setRoomCode("");
    setPlayerId("");
    setIsOwner(false);
  }, []);

  const goToWorldBuilder = useCallback(() => setPage("worldbuilder"), []);

  if (page === "home") return <HomePage onEnterLobby={enterLobby} onWorldBuilder={goToWorldBuilder} />;
  if (page === "worldbuilder") return <WorldBuilder onBack={backToHome} />;
  if (page === "lobby") return <LobbyPage roomCode={roomCode} playerId={playerId} isOwner={isOwner} onGameStart={enterGame} onLeave={backToHome} />;
  return <GamePage roomCode={roomCode} playerId={playerId} isOwner={isOwner} onLeave={backToHome} />;
}
