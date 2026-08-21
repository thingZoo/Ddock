"use client";

import styles from './TabBar.module.css';

const homeIcon = "/ddock/icons/tab-home.svg";
const homeIconActive = "/ddock/icons/tab-home-active.svg";
const discoverIcon = "/ddock/icons/tab-discover.svg";
const discoverIconActive = "/ddock/icons/tab-discover-active.svg";
const depotIcon = "/ddock/icons/tab-depot.svg";
const depotIconActive = "/ddock/icons/tab-depot-active.svg";
const profileIcon = "/ddock/icons/tab-profile.svg";
const profileIconActive = "/ddock/icons/tab-profile-active.svg";

export type TabKey = 'home' | 'discover' | 'depot' | 'profile';

/** URL 의 ?tab= 값이 진짜 탭인지 걸러낼 때 써요 */
export const TAB_KEYS: TabKey[] = ['home', 'discover', 'depot', 'profile'];

const TABS: Array<{ key: TabKey; label: string; icon: string; iconActive: string }> = [
  { key: 'home', label: '홈', icon: homeIcon, iconActive: homeIconActive },
  { key: 'discover', label: '발견', icon: discoverIcon, iconActive: discoverIconActive },
  { key: 'depot', label: '디포', icon: depotIcon, iconActive: depotIconActive },
  { key: 'profile', label: '내로그', icon: profileIcon, iconActive: profileIconActive },
];

interface TabBarProps {
  active: TabKey;
  onChange: (key: TabKey) => void;
}

export function TabBar({ active, onChange }: TabBarProps) {
  return (
    <nav className={styles.tabBar}>
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            className={styles.segment}
            type="button"
            aria-current={isActive ? 'page' : undefined}
            onClick={() => onChange(tab.key)}
          >
            <img className={styles.icon} src={isActive ? tab.iconActive : tab.icon} alt="" />
            <span className={`${styles.label} ${isActive ? styles.labelActive : ''}`}>
              {tab.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
