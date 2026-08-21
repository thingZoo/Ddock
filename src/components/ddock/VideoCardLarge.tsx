"use client";

import type { VideoItem } from "@/data/ddockHome";
import styles from './VideoCardLarge.module.css';

const kebabIcon = "/ddock/icons/kebab.svg";
const likeIcon = "/ddock/icons/like.svg";
const eyeIcon = "/ddock/icons/eye.svg";

interface VideoCardLargeProps {
  video: VideoItem;
  onSelect?: (videoId: string) => void;
  onMenuClick?: (videoId: string) => void;
}

/** 동영상 탭에 쓰는 전체 폭 세로 카드 (썸네일 위, 정보 아래) */
export function VideoCardLarge({ video, onSelect, onMenuClick }: VideoCardLargeProps) {
  return (
    <article className={styles.card}>
      <button
        className={styles.thumbnail}
        type="button"
        aria-label={`${video.title} 재생`}
        onClick={() => onSelect?.(video.id)}
      >
        <img className={styles.thumbnailImage} src={video.thumbnail} alt="" />
        <div className={styles.progressBar}>
          <div className={styles.progressFill} style={{ width: `${video.progress * 100}%` }} />
        </div>
        <div className={styles.durationWrap}>
          <span className={styles.duration}>{video.duration}</span>
        </div>
      </button>

      <div className={styles.body}>
        <div className={styles.titleRow}>
          <h3 className={styles.title}>{video.title}</h3>
          <button
            className={styles.kebabButton}
            type="button"
            aria-label="더보기"
            onClick={() => onMenuClick?.(video.id)}
          >
            <img className={styles.kebab} src={kebabIcon} alt="" />
          </button>
        </div>

        <div className={styles.action}>
          <div className={styles.channel}>
            <img className={styles.avatar} src={video.channelAvatar} alt="" />
            <span className={styles.channelName}>{video.channelName}</span>
          </div>
          <span className={styles.tag}>
            <img className={styles.tagIcon} src={likeIcon} alt="" />
            {video.likeCount}
          </span>
          <span className={styles.tag}>
            <img className={styles.tagIcon} src={eyeIcon} alt="" />
            {video.viewCount}
          </span>
        </div>
      </div>
    </article>
  );
}
