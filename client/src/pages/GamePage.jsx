import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "../utils/api";
import DiceRoller from "../components/DiceRoller";
import ReactMarkdown from "react-markdown";

const CHAR_COLORS = ["#f59e0b", "#3b82f6", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#84cc16", "#e11d48", "#6366f1", "#14b8a6"];
const getCharColor = (name) => {
  if (!name) return CHAR_COLORS[0];
  const idx = [...name].reduce((h, c) => h + c.charCodeAt(0), 0) % CHAR_COLORS.length;
  return CHAR_COLORS[idx];
};


export default function GamePage({ roomCode, playerId, isOwner, ws, onLeave }) {
  const [messages, setMessages] = useState([]);
  const [players, setPlayers] = useState([]);
  const [characters, setCharacters] = useState([]);
  const [currentPlayerId, setCurrentPlayerId] = useState(null);
  const [turnNumber, setTurnNumber] = useState(0);
  const [input, setInput] = useState("");
  const [processing, setProcessing] = useState(false);
  const [typingPlayers, setTypingPlayers] = useState({});
  const [showDice, setShowDice] = useState(false);
  const [showWorldBook, setShowWorldBook] = useState(false);
  const [showCharCard, setShowCharCard] = useState(false);
  const [rollRequest, setRollRequest] = useState(null);
  const [diceResult, setDiceResult] = useState(null);
  const [endingPrompt, setEndingPrompt] = useState(null);
  const [backendUrl, setBackendUrl] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [showDiceLog, setShowDiceLog] = useState(false);
  const [diceHistory, setDiceHistory] = useState([]);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [suggestedActions, setSuggestedActions] = useState([]);
  const [storyline, setStoryline] = useState(null);
  const [discoveries, setDiscoveries] = useState([]);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);

  const { send, on, status } = ws;

  const loadOnce = async () => {
    try {
      const data = await api(`/api/rooms/${roomCode}`);
      setMessages(data.messages || []);
      setPlayers(data.players || []);
      setCharacters(data.characters || []);
      setCurrentPlayerId(data.current_player_id);
      setTurnNumber(data.turn_number);
      if (data.world_module?.content) {
        localStorage.setItem("freeroll_world_" + roomCode, JSON.stringify(data.world_module.content));
        setStoryline(data.world_module.content.storyline || { title: "冒险之旅", stages: ["??", "??"] });
      }
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    loadOnce();
  }, [roomCode]);

  useEffect(() => {
    on("*", handleMessage);
  }, [on]);

  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const onScroll = () => setShowScrollBtn(el.scrollHeight - el.scrollTop - el.clientHeight > 200);
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Auto-scroll on new messages (only if we're near the bottom)
  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
    if (nearBottom || streamingText) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, typingPlayers, streamingText]);

  const handleMessage = useCallback((type, payload) => {
    // room_state or game_started — full state init via WebSocket
    if (type === "room_state" || type === "game_started") {
      setMessages(payload.messages || []);
      setPlayers(payload.players || []);
      setCharacters(payload.characters || []);
      setCurrentPlayerId(payload.current_player_id);
      setTurnNumber(payload.turn_number);
      setDiscoveries(payload.discoveries || []);
      setStreamingText("");  // Clean state on reconnect
      if (payload.world_module?.content) {
        localStorage.setItem("freeroll_world_" + roomCode, JSON.stringify(payload.world_module.content));
        setStoryline(payload.world_module.content.storyline || { title: "冒险之旅", stages: ["??", "??"] });
      }
      if (type === "game_started") return;
    }

    switch (type) {
      case "player_action_broadcast":
        // Show other players' actions in chat (own action already added locally)
        if (payload.player_id !== playerId) {
          setMessages((prev) => [...prev, { id: payload.id || Date.now(), type: "action", content: payload.content, player_id: payload.player_id, turn_number: payload.turn_number }]);
        }
        break;
      case "gm_narrative_chunk":
        setStreamingText((prev) => prev + payload.content);
        break;
      case "gm_narrative_chunk_done":
        setStreamingText((prev) => {
          if (prev) {
            setMessages((msgs) => [...msgs, { id: Date.now(), type: "narrative", content: prev, turn_number: payload.turn_number }]);
          }
          return "";
        });
        setProcessing(false);
        break;
      case "gm_narrative_done":
        setStreamingText((prev) => {
          if (prev) {
            setMessages((msgs) => [...msgs, { id: Date.now(), type: "narrative", content: prev, turn_number: payload.turn_number }]);
          }
          return "";
        });
        setProcessing(false);
        break;
      case "gm_narrative":
        // Finalize: streaming text (if any) becomes permanent message
        setStreamingText((prev) => {
          if (prev) {
            setMessages((msgs) => [...msgs, { id: Date.now(), type: "narrative", content: prev, turn_number: payload.turn_number }]);
          } else {
            setMessages((msgs) => [...msgs, { id: Date.now(), type: "narrative", content: payload.content, turn_number: payload.turn_number }]);
          }
          return "";
        });
        setSuggestedActions(payload.suggested_actions || []);
        setProcessing(false);
        break;
      case "gm_dice_result":
        setDiceResult({ ...payload, _anim: true, _ts: Date.now() });
        setTimeout(() => setDiceResult(null), 8000);
        setDiceHistory((prev) => [{ ...payload, _ts: Date.now() }, ...prev].slice(0, 50));
        setStreamingText("");  // Clear "等待掷骰..." — dice result is here
        setMessages((prev) => [...prev, {
          id: Date.now(), type: "dice",
          content: `${payload.character_name} ${payload.expression} = ${payload.total}`,
          metadata: payload,
        }]);
        break;
      case "state_update":
        const scParts = [];
        const bd = payload.bar_delta || {};
        for (const [k, v] of Object.entries(bd)) scParts.push(`${k} ${v > 0 ? '+' + v : v}`);
        if (payload.add_item) scParts.push(`获得 ${payload.add_item}`);
        if (payload.remove_item) scParts.push(`失去 ${payload.remove_item}`);
        if (payload.add_status) scParts.push(`⚡${payload.add_status}`);
        if (payload.remove_status) scParts.push(`解除 ${payload.remove_status}`);
        const scText = scParts.length > 0 ? `${payload.character_name} ${scParts.join('，')}` : (payload.narrative || `${payload.character_name} 状态变化`);
        setMessages((prev) => [...prev, { id: Date.now(), type: "system", content: scText, metadata: payload }]);
        // Update local character state
        setCharacters((prev) => prev.map((c) => {
          const matches = c.id === payload.character_id || c.name === payload.character_name;
          if (matches) {
            let bars = { ...c.bars };
            const barDelta = payload.bar_delta || {};
            for (const [name, delta] of Object.entries(barDelta)) {
              if (bars[name]) {
                bars[name] = { ...bars[name], current: Math.max(0, Math.min(bars[name].current + delta, bars[name].max)) };
              }
            }
            if (payload.add_bar) {
              bars[payload.add_bar.name] = { current: payload.add_bar.current || 0, max: payload.add_bar.max || 0 };
            }
            if (payload.remove_bar && bars[payload.remove_bar]) {
              delete bars[payload.remove_bar];
            }
            let inv = [...(c.inventory || [])];
            if (payload.add_item) inv.push(payload.add_item);
            if (payload.remove_item) inv = inv.filter((i) => i !== payload.remove_item);
            let st = [...(c.statuses || [])];
            if (payload.add_status) st.push(payload.add_status);
            if (payload.remove_status) st = st.filter((s) => s !== payload.remove_status);
            return { ...c, bars, inventory: inv, statuses: st };
          }
          return c;
        }));
        break;
      case "turn_change":
        setCurrentPlayerId(payload.current_player_id);
        setTurnNumber(payload.turn_number);
        // Clear old suggestions when turn changes — new ones come with next narrative
        if (payload.current_player_id !== playerId) setSuggestedActions([]);
        break;
      case "typing_indicator":
        setTypingPlayers((prev) => {
          const next = { ...prev };
          if (payload.is_typing) next[payload.player_id] = payload.nickname;
          else delete next[payload.player_id];
          return next;
        });
        break;
      case "roll_request":
        setRollRequest(payload);
        setStreamingText("");
        setProcessing(false);
        break;
      case "error":
        setProcessing(false);
        setRollRequest(null);
        if (!payload.player_id || payload.player_id === playerId) {
          setMessages((prev) => [...prev, { id: Date.now(), type: "system", content: `❌ ${payload.message}` }]);
        }
        break;
      case "discoveries_updated":
        setDiscoveries(payload.discoveries || []);
        break;
      case "plot_updated":
        setStoryline(payload.storyline);
        break;
      case "game_ending_prompt":
        setEndingPrompt(payload.reason);
        break;
      case "game_ended":
        setMessages((prev) => [...prev, { id: Date.now(), type: "system", content: "游戏结束！" }]);
        break;
      case "room_rollback":
        loadRoom();
        setProcessing(false);
        break;
      case "player_joined":
      case "player_left":
        loadRoom();
        break;
      case "player_chat":
        setMessages((prev) => [...prev, { id: Date.now(), type: "ooc", content: payload.content, player_id: payload.player_id, nickname: payload.nickname }]);
        break;
      case "error":
        setProcessing(false);
        break;
    }
  }, []);

  const handleSend = () => {
    if (!input.trim() || processing) return;
    const content = input.trim();
    setInput("");
    setProcessing(true);

    // OOC chat — add locally + broadcast
    if (content.startsWith("(OOC)") || content.startsWith("(ooc)")) {
      const oocContent = content.replace(/^\(OOC\)\s*/i, "");
      setMessages((prev) => [...prev, { id: Date.now(), type: "ooc", content: oocContent, player_id: playerId, nickname: players.find((p) => p.id === playerId)?.nickname }]);
      if (!send("player_chat", { content: oocContent })) {
        setProcessing(false);
      }
      return;
    }

    // Show player action immediately in chat
    const actionMsg = { id: Date.now(), type: "action", content, player_id: playerId, turn_number: turnNumber };
    setMessages((prev) => [...prev, actionMsg]);

    if (!send("player_action", { content })) {
      let retries = 0;
      const trySend = () => {
        if (send("player_action", { content })) {
          setProcessing(true);
          return;
        }
        retries++;
        if (retries < 5) setTimeout(trySend, 500 * retries);
        else {
          setProcessing(false);
          setMessages((prev) => [...prev, { id: Date.now(), type: "system", content: "❌ 连接未就绪，请刷新页面后重试" }]);
        }
      };
      trySend();
    }
  };

  const handleBack = () => onLeave();

  const handleRollback = async (toTurn) => {
    try {
      await api(`/api/rooms/${roomCode}/rollback`, {
        method: "POST",
        body: JSON.stringify({ to_turn: toTurn }),
      });
    } catch (e) {
      console.error(e);
    }
  };

  const handleEndGame = async () => {
    try {
      await api(`/api/rooms/${roomCode}/end?player_id=${playerId}`, { method: "POST" });
      setEndingPrompt(null);
    } catch (e) {
      console.error(e);
    }
  };

  const myChar = characters.find((c) => c.player_id === playerId);
  const isMyTurn = currentPlayerId === playerId;
  const typingNames = Object.values(typingPlayers);

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={handleBack} className="text-gray-500 hover:text-gray-300 text-sm">离开</button>
          <span className="text-gray-600">|</span>
          <span className="text-amber-400 font-bold text-sm">回合 {turnNumber}</span>
          <span className="text-gray-600">|</span>
          <button onClick={() => {
            const link = `${window.location.origin}${window.location.pathname}?room=${roomCode}`;
            navigator.clipboard.writeText(link);
          }} className="text-gray-500 hover:text-amber-400 text-xs">
            复制邀请链接
          </button>
          {status === "connected" && <span className="w-2 h-2 rounded-full bg-green-500" title="已连接" />}
          {status === "connecting" && <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" title="连接中..." />}
          {status === "reconnecting" && <span className="text-yellow-400 text-xs animate-pulse">重连中...</span>}
          {status === "disconnected" && <span className="text-red-400 text-xs">已断开</span>}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowDiceLog(!showDiceLog)} className="text-gray-400 hover:text-white text-sm">📊</button>
          <button onClick={() => setShowCharCard(!showCharCard)} className="text-gray-400 hover:text-white text-sm">📋</button>
          <button onClick={() => setShowWorldBook(!showWorldBook)} className="text-gray-400 hover:text-white text-sm">📖</button>
          {isOwner && (
            <button onClick={() => handleRollback(turnNumber - 1)} className="text-gray-400 hover:text-amber-400 text-sm" title="回溯到上一回合">
              ⏪
            </button>
          )}
        </div>
      </div>

      {/* Party status bar — always visible */}
      <div className="px-3 py-2 bg-gray-900 border-b border-gray-800 shrink-0 overflow-x-auto">
        <div className="flex gap-2 items-center min-w-max">
          {characters.map((c) => {
            const isCurrent = c.player_id === currentPlayerId;
            const owner = players.find((p) => p.id === c.player_id);
            return (
              <div key={c.id} className={`shrink-0 flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs transition-all ${isCurrent ? "bg-amber-900/40 border border-amber-600/50 ring-1 ring-amber-500/30" : "bg-gray-800/70 border border-transparent"}`}>
                <span className="font-bold" style={{color: getCharColor(c.name)}}>
                  {c.name}
                </span>
                {c.bars && Object.entries(c.bars).map(([bn, b]) => {
                  const pct = b.max > 0 ? b.current / b.max : 1;
                  return (
                    <div key={bn} className="flex items-center gap-1">
                      <span className="text-gray-500">{bn}</span>
                      <div className="w-12 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${pct <= 0.3 ? "bg-red-500" : pct <= 0.6 ? "bg-yellow-500" : "bg-green-500"}`} style={{width: `${pct*100}%`}} />
                      </div>
                      <span className={`font-mono ${pct <= 0.3 ? "text-red-400" : "text-gray-400"}`}>{b.current}</span>
                    </div>
                  );
                })}
                {c.statuses?.length > 0 && c.statuses.map((s) => (
                  <span key={s} className="text-purple-400 text-xs">⚡{s}</span>
                ))}
                {isCurrent && <span className="text-amber-400 text-xs animate-pulse">◀ 行动中</span>}
              </div>
            );
          })}
          <span className="text-gray-600 text-xs ml-1">回合 {turnNumber}</span>
        </div>
      </div>

      {/* Storyline progress */}
      {storyline && (
        <div className="px-3 py-1.5 bg-gray-900/70 border-b border-gray-800 shrink-0">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-amber-400 font-bold whitespace-nowrap">{storyline.title}</span>
            <div className="flex items-center gap-1 overflow-x-auto">
              {storyline.stages.map((s, i) => {
                // Find current stage: rightmost non-"??" stage
                const lastRevealed = storyline.stages.map((x, j) => x !== "??" ? j : -1).filter(j => j >= 0).pop() ?? -1;
                const isCompleted = i < lastRevealed;
                const isCurrent = i === lastRevealed;
                const isUnrevealed = s === "??";
                return (
                  <div key={i} className="flex items-center gap-1 shrink-0">
                    {i > 0 && <span className="text-gray-700">▸</span>}
                    <span className={`px-1.5 py-0.5 rounded text-xs ${
                      isCompleted ? "text-green-400 bg-green-900/20 line-through decoration-green-700" :
                      isCurrent ? "text-amber-300 bg-amber-900/30 font-bold" :
                      "text-gray-600 bg-gray-800/50"
                    }`}>
                      {isCompleted ? "✓" : ""} {isUnrevealed ? "???" : s}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Messages */}
      <div ref={messagesContainerRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3 relative">
        {messages.map((msg, i) => (
          <MessageBubble key={msg.id || i} msg={msg} players={players} characters={characters} />
        ))}

        {/* Current player indicator (visible when it's someone else's turn) */}
        {!isMyTurn && !processing && currentPlayerId && (
          <div className="flex items-center gap-2 text-sm pl-2 py-1 mb-1 bg-amber-900/10 rounded border border-amber-900/20">
            <span className="text-amber-400 animate-pulse text-lg">⏳</span>
            <span className="text-gray-400">
              <span className="text-amber-300 font-bold">{players.find((p) => p.id === currentPlayerId)?.nickname || "..."}</span>
              {' '}正在思考行动...
            </span>
          </div>
        )}

        {/* Typing indicator */}
        {typingNames.length > 0 && (
          <div className="flex items-center gap-2 text-amber-400/80 text-sm pl-2 py-1">
            <span>{typingNames.join(", ")} 正在输入</span>
            <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
          </div>
        )}

        {/* Streaming narrative */}
        {streamingText && (
          <div className="pl-3 border-l-2 border-amber-600/50">
            <p className="text-gray-200 leading-relaxed whitespace-pre-wrap">{streamingText}<span className="inline-block w-1.5 h-4 bg-amber-400 ml-0.5 animate-pulse" /></p>
          </div>
        )}

        {/* Processing indicator (only show when not streaming) */}
        {processing && !streamingText && (
          <div className="flex items-center gap-2 text-amber-400/70 text-sm pl-2">
            <span>命运编织中（{status}）</span>
            <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />
          </div>
        )}

        {/* Scroll to bottom button */}
        {showScrollBtn && (
          <button onClick={scrollToBottom} className="sticky bottom-2 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-gray-700/90 text-gray-300 text-xs hover:bg-gray-600 z-10">
            ↓ 回到底部
          </button>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Roll request overlay - AI asks player to roll */}
      {rollRequest && (
        <div className="fixed inset-0 flex items-center justify-center z-50 bg-black/60">
          <div className="px-8 py-6 rounded-2xl bg-gray-900 border-2 border-amber-500 text-center space-y-4 animate-pulse">
            <p className="text-gray-400 text-sm">{rollRequest.reason}</p>
            <p className="text-amber-400 text-4xl font-bold font-mono">{rollRequest.dice}</p>
            <p className="text-gray-500 text-sm">{rollRequest.character_name}</p>
            <button
              onClick={() => {
                if (send("roll_confirm", {})) {
                  setRollRequest(null);
                  setProcessing(true);
                }
              }}
              className="px-8 py-3 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-bold text-lg"
            >
              掷骰！
            </button>
            <p className="text-gray-600 text-xs">点击按钮掷骰（30秒后自动掷骰）</p>
          </div>
        </div>
      )}

      {/* Dice result overlay */}
      {diceResult && <DiceResultOverlay result={diceResult} />}

      {/* Dice roller panel */}
      {showDice && (
        <div className="border-t border-gray-800 bg-gray-900 px-4 py-3 shrink-0">
          <DiceRoller
            onRoll={(expr) => { send("dice_roll", { expression: expr }); setShowDice(false); }}
            onClose={() => setShowDice(false)}
          />
        </div>
      )}

      {/* Dice log panel */}
      {showDiceLog && (
        <div className="border-t border-gray-800 bg-gray-900 px-4 py-3 shrink-0 max-h-40 overflow-y-auto">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-amber-400 font-bold text-sm">骰子日志</h3>
            <button onClick={() => setShowDiceLog(false)} className="text-gray-500">✕</button>
          </div>
          {diceHistory.length === 0 ? (
            <p className="text-gray-500 text-xs">还没有掷骰记录</p>
          ) : (
            <div className="space-y-1 text-xs font-mono">
              {diceHistory.map((d, i) => (
                <div key={i} className={`flex justify-between ${d.is_critical === "critical_success" ? "text-yellow-400" : d.is_critical === "critical_failure" ? "text-red-400" : "text-gray-400"}`}>
                  <span>{d.character_name} {d.expression}</span>
                  <span>= {d.total} {d.is_critical ? (d.is_critical === "critical_success" ? "🎉" : "💀") : ""}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Character card panel - all party members */}
      {showCharCard && characters.length > 0 && (
        <div className="border-t border-gray-800 bg-gray-900 px-4 py-3 shrink-0 max-h-64 overflow-y-auto">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-amber-400 font-bold">冒险小队</h3>
            <button onClick={() => setShowCharCard(false)} className="text-gray-500">✕</button>
          </div>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {characters.map((c) => {
              const owner = players.find((p) => p.id === c.player_id);
              const isMe = c.player_id === playerId;
              return (
                <div key={c.id} className={`shrink-0 w-48 p-3 rounded-lg border ${isMe ? "border-amber-600 bg-amber-900/20" : "border-gray-700 bg-gray-800/50"}`}>
                  <div className="flex items-center gap-1 mb-1">
                    <span className="text-white font-bold text-sm truncate">{c.name}</span>
                    {isMe && <span className="text-amber-400 text-xs">(你)</span>}
                  </div>
                  <div className="text-xs text-gray-500 mb-1">{owner?.nickname || ""}</div>
                  {c.bars && Object.entries(c.bars).map(([barName, bar]) => {
                    const pct = bar.max > 0 ? bar.current / bar.max : 1;
                    const color = pct <= 0.3 ? "text-red-500" : pct <= 0.6 ? "text-yellow-500" : "text-green-400";
                    return (
                      <div key={barName} className="mb-1">
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-400">{barName}</span>
                          <span className={color}>{bar.current}/{bar.max}</span>
                        </div>
                        <div className="w-full h-1 bg-gray-700 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full transition-all ${pct <= 0.3 ? "bg-red-500" : pct <= 0.6 ? "bg-yellow-500" : "bg-green-500"}`} style={{ width: `${pct * 100}%` }} />
                        </div>
                      </div>
                    );
                  })}
                  {c.tags?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {c.tags.map((t) => <span key={t} className="px-1 py-0.5 rounded bg-amber-900/50 text-amber-400 text-xs">{t}</span>)}
                    </div>
                  )}
                  {c.statuses?.length > 0 && (
                    <div className="mt-1">
                      {c.statuses.map((s) => <span key={s} className="text-purple-400 text-xs block">⚡ {s}</span>)}
                    </div>
                  )}
                  {c.inventory?.length > 0 && (
                    <div className="mt-1 text-xs text-gray-500 truncate" title={c.inventory.join(", ")}>
                      📦 {c.inventory.slice(0, 3).join(", ")}{c.inventory.length > 3 ? "..." : ""}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* World book panel */}
      {showWorldBook && (
        <div className="border-t border-gray-800 bg-gray-900 px-4 py-3 shrink-0 max-h-64 overflow-y-auto">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-amber-400 font-bold text-sm">世界书</h3>
            <button onClick={() => setShowWorldBook(false)} className="text-gray-500">✕</button>
          </div>
          <div className="text-sm space-y-3">
            {/* Discoveries — dynamic */}
            {discoveries.length > 0 && (
              <div>
                <h4 className="text-gray-400 font-bold text-xs mb-1">已发现</h4>
                <div className="space-y-1">
                  {discoveries.map((d, i) => {
                    const icons = { npc: "👤", location: "📍", clue: "🔍", event: "⚡" };
                    return (
                      <div key={i} className="flex gap-1.5 text-xs">
                        <span>{icons[d.category] || "📌"}</span>
                        <span className="text-gray-300">{d.content}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {/* Static world info */}
            {(() => {
              try {
                const wm = JSON.parse(localStorage.getItem("freeroll_world_" + roomCode) || "{}");
                if (wm.overview) {
                  return (
                    <div>
                      <h4 className="text-gray-400 font-bold text-xs mb-1">世界设定</h4>
                      <p className="text-gray-500 text-xs">{wm.overview}</p>
                    </div>
                  );
                }
              } catch (e) {}
              return null;
            })()}
          </div>
        </div>
      )}

      {/* Ending prompt */}
      {endingPrompt && isOwner && (
        <div className="border-t border-amber-800 bg-amber-900/30 px-4 py-3 shrink-0">
          <div className="flex items-center justify-between">
            <span className="text-amber-400 text-sm">AI 建议结束游戏：{endingPrompt}</span>
            <div className="flex gap-2">
              <button onClick={() => setEndingPrompt(null)} className="px-3 py-1 rounded bg-gray-700 text-white text-sm">继续</button>
              <button onClick={handleEndGame} className="px-3 py-1 rounded bg-amber-600 text-white text-sm">结束游戏</button>
            </div>
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="border-t border-gray-800 bg-gray-900 px-4 py-3 shrink-0">
        {/* AI-suggested action capsules */}
        {suggestedActions.length > 0 && (
          <div className="flex gap-1.5 mb-2 overflow-x-auto pb-1">
            {suggestedActions.map((cap) => (
              <button
                key={cap}
                onClick={() => setInput(cap)}
                className="shrink-0 px-3 py-1 rounded-full bg-amber-900/30 border border-amber-800/50 text-amber-400 hover:bg-amber-900/50 hover:border-amber-600 text-xs whitespace-nowrap"
              >
                {cap}
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <input
            className="flex-1 px-4 py-2.5 rounded-lg bg-gray-800 border border-gray-700 text-white placeholder-gray-500 focus:border-amber-500 focus:outline-none"
            placeholder={isMyTurn ? "输入你的行动..." : "等待其他玩家行动..."}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              if (e.target.value && !processing) send("typing_start", {});
              else send("typing_end", {});
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
                send("typing_end", {});
              }
            }}
            disabled={!isMyTurn && !input.startsWith("(OOC)")}
          />
          {isMyTurn && !processing && (
            <button
              onClick={() => {
                const skipAction = `我暂时观望，等待局势进一步发展`;
                const msg = { id: Date.now(), type: "action", content: skipAction, player_id: playerId, turn_number: turnNumber };
                setMessages((prev) => [...prev, msg]);
                send("player_action", { content: skipAction });
                setProcessing(true);
              }}
              className="px-3 py-2.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-400 text-sm shrink-0"
            >
              跳过
            </button>
          )}
          <button
            onClick={() => { handleSend(); send("typing_end", {}); }}
            disabled={!input.trim() || processing || (!isMyTurn && !input.startsWith("(OOC)") && !input.startsWith("/d"))}
            className="px-4 py-2.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold disabled:opacity-50 shrink-0"
          >
            行动
          </button>
        </div>
        <div className="text-xs text-gray-600 mt-1">
          Enter 发送 | (OOC) 玩家对话
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ msg, players, characters }) {
  const player = msg.player_id ? players.find((p) => p.id === msg.player_id) : null;

  if (msg.type === "narrative") {
    return (
      <div className="pl-3 border-l-2 border-amber-600/50">
        <div className="text-gray-200 leading-relaxed narrative-content">
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              strong: ({ children }) => <strong className="text-amber-300 font-bold">{children}</strong>,
              em: ({ children }) => <em className="text-gray-400 italic">{children}</em>,
              ul: ({ children }) => <ul className="list-disc pl-4 my-1 space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-4 my-1 space-y-0.5">{children}</ol>,
              li: ({ children }) => <li className="text-gray-300">{children}</li>,
              h3: ({ children }) => <h3 className="text-amber-400 font-bold text-sm mt-3 mb-1">{children}</h3>,
              h4: ({ children }) => <h4 className="text-gray-300 font-bold text-sm mt-2 mb-1">{children}</h4>,
              blockquote: ({ children }) => <blockquote className="border-l-2 border-gray-600 pl-3 my-1 text-gray-400 italic">{children}</blockquote>,
              code: ({ children }) => <code className="bg-gray-800 px-1 py-0.5 rounded text-amber-400 text-xs">{children}</code>,
              hr: () => <hr className="border-gray-700 my-2" />,
              text: ({ value, children }) => {
                // Highlight character names in text nodes
                if (typeof value === 'string' && characters?.length) {
                  const names = characters.map(c => c.name).filter(Boolean).sort((a, b) => b.length - a.length);
                  if (names.length) {
                    const pattern = names.map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
                    const parts = value.split(new RegExp(`(${pattern})`, 'g'));
                    return parts.map((part, i) => {
                      const isName = names.includes(part);
                      return isName
                        ? <span key={i} style={{color: getCharColor(part), fontWeight: 'bold'}}>{part}</span>
                        : <span key={i}>{part}</span>;
                    });
                  }
                }
                return children || value;
              },
            }}
          >
            {msg.content}
          </ReactMarkdown>
        </div>
      </div>
    );
  }

  if (msg.type === "dice") {
    const meta = msg.metadata || {};
    const isCrit = meta.is_critical;
    const charName = meta.character_name;
    const nameColor = getCharColor(charName);
    return (
      <div className={`flex justify-center py-2 ${isCrit === "critical_success" ? "critical-success" : isCrit === "critical_failure" ? "critical-failure" : ""}`}>
        <div className={`px-4 py-2 rounded-lg text-sm font-mono ${isCrit === "critical_success" ? "bg-yellow-900/30 border border-yellow-600 text-yellow-400" : isCrit === "critical_failure" ? "bg-red-900/30 border border-red-600 text-red-400" : "bg-gray-800 text-gray-300"}`}>
          <span style={{color: nameColor, fontWeight: 'bold'}}>{charName || "??"}</span>
          <span> {meta.expression} = {meta.total}</span>
          {meta.dc != null && <span className="ml-2">DC {meta.dc} — {meta.success ? "✅ 成功" : "❌ 失败"}</span>}
          {isCrit === "critical_success" && <span className="ml-2">🎉 大成功！</span>}
          {isCrit === "critical_failure" && <span className="ml-2">💀 大失败！</span>}
        </div>
      </div>
    );
  }

  if (msg.type === "system") {
    return <p className="text-center text-purple-400 text-sm py-1">{msg.content}</p>;
  }

  if (msg.type === "action") {
    const char = characters?.find((c) => c.player_id === msg.player_id);
    const nameColor = getCharColor(char?.name);
    return (
      <div className="flex items-start gap-2 bg-amber-900/10 rounded-lg px-3 py-2 border border-amber-900/30">
        <span className="font-bold text-xs shrink-0 mt-0.5" style={{color: nameColor}}>{char?.name || player?.nickname || "冒险者"}</span>
        <span className="text-gray-200 text-sm">▸ {msg.content}</span>
      </div>
    );
  }

  if (msg.type === "ooc") {
    return (
      <div className="flex gap-2 pl-2 border-l-2 border-gray-700 opacity-70">
        <span className="text-gray-500 text-xs shrink-0">[{msg.nickname || player?.nickname || "玩家"}]</span>
        <p className="text-gray-400 text-xs italic">{msg.content}</p>
      </div>
    );
  }

  return null;
}

function DiceResultOverlay({ result }) {
  const isCrit = result.is_critical;
  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 pointer-events-none">
      <div className={`px-6 py-4 rounded-xl text-center ${isCrit === "critical_success" ? "bg-yellow-900/90 border-2 border-yellow-500" : isCrit === "critical_failure" ? "bg-red-900/90 border-2 border-red-500" : "bg-gray-900/90 border border-gray-700"}`}>
        <div className="text-xs text-gray-400 mb-1">{result.character_name}</div>
        <div className={`text-3xl font-bold ${isCrit === "critical_success" ? "text-yellow-400" : isCrit === "critical_failure" ? "text-red-400" : "text-white"}`}>
          {result.expression} = {result.total}
        </div>
        {result.rolls && <div className="text-sm text-gray-400">[ {result.rolls.join(", ")} ] + {result.bonus}</div>}
        {isCrit === "critical_success" && <div className="text-yellow-400 font-bold mt-1">大成功！</div>}
        {isCrit === "critical_failure" && <div className="text-red-400 font-bold mt-1">大失败！</div>}
      </div>
    </div>
  );
}
