/** 로그북 (355:10032) — MVP에선 자리만 두고 빈 상태로 둡니다 */
export function LogTab() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-8 py-24 text-center">
      <div className="grid h-14 w-14 place-items-center rounded-full bg-zinc-100">
        <svg width="24" height="24" viewBox="0 0 24 24" className="text-zinc-300">
          <path
            d="M4 5h16v14H4zM8 9h8M8 13h5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <p className="t-sm-bold text-zinc-700">아직 남긴 로그가 없어요</p>
      <p className="t-xs-body text-zinc-500">
        카드를 따라 해보고 결과물을 남기면 여기에 쌓여요.
        <br />
        기록 기능은 다음 업데이트에서 열려요.
      </p>
    </div>
  );
}
