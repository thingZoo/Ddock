"use client";

import { useState } from 'react';
import { AppHeader } from "./AppHeader";
import { NewsTicker } from "./NewsTicker";
import { PollDeck } from "./PollDeck";
import { ScrollRow } from "./ScrollRow";
import { SectionHeading } from "./SectionHeading";
import { VideoCard } from "./VideoCard";
import { IssuePollCard } from "./IssuePollCard";
import {
  heroPolls,
  issuePolls,
  newsHeadlines,
  popularVideos,
  weeklyVideos,
} from "@/data/ddockHome";
import styles from './Home.module.css';

interface HomeProps {
  /** 투표 결과 화면으로 이동한다 */
  onPollSelect?: (pollId: string) => void;
  /** 영상 상세페이지로 이동한다 (courseId) */
  onVideoSelect?: (courseId: string) => void;
}

export function Home({ onPollSelect, onVideoSelect }: HomeProps) {
  /** 투표 결과는 답한 뒤에만 공개되므로 pollId → 선택 인덱스로 들고 있는다. */
  const [votes, setVotes] = useState<Record<string, number>>({});
  /** 배경에 흐리게 깔아둘 이미지. 앞으로 올라온 투표를 따라간다. */
  const [activePoll, setActivePoll] = useState(heroPolls[0]);

  /*
   * 상단 덱은 '진행중인 투표'라 답하고 나면 그 자리에서 결과 비율만 공개한다.
   * 결과 화면으로 넘어가는 건 아래 '투표로 알아보는 AI 이슈'의 마감된 투표뿐이다.
   */
  const handleVote = (pollId: string, optionIndex: number) => {
    setVotes((prev) => ({ ...prev, [pollId]: optionIndex }));
  };

  return (
    <div className={styles.page}>
      <div className={styles.backdrop} aria-hidden="true">
        <img
          className={styles.backdropImage}
          src={activePoll.thumbnail}
          alt=""
          style={
            activePoll.thumbnailPosition
              ? { objectPosition: activePoll.thumbnailPosition }
              : undefined
          }
        />
        <div className={styles.backdropOverlay} />
      </div>

      <div className={styles.header}>
        <AppHeader />
      </div>

      <main className={styles.content}>
        <NewsTicker headlines={newsHeadlines} />

        <PollDeck
          polls={heroPolls}
          votes={votes}
          onVote={handleVote}
          onActivePollChange={setActivePoll}
        />

        <section>
          <SectionHeading
            title="위클리 업데이트 소식"
            subtitle="최근 한 주간 업데이트된 주요 AI 소식"
          />
          <ScrollRow className={styles.videoRow}>
            {weeklyVideos.map((video) => (
              <VideoCard key={video.id} video={video} onSelect={onVideoSelect} />
            ))}
            <div className={styles.rowEnd} />
          </ScrollRow>
        </section>

        <section>
          <SectionHeading title="디독 인기 TOP 10" subtitle="최근 유저들이 많이 본 요즘 대세 콘텐츠" />
          <ScrollRow className={styles.videoRow}>
            {popularVideos.map((video) => (
              <VideoCard key={video.id} video={video} onSelect={onVideoSelect} />
            ))}
            <div className={styles.rowEnd} />
          </ScrollRow>
        </section>

        <section>
          <SectionHeading title="투표로 알아보는 AI 이슈" subtitle="그 이슈, 다른 사람들은 어떻게 생각할까?" />
          <ScrollRow className={styles.issueRow}>
            {issuePolls.map((poll) => (
              <IssuePollCard key={poll.id} poll={poll} onSelect={onPollSelect} />
            ))}
            <div className={styles.rowEnd} />
          </ScrollRow>
        </section>
      </main>
    </div>
  );
}
