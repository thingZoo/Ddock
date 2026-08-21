import Link from "next/link";
import Image from "next/image";
import { allCourses } from "@/data/course";

/**
 * 임시 홈 — 메인 홈 화면은 팀원이 만들어요 (feature/home).
 * 여기서는 상세페이지로 들어가는 입구만 둡니다.
 */
export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[var(--app-w)] flex-col gap-4 bg-white px-4 py-10">
      <div>
        <p className="t-xs-medium text-zinc-500">디자이너를 위한 AI 브리핑</p>
        <h1 className="t-xl-bold pt-1 text-zinc-900">Ddock</h1>
        <p className="t-xs-body pt-2 text-zinc-600">
          메인 홈 화면은 팀원이 만들고 있어요. 지금은 상세페이지로 바로 들어가는 입구만 있습니다.
        </p>
      </div>

      {allCourses.map((c) => (
        <Link
          key={c.id}
          href={`/videos/${c.id}`}
          className="flex flex-col gap-3 rounded-card border border-border bg-white p-4"
        >
          <div className="relative h-[144px] w-full overflow-hidden rounded-lg">
            <Image src={c.thumbnail} alt="" fill sizes="343px" className="object-cover" />
          </div>
          <p className="t-sm-bold text-zinc-900">{c.title}</p>
          <p className="t-xs-medium text-zinc-500">
            {c.channel.name} · {c.publishedLabel}
          </p>
        </Link>
      ))}
    </main>
  );
}
