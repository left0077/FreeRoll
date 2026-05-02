import { useState } from "react";

const PRESETS = ["d4", "d6", "d8", "d10", "d12", "d20", "d100", "2d6", "2d6+3", "d20+5"];

export default function DiceRoller({ onRoll, onClose }) {
  const [expression, setExpression] = useState("d20");

  return (
    <div className="space-y-2">
      <div className="flex gap-1.5 flex-wrap">
        {PRESETS.map((p) => (
          <button
            key={p}
            onClick={() => onRoll(p)}
            className="px-3 py-1.5 rounded bg-gray-800 border border-gray-700 text-white hover:border-amber-500 text-sm font-mono"
          >
            {p}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          className="flex-1 px-3 py-1.5 rounded bg-gray-800 border border-gray-700 text-white text-sm font-mono focus:border-amber-500 focus:outline-none"
          placeholder="自定义，如 3d8-2"
          value={expression}
          onChange={(e) => setExpression(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") onRoll(expression); }}
        />
        <button
          onClick={() => onRoll(expression)}
          className="px-4 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white text-sm font-bold"
        >
          掷
        </button>
      </div>
    </div>
  );
}
