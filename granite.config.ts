import { defineConfig } from '@apps-in-toss/web-framework/config';

export default defineConfig({
  // 콘솔에 등록된 appName (변경 불가)
  appName: 'ddock',
  brand: {
    displayName: '디독',
    primaryColor: '#F97316',
    // 콘솔 앱 정보에 업로드한 라이트 모드 로고
    icon: 'https://static.toss.im/appsintoss/79245/960e063a-f47e-4b6a-a5c8-5ff51b0bde49.png',
  },
  web: {
    host: 'localhost',
    port: 5173,
    commands: {
      dev: 'vite dev',
      build: 'vite build',
    },
  },
  permissions: [],
  outdir: 'dist',
});
