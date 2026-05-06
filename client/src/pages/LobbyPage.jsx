import { useState, useEffect, useRef } from "react";
import { api } from "../utils/api";

const TEMPLATES = [
  { key: "isekai_adventure", name: "异世界冒险", desc: "剑与魔法的奇幻大陆，击败魔王军" },
  { key: "japanese_high_school", name: "日式校园高中", desc: "青春、恋爱与社团活动的每一天" },
  { key: "rainbow_six", name: "彩虹六号", desc: "精英反恐部队的战术行动" },
  { key: "animal_world", name: "动物世界", desc: "非洲草原上的生存与荣耀" },
  { key: "nailong_vs_laoda", name: "奶龙大战劳大", desc: "棉花糖火焰 vs 可乐炸弹！" },
  { key: "gambler_king", name: "赌王争霸", desc: "澳门赌场，筹码与心理的巅峰对决" },
];

export default function LobbyPage({ roomCode, playerId, isOwner, ws, onGameStart, onLeave }) {
  const [room, setRoom] = useState(null);
  const [charDesc, setCharDesc] = useState("");
  const [generatingChar, setGeneratingChar] = useState(false);
  const [worldType, setWorldType] = useState("template");
  const [worldRef, setWorldRef] = useState("isekai_adventure");
  const [searchQuery, setSearchQuery] = useState("");
  const [generatingWorld, setGeneratingWorld] = useState(false);
  const [worldGenText, setWorldGenText] = useState("");
  const worldGenRef = useRef(null);
  const [style, setStyle] = useState("");
  const [tone, setTone] = useState("");
  const [customStyle, setCustomStyle] = useState("");
  const [error, setError] = useState("");
  const [expandedChar, setExpandedChar] = useState(null);
  const [copied, setCopied] = useState(false);

  const { on, status } = ws;

  useEffect(() => {
    loadRoom();
    on("player_joined", loadRoom);
    on("player_left", loadRoom);
    on("game_started", onGameStart);
    on("error", (p) => setError(p.message));
  }, [roomCode]);

  const loadRoom = async () => {
    try {
      const data = await api(`/api/rooms/${roomCode}`);
      setRoom(data);
    } catch (e) { setError(e.message); }
  };

  useEffect(() => {
    on("world_updated", () => { loadRoom(); });
    on("character_updated", loadRoom);
    on("world_gen_chunk", (p) => {
      setWorldGenText((prev) => prev + p.content);
    });
    on("world_gen_done", () => {});
  }, [on]);

  const handleResetWorld = async () => {
    try { await api(`/api/worlds/${roomCode}`, { method: "DELETE" }); await loadRoom(); }
    catch (e) { setError(e.message); }
  };

  const handleDeleteChar = async (charId) => {
    try { await api(`/api/characters/${charId}?room_code=${roomCode}`, { method: "DELETE" }); await loadRoom(); }
    catch (e) { setError(e.message); }
  };

  const handleCopyLink = () => {
    const link = `${window.location.origin}${window.location.pathname}?room=${roomCode}`;
    navigator.clipboard.writeText(link).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleGenerateWorld = async () => {
    setGeneratingWorld(true); setError(""); setWorldGenText("");
    try {
      const body = { type: worldType, ref: worldType === "web_search" ? searchQuery : worldRef, room_code: roomCode,
        style, tone, custom_style: customStyle };
      await api("/api/worlds/generate", { method: "POST", body: JSON.stringify(body) });
      await loadRoom();
    } catch (e) { setError(e.message); }
    // Brief delay so user can see the completed streaming text before transition
    setTimeout(() => {
      setGeneratingWorld(false);
      setWorldGenText("");
    }, 500);
  };

  const handleGenerateChar = async () => {
    if (!charDesc.trim()) return;
    setGeneratingChar(true); setError("");
    try {
      await api("/api/characters/generate", { method: "POST", body: JSON.stringify({ room_code: roomCode, player_id: playerId, description: charDesc }) });
      await loadRoom(); setCharDesc("");
    } catch (e) { setError(e.message); }
    setGeneratingChar(false);
  };

  const handleClaimPreset = async (index) => {
    try {
      await api("/api/characters/claim", { method: "POST", body: JSON.stringify({ room_code: roomCode, player_id: playerId, preset_index: index }) });
      await loadRoom();
    } catch (e) { setError(e.message); }
  };

  const handleStart = async () => {
    try { await api(`/api/rooms/${roomCode}/start?player_id=${playerId}`, { method: "POST" }); }
    catch (e) { setError(e.message); }
  };

  if (!room) return <div className="min-h-screen flex items-center justify-center text-gray-400">加载中...</div>;

  const myChar = room.characters?.find((c) => c.player_id === playerId);
  const worldDone = !!room.world_module;
  const playersWithoutChar = room.players?.filter((p) => !room.characters?.find((c) => c.player_id === p.id)) || [];
  const allHaveChars = room.characters?.length >= room.players?.length && playersWithoutChar.length === 0;
  const canStart = isOwner && worldDone && allHaveChars && room.players?.length >= 1;

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* Left sidebar — players & status only */}
      <div className="w-full md:w-64 bg-gray-900 border-r border-gray-800 p-4 flex flex-col gap-4 overflow-y-auto shrink-0">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-amber-400">FreeRoll</h2>
          <button onClick={onLeave} className="text-gray-500 hover:text-gray-300 text-sm">离开</button>
        </div>

        <div className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-2">
          <span className="text-gray-400 text-sm">房间码</span>
          <span className="text-white font-mono font-bold text-lg tracking-wider">{room.code}</span>
          <button onClick={handleCopyLink} className="ml-auto text-amber-400 hover:text-amber-300 text-sm">
            {copied ? "已复制" : "复制链接"}
          </button>
        </div>

        {status !== "connected" && (
          <div className="text-xs text-yellow-400 bg-yellow-900/20 rounded px-2 py-1">
            {status === "reconnecting" ? "重连中..." : status === "connecting" ? "连接中..." : "已断开"}
          </div>
        )}

        <div>
          <h3 className="text-sm text-gray-500 mb-2">冒险者 ({room.players?.length || 0}/12)</h3>
          {room.players?.map((p) => {
            const char = room.characters?.find((c) => c.player_id === p.id);
            return (
              <div key={p.id}>
                <div className={`flex items-center gap-2 py-1.5 cursor-pointer ${p.id === playerId ? "text-amber-400" : "text-gray-300"}`}
                  onClick={() => char && setExpandedChar(expandedChar === char.id ? null : char.id)}>
                  <span className={`w-2 h-2 rounded-full ${p.is_online ? "bg-green-500" : "bg-gray-600"}`} />
                  <span className="truncate text-sm">{p.nickname}{p.is_owner ? " 👑" : ""}</span>
                  {char ? <span className="text-xs text-gray-500 truncate">— {char.name}</span> : <span className="text-xs text-red-400">未车卡</span>}
                </div>
                {char && expandedChar === char.id && (
                  <div className="ml-4 mb-2 p-2 rounded bg-gray-800/50 text-xs space-y-1">
                    <span className="text-white font-bold">{char.name}</span>
                    {char.bars && Object.entries(char.bars).map(([bn, b]) => (
                      <div key={bn} className="flex justify-between"><span className="text-gray-500">{bn}</span><span className={b.current <= b.max * 0.3 ? "text-red-400" : "text-gray-300"}>{b.current}/{b.max}</span></div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {isOwner && (
          <div className="border-t border-gray-800 pt-4 space-y-1">
            <h3 className="text-sm font-bold text-gray-400 mb-1">准备状态</h3>
            <CheckItem ok={worldDone} label="世界模组已生成" />
            <CheckItem ok={room.players?.length >= 1} label={`玩家就位 (${room.players?.length}/12)`} />
            <CheckItem ok={allHaveChars} label={`全部车卡完成 (${room.characters?.length}/${room.players?.length})`} />
            {canStart && (
              <button onClick={handleStart} className="w-full mt-3 py-3 rounded-lg bg-green-600 hover:bg-green-500 text-white font-bold text-base">
                开始冒险！
              </button>
            )}
            {!canStart && worldDone && <p className="text-xs text-gray-500 mt-1">等待所有玩家完成车卡...</p>}
          </div>
        )}
      </div>

      {/* Right — main interactive area */}
      <div className="flex-1 p-4 md:p-8 overflow-y-auto">
        {error && <p className="text-red-400 text-sm text-center mb-4">{error}</p>}

        {/* === World generation === */}
        {isOwner && !worldDone && !generatingWorld ? (
          <div className="max-w-lg mx-auto space-y-4">
            <h3 className="text-lg font-bold text-amber-400">生成世界模组</h3>
            <p className="text-sm text-gray-400">选择一种方式创建游戏世界观</p>
            <div className="flex gap-2">
              {["template", "web_search"].map((t) => (
                <button key={t} onClick={() => setWorldType(t)}
                  className={`flex-1 py-2 rounded-lg text-sm font-bold ${worldType === t ? "bg-amber-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"}`}>
                  {t === "template" ? "预设模板" : "自由描述"}
                </button>
              ))}
            </div>
            {worldType === "template" ? (
              <div className="grid gap-2">
                {TEMPLATES.map((t) => (
                  <button key={t.key} onClick={() => { setWorldRef(t.key); }}
                    className={`w-full text-left px-4 py-3 rounded-lg border ${worldRef === t.key ? "border-amber-600 bg-amber-900/20" : "border-gray-700 bg-gray-800/50 hover:border-gray-600"}`}>
                    <div className="text-white font-bold">{t.name}</div>
                    <div className="text-xs text-gray-400">{t.desc}</div>
                  </button>
                ))}
              </div>
            ) : (
              <input className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:border-amber-500 focus:outline-none"
                placeholder="描述你想要的世界，如：赛博朋克修仙门派" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
            )}
            {/* Style: button selects */}
            <div>
              <p className="text-xs text-gray-500 mb-1.5">文风（可选）</p>
              <div className="flex flex-wrap gap-1.5">
                {["", "圣经体", "文言文", "申论风", "轻小说", "硬核写实", "喷子体"].map((s) => (
                  <button key={s} type="button" onClick={() => setStyle(style === s ? "" : s)}
                    className={`px-3 py-1 rounded-full text-xs ${style === s ? "bg-amber-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"}`}>
                    {s || "默认"}
                  </button>
                ))}
                <input className="w-24 px-2 py-1 rounded-full bg-gray-800 border border-gray-700 text-white text-xs focus:border-amber-500 focus:outline-none"
                  placeholder="自定义..." value={style && !["圣经体","文言文","申论风","轻小说","硬核写实","喷子体"].includes(style) ? style : ""}
                  onChange={(e) => setStyle(e.target.value)} />
              </div>
            </div>
            {/* Plot tightness: button selects */}
            <div>
              <p className="text-xs text-gray-500 mb-1.5">主线紧密度</p>
              <div className="flex flex-wrap gap-1.5">
                {[{v:"strict",l:"紧扣主线"},{v:"guided",l:"适度引导"},{v:"free",l:"自由发挥"}].map((o) => (
                  <button key={o.v} type="button" onClick={() => setTone(tone === o.v ? "" : o.v)}
                    className={`px-3 py-1 rounded-full text-xs ${tone === o.v ? "bg-amber-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"}`}>
                    {o.l}
                  </button>
                ))}
              </div>
            </div>
            <input className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm focus:border-amber-500 focus:outline-none"
              placeholder="额外创作要求（可选），如：禁止出现魔法少女" value={customStyle} onChange={(e) => setCustomStyle(e.target.value)} />
            <button onClick={handleGenerateWorld} disabled={generatingWorld}
              className="w-full py-3 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold disabled:opacity-50">
              {generatingWorld ? "AI 编织世界中..." : "生成世界"}
          </button>
          </div>
        ) : !worldDone && !generatingWorld ? (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-2xl mb-2">等待房主生成世界模组...</p>
            <p className="text-sm">生成后即可创建或选择你的角色</p>
          </div>
        ) : null}

        {/* === World overview — shows streaming text during generation === */}
        {(worldDone || generatingWorld) && (
          <div className="max-w-2xl mx-auto mb-8">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-amber-400 font-bold text-lg">
                {generatingWorld ? "正在生成世界..." : TEMPLATES.find((t) => t.key === room.world_module?.source_ref)?.name || room.world_module?.source_ref || "世界模组"}
              </h3>
              {isOwner && worldDone && (
                <button onClick={handleResetWorld} className="text-xs text-gray-500 hover:text-red-400">重置</button>
              )}
            </div>
            <div className="p-4 rounded-lg bg-gray-800/50 border border-gray-700 space-y-3">
              {generatingWorld ? (
                <p ref={worldGenRef} className="text-gray-300 text-sm leading-relaxed">
                  <span className="inline-block w-1.5 h-4 bg-amber-400 animate-pulse" />
                </p>
              ) : (
                <>
                  <p className="text-gray-300 text-sm leading-relaxed">
                    {room.world_module?.content?.overview || "世界已就绪，等待冒险者..."}
                  </p>
                  {room.world_module?.content?.factions?.length > 0 && (
                    <div className="text-sm text-gray-400">势力：{room.world_module.content.factions.join(" · ")}</div>
                  )}
                  {room.world_module?.content?.custom_rules?.length > 0 && (
                    <div className="text-sm text-amber-400/70">规则：{room.world_module.content.custom_rules.join("；")}</div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* === Preset character selection === */}
        {worldDone && room.world_module?.preset_characters?.length > 0 && !myChar && (
          <div className="max-w-lg mx-auto mb-6">
            <h3 className="text-amber-400 font-bold mb-3">选择预设角色</h3>
            <div className="grid gap-2">
              {room.world_module.preset_characters.map((pc, i) => {
                const claimed = room.characters?.some((c) => c.name === pc.name);
                return (
                  <button key={i} onClick={() => !claimed && handleClaimPreset(i)} disabled={claimed}
                    className={`w-full text-left px-4 py-3 rounded-lg border text-sm ${claimed ? "border-gray-800 bg-gray-800/20 text-gray-600 cursor-not-allowed" : "border-gray-700 bg-gray-800/50 hover:border-amber-600 text-white"}`}>
                    <div className="font-bold flex items-center gap-2">
                      {pc.name}
                      {claimed && <span className="text-xs text-gray-500 font-normal">（已被认领）</span>}
                    </div>
                    <div className="text-xs text-gray-400">{pc.description}</div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* === Character creation === */}
        {worldDone && !myChar && (
          <div className="max-w-md mx-auto space-y-4">
            <h3 className="text-lg font-bold text-amber-400">
              {room.world_module?.preset_characters?.length > 0 ? "或者，自定义角色" : "创建你的角色"}
            </h3>
            <p className="text-sm text-gray-400">用一句话描述你想扮演的角色，AI 帮你生成完整角色卡</p>
            <textarea className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white placeholder-gray-500 focus:border-amber-500 focus:outline-none h-24 resize-none"
              placeholder="例如：沉默寡言的精灵弓箭手，背负着灭族之仇..."
              value={charDesc} onChange={(e) => setCharDesc(e.target.value)} />
            <button onClick={handleGenerateChar} disabled={generatingChar || !charDesc.trim()}
              className="w-full py-3 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold disabled:opacity-50">
              {generatingChar ? "AI 车卡中..." : "AI 生成角色"}
            </button>
          </div>
        )}

        {/* === My character === */}
        {myChar && (
          <div className="max-w-md mx-auto space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-amber-400">你的角色</h3>
              <button onClick={() => handleDeleteChar(myChar.id)} className="text-xs text-gray-500 hover:text-red-400">删除重建</button>
            </div>
            {room?.status === "playing" && (
              <button onClick={onGameStart}
                className="w-full py-3 rounded-lg bg-green-600 hover:bg-green-500 text-white font-bold text-base">
                进入游戏
              </button>
            )}
            <div className="p-4 rounded-lg bg-gray-800 border border-gray-700 space-y-3">
              <div className="flex justify-between items-start">
                <div>
                  <h4 className="text-xl font-bold text-white">{myChar.name}</h4>
                  <p className="text-sm text-gray-400 mt-1">{myChar.description}</p>
                </div>
                <div className="text-right space-y-1">
                  {myChar.bars && Object.entries(myChar.bars).map(([bn, b]) => (
                    <div key={bn}><div className="text-xs text-gray-500">{bn}</div>
                      <div className={`font-bold ${b.current <= b.max * 0.3 ? "text-red-400" : "text-white"}`}>{b.current}/{b.max}</div>
                    </div>
                  ))}
                </div>
              </div>
              {myChar.tags?.length > 0 && (
                <div className="flex flex-wrap gap-1.5">{myChar.tags.map((t) => <span key={t} className="px-2 py-0.5 rounded bg-amber-900/50 text-amber-400 text-xs">{t}</span>)}</div>
              )}
              {myChar.attributes && Object.keys(myChar.attributes).length > 0 && (
                <div className="grid grid-cols-2 gap-2">{Object.entries(myChar.attributes).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm"><span className="text-gray-500">{k}</span><span className="text-white">{v}</span></div>
                ))}</div>
              )}
              {myChar.inventory?.length > 0 && <div className="text-sm text-gray-400">物品：{myChar.inventory.join("、")}</div>}
              {myChar.statuses?.length > 0 && <div className="text-sm text-purple-400">状态：{myChar.statuses.join("、")}</div>}
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
