import { allCourses } from "../../data/course";
import type { Course } from "../types";
import { resolveUserCourses } from "./adapter";
import { loadAllPublishedContent } from "./loader";

export function getAllUserCourses(): Course[] {
  return resolveUserCourses(allCourses, loadAllPublishedContent());
}

export function getUserCourseById(courseId: string): Course | undefined {
  return getAllUserCourses().find((course) => course.id === courseId);
}
