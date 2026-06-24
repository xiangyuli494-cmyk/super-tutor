import type { MasteryItem } from "../api/types";

interface Props {
  items: MasteryItem[];
}

const stateColors: Record<string, string> = {
  mastered: "bg-green-500",
  reviewing: "bg-blue-500",
  learning: "bg-yellow-500",
  new: "bg-gray-300",
};

export default function MasteryChart({ items }: Props) {
  if (!items.length) return null;

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const pct = Math.round((item.accuracy ?? 0) * 100);
        const color = stateColors[item.state ?? ""] ?? "bg-primary-500";
        return (
          <div key={item.knowledge_node_id}>
            <div className="flex justify-between text-xs mb-1">
              <span className="font-medium truncate mr-2">
                {item.knowledge_node_id}
              </span>
              <span className="text-gray-400">
                {item.correct_attempts}/{item.total_attempts} ({pct}%)
              </span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all ${color}`}
                style={{ width: `${Math.max(pct, 5)}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-400 mt-0.5">
              <span>{item.state}</span>
              {item.sm2_interval_days != null && (
                <span>间隔 {item.sm2_interval_days}d</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
