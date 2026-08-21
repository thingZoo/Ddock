"use client";

import styles from './AppHeader.module.css';

const logo = "/ddock/icons/logo.svg";
const searchIcon = "/ddock/icons/search.svg";
const bellIcon = "/ddock/icons/bell.svg";

interface AppHeaderProps {
  onSearchClick?: () => void;
  onNotificationClick?: () => void;
}

/*
 * 앱인토스 심사 항목 확인 필요:
 * 미니앱 위에는 토스 내비게이션 바가 얹히고 거기에 브랜드 로고와 앱 이름이 이미 표시된다.
 * 이 자체 헤더가 토스 내비게이션 바와 중복 노출되지 않는지 실기기에서 확인해야 한다.
 */
export function AppHeader({ onSearchClick, onNotificationClick }: AppHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.left}>
        <img className={styles.logo} src={logo} alt="디독" />
      </div>
      <div className={styles.right}>
        <button className={styles.iconButton} type="button" aria-label="검색" onClick={onSearchClick}>
          <img className={styles.icon} src={searchIcon} alt="" />
        </button>
        <button
          className={styles.iconButton}
          type="button"
          aria-label="알림"
          onClick={onNotificationClick}
        >
          <img className={styles.iconBell} src={bellIcon} alt="" />
        </button>
      </div>
    </header>
  );
}
