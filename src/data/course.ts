import type { Course, ActionLine } from "@/lib/types";

/** 문장 → ActionLine. `백틱`으로 감싼 부분은 인라인 코드 칩이 돼요 */
function line(raw: string): ActionLine {
  const parts: ActionLine["parts"] = [];
  raw.split(/(`[^`]+`)/).forEach((chunk) => {
    if (!chunk) return;
    if (chunk.startsWith("`") && chunk.endsWith("`")) {
      parts.push({ kind: "code", value: chunk.slice(1, -1) });
    } else {
      parts.push({ kind: "text", value: chunk });
    }
  });
  return { parts };
}

export const course: Course = {
  id: "claude-code-video-edit",
  youtubeId: "-1zFrs_TnoM",
  title: "클로드 코드로 영상 편집 완전 자동화하기",
  breadcrumb: ["동영상", "콘텐츠", "Sandy Lee AI"],
  thumbnail: "/img/hero.jpg",
  channel: {
    name: "Sandy Lee AI",
    avatar: "/img/avatar1.jpg",
    url: "https://www.youtube.com/@sandyleeai",
    platform: "유튜브",
  },
  publishedAt: "2026-07-20",
  publishedLabel: "2026년 7월 20일",
  ratingLabel: "2.8점",
  helpLabel: "도움 2.8",
  viewLabel: "조회수 6만 3천 회",
  viewCountLabel: "63,231",
  likeLabel: "4.3천",
  tags: [
    "영상편집",
    "영상",
    "클로드 코드",
    "위스퍼",
    "FFmepeg",
    "하이퍼프레임즈",
    "힉스필드",
    "자동화",
  ],
  recommend: {
    badge: "추천해요",
    title: "AI 영상 편집 초보자들 주목",
    body: "지금 보고 있는 이 영상, 전부 AI가 편집했다고 하면 믿어지시나요? 폴더에 원본 영상만 넣으면 Claude Code가 컷 편집, 무음 구간 제거, 모션그래픽·자막 삽입(브랜드 폰트·컬러 반영), 효과음 추가, AI B-roll 생성까지 자동으로 처리하는 워크플로우를 만들어봐요.",
  },
  tools: [
    { name: "Claude", icon: "/img/tool1.jpg" },
    { name: "Whisper", icon: "/img/tool2.jpg" },
    { name: "FFmpeg", icon: "/img/tool3.jpg" },
    { name: "하이퍼프레임즈", icon: "/img/tool4.jpg" },
    { name: "힉스필드", icon: "/img/tool5.jpg" },
  ],
  toolHighlight: {
    name: "Claude Code",
    url: "https://claude.ai",
    desc: "전체 편집을 지휘하는 핵심 도구 (Max 플랜 월 $100 사용 중이나, 가벼운 용도는 $20 기본 플랜으로도 시작 가능)",
  },
  relatedVideos: [
    {
      id: "rel-1",
      title: "그냥 “PPT 만들어줘”라고 하면 망합니다. (클로드 PPT 제작 노하우)",
      thumbnail: "/img/rel1.jpg",
      duration: "11:27",
      progress: 0,
      channelName: "헤이디_PPT 디자인",
      channelAvatar: "/img/avatar1.jpg",
      likeLabel: "4.3천",
      viewLabel: "12만",
    },
    {
      id: "rel-2",
      title: "끝까지 버티다 결국 AI로 영상 만들고 느낀 솔직한 심정 // MSI",
      thumbnail: "/img/rel2.jpg",
      duration: "10:02",
      progress: 0.18,
      channelName: "JohnKOBA Design",
      channelAvatar: "/img/avatar2.jpg",
      likeLabel: "3.7천",
      viewLabel: "14만",
    },
  ],
  parts: [
    {
      id: "part-1",
      partNo: 1,
      chapterNo: "CH 01",
      title: "뭘 깔아야 시작할 수 있어요? feat. MCP",
      thumbnail: "/img/part1.jpg",
      timeLabel: "09:51-12:36",
      startSec: 591,
      endSec: 756,
      doneCount: 4,
      steps: [
        {
          id: "p1s1",
          order: 1,
          variant: "basic",
          title: "Claude Code로 MCP를 설치해요",
          actions: [
            line("Antigravity IDE에서 Claude Code 실행"),
            line("Open AI Whisper 설치"),
            line("FFmpeg 설치"),
          ],
          startSec: 591,
          endSec: 640,
          infoSheets: [
            {
              id: "p1s1i1",
              question: "MCP가 뭐예요?",
              body: "Claude가 바깥 프로그램을 부를 수 있게 이어주는 연결 규격이에요. 이걸 붙여야 Claude Code가 내 컴퓨터의 Whisper나 FFmpeg를 직접 돌릴 수 있어요.",
              timeLabel: "10:12",
              timeSec: 612,
            },
          ],
        },
        {
          id: "p1s2",
          order: 2,
          variant: "prompt",
          title: "원하는 자막 스타일을 붙여넣어요",
          actions: [
            line("마음에 드는 자막 화면을 캡쳐"),
            line("Claude Code에 붙여넣고 프롬프트를 보내요"),
          ],
          prompt: {
            label: "복사해서 그대로 쓰세요",
            code:
              "이 스타일은 마음에 들어요.\n다만 이 색은 제 브랜드 키트 색인 골드로 바꿔주세요.\n" +
              "폰트는 Pretendard SemiBold, 자막은 화면 아래에서 12% 띄우고,\n" +
              "한 줄에 최대 18자까지만 넣어주세요. 두 줄을 넘기면 컷을 나눠도 좋아요.\n" +
              "외곽선은 넣지 말고 대신 뒤에 40% 투명도의 검은 박스를 깔아주세요.",
          },
          startSec: 640,
          endSec: 690,
          infoSheets: [
            {
              id: "p1s2i1",
              question: "캡쳐 대신 말로 설명해도 되나요?",
              body: "돼요. 다만 캡쳐가 훨씬 빨라요. 폰트 굵기나 자막 위치처럼 말로 옮기기 번거로운 게 그림 한 장에 다 들어 있거든요.",
              timeLabel: "11:05",
              timeSec: 665,
            },
            {
              id: "p1s2i2",
              question: "브랜드 키트 색은 어디서 가져와요?",
              body: "피그마 파일의 색 변수를 그대로 불러줘도 되고, 헥스값을 직접 적어줘도 됩니다. 매번 같은 값을 쓰려면 프로젝트 폴더에 적어두고 참조시키는 쪽이 안정적이에요.",
              timeLabel: "11:31",
              timeSec: 691,
            },
          ],
        },
        {
          id: "p1s3",
          order: 3,
          variant: "basic",
          title: "원본 영상을 폴더에 넣어요",
          actions: [
            line("프로젝트 안에 `raw` 폴더를 만들어요"),
            line("촬영본을 그대로 넣기 — 이름은 안 바꿔도 돼요"),
          ],
          startSec: 690,
          endSec: 720,
          infoSheets: [
            {
              id: "p1s3i1",
              question: "파일이 크면 오래 걸리나요?",
              body: "Whisper가 음성을 먼저 훑어요. 1시간짜리 기준으로 몇 분 걸립니다. 그동안 다른 창에서 작업해도 됩니다.",
              timeLabel: "11:52",
              timeSec: 712,
            },
          ],
        },
        {
          id: "p1s4",
          order: 4,
          variant: "warning",
          title: "모델은 Sonnet으로 설정해요",
          actions: [line("`/switch model` 입력 → Sonnet 선택")],
          warning: {
            title: "Fable 모델은 이 작업에는 과해요",
            body: "편집할 땐 Sonnet으로 바꾸고 시작하세요. Fable은 토큰을 많이 잡아먹어요.",
          },
          startSec: 720,
          endSec: 756,
          infoSheets: [
            {
              id: "p1s4i1",
              question: "언제 어떤 모델을 써요?",
              body: "처음 설정하고 계획을 짤 땐 가장 똑똑한 Opus, 실제로 편집을 돌릴 땐 Sonnet. 화자가 쓰는 방식이에요. 수익이 크게 걸린 프로젝트라면 Fable도 쓸 만하지만 편집 작업엔 과합니다.",
              timeLabel: "14:33",
              timeSec: 873,
            },
            {
              id: "p1s4i2",
              question: "편집이 크레딧을 먹나요?",
              body: "아니요. 토큰을 씁니다. 구독료 안에서 돌아가요. 화자는 월 100달러 플랜을 쓰는데, 편집이 많지 않으면 20달러 기본 플랜으로 시작해도 충분하다고 합니다.",
              timeLabel: "08:22",
              timeSec: 502,
            },
          ],
        },
      ],
    },
    {
      id: "part-2",
      partNo: 2,
      chapterNo: "CH 02",
      title: "AI가 내 브랜드를 어떻게 알아요?",
      thumbnail: "/img/part2.jpg",
      timeLabel: "12:36-13:47",
      startSec: 756,
      endSec: 827,
      doneCount: 1,
      steps: [
        {
          id: "p2s1",
          order: 1,
          variant: "basic",
          title: "브랜드 키트 폴더를 만들어요",
          actions: [
            line("프로젝트 맨 위에 `brand` 폴더 생성"),
            line("로고·폰트·컬러 값을 한곳에 모으기"),
          ],
          startSec: 756,
          endSec: 776,
          infoSheets: [
            {
              id: "p2s1i1",
              question: "폴더 이름을 꼭 brand로 해야 하나요?",
              body: "아니요. 다만 매번 같은 이름을 쓰면 프롬프트에서 `@brand` 한 번으로 통째로 넘길 수 있어서 편해요.",
              timeLabel: "12:44",
              timeSec: 764,
            },
          ],
        },
        {
          id: "p2s2",
          order: 2,
          variant: "prompt",
          title: "브랜드 규칙을 문장으로 적어줘요",
          actions: [line("`brand/rules.md` 만들고 아래 내용을 붙여넣기")],
          prompt: {
            label: "복사해서 그대로 쓰세요",
            code:
              "우리 브랜드 톤은 담백하고 군더더기가 없어요.\n" +
              "자막에는 느낌표를 쓰지 않고, 이모지도 넣지 않습니다.\n" +
              "강조는 색이 아니라 굵기로만 합니다.\n" +
              "인트로는 3초를 넘기지 않고, 로고는 마지막에 한 번만 노출해요.",
          },
          startSec: 776,
          endSec: 800,
          infoSheets: [],
        },
        {
          id: "p2s3",
          order: 3,
          variant: "basic",
          title: "@로 브랜드 폴더를 물려요",
          actions: [line("`@brand` 입력 → 폴더 선택 → 편집 지시와 함께 보내기")],
          startSec: 800,
          endSec: 815,
          infoSheets: [
            {
              id: "p2s3i1",
              question: "매번 물려야 하나요?",
              body: "한 세션 안에서는 한 번이면 됩니다. 창을 새로 열면 다시 물려주세요.",
              timeLabel: "13:20",
              timeSec: 800,
            },
          ],
        },
        {
          id: "p2s4",
          order: 4,
          variant: "warning",
          title: "결과물을 눈으로 한 번 봐요",
          actions: [line("자막 첫 30초만 재생해서 폰트·색 확인")],
          warning: {
            title: "톤이 흔들리면 여기서 잡아야 해요",
            body: "뒤 공정까지 간 다음에 고치면 전부 다시 돌려야 합니다.",
          },
          startSec: 815,
          endSec: 827,
          infoSheets: [],
        },
      ],
    },
    {
      id: "part-3",
      partNo: 3,
      chapterNo: "CH 03",
      title: "매번 똑같이 시키기 귀찮잖아요? feat. SKILL",
      thumbnail: "/img/part3.jpg",
      timeLabel: "13:47-15:41",
      startSec: 827,
      endSec: 941,
      doneCount: 0,
      steps: [
        {
          id: "p3s1",
          order: 1,
          variant: "basic",
          title: "스킬 파일을 만들어요",
          actions: [line("`.claude/skills/` 폴더에 `video-edit.md` 생성")],
          startSec: 827,
          endSec: 860,
          infoSheets: [
            {
              id: "p3s1i1",
              question: "스킬이 뭐예요?",
              body: "매번 치던 프롬프트를 파일로 굳혀둔 거예요. 다음부터는 이름만 부르면 같은 순서로 일합니다.",
              timeLabel: "13:55",
              timeSec: 835,
            },
          ],
        },
        {
          id: "p3s2",
          order: 2,
          variant: "prompt",
          title: "일하는 순서를 적어요",
          actions: [line("스킬 파일 안에 단계를 번호로 적기")],
          prompt: {
            label: "복사해서 그대로 쓰세요",
            code:
              "1. raw 폴더의 영상을 Whisper로 받아쓰기\n" +
              "2. 무음 구간 0.6초 이상이면 잘라내기\n" +
              "3. brand/rules.md 를 읽고 자막 스타일 적용\n" +
              "4. 컷 전환마다 효과음 후보 3개 제안\n" +
              "5. 최종본을 out 폴더에 mp4로 내보내기",
          },
          startSec: 860,
          endSec: 900,
          infoSheets: [],
        },
        {
          id: "p3s3",
          order: 3,
          variant: "basic",
          title: "스킬을 불러서 돌려요",
          actions: [line("채팅에 `video-edit 스킬로 돌려줘` 라고 입력")],
          startSec: 900,
          endSec: 925,
          infoSheets: [],
        },
        {
          id: "p3s4",
          order: 4,
          variant: "warning",
          title: "중간 결과를 저장해요",
          actions: [line("`작업 내역을 CLAUDE.md에 저장해 줘` 라고 요청")],
          warning: {
            title: "안 하면 다음에 처음부터예요",
            body: "창을 닫으면 맥락이 사라져요. 스킬을 고친 내용도 같이 적어두세요.",
          },
          startSec: 925,
          endSec: 941,
          infoSheets: [],
        },
      ],
    },
    {
      id: "part-4",
      partNo: 4,
      chapterNo: "CH 04",
      title: "B-roll은 어떻게 넣어요? feat. Higgsfield",
      thumbnail: "/img/part4.jpg",
      timeLabel: "16:55-20:35",
      startSec: 1015,
      endSec: 1235,
      doneCount: 0,
      steps: [
        {
          id: "p4s1",
          order: 1,
          variant: "warning",
          title: "Higgsfield MCP를 연결해요",
          actions: [line("커넥터 URL 복사 → `MCP 연결해 줘` → 로그인")],
          warning: {
            title: "여긴 비싸요",
            body: "15~30초 영상 하나에 2~3천 원이 나가요. B-roll은 꼭 필요한 컷에만 쓰세요.",
          },
          startSec: 1015,
          endSec: 1080,
          infoSheets: [
            {
              id: "p4s1i1",
              question: "붙었는지 확인하려면",
              body: "`/mcp` 로 들어가면 연결 목록이 보여요.",
              timeLabel: "17:20",
              timeSec: 1040,
            },
          ],
        },
        {
          id: "p4s2",
          order: 2,
          variant: "prompt",
          title: "필요한 컷만 골라서 만들어요",
          actions: [line("자막에서 B-roll이 필요한 구간을 지정")],
          prompt: {
            label: "복사해서 그대로 쓰세요",
            code:
              "02:14~02:19 구간에 들어갈 B-roll을 만들어 줘.\n" +
              "노트북 화면에 코드가 빠르게 스크롤되는 5초짜리,\n" +
              "카메라는 천천히 왼쪽으로 밀고, 색감은 따뜻한 주황 계열로.\n" +
              "사람 얼굴은 넣지 말아 줘.",
          },
          startSec: 1080,
          endSec: 1160,
          infoSheets: [
            {
              id: "p4s2i1",
              question: "한 번에 안 나오면",
              body: "Higgsfield 안에서 만든 이미지를 넘기면 영상화가 훨씬 잘 됩니다.",
              timeLabel: "18:40",
              timeSec: 1120,
            },
          ],
        },
        {
          id: "p4s3",
          order: 3,
          variant: "basic",
          title: "타임라인에 끼워 넣어요",
          actions: [line("`out/broll` 에 저장하고 해당 구간에 배치해 달라고 요청")],
          startSec: 1160,
          endSec: 1200,
          infoSheets: [],
        },
        {
          id: "p4s4",
          order: 4,
          variant: "basic",
          title: "최종본을 내보내요",
          actions: [line("`최종본 mp4로 내보내 줘` 요청 → `out` 폴더 확인")],
          startSec: 1200,
          endSec: 1235,
          infoSheets: [],
        },
      ],
    },
  ],
  script: [
    {
      id: "s1",
      partNo: 1,
      chapter: "CH 01 · What Claude Code edits for you",
      timeLabel: "00:00:00",
      timeSec: 0,
      text: "지금 보고 계신 영상은 Claude Code가 처음부터 끝까지 전부 직접 편집한 것입니다. 저는 사실 기술적인 사람이 아니에요. 제가 해야 할 일은 영상을 폴더에 드롭하는 것뿐이었고, Claude가 저 대신 전체 영상을 편집해줬습니다.",
    },
    {
      id: "s2",
      partNo: 1,
      chapter: "CH 01 · What Claude Code edits for you",
      timeLabel: "00:00:13",
      timeSec: 13,
      text: "솔직히 말해서, 과거의 AI 영상 편집기는 정말 나빴는데, 저는 결국 어떻게 하면 이걸 예쁘게 보이게 할 수 있을지 방법을 찾았어요. 이 도구는 모든 컷을 처리하고, 죽은 공간을 모두 잘라내며, 이런 식으로 모션 그래픽을 추가하고, 아래에 이런 식으로 자막까지 넣어줍니다.",
    },
    {
      id: "s3",
      partNo: 1,
      chapter: "CH 01 · What Claude Code edits for you",
      timeLabel: "00:00:28",
      timeSec: 28,
      text: "그리고 이 자막은 제 브랜드 키트로, 제가 원하는 폰트와 색상이에요. 다른 폰트나 색상을 원하시면, 그에 맞는 다른 스타일도 만들어줄 수 있어요. 그래서 정말 커스터마이징이 가능합니다. 또한 Claude Code는 영상 내용을 듣고, 자동으로 사운드 이펙트를 추가해줍니다.",
    },
    {
      id: "s4",
      partNo: 1,
      chapter: "CH 07 · Full live demo setup",
      timeLabel: "00:09:51",
      timeSec: 591,
      text: "그래서 제가 하고 싶은 건, 여러분과 함께 처음부터 끝까지 완전한 실습을 하는 거예요. 그렇게 하면 제가 실제로 어떻게 작업하는지 정확히 보여드릴 수 있죠. 제가 준비한 모든 단계를 바탕으로, 이 특정 작업을 위해 Claude를 열어보겠습니다.",
    },
    {
      id: "s5",
      partNo: 1,
      chapter: "CH 07 · Full live demo setup",
      timeLabel: "00:10:09",
      timeSec: 609,
      text: "그리고 참고로, 제가 사용하는 IDE, 즉 플랫폼인 Claude Code는 Anti-Gravity IDE라고 불립니다. 제가 Visual Studio과 다른 플랫폼 대신 이걸 쓰는 이유는 이전에 Anti-Gravity Agent를 선호했기 때문이에요. 다만 토큰이 너무 빨리 소진되어 더 이상 사용할 수 없게 되었죠.",
    },
    {
      id: "s6",
      partNo: 1,
      chapter: "CH 07 · Full live demo setup",
      timeLabel: "00:10:23",
      timeSec: 623,
      text: "더 이상 그 플랫폼을 쓸 수 없었지만, 저는 여전히 Anti-Gravity IDE를 사용하고 있어요. 특히 이 플랫폼이 무료이기 때문에 더 유용하죠. 여기서 저는 Claude Code를 사용해서 이 플랫폼에서 Claude Code가 제대로 작동하도록 하고 있습니다.",
    },
    {
      id: "s7",
      partNo: 2,
      chapter: "CH 02 · Brand kit",
      timeLabel: "00:12:36",
      timeSec: 756,
      text: "브랜드 키트를 먼저 만들어 두는 이유는 간단해요. AI가 우리 브랜드를 모르는 채로 시작하면 매번 다른 결과가 나옵니다. 폰트, 색, 자막 위치를 한 번 적어두면 그다음부터는 흔들리지 않아요.",
    },
    {
      id: "s8",
      partNo: 3,
      chapter: "CH 03 · Skill",
      timeLabel: "00:13:47",
      timeSec: 827,
      text: "매번 같은 프롬프트를 치는 게 귀찮아지는 순간이 옵니다. 그때 스킬로 굳혀두면 됩니다. 파일 하나에 순서를 적어두고, 다음부터는 이름만 부르면 돼요.",
    },
    {
      id: "s9",
      partNo: 4,
      chapter: "CH 04 · B-roll",
      timeLabel: "00:16:55",
      timeSec: 1015,
      text: "B-roll은 있으면 확실히 좋은데 비용이 붙습니다. 그래서 저는 꼭 필요한 구간만 골라서 씁니다. 말이 길어지는 구간, 화면이 정지된 구간 정도면 충분해요.",
    },
  ],
};

export const allCourses: Course[] = [course];
