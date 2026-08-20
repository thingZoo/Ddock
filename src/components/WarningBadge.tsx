import type { Warning } from "@/lib/types";

export function WarningBadge({ warning }: { warning: Warning }) {
  return (
    <div className="rounded-xl border border-amber-300 bg-amber-50 p-3">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-amber-500" aria-hidden>
          ⚠
        </span>
        <div>
          <p className="text-sm font-semibold text-amber-900">{warning.title}</p>
          <p className="mt-1 text-sm leading-relaxed text-amber-800 whitespace-pre-line">
            {warning.body}
          </p>
          {warning.timeRange && (
            <p className="mt-1.5 text-xs text-amber-600">{warning.timeRange}</p>
          )}
        </div>
      </div>
    </div>
  );
}
