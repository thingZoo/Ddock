import { useEffect, useState } from 'react';
import { Home } from './pages/Home';
import { PollResult } from './pages/PollResult';
import { TabBar, type TabKey } from './components/TabBar';

type Screen = { name: 'home' } | { name: 'pollResult'; pollId: string };

export default function App() {
  const [tab, setTab] = useState<TabKey>('home');
  const [screen, setScreen] = useState<Screen>({ name: 'home' });

  /*
   * 화면 이동을 브라우저 히스토리에 쌓는다.
   * 앱인토스 체크리스트가 요구하는 "토스 내비게이션 바 뒤로가기가 모든 화면에서
   * 정상 동작"과 "최초 화면에서 뒤로가기를 누르면 미니앱이 종료된다"를 만족시키려면
   * 자체 상태만으로 화면을 바꾸지 않고 히스토리를 함께 움직여야 한다.
   */
  useEffect(() => {
    const handlePopState = (event: PopStateEvent) => {
      const next = (event.state?.screen as Screen | undefined) ?? { name: 'home' };
      setScreen(next);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const openPollResult = (pollId: string) => {
    const next: Screen = { name: 'pollResult', pollId };
    window.history.pushState({ screen: next }, '');
    setScreen(next);
    window.scrollTo(0, 0);
  };

  const goBack = () => {
    window.history.back();
  };

  if (screen.name === 'pollResult') {
    return <PollResult pollId={screen.pollId} onBack={goBack} />;
  }

  return (
    <>
      {tab === 'home' ? <Home onPollSelect={openPollResult} /> : null}
      <TabBar active={tab} onChange={setTab} />
    </>
  );
}
