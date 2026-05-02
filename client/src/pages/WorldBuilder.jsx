import { useState, useRef } from "react";
import { api } from "../utils/api";

const EMPTY_WORLD = {
  overview: "",
  factions: [],
  custom_rules: [],
  bar_schema: { "HP": { "default": 20, "description": "生命值" } },
  initial_scene: "",
};

export default function WorldBuilder({ onBack, onCreateRoom }) {
  const [world, setWorld] = useState(structuredClone(EMPTY_WORLD));
  const [jsonText, setJsonText] = useState("");
  const [mode, setMode] = useState("edit"); // edit | json | generate
  const [genType, setGenType] = useState("template");
  const [genRef, setGenRef] = useState("classic_dungeon");
  const [genSearch, setGenSearch] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const fileInputRef = useRef(null);

  const addFaction = () => setWorld((w) => ({ ...w, factions: [...w.factions, ""] }));
  const updateFaction = (i, v) => setWorld((w) => {
    const f = [...w.factions]; f[i] = v; return { ...w, factions: f };
  });
  const removeFaction = (i) => setWorld((w) => ({ ...w, factions: w.factions.filter((_, j) => j !== i) }));

  const addRule = () => setWorld((w) => ({ ...w, custom_rules: [...w.custom_rules, ""] }));
  const updateRule = (i, v) => setWorld((w) => {
    const r = [...w.custom_rules]; r[i] = v; return { ...w, custom_rules: r };
  });
  const removeRule = (i) => setWorld((w) => ({ ...w, custom_rules: w.custom_rules.filter((_, j) => j !== i) }));

  const addBar = () => {
    const name = prompt("数值条名称（如 SAN、好感度）：");
    if (!name) return;
    setWorld((w) => ({ ...w, bar_schema: { ...w.bar_schema, [name]: { default: 10, description: "" } } }));
  };
  const updateBar = (name, field, val) => setWorld((w) => ({
    ...w, bar_schema: { ...w.bar_schema, [name]: { ...w.bar_schema[name], [field]: field === "default" ? parseInt(val) || 0 : val } }
  }));
  const removeBar = (name) => setWorld((w) => {
    const bs = { ...w.bar_schema }; delete bs[name]; return { ...w, bar_schema: bs };
  });

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(world, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `freeroll_world_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result);
        setWorld(data);
        setError("已加载世界观文件");
        setTimeout(() => setError(""), 2000);
      } catch (err) {
        setError("JSON 解析失败，请检查文件格式");
      }
    };
    reader.readAsText(file);
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setError("");
    try {
      const type = genType === "search" ? "web_search" : "template";
      const ref = genType === "search" ? genSearch : genRef;
      const data = await api("/api/worlds/generate", {
        method: "POST",
        body: JSON.stringify({ type, ref, room_code: "" }),
      });
      if (data.content) {
        setWorld({
          overview: data.content.overview || "",
          factions: data.content.factions || [],
          custom_rules: data.content.custom_rules || [],
          bar_schema: data.content.bar_schema || { HP: { default: 20, description: "生命值" } },
          initial_scene: data.content.initial_scene || "",
        });
      }
      setMode("edit");
    } catch (e) {
      setError(e.message);
    }
    setGenerating(false);
  };

  const handleUseWorld = async () => {
    // Create room with this world pre-loaded
    try {
      const data = await api("/api/rooms", {
        method: "POST",
        body: JSON.stringify({ nickname: "房主", character_mode: "create" }),
      });
      // Attach world to room
      await api("/api/worlds/generate", {
        method: "POST",
        body: JSON.stringify({
          type: "template",
          ref: genRef,
          room_code: data.code,
        }),
      });
      // Override the generated world with our custom one
      const roomData = await api(`/api/rooms/${data.code}`);
      // We need to directly set the world... but there's no PUT for that.
      // Instead, we'll save the world JSON and let the user upload it in the lobby.
      onCreateRoom(data.code, data.player_id);
    } catch (e) {
      setError("创建房间失败：" + e.message);
    }
  };

  const handleApplyToRoom = async () => {
    // Save world to file, then prompt user to upload in lobby
    handleDownload();
    setError("已下载，请在等待室中使用上传 TXT 功能导入（或直接粘贴 JSON）");
    setTimeout(() => setError(""), 4000);
  };

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900 border-b border-gray-800">
        <button onClick={onBack} className="text-gray-400 hover:text-white text-sm">← 返回</button>
        <h1 className="text-amber-400 font-bold">世界观构建器</h1>
        <div className="flex gap-2">
          <button onClick={handleDownload} className="text-sm px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-white">
            {saved ? "已保存" : "下载 JSON"}
          </button>
          <button onClick={() => fileInputRef.current?.click()} className="text-sm px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-white">
            上传 JSON
          </button>
          <input ref={fileInputRef} type="file" accept=".json" onChange={handleUpload} className="hidden" />
        </div>
      </div>

      {/* Mode tabs */}
      <div className="flex gap-1 px-4 py-2 bg-gray-900/50 border-b border-gray-800">
        {["edit", "json", "generate"].map((m) => (
          <button key={m} onClick={() => setMode(m)}
            className={`px-4 py-1.5 rounded text-sm ${mode === m ? "bg-amber-600 text-white" : "text-gray-400 hover:text-white"}`}>
            {m === "edit" ? "可视化编辑" : m === "json" ? "JSON 编辑" : "AI 生成"}
          </button>
        ))}
      </div>

      <div className="max-w-3xl mx-auto p-4 md:p-8">
        {error && <p className={`text-sm mb-4 ${error.includes("已") || error.includes("成功") ? "text-green-400" : "text-red-400"}`}>{error}</p>}

        {mode === "edit" && (
          <div className="space-y-6">
            {/* Overview */}
            <div>
              <label className="block text-sm text-gray-400 mb-1">世界观概述</label>
              <textarea className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white focus:border-amber-500 focus:outline-none h-24 resize-none"
                value={world.overview} onChange={(e) => setWorld((w) => ({ ...w, overview: e.target.value }))}
                placeholder="描述这个世界的背景、时代、氛围..." />
            </div>

            {/* Factions */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm text-gray-400">势力/种族</label>
                <button onClick={addFaction} className="text-xs text-amber-400 hover:text-amber-300">+ 添加</button>
              </div>
              {world.factions.map((f, i) => (
                <div key={i} className="flex gap-2 mb-1">
                  <input className="flex-1 px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm focus:border-amber-500 focus:outline-none"
                    value={f} onChange={(e) => updateFaction(i, e.target.value)} placeholder={`势力 ${i + 1}`} />
                  <button onClick={() => removeFaction(i)} className="text-red-400 hover:text-red-300 text-sm">✕</button>
                </div>
              ))}
            </div>

            {/* Rules */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm text-gray-400">特色规则</label>
                <button onClick={addRule} className="text-xs text-amber-400 hover:text-amber-300">+ 添加</button>
              </div>
              {world.custom_rules.map((r, i) => (
                <div key={i} className="flex gap-2 mb-1">
                  <input className="flex-1 px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm focus:border-amber-500 focus:outline-none"
                    value={r} onChange={(e) => updateRule(i, e.target.value)} placeholder={`规则 ${i + 1}`} />
                  <button onClick={() => removeRule(i)} className="text-red-400 hover:text-red-300 text-sm">✕</button>
                </div>
              ))}
            </div>

            {/* Bar schema */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm text-gray-400">数值条</label>
                <button onClick={addBar} className="text-xs text-amber-400 hover:text-amber-300">+ 添加</button>
              </div>
              <div className="space-y-2">
                {Object.entries(world.bar_schema).map(([name, bar]) => (
                  <div key={name} className="flex items-center gap-2 p-2 rounded bg-gray-800/50 text-sm">
                    <span className="text-white font-bold w-20">{name}</span>
                    <input className="w-16 px-2 py-1 rounded bg-gray-700 border border-gray-600 text-white text-xs text-center"
                      type="number" value={bar.default} onChange={(e) => updateBar(name, "default", e.target.value)} />
                    <input className="flex-1 px-2 py-1 rounded bg-gray-700 border border-gray-600 text-white text-xs"
                      value={bar.description} onChange={(e) => updateBar(name, "description", e.target.value)}
                      placeholder="描述，如 生命值" />
                    <button onClick={() => removeBar(name)} className="text-red-400 hover:text-red-300 text-sm">✕</button>
                  </div>
                ))}
              </div>
            </div>

            {/* Initial scene */}
            <div>
              <label className="block text-sm text-gray-400 mb-1">初始场景</label>
              <textarea className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white focus:border-amber-500 focus:outline-none h-24 resize-none"
                value={world.initial_scene} onChange={(e) => setWorld((w) => ({ ...w, initial_scene: e.target.value }))}
                placeholder="游戏开始时的场景描述..." />
            </div>
          </div>
        )}

        {mode === "json" && (
          <div className="space-y-3">
            <p className="text-sm text-gray-400">直接编辑 JSON，修改后点击"应用"切回可视化模式</p>
            <textarea className="w-full px-4 py-3 rounded-lg bg-gray-800 border border-gray-700 text-white font-mono text-sm focus:border-amber-500 focus:outline-none h-96 resize-none"
              value={jsonText || JSON.stringify(world, null, 2)}
              onChange={(e) => setJsonText(e.target.value)} />
            <button onClick={() => {
              try {
                const parsed = JSON.parse(jsonText);
                setWorld(parsed);
                setMode("edit");
                setError("");
              } catch (e) {
                setError("JSON 格式错误：" + e.message);
              }
            }} className="px-4 py-2 rounded bg-amber-600 hover:bg-amber-500 text-white text-sm">
              应用 JSON
            </button>
          </div>
        )}

        {mode === "generate" && (
          <div className="max-w-md mx-auto space-y-4">
            <p className="text-sm text-gray-400">用 AI 生成世界观，然后可以在可视化编辑器中调整</p>
            <select className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm"
              value={genType} onChange={(e) => setGenType(e.target.value)}>
              <option value="template">预设模板</option>
              <option value="search">搜索作品</option>
            </select>
            {genType === "template" ? (
              <select className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm"
                value={genRef} onChange={(e) => setGenRef(e.target.value)}>
                <option value="classic_dungeon">经典地城</option>
                <option value="cthulhu_investigation">克苏鲁调查</option>
                <option value="cyberpunk_bar">赛博朋克酒吧</option>
              </select>
            ) : (
              <input className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-700 text-white text-sm"
                placeholder="输入作品名，如《诡秘之主》" value={genSearch} onChange={(e) => setGenSearch(e.target.value)} />
            )}
            <button onClick={handleGenerate} disabled={generating}
              className="w-full py-3 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold disabled:opacity-50">
              {generating ? "AI 生成中..." : "生成世界观"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
