export function TagChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 text-xs font-medium text-neutral-600">
      #{label}
    </span>
  );
}
