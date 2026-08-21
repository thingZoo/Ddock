import avatar1 from '../assets/mock/avatar-1.png';
import avatar2 from '../assets/mock/avatar-2.png';
import { heroPolls, issuePolls, type Poll } from './home';

export interface DailyVotes {
  /** 요일 한 글자 */
  day: string;
  /** 첫 번째 선택지 득표 */
  first: number;
  /** 두 번째 선택지 득표 */
  second: number;
  /** 집계 전이라 막대를 그리지 않는 날 */
  empty?: boolean;
}

export interface CommentItem {
  id: string;
  author: string;
  avatar: string;
  timeLabel: string;
  text: string;
  replies?: CommentItem[];
}

export interface PollResultData {
  /** 상단 태그에 노출되는 분류 */
  category: string;
  periodLabel: string;
  /** [첫 번째 선택지, 두 번째 선택지] 총 득표 */
  votes: [number, number];
  daily: DailyVotes[];
  likeCount: number;
  viewCount: number;
  /** 공감 요약에 노출되는 대표 사용자와 나머지 인원 */
  reactionUser: string;
  reactionOthers: number;
  comments: CommentItem[];
}

const designSystemResult: PollResultData = {
  category: '업무 생산성',
  periodLabel: '2026. 7. 20 ~ 2026. 7. 26',
  // 시안 결과 페이지 기준: YES 45표 / NO 35표, 합계 80명
  votes: [45, 35],
  daily: [
    { day: '월', first: 0, second: 0, empty: true },
    { day: '화', first: 11, second: 5 },
    { day: '수', first: 4, second: 10 },
    { day: '목', first: 10, second: 11 },
    { day: '금', first: 11, second: 4 },
    { day: '토', first: 8, second: 2 },
    { day: '일', first: 1, second: 3 },
  ],
  likeCount: 6,
  viewCount: 52,
  reactionUser: '갓생러',
  reactionOthers: 4,
  comments: [
    {
      id: 'c1',
      author: '갓생러',
      avatar: avatar1,
      timeLabel: '4시간 전',
      text: '토큰만 정리해두면 확실히 빠르네요',
      replies: [
        {
          id: 'c1-r1',
          author: '배짱',
          avatar: avatar2,
          timeLabel: '1시간 전',
          text: '그러니까요',
        },
      ],
    },
    {
      id: 'c2',
      author: '인생은즐겁게',
      avatar: avatar2,
      timeLabel: '3시간 전',
      text: '컴포넌트 네이밍부터 맞춰야 하더라고요',
    },
    {
      id: 'c3',
      author: '아식은치킨',
      avatar: avatar1,
      timeLabel: '41분 전',
      text: '디자인 QA까지 맡기는 건 아직 이른 듯요',
    },
  ],
};

const characterAnimationResult: PollResultData = {
  category: '영상 제작',
  periodLabel: '2026. 7. 20 ~ 2026. 7. 26',
  // 시안 결과 페이지 기준: YES 26표 / NO 46표, 합계 72명
  votes: [26, 46],
  daily: [
    { day: '월', first: 0, second: 0, empty: true },
    { day: '화', first: 4, second: 10 },
    { day: '수', first: 6, second: 6 },
    { day: '목', first: 6, second: 13 },
    { day: '금', first: 4, second: 10 },
    { day: '토', first: 4, second: 6 },
    { day: '일', first: 2, second: 1 },
  ],
  likeCount: 5,
  viewCount: 52,
  reactionUser: '갓생러',
  reactionOthers: 4,
  comments: [
    {
      id: 'a1',
      author: '모션러버',
      avatar: avatar2,
      timeLabel: '2시간 전',
      text: '생각보다 안 해본 사람이 많네요',
    },
    {
      id: 'a2',
      author: '갓생러',
      avatar: avatar1,
      timeLabel: '30분 전',
      text: '툴만 정해지면 바로 해볼 만해요',
    },
  ],
};

/** pollId → 결과 데이터. 아직 결과가 없는 투표는 첫 번째 데이터를 재사용한다. */
const RESULTS: Record<string, PollResultData> = {
  'issue-design-system': designSystemResult,
  'issue-character': characterAnimationResult,
};

const ALL_POLLS: Poll[] = [...heroPolls, ...issuePolls];

export function findPoll(pollId: string): Poll | undefined {
  return ALL_POLLS.find((poll) => poll.id === pollId);
}

export function findPollResult(pollId: string): PollResultData {
  return RESULTS[pollId] ?? designSystemResult;
}
