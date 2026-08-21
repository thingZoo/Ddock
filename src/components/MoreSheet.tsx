"use client";

import Image from "next/image";
import type { Course } from "@/lib/types";
import { BottomSheet } from "./BottomSheet";
import { PillChip, SquareChip } from "./Chip";
import { YouTubeIcon } from "./YouTubeIcon";
import { ProgressGauge } from "./ProgressGauge";

/** 더보기 시트 (355:9050) — 8개 섹션 */
export function MoreSheet({
  open,
  onClose,
  course,
  onPickPart,
}: {
  open: boolean;
  onClose: () => void;
  course: Course;
  onPickPart: (partId: string) => void;
}) {
  return (
    <BottomSheet open={open} onClose={onClose}>
      <div className="flex flex-col gap-4 px-4">
        {/* 1. 제목 */}
        <h2 className="t-xl-bold text-zinc-900">{course.title}</h2>

        {/* 2. 메타 칩 */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="t-xs-medium inline-flex items-center justify-center gap-1 rounded-pill bg-zinc-100 px-2.5 py-1.5 text-zinc-500">
            <YouTubeIcon size={16} />
            {course.channel.name}
          </span>
          <PillChip icon="/icons/calendar.svg" label={course.publishedLabel} />
          <PillChip icon="/icons/star.svg" iconSize={12} label={course.ratingLabel} />
          <PillChip icon="/icons/eye.svg" label={course.viewCountLabel} />
          <PillChip icon="/icons/like.svg" label={course.likeLabel} />
        </div>

        {/* 3. 추천 카드 */}
        <section className="flex flex-col gap-4 rounded-card border border-border p-4">
          <div className="flex flex-col gap-1">
            <span className="t-2xs-medium w-fit rounded-pill bg-orange-500 px-1 py-0.5 text-white">
              {course.recommend.badge}
            </span>
            <h3 className="t-md-bold text-zinc-950">{course.recommend.title}</h3>
          </div>
          <p className="t-xs-body text-zinc-900">{course.recommend.body}</p>
        </section>

        {/* 4. 이런 도구들을 다뤄요 */}
        <section className="flex flex-col gap-4 rounded-card border border-border p-4">
          <h3 className="t-md-bold text-zinc-900">이런 도구들을 다뤄요</h3>
          <div className="scroll-x flex gap-2">
            {course.tools.map((t) => (
              <Image
                key={t.name}
                src={t.icon}
                alt={t.name}
                width={56}
                height={56}
                className="h-14 w-14 shrink-0 rounded-lg object-cover"
              />
            ))}
          </div>
          <p className="t-xs-body text-zinc-900">
            <b className="font-bold">{course.toolHighlight.name}</b>{" "}
            (
            <a
              href={course.toolHighlight.url}
              target="_blank"
              rel="noreferrer"
              className="text-blue-09 underline"
            >
              {course.toolHighlight.url}
            </a>
            )
            <br />
            <br />
            {course.toolHighlight.desc}
          </p>
        </section>

        {/* 5. 파트별 확인하기 */}
        <section className="flex flex-col gap-3 rounded-card border border-border p-4">
          <h3 className="t-md-bold text-zinc-900">파트별 확인하기</h3>
          <div className="scroll-x flex gap-3">
            {course.parts.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onPickPart(p.id)}
                className="flex w-[150px] shrink-0 flex-col gap-2 text-left"
              >
                <div className="relative h-[84px] w-full overflow-hidden rounded-lg">
                  <Image src={p.thumbnail} alt="" fill sizes="150px" className="object-cover" />
                  <span className="t-2xs-medium absolute bottom-1 left-1 rounded-chip bg-black/70 px-1.5 py-0.5 text-white">
                    {p.timeLabel}
                  </span>
                </div>
                <p className="t-xs-medium clamp-2 text-zinc-700">{p.title}</p>
                <ProgressGauge done={Math.min(p.doneCount, p.steps.length)} total={p.steps.length} />
              </button>
            ))}
          </div>
        </section>

        {/* 6. 태그 */}
        <div className="flex flex-wrap content-center items-center gap-1">
          {course.tags.map((t) => (
            <SquareChip key={t} label={t} />
          ))}
        </div>

        {/* 7. 채널 행 */}
        <a
          href={course.channel.url}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 py-2"
        >
          <Image
            src={course.channel.avatar}
            alt=""
            width={36}
            height={36}
            className="h-9 w-9 rounded-full object-cover"
          />
          <span className="t-sm-medium flex-1 text-zinc-700">
            {course.channel.name} · {course.channel.platform}
          </span>
          <svg width="18" height="18" viewBox="0 0 18 18" className="text-zinc-500">
            <path
              d="M7 3H3v12h12v-4M11 3h4v4M15 3l-7 7"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </a>

        {/* 8. 이런 영상도 있어요 */}
        <section className="flex flex-col gap-4 pt-2">
          <h3 className="t-md-bold text-zinc-900">이런 영상도 있어요</h3>
          <div className="scroll-x flex gap-4">
            {course.relatedVideos.map((v) => (
              <article key={v.id} className="w-[256px] shrink-0">
                <div className="relative h-[144px] w-full overflow-hidden rounded-[10px] border border-black/10">
                  <Image src={v.thumbnail} alt="" fill sizes="256px" className="object-cover" />
                  <span className="absolute inset-x-0 bottom-0 h-1 bg-white/60">
                    {v.progress > 0 && (
                      <span
                        className="absolute inset-y-0 left-0 rounded-pill bg-orange-500"
                        style={{ width: `${v.progress * 100}%` }}
                      />
                    )}
                  </span>
                  <span className="t-xs-normal absolute bottom-3 right-2.5 rounded-md bg-black/70 px-1.5 py-1 text-white">
                    {v.duration}
                  </span>
                </div>
                <div className="flex flex-col gap-2 px-0.5 pt-2.5">
                  <p className="t-sm-semibold clamp-2 text-zinc-800">{v.title}</p>
                  <div className="flex items-center gap-2">
                    <Image
                      src={v.channelAvatar}
                      alt=""
                      width={28}
                      height={28}
                      className="h-7 w-7 shrink-0 rounded-full object-cover"
                    />
                    <span className="t-xs-medium min-w-0 flex-1 truncate text-zinc-500">
                      {v.channelName}
                    </span>
                    <PillChip icon="/icons/like.svg" label={v.likeLabel} />
                    <PillChip icon="/icons/eye.svg" label={v.viewLabel} />
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </BottomSheet>
  );
}
