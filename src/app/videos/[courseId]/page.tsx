import { notFound } from "next/navigation";
import { VideoDetail } from "@/components/VideoDetail";
import {
  getAllUserCourses,
  getUserCourseById,
} from "@/lib/published-content/resolver";

export function generateStaticParams() {
  return getAllUserCourses().map((course) => ({ courseId: course.id }));
}

export default async function VideoDetailPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  const course = getUserCourseById(courseId);
  if (!course) notFound();
  return <VideoDetail course={course} />;
}
