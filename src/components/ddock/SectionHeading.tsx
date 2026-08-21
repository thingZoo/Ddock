"use client";

import styles from './SectionHeading.module.css';

const chevronSection = "/ddock/icons/chevron-section.svg";

interface SectionHeadingProps {
  title: string;
  subtitle?: string;
  onMoreClick?: () => void;
  /** 더보기 화살표를 감춘다 (탐색 섹션 헤더는 화살표가 없다) */
  hideMore?: boolean;
}

export function SectionHeading({ title, subtitle, onMoreClick, hideMore }: SectionHeadingProps) {
  return (
    <div className={styles.section}>
      <div className={styles.row}>
        <h2 className={styles.title}>{title}</h2>
        {!hideMore && (
          <button
            className={styles.more}
            type="button"
            aria-label={`${title} 더보기`}
            onClick={onMoreClick}
          >
            <img className={styles.moreIcon} src={chevronSection} alt="" />
          </button>
        )}
      </div>
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
    </div>
  );
}
