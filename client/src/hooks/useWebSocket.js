import { useEffect, useRef, useCallback, useState } from "react";
import { getBackendUrl } from "../utils/api";

export function useWebSocket(roomCode, playerId) {
  const wsRef = useRef(null);
  const handlersRef = useRef({});
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const intentionalCloseRef = useRef(false);
  const [status, setStatus] = useState("disconnected"); // disconnected | connecting | connected | reconnecting

  const doConnect = useCallback(() => {
    if (!roomCode || !playerId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const base = getBackendUrl();
    const wsUrl = base.replace(/^http/, "ws");
    const url = `${wsUrl}/ws/${roomCode}?player_id=${playerId}`;

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      reconnectAttemptsRef.current = 0;
      // Call sync handler so the page can reload room state
      if (handlersRef.current["_reconnected"]) {
        handlersRef.current["_reconnected"]();
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      wsRef.current = null;
      // Auto-reconnect unless intentionally closed
      if (!intentionalCloseRef.current && roomCode && playerId) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 8000);
        reconnectAttemptsRef.current++;
        setStatus("reconnecting");
        reconnectTimerRef.current = setTimeout(doConnect, delay);
      }
    };

    ws.onerror = () => {
      // onclose will fire after this
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const type = data.type;
      const payload = data.payload || {};
      if (handlersRef.current[type]) {
        handlersRef.current[type](payload);
      }
      if (handlersRef.current["*"]) {
        handlersRef.current["*"](type, payload);
      }
    };
  }, [roomCode, playerId]);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus("disconnected");
  }, []);

  const on = useCallback((type, handler) => {
    handlersRef.current[type] = handler;
  }, []);

  const off = useCallback((type) => {
    delete handlersRef.current[type];
  }, []);

  const send = useCallback((type, payload = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, payload }));
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    return () => disconnect();
  }, [disconnect]);

  return { connect: doConnect, disconnect, send, on, off, status };
}
