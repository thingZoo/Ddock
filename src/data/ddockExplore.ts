import type { VideoItem } from "./ddockHome";

/** 탐색 필터 탭 */
export const exploreTabs = ['ALL', '동영상', 'Shorts'] as const;
export type ExploreTab = (typeof exploreTabs)[number];

/** 동영상 탭의 카테고리 칩. 첫 항목이 기본 선택된다. */
export const videoChips = [
  '전체',
  'UX/UI',
  '이미지 생성',
  '영상 제작',
  'AI 수익화',
  '3D · VFX',
] as const;
export type VideoChip = (typeof videoChips)[number];

export interface ExploreSection {
  id: string;
  title: string;
  subtitle: string;
  videos: VideoItem[];
}

export const exploreSections: ExploreSection[] = [
  {
    id: 'time-saver',
    title: '야근 줄여주는 디자인 시간 단축법',
    subtitle: '손 아프게 반복하던 작업, 5분으로 줄이는 법',
    videos: [
      {
        id: 'ts-1',
        title: 'AI를 활용해 더 빠르게 디자인하는 방법 (전체 워크플로우)',
        thumbnail: "/ddock/explore/ex-1.png",
        duration: '5:46',
        channelName: 'Rachel How',
        channelAvatar: "/ddock/mock/avatar-1.png",
        likeCount: '3.1천',
        viewCount: '10만',
        progress: 0.18,
      },
      {
        id: 'ts-2',
        title: 'Higgsfield AI와 Claude Fable 5를 활용해 얼굴 없는 틈새 채널 자동화하기',
        thumbnail: "/ddock/explore/ex-2.png",
        duration: '10:26',
        channelName: 'Higgsfield AI',
        channelAvatar: "/ddock/mock/avatar-2.png",
        likeCount: '4.2천',
        viewCount: '11만',
        progress: 0,
      },
    ],
  },
  {
    id: 'card-news',
    title: '카드뉴스, 이제 알아서 착착',
    subtitle: '복사해서 붙여넣기만 하면 되는 검증된 프롬프트',
    videos: [
      {
        id: 'cn-1',
        title: '궁극의 나노 바나나 튜토리얼: 15가지 즉각적인 기술',
        thumbnail: "/ddock/explore/ex-3.png",
        duration: '27:07',
        channelName: 'AI Master',
        channelAvatar: "/ddock/mock/avatar-1.png",
        likeCount: '5.6천',
        viewCount: '23만',
        progress: 0,
      },
      {
        id: 'cn-2',
        title: 'AI 디자이너 가이드: Figma 활용 완벽 정리',
        thumbnail: "/ddock/mock/top10-2.png",
        duration: '18:03',
        channelName: 'Codex Lab',
        channelAvatar: "/ddock/mock/avatar-2.png",
        likeCount: '2.4천',
        viewCount: '9.1만',
        progress: 0,
      },
    ],
  },
  {
    id: 'high-income',
    title: '이것만 따라오면 월 천만 원',
    subtitle: '상위 1% 디자이너만 쓰는 AI 워크플로우',
    videos: [
      {
        id: 'hi-1',
        title: 'Claude 3.5 + Higgsfield MCP로 부자가 되는 방법!',
        thumbnail: "/ddock/explore/s3-over.png",
        duration: '10:06',
        channelName: 'Higgsfield AI',
        channelAvatar: "/ddock/mock/avatar-2.png",
        likeCount: '7.2천',
        viewCount: '31만',
        progress: 0.4,
      },
      {
        id: 'hi-2',
        title: '따라만 하면 되는 유튜브 수익화 채널 세팅 A to Z',
        thumbnail: "/ddock/explore/s3-2.png",
        duration: '27:07',
        channelName: 'JohnKOBA Design',
        channelAvatar: "/ddock/mock/avatar-1.png",
        likeCount: '3.3천',
        viewCount: '12만',
        progress: 0,
      },
    ],
  },
];

/** 동영상 탭의 세로 카드 리스트. category 로 칩 필터가 걸린다. */
export interface VideoListItem extends VideoItem {
  category: VideoChip;
}

export const videoListItems: VideoListItem[] = [
  {
    id: 'v-1',
    courseId: 'claude-code-video-edit',
    title: '클로드 코드로 영상 편집 완전 자동화하기',
    thumbnail: "/ddock/explore/vid-1.png",
    duration: '5:46',
    channelName: 'Sandy Lee AI',
    channelAvatar: "/ddock/mock/avatar-1.png",
    likeCount: '1.4천',
    viewCount: '4.6만',
    progress: 0,
    category: '영상 제작',
  },
  {
    id: 'v-2',
    title: 'AI로 YouTube용 3D 애니메이션 영상을 만드는 방법 (전체 가이드)',
    thumbnail: "/ddock/explore/vid-2.png",
    duration: '5:46',
    channelName: 'Youri van Hofwegen',
    channelAvatar: "/ddock/mock/avatar-2.png",
    likeCount: '1.9천',
    viewCount: '21만',
    progress: 0,
    category: '3D · VFX',
  },
  {
    id: 'v-3',
    title: '그냥 "PPT 만들어줘"라고 하면 망합니다 (클로드 PPT 제작 노하우)',
    thumbnail: "/ddock/mock/top10-1.png",
    duration: '11:27',
    channelName: '헤이디_PPT 디자인',
    channelAvatar: "/ddock/mock/avatar-1.png",
    likeCount: '4.3천',
    viewCount: '12만',
    progress: 0,
    category: 'UX/UI',
  },
  {
    id: 'v-4',
    title: 'AI 이미지 생성, 실무자가 진짜 쓰는 프롬프트 모음',
    thumbnail: "/ddock/mock/top10-2.png",
    duration: '18:03',
    channelName: 'Codex Lab',
    channelAvatar: "/ddock/mock/avatar-2.png",
    likeCount: '2.4천',
    viewCount: '9.1만',
    progress: 0,
    category: '이미지 생성',
  },
  {
    id: 'v-5',
    title: 'AI로 월 천만 원 버는 디자이너의 수익화 파이프라인',
    thumbnail: "/ddock/mock/video-1.png",
    duration: '22:10',
    channelName: 'Rachel How',
    channelAvatar: "/ddock/mock/avatar-1.png",
    likeCount: '7.2천',
    viewCount: '31만',
    progress: 0,
    category: 'AI 수익화',
  },
];
