import type { Difficulty } from "@/lib/types";

const LEVELS: Difficulty[] = ["입문", "중급", "심화"];

export function DifficultyDots({ level }: { level: Difficulty }) {
  const activeIndex = LEVELS.indexOf(level);
  return (
    <span className="inline-flex items-center gap-2 text-xs text-neutral-500">
      <span className="flex gap-1">
        {LEVELS.map((_, i) => (
          <span
            key={i}
            className={`h-1.5 w-1.5 rounded-full ${
              i <= activeIndex ? "bg-neutral-800" : "bg-neutral-200"
            }`}
          />
        ))}
      </span>
      {level}
    </span>
  );
}
