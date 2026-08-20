import { notFound } from "next/navigation";
import { allCourses } from "@/data/course";
import { LearnFlow } from "@/components/LearnFlow";

export function generateStaticParams() {
  return allCourses.map((c) => ({ courseId: c.id }));
}

export default async function LearnPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  const course = allCourses.find((c) => c.id === courseId);
  if (!course) notFound();

  return (
    <main className="min-h-screen bg-neutral-50">
      <LearnFlow course={course} />
    </main>
  );
}
