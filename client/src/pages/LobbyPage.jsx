import { useState, useEffect } from "react";
import { api } from "../utils/api";
import { useWebSocket } from "../hooks/useWebSocket";

const TEMPLATES = [
  { key: "classic_dungeon", name: "经典地城", desc: "古老地下城中的失落宝藏" },
  { key: "cthulhu_investigation", name: "克苏鲁调查", desc: "不可名状的恐怖在等待" },
  { key: "cyberpunk_bar", name: "赛博朋克酒吧", desc: "霓虹之下，暗流涌动" },
];

export default function LobbyPage({ roomCode, playerId, isOwner, onGameStart, onLeave }) {
  const [room, setRoom] = useState(null);
  const [charDesc, setCharDesc] = useState("");
  const [generatingChar, setGeneratingChar] = useState(false);
  const [worldType, setWorldType] = useState("template");
  const [worldRef, setWorldRef] = useState("classic_dungeon");
  const [searchQuery, setSearchQuery] = useState("");
  const [generatingWorld, setGeneratingWorld] = useState(false);
  const [error, setError] = useState("");
  const [expandedChar, setExpandedChar] = useState(null);
  const [copied, setCopied] = useState(false);

  const { connect, disconnect, on, status } = useWebSocket(roomCode, playerId);

  useEffect(() => {
    connect();
    loadRoom();
    on("player_joined", loadRoom);
    on("player_left", loadRoom);
    on("game_started", onGameStart);
    on("error", (p) => setError(p.message));
    on("_reconnected", loadRoom);
    return () => disconnect();
  }, [roomCode]);

  const loadRoom = async () => {
    try {
      const data = await api(`/api/rooms/${roomCode}`);
      setRoom(data);
    } catch (e) {
      setError(e.message);
    }
  };

  // Listen for world updates
  useEffect(() => {
    on("world_updated", loadRoom);
    on("character_updated", loadRoom);
  }, [on]);

  const handleResetWorld = async () => {
    try {
      await api(`/api/worlds/${roomCode}`, { method: "DELETE" });
      await loadRoom();
    } catch (e) {
      setError(e.message);
    }
  };

  const handleDeleteChar = async (charId) => {
    try {
      await api(`/api/characters/${charId}?room_code=${roomCode}`, { method: "DELETE" });
      await loadRoom();
    } catch (e) {
      setError(e.message);
    }
  };

  const handleCopyLink = () => {
    const link = `${window.location.origin}${window.location.pathname}?room=${roomCode}`;
    navigator.clipboard.writeText(link).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleGenerateWorld = async () => {
    setGeneratingWorld(true);
    setError("");
    try {
      const body = { type: worldType, ref: worldType === "web_search" ? searchQuery : worldRef, room_code: roomCode };
      await api("/api/worlds/generate", { method: "POST", body: JSON.stringify(body) });
      await loadRoom();
    } catch (e) {
      setError(e.message);
    }
    setGeneratingWorld(false);
  };

  const handleGenerateChar = async () => {
    if (!charDesc.trim()) return;
    setGeneratingChar(true);
    setError("");
    try {
      await api("/api/characters/generate", {
        method: "POST",
        body: JSON.stringify({ room_code: roomCode, player_id: playerId, description: charDesc }),
      });
      await loadRoom();
      setCharDesc("");
    } catch (e) {
      setError(e.message);
    }
    setGeneratingChar(false);
  };

  const handleClaimPreset = async (index) => {
    try {
      await api("/api/characters/claim", {
        method: "POST",
        body: JSON.stringify({ room_code: roomCode, player_id: playerId, preset_index: index }),
      });
      await loadRoom();
    } catch (e) {
      setError(e.message);
    }
  };

  const handleStart = async () => {
    try {
      await api(`/api/rooms/${roomCode}/start?player_id=${playerId}`, { method: "POST" });
    } catch (e) {
      setError(e.message);
    }
  };

  if (!room) return <div className="min-h-screen flex items-center justify-center text-gray-400">加载中...</div>;

  const myChar = room.characters?.find((c) => c.player_id === playerId);
  const worldDone = !!room.world_module;
  const playersWithoutChar = room.players?.filter((p) => !room.characters?.find((c) => c.player_id === p.id)) || [];
  const allHaveChars = room.characters?.length >= room.players?.length && playersWithoutChar.length === 0;
  const canStart = isOwner && worldDone && allHaveChars && room.players?.length >= 1;

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* Left sidebar */}
      <div className="w-full md:w-80 bg-gray-900 border-r border-gray-800 p-4 flex flex-col gap-4 overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-amber-400">FreeRoll</h2>
          <button onClick={onLeave} className="text-gray-500 hover:text-gray-300 text-sm">离开</button>
        </div>

        {/* Room code with share link copy */}
        <div className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-2">
          <span className="text-gray-400 text-sm">房间码</span>
          <span className="text-white font-mono font-bold text-lg tracking-wider">{room.code}</span>
          <button onClick={handleCopyLink} className="ml-auto text-amber-400 hover:text-amber-300 text-sm">
            {copied ? "链接已复制" : "复制链接"}
          </button>
        </div>

        {/* Connection status */}
        {status !== "connected" && (
          <div className="text-xs text-yellow-400 bg-yellow-900/20 rounded px-2 py-1">
            {status === "reconnecting" ? "重连中..." : status === "connecting" ? "连接中..." : "已断开"}
          </div>
        )}

        {/* Players */}
        <div>
          <h3 className="text-sm text-gray-500 mb-2">冒险者 ({room.players?.length || 0}/12)</h3>
          {room.players?.map((p) => {
            const char = room.characters?.find((c) => c.player_id === p.id);
            return (
              <div key={p.id}>
                <div
                  className={`flex items-center gap-2 py-1.5 cursor-pointer ${p.id === playerId ? "text-amber-400" : "text-gray-300"} ${char ? "hover:text-white" : ""}`}
                  onClick={() => char && setExpandedChar(expandedChar === char.id ? null : char.id)}
                >
                  <span className={`w-2 h-2 rounded-full ${p.is_online ? "bg-green-500" : "bg-gray-600"}`} />
                  <span className="truncate">{p.nickname}{p.is_owner ? " 👑" : ""}</span>
                  {char ? (
                    <span className="text-xs text-gray-500 truncate">— {char.name}</span>
                  ) : (
                    <span className="text-xs text-red-400">未车卡</span>
                  )}
                  {char && <span className="text-gray-600 text-xs ml-auto">{expandedChar === char.id ? "▲" : "▼"}</span>}
                </div>
                {/* Expanded character card */}
                {char && expandedChar === char.id && (
                  <div className="ml-4 mb-2 p-2 rounded bg-gray-800/50 text-xs space-y-1">
                    <div className="flex justify-between">
                      <span className="text-white font-bold">{char.name}</span>
                    </div>
                    {char.bars && Object.entries(char.bars).map(([bn, b]) => (
                      <div key={bn} className="flex justify-between text-xs">
                        <span className="text-gray-500">{bn}</span>
                        <span className={b.current <= b.max * 0.3 ? "text-red-400" : "text-gray-300"}>{b.current}/{b.max}</span>
                      </div>
                    ))}
                    {char.tags?.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {char.tags.map((t) => <span key={t} className="px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-400">{t}</span>)}
                      </div>
                    )}
                    {char.description && <p className="text-gray-400">{char.description}</p>}
                    {char.inventory?.length > 0 && (
                      <p className="text-gray-500">物品：{char.inventory.join("、")}</p>
                    )}
                    {char.statuses?.length > 0 && (
                      <p className="text-purple-400">状态：{char.statuses.join("、")}</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* World management (owner only) */}
        {isOwner && worldDone && (
          <div className="border-t border-gray-800 pt-4">
            <button onClick={handleResetWorld} className="w-full py-2 rounded bg-gray-700 hover:bg-red-900/50 text-gray-400 hover:text-red-400 text-sm">
              重置世界观，重新选择
            </button>
          </div>
        )}
        {isOwner && !worldDone && (
          <div className="space-y-3 border-t border-gray-800 pt-4">
            <h3 className="text-sm font-bold text-gray-400">生成世界模组</h3>
            <select className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm"
              value={worldType} onChange={(e) => setWorldType(e.target.value)}>
              <option value="template">预设模板</option>
              <option value="web_search">搜索作品</option>
            </select>
            {worldType === "template" ? (
              <select className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm"
                value={worldRef} onChange={(e) => setWorldRef(e.target.value)}>
                {TEMPLATES.map((t) => <option key={t.key} value={t.key}>{t.name} — {t.desc}</option>)}
              </select>
            ) : (
              <input className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm"
                placeholder="输入作品名，如《诡秘之主》" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
            )}
            <button onClick={handleGenerateWorld} disabled={generatingWorld}
              className="w-full py-2 rounded bg-amber-600 hover:bg-amber-500 text-white text-sm font-bold disabled:opacity-50">
              {generatingWorld ? "AI 编织世界中..." : "生成世界"}
            </button>
          </div>
        )}

        {/* Preset characters + custom option */}
        {worldDone && room.world_module?.preset_characters?.length > 0 && !myChar && (
          <div className="space-y-2 border-t border-gray-800 pt-4">
            <h3 className="text-sm font-bold text-gray-400">选择预设角色</h3>
            {room.world_module.preset_characters.map((pc, i) => (
              <button key={i} onClick={() => handleClaimPreset(i)}
                className="w-full text-left px-3 py-2 rounded bg-gray-800 hover:bg-gray-700 text-white text-sm">
                <div className="font-bold">{pc.name}</div>
                <div className="text-xs text-gray-400">{pc.description}</div>
              </button>
            ))}
            <div className="border-t border-gray-700 pt-2 mt-2">
              <p className="text-xs text-gray-500 mb-1">或者创建你自己的角色：</p>
            </div>
          </div>
        )}

        {/* Start checklist */}
        {isOwner && (
          <div className="border-t border-gray-800 pt-4 space-y-1">
            <h3 className="text-sm font-bold text-gray-400 mb-1">准备状态</h3>
            <CheckItem ok={worldDone} label="世界模组已生成" />
            <CheckItem ok={room.players?.length >= 1} label={`玩家就位 (${room.players?.length}/12)`} />
            <CheckItem ok={allHaveChars} label={`全部车卡完成 (${room.characters?.length}/${room.players?.length})`} />
            {canStart && (
              <button onClick={handleStart}
                className="w-full mt-3 py-3 rounded-lg bg-green-600 hover:bg-green-500 text-white font-bold text-base">
                开始冒险！
              </button>
            )}
            {!canStart && worldDone && (
              <p className="text-xs text-gray-500 mt-1">等待所有玩家完成车卡...</p>
            )}
          </div>
        )}
      </div>

      {/* Right: Main area */}
      <div className="flex-1 p-4 md:p-8 overflow-y-auto">
        {error && <p className="text-red-400 text-sm text-center mb-4">{error}</p>}

        {/* Waiting for world */}
        {!worldDone && (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-2xl mb-2">等待房主生成世界模组...</p>
            <p className="text-sm">生成后即可创建或选择你的角色</p>
          </div>
        )}

        {/* World created - show overview */}
        {worldDone && (
          <div className="max-w-2xl mx-auto mb-8">
            <div className="p-4 rounded-lg bg-gray-800/50 border border-gray-700 space-y-3">
              <h3 className="text-amber-400 font-bold text-lg">
                {room.world_module?.source_ref === "classic_dungeon" ? "经典地城" :
                 room.world_module?.source_ref === "cthulhu_investigation" ? "克苏鲁调查" :
                 room.world_module?.source_ref === "cyberpunk_bar" ? "赛博朋克酒吧" :
                 room.world_module?.source_ref || "世界模组"}
              </h3>
              <p className="text-gray-300 text-sm leading-relaxed">
                {room.world_module?.content?.overview || "世界已就绪，等待冒险者..."}
              </p>
              {room.world_module?.content?.factions?.length > 0 && (
                <div className="text-sm text-gray-400">
                  势力：{room.world_module.content.factions.join(" · ")}
                </div>
              )}
              {room.world_module?.content?.custom_rules?.length > 0 && (
                <div className="text-sm text-amber-400/70">
                  规则：{room.world_module.content.custom_rules.join("；")}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Character creation - shown when world done, no character yet */}
        {worldDone && !myChar && (
          <div className="max-w-md mx-auto space-y-4">
            <h3 className="text-lg font-bold text-amber-400">
              {room.world_module?.preset_characters?.length > 0 ? "或自定义角色" : "创建你的角色"}
            </h3>
            <p className="text-sm text-gray-400">用一句话描述你想扮演的角色，AI 帮你生成完整角色卡</p>
            <textarea
              className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white placeholder-gray-500 focus:border-amber-500 focus:outline-none h-24 resize-none"
              placeholder="例如：沉默寡言的精灵弓箭手，背负着灭族之仇..."
              value={charDesc}
              onChange={(e) => setCharDesc(e.target.value)}
            />
            <button onClick={handleGenerateChar} disabled={generatingChar || !charDesc.trim()}
              className="w-full py-3 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold disabled:opacity-50">
              {generatingChar ? "AI 车卡中..." : "AI 生成角色"}
            </button>
          </div>
        )}

        {/* My character card with delete option */}
        {myChar && (
          <div className="max-w-md mx-auto space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-amber-400">你的角色</h3>
              <button onClick={() => handleDeleteChar(myChar.id)} className="text-xs text-gray-500 hover:text-red-400">
                删除重建
              </button>
            </div>
            <div className="p-4 rounded-lg bg-gray-800 border border-gray-700 space-y-3">
              <div className="flex justify-between items-start">
                <div>
                  <h4 className="text-xl font-bold text-white">{myChar.name}</h4>
                  <p className="text-sm text-gray-400 mt-1">{myChar.description}</p>
                </div>
                <div className="text-right space-y-1">
                  {myChar.bars && Object.entries(myChar.bars).map(([bn, b]) => (
                    <div key={bn}>
                      <div className="text-xs text-gray-500">{bn}</div>
                      <div className={`font-bold ${b.current <= b.max * 0.3 ? "text-red-400" : "text-white"}`}>
                        {b.current}/{b.max}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {myChar.tags?.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {myChar.tags.map((t) => <span key={t} className="px-2 py-0.5 rounded bg-amber-900/50 text-amber-400 text-xs">{t}</span>)}
                </div>
              )}
              {myChar.attributes && Object.keys(myChar.attributes).length > 0 && (
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(myChar.attributes).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-sm">
                      <span className="text-gray-500">{k}</span><span className="text-white">{v}</span>
                    </div>
                  ))}
                </div>
              )}
              {myChar.inventory?.length > 0 && (
                <div className="text-sm text-gray-400">物品：{myChar.inventory.join("、")}</div>
              )}
              {myChar.statuses?.length > 0 && (
                <div className="text-sm text-purple-400">状态：{myChar.statuses.join("、")}</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CheckItem({ ok, label }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={ok ? "text-green-400" : "text-gray-600"}>{ok ? "✅" : "○"}</span>
      <span className={ok ? "text-gray-300" : "text-gray-600"}>{label}</span>
    </div>
  );
}
