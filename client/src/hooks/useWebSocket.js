import { useEffect, useRef, useCallback, useState } from "react";
import { getBackendUrl } from "../utils/api";

export function useWebSocket(roomCode, playerId) {
  const wsRef = useRef(null);
  const handlersRef = useRef({});
  const pendingRef = useRef({}); // { _rid: { resolve, reject, timer } }
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const intentionalCloseRef = useRef(false);
  const [status, setStatus] = useState("disconnected");

  const doConnect = useCallback(() => {
    if (!roomCode || !playerId) return;
    const ready = wsRef.current?.readyState;
    if (ready === WebSocket.OPEN || ready === WebSocket.CONNECTING) return;

    intentionalCloseRef.current = false;

    const base = getBackendUrl();
    const wsUrl = base.replace(/^http/, "ws");
    const url = `${wsUrl}/ws/${roomCode}?player_id=${playerId}`;
    console.log('[WS] Connecting to', url);

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WS] Connected');
      setStatus("connected");
      reconnectAttemptsRef.current = 0;
    };

    ws.onclose = (event) => {
      console.log('[WS] Closed', event.code, event.reason);
      // Reject all pending requests
      for (const [rid, p] of Object.entries(pendingRef.current)) {
        clearTimeout(p.timer);
        p.reject(new Error("WebSocket disconnected"));
        delete pendingRef.current[rid];
      }
      setStatus("disconnected");
      wsRef.current = null;
      if (!intentionalCloseRef.current && roomCode && playerId) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 8000);
        reconnectAttemptsRef.current++;
        console.log('[WS] Reconnecting in', delay, 'ms');
        setStatus("reconnecting");
        reconnectTimerRef.current = setTimeout(doConnect, delay);
      }
    };

    ws.onerror = (event) => { console.log('[WS] Error', event); };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const rid = data._rid;
      const type = data.type;
      const payload = data.payload || {};

      // Resolve pending request-response if matching _rid
      if (rid && pendingRef.current[rid]) {
        const p = pendingRef.current[rid];
        clearTimeout(p.timer);
        delete pendingRef.current[rid];
        if (data._error) p.reject(new Error(data._error));
        else p.resolve(data);
      }

      // Dispatch to registered event handlers
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

  // Request-response: sends a message and returns a Promise that resolves on response
  const request = useCallback((type, payload = {}, timeoutMs = 30000) => {
    return new Promise((resolve, reject) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        reject(new Error("WebSocket not connected"));
        return;
      }
      const rid = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
      const timer = setTimeout(() => {
        delete pendingRef.current[rid];
        reject(new Error("Request timed out"));
      }, timeoutMs);
      pendingRef.current[rid] = { resolve, reject, timer };
      wsRef.current.send(JSON.stringify({ type, payload, _rid: rid }));
    });
  }, []);

  useEffect(() => {
    return () => disconnect();
  }, [disconnect]);

  return { connect: doConnect, disconnect, send, request, on, off, status };
}
