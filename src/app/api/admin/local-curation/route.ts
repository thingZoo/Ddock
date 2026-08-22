import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import path from "node:path";

import { parsePreprocessedInput } from "@/lib/admin-content-review/local-ai";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const encoder = new TextEncoder();

function jsonError(error: string, status: number) {
  return Response.json({ error }, { status });
}

function childEnvironment(): NodeJS.ProcessEnv {
  const environment = { ...process.env };
  delete environment.ANTHROPIC_API_KEY;
  delete environment.OPENAI_API_KEY;
  delete environment.GEMINI_API_KEY;
  environment.HF_HUB_OFFLINE = "1";
  environment.TRANSFORMERS_OFFLINE = "1";
  environment.HF_HUB_DISABLE_TELEMETRY = "1";
  environment.PYTHONUNBUFFERED = "1";
  return environment;
}

export async function POST(request: Request) {
  if (process.env.DDOCK_ENABLE_LOCAL_AI !== "1" || process.env.VERCEL) {
    return jsonError("로컬 AI 기능이 비활성화되어 있습니다. DDOCK_ENABLE_LOCAL_AI=1로 실행해주세요.", 403);
  }
  const python = process.env.DDOCK_LOCAL_PYTHON?.trim();
  if (!python) {
    return jsonError("DDOCK_LOCAL_PYTHON에 MLX Qwen이 설치된 Python 경로를 지정해주세요.", 503);
  }
  try {
    await access(python);
  } catch {
    return jsonError("DDOCK_LOCAL_PYTHON 경로를 실행할 수 없습니다.", 503);
  }

  let preprocessed: ReturnType<typeof parsePreprocessedInput>;
  try {
    preprocessed = parsePreprocessedInput(await request.json());
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "전처리 JSON을 읽을 수 없습니다.", 400);
  }

  const pipelineDirectory = path.join(
    process.cwd(),
    "internal-tools",
    "youtube-content-pipeline",
  );
  const generator = path.join(pipelineDirectory, "ddock_admin_skill_generator.py");
  const generatorArgs = [generator, "--stdin", "--stream"];
  const outputPath = process.env.DDOCK_ADMIN_SKILL_OUTPUT?.trim();
  if (outputPath) generatorArgs.push("--output", outputPath);
  const child = spawn(python, generatorArgs, {
    cwd: pipelineDirectory,
    env: childEnvironment(),
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stdin.end(JSON.stringify(preprocessed));

  let stderr = "";
  let resultSeen = false;
  child.stderr.on("data", (chunk: Buffer) => {
    stderr = (stderr + chunk.toString("utf8")).slice(-20_000);
  });

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false;
      const close = () => {
        if (!closed) {
          closed = true;
          controller.close();
        }
      };
      child.stdout.on("data", (chunk: Buffer) => {
        if (closed) return;
        const text = chunk.toString("utf8");
        if (text.includes('\"type\": \"result\"') || text.includes('\"type\":\"result\"')) {
          resultSeen = true;
        }
        controller.enqueue(encoder.encode(text));
      });
      child.on("error", (error) => {
        if (closed) return;
        controller.enqueue(
          encoder.encode(`${JSON.stringify({ type: "error", message: error.message })}\n`),
        );
        close();
      });
      child.on("close", (code) => {
        if (closed) return;
        if (code !== 0 || !resultSeen) {
          const message = stderr.trim() || `로컬 Python이 종료되었습니다. (code ${code ?? "unknown"})`;
          controller.enqueue(
            encoder.encode(`${JSON.stringify({ type: "error", message })}\n`),
          );
        }
        close();
      });
      request.signal.addEventListener("abort", () => child.kill("SIGTERM"), { once: true });
    },
    cancel() {
      child.kill("SIGTERM");
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
