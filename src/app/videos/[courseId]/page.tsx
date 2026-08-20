import Link from "next/link";
import { notFound } from "next/navigation";
import { allCourses } from "@/data/course";
import { TagChip } from "@/components/TagChip";
import { DifficultyDots } from "@/components/DifficultyDots";

export function generateStaticParams() {
  return allCourses.map((c) => ({ courseId: c.id }));
}

export default async function VideoDetailPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  const course = allCourses.find((c) => c.id === courseId);
  if (!course) notFound();

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col gap-6 px-4 py-8">
      <Link href="/" className="text-xs text-neutral-400 hover:text-neutral-600">
        ← 목록으로
      </Link>

      <header>
        <p className="text-xs font-medium text-neutral-400">{course.durationLabel}</p>
        <h1 className="mt-1 text-xl font-bold leading-snug text-neutral-900">{course.title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-neutral-600">{course.description}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {course.tags.map((t) => (
            <TagChip key={t} label={t} />
          ))}
        </div>
      </header>

      <Link
        href={`/videos/${course.id}/learn`}
        className="rounded-xl bg-neutral-900 px-4 py-3 text-center text-sm font-semibold text-white"
      >
        따라잡기 시작 · 학습 카드 {course.cards.length}개
      </Link>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-neutral-500">학습 카드</h2>
        {course.cards.map((card) => (
          <div key={card.id} className="rounded-2xl border border-neutral-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-neutral-400">
                {card.order}. {card.timeRange}
              </p>
              <DifficultyDots level={card.difficulty} />
            </div>
            <h3 className="mt-1 text-sm font-semibold leading-snug text-neutral-900">
              {card.title}
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-neutral-600">{card.summary}</p>
            <p className="mt-2 text-xs text-neutral-400">STEP {card.steps.length}개</p>
          </div>
        ))}
      </section>
    </main>
  );
}
