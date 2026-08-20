import Link from "next/link";
import { allCourses } from "@/data/course";
import { TagChip } from "@/components/TagChip";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-6 px-4 py-10">
      <header>
        <p className="text-sm font-medium text-neutral-400">디자이너를 위한 AI 브리핑</p>
        <h1 className="mt-1 text-2xl font-bold text-neutral-900">Ddock</h1>
        <p className="mt-2 text-sm leading-relaxed text-neutral-600">
          영상 하나를 안 봐도 손으로 따라할 수 있는 학습 카드로 바꿔드려요. 액션만 표면에 남기고,
          궁금한 건 ⓘ로 열어보세요.
        </p>
      </header>

      <section className="flex flex-col gap-3">
        {allCourses.map((c) => (
          <Link
            key={c.id}
            href={`/videos/${c.id}`}
            className="block rounded-2xl border border-neutral-200 bg-white p-4 transition hover:border-neutral-400"
          >
            <p className="text-xs font-medium text-neutral-400">{c.durationLabel}</p>
            <h2 className="mt-1 text-base font-semibold leading-snug text-neutral-900">
              {c.title}
            </h2>
            <p className="mt-1.5 text-sm leading-relaxed text-neutral-600 line-clamp-2">
              {c.description}
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {c.tags.slice(0, 4).map((t) => (
                <TagChip key={t} label={t} />
              ))}
            </div>
          </Link>
        ))}
      </section>
    </main>
  );
}
