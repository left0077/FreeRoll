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
  }, []);

  const getPlayerId = useCallback((roomCode) => {
    return localStorage.getItem(PLAYER_KEY_PREFIX + roomCode) || null;
  }, []);

  return { nickname, setNickname, savePlayerId, getPlayerId };
}
