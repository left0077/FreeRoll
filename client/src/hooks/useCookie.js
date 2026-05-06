import { useState, useCallback } from "react";

const NICKNAME_KEY = "freeroll_nickname";
const PLAYER_KEY_PREFIX = "freeroll_player_";

export function useCookie() {
  const [nickname, setNicknameState] = useState(() => {
    return localStorage.getItem(NICKNAME_KEY) || "";
  });

  const setNickname = useCallback((name) => {
    localStorage.setItem(NICKNAME_KEY, name);
    setNicknameState(name);
  }, []);

  const savePlayerId = useCallback((roomCode, playerId) => {
    localStorage.setItem(PLAYER_KEY_PREFIX + roomCode, playerId);
    localStorage.setItem("freeroll_last_room", roomCode);
    localStorage.setItem("freeroll_last_player", playerId);
  }, []);

  const getPlayerId = useCallback((roomCode) => {
    return localStorage.getItem(PLAYER_KEY_PREFIX + roomCode) || null;
  }, []);

  const getLastGame = useCallback(() => {
    const code = localStorage.getItem("freeroll_last_room");
    const pid = localStorage.getItem("freeroll_last_player");
    if (code && pid) return { roomCode: code, playerId: pid };
    return null;
  }, []);

  const clearLastGame = useCallback(() => {
    localStorage.removeItem("freeroll_last_room");
    localStorage.removeItem("freeroll_last_player");
  }, []);

  return { nickname, setNickname, savePlayerId, getPlayerId, getLastGame, clearLastGame };
}
