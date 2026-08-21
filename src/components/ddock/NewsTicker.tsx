"use client";

import { useEffect, useState } from 'react';
import type { NewsHeadline } from "@/data/ddockHome";
import styles from './NewsTicker.module.css';

const chatIcon = "/ddock/icons/chat-check.svg";
const statArrow = "/ddock/icons/stat-arrow.svg";
const chevron = "/ddock/icons/chevron.svg";

interface NewsTickerProps {
  headlines: NewsHeadline[];
  /** 접힌 상태에서 헤드라인이 자동으로 넘어가는 간격(ms) */
  rotateIntervalMs?: number;
}

function TrendArrow({ trend }: { trend: NewsHeadline['trend'] }) {
  return (
    <span className={`${styles.trend} ${trend === 'up' ? styles.trendUp : ''}`}>
      <img className={styles.trendIcon} src={statArrow} alt={trend === 'up' ? '상승' : '하락'} />
    </span>
  );
}

export function NewsTicker({ headlines, rotateIntervalMs = 3000 }: NewsTickerProps) {
  const [expanded, setExpanded] = useState(false);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (expanded || headlines.length <= 1) {
      return;
    }
    const timer = window.setInterval(() => {
      setIndex((prev) => (prev + 1) % headlines.length);
    }, rotateIntervalMs);
    return () => window.clearInterval(timer);
  }, [expanded, headlines.length, rotateIntervalMs]);

  const current = headlines[index];

  return (
    <div className={styles.wrapper}>
      <div className={styles.panel}>
        <button
          className={styles.row}
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={expanded}
        >
          <span className={styles.label}>
            <img className={styles.labelIcon} src={chatIcon} alt="" />
            지금 뜨는 뉴스
          </span>
          {!expanded && current ? (
            <span className={styles.headline}>
              <span className={styles.headlineText}>
                <span className={styles.rank}>{current.rank}</span>
                <span className={styles.title}>{current.title}</span>
              </span>
              <TrendArrow trend={current.trend} />
            </span>
          ) : (
            <span className={styles.headline} />
          )}
          <span className={`${styles.chevron} ${expanded ? styles.chevronOpen : ''}`}>
            <img className={styles.chevronIcon} src={chevron} alt="" />
          </span>
        </button>

        {expanded && (
          <>
            <ul className={styles.list}>
              {headlines.map((headline) => (
                <li key={headline.rank}>
                  <button className={styles.listItem} type="button">
                    <span className={styles.headlineText}>
                      <span className={styles.rank}>{headline.rank}</span>
                      <span className={styles.title}>{headline.title}</span>
                    </span>
                    <TrendArrow trend={headline.trend} />
                  </button>
                </li>
              ))}
            </ul>
            <div className={styles.footer}>뉴스 더보기</div>
          </>
        )}
      </div>
    </div>
  );
}
