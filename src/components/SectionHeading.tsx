import chevronSection from '../assets/icons/chevron-section.svg';
import styles from './SectionHeading.module.css';

interface SectionHeadingProps {
  title: string;
  subtitle?: string;
  onMoreClick?: () => void;
}

export function SectionHeading({ title, subtitle, onMoreClick }: SectionHeadingProps) {
  return (
    <div className={styles.section}>
      <div className={styles.row}>
        <h2 className={styles.title}>{title}</h2>
        <button className={styles.more} type="button" aria-label={`${title} 더보기`} onClick={onMoreClick}>
          <img className={styles.moreIcon} src={chevronSection} alt="" />
        </button>
      </div>
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
    </div>
  );
}
