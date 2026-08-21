import { useMemo, useState } from 'react';
import searchIcon from '../assets/icons/search-line.svg';
import chevron from '../assets/icons/chevron.svg';
import { ScrollRow } from '../components/ScrollRow';
import { SectionHeading } from '../components/SectionHeading';
import { VideoCard } from '../components/VideoCard';
import { VideoCardLarge } from '../components/VideoCardLarge';
import {
  exploreSections,
  exploreTabs,
  videoChips,
  videoListItems,
  type ExploreTab,
  type VideoChip,
} from '../data/explore';
import styles from './Explore.module.css';

interface ExploreProps {
  onVideoSelect?: (videoId: string) => void;
}

export function Explore({ onVideoSelect }: ExploreProps) {
  const [tab, setTab] = useState<ExploreTab>('ALL');
  const [chip, setChip] = useState<VideoChip>('전체');
  const [query, setQuery] = useState('');

  /*
   * '따라하기' 탭은 섹션별 가로 스크롤, '동영상' 탭은 칩 필터 + 세로 리스트로 화면이 다르다.
   * 검색어는 두 탭 모두에서 제목·채널에 적용한다.
   */
  const keyword = query.trim().toLowerCase();

  const sections = useMemo(() => {
    if (!keyword) return exploreSections;
    return exploreSections
      .map((section) => {
        const sectionHit = section.title.toLowerCase().includes(keyword);
        const videos = section.videos.filter(
          (video) =>
            sectionHit ||
            video.title.toLowerCase().includes(keyword) ||
            video.channelName.toLowerCase().includes(keyword),
        );
        return { ...section, videos };
      })
      .filter((section) => section.videos.length > 0);
  }, [keyword]);

  const listVideos = useMemo(() => {
    return videoListItems.filter((video) => {
      const chipHit = chip === '전체' || video.category === chip;
      const searchHit =
        !keyword ||
        video.title.toLowerCase().includes(keyword) ||
        video.channelName.toLowerCase().includes(keyword);
      return chipHit && searchHit;
    });
  }, [chip, keyword]);

  const isVideoTab = tab === '동영상';

  return (
    <div className={styles.page}>
      <div className={styles.searchWrap}>
        <div className={styles.searchBar}>
          <input
            className={styles.searchInput}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="찾으시는 키워드가 있으신가요?"
            aria-label="검색"
          />
          <img className={styles.searchIcon} src={searchIcon} alt="" />
        </div>
      </div>

      <div className={styles.tabs} role="tablist">
        {exploreTabs.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={`${styles.tab} ${tab === name ? styles.tabActive : ''}`}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>

      {isVideoTab ? (
        <>
          <ScrollRow className={styles.chipRow}>
            {videoChips.map((name) => (
              <button
                key={name}
                type="button"
                aria-pressed={chip === name}
                className={`${styles.chip} ${chip === name ? styles.chipActive : ''}`}
                onClick={() => setChip(name)}
              >
                {name}
              </button>
            ))}
            <div className={styles.chipEnd} />
          </ScrollRow>

          <div className={styles.listMeta}>
            <span className={styles.listCount}>{listVideos.length}개</span>
            <button className={styles.sortButton} type="button">
              좋아요순
              <img className={styles.sortIcon} src={chevron} alt="" />
            </button>
          </div>

          {listVideos.length === 0 ? (
            <div className={styles.empty}>
              <p className={styles.emptyTitle}>결과가 없어요</p>
              <p className={styles.emptyText}>다른 카테고리나 키워드로 찾아보세요</p>
            </div>
          ) : (
            <div className={styles.videoList}>
              {listVideos.map((video) => (
                <VideoCardLarge key={video.id} video={video} onSelect={onVideoSelect} />
              ))}
            </div>
          )}
        </>
      ) : sections.length === 0 ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>검색 결과가 없어요</p>
          <p className={styles.emptyText}>다른 키워드로 다시 찾아보세요</p>
        </div>
      ) : (
        <div className={styles.sections}>
          {sections.map((section) => (
            <section key={section.id}>
              <SectionHeading title={section.title} subtitle={section.subtitle} hideMore />
              <ScrollRow className={styles.videoRow}>
                {section.videos.map((video) => (
                  <VideoCard key={video.id} video={video} onSelect={onVideoSelect} />
                ))}
                <div className={styles.rowEnd} />
              </ScrollRow>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
