
/** 두 선택지 중 하나를 고르는 투표. YES/NO 도, 도구 이름 대결도 같은 모양이다. */
export interface Poll {
  id: string;
  question: string;
  thumbnail: string;
  /** 시안의 크롭 위치를 맞추기 위한 object-position 값 */
  thumbnailPosition?: string;
  /** 참여자 수 */
  voterCount: number;
  options: [string, string];
  /** 첫 번째 선택지의 득표율(%). 투표 전에는 null이라 '??%'로 가려진다. */
  firstRatio: number | null;
  /** 마감까지 남은 시간 표기 (예: '3일 06:59 남음') */
  remainingLabel?: string;
  /** 진행 기간 표기 (예: '2026. 7. 20 ~ 2026. 7. 26') */
  periodLabel?: string;
  /** 이미 참여한 투표면 썸네일에 '참여' 배지가 붙는다. */
  participated?: boolean;
}

export interface VideoItem {
  id: string;
  title: string;
  thumbnail: string;
  duration: string;
  channelName: string;
  channelAvatar: string;
  likeCount: string;
  viewCount: string;
  /** 시청 진행률(0~1). 0이면 진행 바를 그리지 않는다. */
  progress: number;
}

export interface NewsHeadline {
  rank: number;
  title: string;
  trend: 'up' | 'down';
}

export const newsHeadlines: NewsHeadline[] = [
  { rank: 1, title: '클로드 코드 보안 검사기', trend: 'up' },
  { rank: 2, title: '클로드 음성 대화, 이제 한국어도 가능', trend: 'up' },
  { rank: 3, title: '제미나이 스피크, 2만원대 인상', trend: 'down' },
  { rank: 4, title: '오픈AI Presence : 기업용 AI 상담원', trend: 'up' },
];

/*
 * 홈 상단 덱은 '진행중인 투표'만 담는다.
 * 마감된 투표는 아래 issuePolls 로만 노출되고, 같은 투표가 양쪽에 겹치지 않게 한다.
 */
export const heroPolls: Poll[] = [
  {
    id: 'poll-image-generator',
    question: '2026년 최고의 AI 이미지 생성기는?',
    thumbnail: "/ddock/mock/poll-cinema.png",
    // 시안이 가로로 확대해 오른쪽을 보여주는 구간(가로 24~100%)의 가운데
    thumbnailPosition: '62% center',
    voterCount: 72,
    options: ['Gemini', 'ChatGPT'],
    // 시안 홈_투표 후 기준: Gemini 40% / ChatGPT 60%
    firstRatio: 40,
    remainingLabel: '3일 06:59 남음',
  },
  {
    id: 'poll-prompt-sense',
    question: '프롬프트에도 디자인 감각이 필요할까?',
    thumbnail: "/ddock/mock/poll-prompt.png",
    voterCount: 35,
    options: ['YES', 'NO'],
    firstRatio: 68,
    remainingLabel: '3일 06:59 남음',
  },
];

export const weeklyVideos: VideoItem[] = [
  {
    id: 'weekly-1',
    title: 'Figma Motion과 생성형 플러그인/셰이더를 활용해 30분 만에 바이럴 광고 캠페인 제작하기',
    thumbnail: "/ddock/mock/video-1.png",
    duration: '11:27',
    channelName: 'Figma',
    channelAvatar: "/ddock/mock/avatar-1.png",
    likeCount: '97개',
    viewCount: '3.7천',
    progress: 0,
  },
  {
    id: 'weekly-2',
    title: 'Figma 2026 업데이트: Figma의 새로운 기능은 무엇일까요?',
    thumbnail: "/ddock/mock/video-2.png",
    duration: '10:06',
    channelName: 'Nexfield Academy',
    channelAvatar: "/ddock/mock/avatar-2.png",
    likeCount: '211개',
    viewCount: '7.2천',
    progress: 0.18,
  },
];

export const popularVideos: VideoItem[] = [
  {
    id: 'popular-1',
    title: '그냥 "PPT 만들어줘"라고 하면 망합니다. (클로드 PPT 제작 노하우)',
    thumbnail: "/ddock/mock/top10-1.png",
    duration: '11:27',
    channelName: '헤이디_PPT 디자인',
    channelAvatar: "/ddock/mock/top10-avatar-1.png",
    likeCount: '4.3천',
    viewCount: '12만',
    progress: 0,
  },
  {
    id: 'popular-2',
    title: '끝까지 버티다 결국 AI로 영상 만들고 느낀 솔직한 심정 // MSI',
    thumbnail: "/ddock/mock/top10-2.png",
    duration: '10:02',
    channelName: 'JohnKOBA Design',
    channelAvatar: "/ddock/mock/top10-avatar-2.png",
    likeCount: '3.7천',
    viewCount: '14만',
    progress: 0.184,
  },
];

export const issuePolls: Poll[] = [
  {
    id: 'issue-design-system',
    question: '클로드 코드로 디자인 시스템 만들어봤어?',
    thumbnail: "/ddock/mock/issue-design-system.png",
    voterCount: 80,
    options: ['YES', 'NO'],
    firstRatio: 65,
    periodLabel: '2026. 7. 20 ~ 2026. 7. 26',
    participated: true,
  },
  {
    id: 'issue-character',
    question: 'AI로 캐릭터 애니메이션 만들어 봤어?',
    thumbnail: "/ddock/mock/issue-character.png",
    // 세로로 긴 원본에서 캐릭터가 보이는 구간
    thumbnailPosition: 'center 62%',
    voterCount: 72,
    options: ['YES', 'NO'],
    firstRatio: 40,
    periodLabel: '2026. 7. 20 ~ 2026. 7. 26',
    participated: true,
  },
];
