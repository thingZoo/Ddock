/**
 * Pretendard 동적 서브셋을 node_modules 에서 public/fonts 로 복사해요.
 * 폰트 바이너리(92개)를 저장소에 넣지 않으려고 빌드 전에 자동으로 돕니다.
 * package.json 의 predev / prebuild 에 걸려 있어요.
 */
import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const src = path.join(root, "node_modules/pretendard/dist/web/variable");
const outDir = path.join(root, "public/fonts");
const outFonts = path.join(outDir, "pretendard");

if (!existsSync(src)) {
  console.warn("[fonts] pretendard 패키지를 못 찾았어요. npm install 후 다시 돌려주세요.");
  process.exit(0);
}

await mkdir(outFonts, { recursive: true });
await cp(path.join(src, "woff2-dynamic-subset"), outFonts, { recursive: true });

const css = await readFile(path.join(src, "pretendardvariable-dynamic-subset.css"), "utf8");
await writeFile(
  path.join(outDir, "pretendard.css"),
  css.replaceAll("./woff2-dynamic-subset/", "/fonts/pretendard/"),
  "utf8"
);

console.log("[fonts] Pretendard 서브셋 준비 완료 → public/fonts");
