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

const imageGeneratorResult: PollResultData = {
  category: '이미지 생성',
  periodLabel: '2026. 7. 20 ~ 2026. 7. 23',
  votes: [30, 42],
  daily: [
    { day: '월', first: 0, second: 0, empty: true },
    { day: '화', first: 4, second: 9 },
    { day: '수', first: 5, second: 7 },
    { day: '목', first: 7, second: 8 },
    { day: '금', first: 5, second: 9 },
    { day: '토', first: 5, second: 6 },
    { day: '일', first: 4, second: 3 },
  ],
  likeCount: 5,
  viewCount: 52,
  reactionUser: '갓생러',
  reactionOthers: 4,
  comments: [
    {
      id: 'c1',
      author: '갓생러',
      avatar: avatar1,
      timeLabel: '4시간 전',
      text: '역시 GPT를 많이 쓰네요',
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
      text: '제미나이가 앞으로 더 좋아질듯요',
    },
    {
      id: 'c3',
      author: '아식은치킨',
      avatar: avatar1,
      timeLabel: '41분 전',
      text: '이미지 생성은 다른 툴로 더 많이 하지 않나요?',
    },
  ],
};

const characterAnimationResult: PollResultData = {
  category: '캐릭터 애니메이션',
  periodLabel: '2026. 7. 20 ~ 2026. 7. 26',
  votes: [14, 21],
  daily: [
    { day: '월', first: 0, second: 0, empty: true },
    { day: '화', first: 2, second: 4 },
    { day: '수', first: 3, second: 3 },
    { day: '목', first: 3, second: 5 },
    { day: '금', first: 2, second: 4 },
    { day: '토', first: 2, second: 3 },
    { day: '일', first: 2, second: 2 },
  ],
  likeCount: 3,
  viewCount: 28,
  reactionUser: '갓생러',
  reactionOthers: 2,
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
  'poll-image-generator': imageGeneratorResult,
  'poll-character-animation': characterAnimationResult,
  'issue-character': characterAnimationResult,
  'issue-design-system': imageGeneratorResult,
};

const ALL_POLLS: Poll[] = [...heroPolls, ...issuePolls];

export function findPoll(pollId: string): Poll | undefined {
  return ALL_POLLS.find((poll) => poll.id === pollId);
}

export function findPollResult(pollId: string): PollResultData {
  return RESULTS[pollId] ?? imageGeneratorResult;
}
