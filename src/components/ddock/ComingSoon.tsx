"use client";

import styles from './ComingSoon.module.css';

const depotIcon = "/ddock/icons/tab-depot.svg";
const profileIcon = "/ddock/icons/tab-profile.svg";

/** 아직 안 만든 탭 — 흰 화면 대신 여기서 뭘 하게 될지 알려줘요 */
const COPY = {
  depot: {
    icon: depotIcon,
    title: '디포는 준비 중이에요',
    text: '저장해둔 카드와 프롬프트를\n여기 한자리에 모을 거예요',
  },
  profile: {
    icon: profileIcon,
    title: '내로그는 준비 중이에요',
    text: '따라한 기록과 남긴 로그가\n여기 쌓일 거예요',
  },
} as const;

export type ComingSoonKey = keyof typeof COPY;

export function ComingSoon({ which }: { which: ComingSoonKey }) {
  const { icon, title, text } = COPY[which];

  return (
    <div className={styles.page}>
      <div className={styles.box}>
        <div className={styles.iconWrap}>
          <img className={styles.icon} src={icon} alt="" />
        </div>
        <p className={styles.title}>{title}</p>
        {/* 줄바꿈은 시안대로 두 줄 고정 */}
        <p className={styles.text}>{text}</p>
      </div>
    </div>
  );
}
