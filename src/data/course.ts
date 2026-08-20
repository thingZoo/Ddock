import type { Course } from "@/lib/types";

// 프로젝트 문서 `claude/B안_카드구성.md` 원문을 그대로 옮긴 시드 데이터입니다.
// difficulty(난이도 점)와 tags(태그 칩) 값은 문서에 정확한 목록이 없어 임시로 채운 값이라,
// 실제 명세서(v0.6.1) 확정되면 교체해야 합니다.

export const course: Course = {
  id: "claude-code-marketing-agency",
  title: "클로드 코드로 만드는 AI 콘텐츠 마케팅 에이전시",
  sourceUrl: "https://www.youtube.com/watch?v=-1zFrs_TnoM",
  durationLabel: "1시간 38분",
  description:
    "빌더 조쉬의 라이브 실습 영상을 실습 카드 5개 · STEP 20개로 압축했어요. 영상 없이 따라와도 손이 움직일 수 있게, 표면엔 액션만 남기고 나머지는 ⓘ 바텀시트 뒤로 넣었습니다.",
  tags: [
    "오르카",
    "클로드코드",
    "컨텍스트",
    "서브에이전트",
    "GPT Image",
    "영상생성",
    "자동발행",
    "마케팅에이전트",
  ],
  cards: [
    {
      id: "card-01",
      order: 1,
      title: "AI한테 뭘 알려주고 시작해요? feat. Orca",
      timeRange: "07:34~28:50",
      summary:
        "AI가 우리 브랜드를 모르는 채로 시작하면 매번 다른 결과가 나와요. 레퍼런스부터 깔아둬요.",
      tags: ["오르카", "클로드코드", "컨텍스트"],
      difficulty: "입문",
      checkpoint: "`context` 폴더 안에 캐릭터 1장 + 레퍼런스 2~3장.",
      checkpointTimeRange: "28:28~28:50",
      steps: [
        {
          id: "card-01-step-01",
          order: 1,
          title: "오르카에 프로젝트 폴더를 만들어요",
          timeRange: "11:14~11:50",
          action: "오르카 → 새 프로젝트 만들기 → 이름 입력 (예: claude-project)",
          warnings: [],
          infoSheets: [
            {
              id: "card-01-step-01-info-01",
              question: "오르카를 꼭 써야 하나요?",
              body: "아니요. 터미널만 있으면 돼요. 다만 조쉬가 커서에서 오르카로 갈아탄 이유가 있어요. 커서는 코드 화면을 감추고 단순해지는 쪽으로 갔는데, 에이전트를 여러 개 굴리려면 창이 많이 필요하거든요. 오르카는 한 화면에서 터미널을 8개까지 쪼개고 브라우저까지 같이 봐요. 무료고, 휴대전화 페어링도 됩니다.",
              timeRange: "07:53~11:16",
            },
          ],
        },
        {
          id: "card-01-step-02",
          order: 2,
          title: "터미널에 claude를 쳐요",
          timeRange: "11:46~12:14",
          action: "프로젝트를 열면 터미널이 떠요. `claude` 입력하고 엔터.",
          warnings: [],
          infoSheets: [
            {
              id: "card-01-step-02-info-01",
              question: "창을 미리 쪼개두면 편해요",
              body: "터미널 분할 버튼을 누르면 창이 옆으로 갈라져요. 끌어다 배치하면 8분할까지 돼요. 뒤에서 카드뉴스 창, 블로그 창, 웹사이트 창을 동시에 돌릴 거라 지금 익혀두면 좋아요.",
              timeRange: "12:12~13:18",
            },
          ],
        },
        {
          id: "card-01-step-03",
          order: 3,
          title: "context 폴더를 만들어요",
          timeRange: "22:02~22:43",
          action: "파일 영역 우클릭 → 새 폴더 → `context` 입력",
          warnings: [],
          infoSheets: [
            {
              id: "card-01-step-03-info-01",
              question: "이 폴더가 왜 필요해요?",
              body: '우리가 어디로 가려는지를 AI한테 통째로 넘겨주는 공간이에요. 팀을 짜기 전에 길잡이를 먼저 깔아두는 셈이에요.\n\n"컨텍스트 안 넣어도 순정 모델이 제일 잘한다"는 말도 있던데요?\n코딩은 맞는 말이에요. 코드 품질을 맞추려고 하네스를 짜던 개발자들 사이에서 나온 얘기예요. 카드뉴스처럼 톤을 매번 똑같이 유지해야 하는 작업은 달라요. 컨텍스트를 안 깔면 생성할 때마다 스타일이 흔들려요.',
              timeRange: "22:51~24:38",
            },
          ],
        },
        {
          id: "card-01-step-04",
          order: 4,
          title: "캐릭터랑 레퍼런스 이미지를 넣어요",
          timeRange: "24:55~28:22",
          action:
            "캐릭터 1장을 `클로드.png`로 이름 바꿔 넣고, 마음에 드는 톤의 카드뉴스 2~3장을 같이 넣어요.",
          warnings: [],
          infoSheets: [
            {
              id: "card-01-step-04-info-01",
              question: "레퍼런스는 어떻게 고르나요?",
              body: "그대로 베낄 필요 없어요. 조쉬도 처음 본 톤 대신 자기가 좋아하는 다른 톤으로 바꿔 넣었어요. 파일명을 알아보기 쉽게 바꿔두면 나중에 `@`로 지정할 때 편해요.",
              timeRange: "27:02~28:50",
            },
          ],
        },
      ],
    },
    {
      id: "card-02",
      order: 2,
      title: "한 AI에게 다 시키지 말고 역할부터 나눠보세요",
      timeRange: "28:50~46:21",
      summary: "제작·검수·디렉팅 역할을 나눠서, 반복해 쓸 AI 마케팅 팀을 만들어요.",
      tags: ["클로드코드", "서브에이전트"],
      difficulty: "중급",
      checkpoint:
        "`.claude/agents/`에 에이전트 파일들, `.claude/skills/`에 캠페인 파이프라인 하나. 첫 카드뉴스도 하나 나오는데, 색만 깔린 HTML이라 별로예요. 원래 이래요.",
      checkpointTimeRange: "39:32~44:26",
      steps: [
        {
          id: "card-02-step-01",
          order: 1,
          title: "만들 것을 개수까지 적어요",
          timeRange: "30:11~31:07",
          action: "원하는 결과물을 숫자로 못 박아 적어요.",
          prompt: {
            id: "card-02-step-01-prompt",
            code: "내가 원하는 것은 1:1 사이즈의 6장 형태의 카드뉴스 생성이랑,\n3천 자 정도의 블로그, 그리고 500자 정도의 뉴스레터·쓰레드·링크드인 포스팅 등이야.\n이러한 형태의 마케팅 에이전트 팀을 우선 추천해 줘.",
          },
          warnings: [],
          infoSheets: [
            {
              id: "card-02-step-01-info-01",
              question: "프롬프트는 얼마나 길게 써야 해요?",
              body: "조쉬는 하나에 30분을 쓸 때도 있어요. 의도를 TMI처럼 다 풀어야 맥락이 잡혀요. 길게 쓰기가 힘들면 음성 입력을 붙이세요. 말로 하면 훨씬 길게 나와요.",
              timeRange: "31:53~33:32",
            },
          ],
        },
        {
          id: "card-02-step-02",
          order: 2,
          title: "@로 context 폴더를 물려요",
          timeRange: "31:03~31:57",
          action: "`@` 입력 → `context` 폴더 선택 → 파일도 `@`로 지정",
          prompt: {
            id: "card-02-step-02-prompt",
            code: "@context @context/클로드.png 가 메인 캐릭터야.\n나머지 파일들은 카드뉴스와 전체적인 브랜딩 느낌을 표현한 그림들이야.\n이 내용 파악해서 에이전트 팀 추천해 줘.",
          },
          warnings: [],
          infoSheets: [],
        },
        {
          id: "card-02-step-03",
          order: 3,
          title: '구성안을 보고 "진행해"',
          timeRange: "35:00~35:32",
          action: "팀 구성안이 올라오면 `진행해` 한 마디로 만들어져요.",
          warnings: [],
          infoSheets: [
            {
              id: "card-02-step-03-info-01",
              question: "어떤 팀이 나오나요?",
              body: "오케스트레이터(마케팅 디렉터) 1명, 제작 3명(카드뉴스 크리에이터·블로그 라이터·소셜 미디어 라이터), 검수 담당(브랜드 가디언·카피 리뷰어). 검수 쪽은 요청 안 해도 알아서 껴줘요.",
              timeRange: "33:44~35:21",
            },
            {
              id: "card-02-step-03-info-02",
              question: "스킬 하나로도 되는데 왜 팀으로 해요?",
              body: "카드뉴스 스킬 하나만 만들어 싱글로 써도 돼요. 다만 톤을 매번 똑같이 유지하려면 팀 쪽이 안정적이에요.",
              timeRange: "36:06~37:02",
            },
          ],
        },
        {
          id: "card-02-step-04",
          order: 4,
          title: "CLAUDE.md를 만들어요",
          timeRange: "44:39~46:00",
          action: "아래 한 줄이면 돼요.",
          prompt: {
            id: "card-02-step-04-prompt",
            code: "CLAUDE.md 파일 만들어 줘.",
          },
          warnings: [],
          infoSheets: [
            {
              id: "card-02-step-04-info-01",
              question: "이걸 왜 따로 만들어요?",
              body: "서브에이전트를 아무리 잘 만들어도 CLAUDE.md가 없으면 작업 순서를 까먹어요. 제조업의 SOP(업무 매뉴얼)와 같은 자리예요. 누가 먼저 일하고 누구한테 넘기는지를 여기 적습니다.\n\n그래서 에이전트가 뭔데요?\n마크다운 프롬프트 모음집이에요. 위에 머리말, 아래에 일하는 순서가 적힌 파일이고, `.claude/agents/`에 있어요. 숨김 폴더라 파일 목록에서 숨김 표시를 켜야 보여요.",
              timeRange: "43:23~46:14",
            },
          ],
        },
      ],
    },
    {
      id: "card-03",
      order: 3,
      title: "결과물이 밋밋해요? 이미지 엔진을 붙이세요 feat. GPT Image 2.0",
      timeRange: "46:21~1:10:08",
      summary:
        "클로드엔 이미지 생성 엔진이 없어요. 카드 모양만 HTML로 짜준 거예요. 엔진을 붙이면 달라져요.",
      tags: ["GPT Image", "컨텍스트"],
      difficulty: "중급",
      checkpoint:
        "첫 HTML판과 나란히 놓고 봐요. 폰트와 스타일이 올라가고, 캐릭터가 돋보기를 드는 식의 동작까지 들어와요.",
      checkpointTimeRange: "1:07:30~1:09:21",
      steps: [
        {
          id: "card-03-step-01",
          order: 1,
          title: ".env 파일을 만들어요",
          timeRange: "49:13~49:32",
          action: "프로젝트 맨 위에 `.env` 파일 생성",
          warnings: [],
          infoSheets: [
            {
              id: "card-03-step-01-info-01",
              question: ".gitignore는 뭐예요?",
              body: '"이 파일들은 깃에 올리지 마"라고 적어두는 목록이에요. 프로젝트를 만들면 기본으로 생기고, `.env`가 여기 들어 있는지 꼭 확인하세요.\n\n나중에 배포할 땐 키를 어디 넣어요?\nVercel → Settings → Environment Variables. 데이터베이스는 Supabase, 배포는 Vercel이 맡는다고 보면 돼요.',
              timeRange: "53:34~56:27",
            },
          ],
        },
        {
          id: "card-03-step-02",
          order: 2,
          title: "OpenAI API 키를 발급받아요",
          timeRange: "50:35~51:21",
          action: "platform.openai.com → API keys → Create new secret key → 이름 입력 → 복사",
          warnings: [
            {
              id: "card-03-step-02-warning-01",
              title: "키가 새면 돈이 나가요",
              body: "조쉬는 예전에 깃허브 코드에 제미나이 키를 하드코딩했다가 탈취당해 270만 원이 나갔어요. `.env`에만 넣고, 화면 공유·영상에도 노출하지 마세요.",
              timeRange: "49:28~50:37",
            },
          ],
          infoSheets: [],
        },
        {
          id: "card-03-step-03",
          order: 3,
          title: ".env에 키를 붙여넣어요",
          timeRange: "51:20~51:36",
          action: "`OPENAI_API_KEY=` 뒤에 붙여넣고 저장",
          warnings: [],
          infoSheets: [],
        },
        {
          id: "card-03-step-04",
          order: 4,
          title: '"HTML로 만들지 말고 이 키 써"',
          timeRange: "51:26~53:08",
          action: "키를 넣었다는 사실과, HTML로 만들지 말라는 걸 같이 알려줘요.",
          prompt: {
            id: "card-03-step-04-prompt",
            code: ".env 파일에 OpenAI API 키를 넣었어. 이걸로 GPT Image 2.0 모델을 쓰고 싶어.\n지금부터 카드뉴스를 생성할 때 무조건 해당 API 키를 참고해서 생성해 줘.\n지금처럼 HTML로 만들지 말고.\n\n브랜드 이미지는 @context 이 내용들을 꼭 참고하고,\n캐릭터는 @context/클로드.png 를 꼭 참고해서 모든 카드뉴스의 캐릭터를 잘 생성해 줘.\n테스트 이미지 하나 만들어 보자.",
          },
          warnings: [],
          infoSheets: [
            {
              id: "card-03-step-04-info-01",
              question: "돈 얼마나 들어요?",
              body: "카드뉴스 한 장에 몇백 원이 안 돼요. 혼자 소셜 미디어를 굴리는 정도면 걱정 안 해도 됩니다.",
              timeRange: "57:34~58:27",
            },
            {
              id: "card-03-step-04-info-02",
              question: "API 키 없이 하는 방법도 있어요",
              body: '클로드 코드 안에 코덱스 CLI 플러그인을 붙이면 키 없이 GPT Image 2.0을 부를 수 있어요. 유료 코덱스 계정이 필요해요. 조쉬도 라이브 중에 알았어요. "제가 굳이 키를 연동하라는 걸 안 보여줘도 됐었네."',
              timeRange: "1:01:51~1:03:07",
            },
          ],
        },
        {
          id: "card-03-step-05",
          order: 5,
          title: "6장 세트를 뽑아요",
          timeRange: "1:01:13~1:01:50",
          action: "원본 레퍼런스를 한 번 더 물리고 세트로 요청해요.",
          prompt: {
            id: "card-03-step-05-prompt",
            code: "테스트 결과물은 잘 나온 것 같은데,\n클로드 캐릭터랑 다른 캐릭터들 해서 좀 더 원래 줬던 이미지 형태로 만들고 싶어.\n@context/클로드.png @context/레퍼런스.png 좀 더 참고해서\n비슷한 스타일로 6장짜리 세트 하나 생성해 보자.",
          },
          warnings: [],
          infoSheets: [
            {
              id: "card-03-step-05-info-01",
              question: "중간에 내용이 빠져요",
              body: "여러 에이전트를 거치는 동안 핵심 정보가 누락되면 컨텍스트 윈도우가 모자란 거예요. 모델 선택에서 `1M 컨텍스트`가 붙은 모델로 바꾸세요. 사람도 지치면 생산성이 떨어지는 것과 같아요.",
              timeRange: "1:05:32~1:07:35",
            },
          ],
        },
      ],
    },
    {
      id: "card-04",
      order: 4,
      title: "카드 이미지, 영상으로도 쓰고 싶어요? feat. Higgsfield",
      timeRange: "1:10:08~1:19:22",
      summary: "정지 이미지보다 인스타 반응이 올라가요. 6장 중 첫 장만 움직이게 해도 충분해요.",
      tags: ["영상생성"],
      difficulty: "심화",
      checkpoint: "5초짜리 영상 1개. 캐릭터가 튀고 글자가 흔들려요.",
      checkpointTimeRange: "1:18:33~1:19:08",
      steps: [
        {
          id: "card-04-step-01",
          order: 1,
          title: "Higgsfield MCP를 연결해요",
          timeRange: "1:11:27~1:12:24",
          action: '"Higgsfield MCP" 검색 → 커넥터 URL 복사 → 클로드 코드에 붙여넣고 `MCP 연결해 줘` → 로그인',
          warnings: [
            {
              id: "card-04-step-01-warning-01",
              title: "여긴 비싸요",
              body: "15~30초 영상 하나에 2~3천 원이 나가요. Higgsfield는 Seedance 모델 기반이라, Seedance를 밖에서 직접 쓰면 더 싸게 됩니다. 오늘은 연결이 쉬워서 쓰는 거예요.",
              timeRange: "1:12:47~1:13:50",
            },
          ],
          infoSheets: [
            {
              id: "card-04-step-01-info-01",
              question: "붙었는지 확인하려면",
              body: "`/mcp` 로 들어가면 연결 목록이 보여요.",
              timeRange: "1:12:14~1:12:38",
            },
          ],
        },
        {
          id: "card-04-step-02",
          order: 2,
          title: "카드 1장을 영상으로 바꿔요",
          timeRange: "1:14:07~1:14:39",
          action: "카드 이미지를 채팅창에 끌어다 놓고 지시해요.",
          prompt: {
            id: "card-04-step-02-prompt",
            code: "이 카드 이미지를 Higgsfield MCP로 5초짜리로,\n캐릭터가 통통 튀어다니고 글자도 조금씩 움직이는 듯한 느낌으로 생성해 줘.",
          },
          warnings: [],
          infoSheets: [
            {
              id: "card-04-step-02-info-01",
              question: "한 번에 안 되면",
              body: "클로드 코드에서 만든 이미지를 넘기면 영상화가 잘 안 되는 경우가 있어요. Higgsfield 서비스 안에서 만든 이미지를 넘기면 훨씬 잘 나와요.",
              timeRange: "1:14:35~1:15:39",
            },
          ],
        },
        {
          id: "card-04-step-03",
          order: 3,
          title: "첫 장만 영상으로 가세요",
          timeRange: "1:19:05~1:19:22",
          action: "나머지 5장은 브랜드 톤 그대로 이미지로 두세요.",
          warnings: [],
          infoSheets: [],
        },
      ],
    },
    {
      id: "card-05",
      order: 5,
      title: "만든 걸 자동으로 올리고 싶어요 feat. Buffer",
      timeRange: "1:19:22~1:26:19",
      summary: "카드뉴스·블로그·소셜 글을 한 페이지에서 굴리고, 매일 오전 9시에 자동으로 올려요.",
      tags: ["자동발행", "마케팅에이전트"],
      difficulty: "심화",
      checkpoint:
        "마케팅 스튜디오 페이지가 나와요. 디렉터 / 카드뉴스 / 블로그 / SNS 탭이 있고, 캠페인 주제를 넣으면 아래로 결과가 생성돼요. 만든 영상도 자동 재생되고 히스토리도 남아요.",
      checkpointTimeRange: "1:25:08~1:26:14",
      steps: [
        {
          id: "card-05-step-01",
          order: 1,
          title: "블로그 에이전트를 돌려요",
          timeRange: "1:16:40~1:17:30",
          action: "영상 작업 창은 그대로 두고 터미널을 하나 더 열어요.",
          prompt: {
            id: "card-05-step-01-prompt",
            code: "지금 카드뉴스 만든 브랜드 톤 가지고 블로그 에이전트를 가동해서\nHTML 기반의 블로그 페이지 하나 생성해 줘.",
          },
          warnings: [],
          infoSheets: [
            {
              id: "card-05-step-01-info-01",
              question: "글만 나와요",
              body: "본문 중간 이미지는 안 들어가요. GPT Image 2.0으로 별도 프롬프트를 먹여야 합니다.",
              timeRange: "1:25:43~1:26:04",
            },
          ],
        },
        {
          id: "card-05-step-02",
          order: 2,
          title: "작업 내역을 저장해요",
          timeRange: "1:19:37~1:20:01",
          action: "이걸 빼먹으면 다음에 처음부터 다시 해야 해요.",
          prompt: {
            id: "card-05-step-02-prompt",
            code: "지금까지의 작업 내역을 CLAUDE.md랑 카드뉴스 에이전트에 잘 저장해 줘.",
          },
          warnings: [],
          infoSheets: [],
        },
        {
          id: "card-05-step-03",
          order: 3,
          title: "팀을 굴릴 웹사이트를 만들어요",
          timeRange: "1:20:38~1:21:17",
          action: "터미널을 하나 더 열고, 끝에 루프를 걸어요.",
          prompt: {
            id: "card-05-step-03-prompt",
            code: "전체 마케팅 에이전트 팀을 웹에서 돌릴 수 있도록 웹사이트를 하나 만들어 줘.\n잘 작동되는지 루프로 확인하고 완성도 있게 만들어 줘.",
          },
          warnings: [],
          infoSheets: [
            {
              id: "card-05-step-03-info-01",
              question: "루프를 왜 걸어요?",
              body: "에러 없이 한 번에 뽑으려고요. 내가 중간에 확인을 덜 해도 완성도가 올라와요. 중간중간 검수해야 하는 작업엔 안 걸어요.",
              timeRange: "1:21:11~1:21:49",
            },
          ],
        },
        {
          id: "card-05-step-04",
          order: 4,
          title: "자동 발행을 걸어요",
          timeRange: "1:22:22~1:24:05",
          action: "버퍼(Buffer)에 가입하고 API 키를 발급받아 연동해요.",
          warnings: [
            {
              id: "card-05-step-04-warning-01",
              title: "티스토리·네이버는 어려워요",
              body: "워드프레스는 되는데 티스토리·네이버는 방법이 까다로워요. 쓰레드·링크드인 다이렉트 연동도 마찬가지고요. 버퍼를 한 번 거치세요.",
              timeRange: "1:24:01~1:24:47",
            },
          ],
          infoSheets: [
            {
              id: "card-05-step-04-info-01",
              question: "버퍼가 뭐예요?",
              body: "인스타·쓰레드·X·링크드인에 글을 한꺼번에 올려주는 서비스예요. API와 MCP를 둘 다 지원해서, 연동하면 매일 오전 9시 자동 배포까지 걸 수 있어요. 예전엔 무료 키가 있었는데 지금은 유료 플랜이 필요해요.",
            },
          ],
        },
      ],
    },
  ],
};

export const allCourses: Course[] = [course];
