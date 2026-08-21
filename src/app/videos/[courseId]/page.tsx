import { notFound } from "next/navigation";
import { allCourses } from "@/data/course";
import { VideoDetail } from "@/components/VideoDetail";

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
  return <VideoDetail course={course} />;
}
