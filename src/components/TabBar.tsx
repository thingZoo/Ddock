import homeIcon from '../assets/icons/tab-home.svg';
import discoverIcon from '../assets/icons/tab-discover.svg';
import depotIcon from '../assets/icons/tab-depot.svg';
import profileIcon from '../assets/icons/tab-profile.svg';
import styles from './TabBar.module.css';

export type TabKey = 'home' | 'discover' | 'depot' | 'profile';

const TABS: Array<{ key: TabKey; label: string; icon: string }> = [
  { key: 'home', label: '홈', icon: homeIcon },
  { key: 'discover', label: '발견', icon: discoverIcon },
  { key: 'depot', label: '디포', icon: depotIcon },
  { key: 'profile', label: '내로그', icon: profileIcon },
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
            <img
              className={`${styles.icon} ${isActive ? styles.iconActive : ''}`}
              src={tab.icon}
              alt=""
            />
            <span className={`${styles.label} ${isActive ? styles.labelActive : ''}`}>
              {tab.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
