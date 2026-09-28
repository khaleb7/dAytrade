import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fixturesDir, scriptsDir, storeRoot } from "@daytrade/shared";

function pythonBin(): string {
  return process.env.DAYTRADE_PYTHON || process.env.PYTHON || "python3";
}

function runPython(args: string[], cwd: string): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(pythonBin(), args, { cwd, env: process.env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));
    child.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }));
  });
}

export async function ingestLiveFeeds(): Promise<unknown> {
  const cwd = scriptsDir();
  const r = await runPython(["fetch_news.py", "ingest", "--live-feeds"], cwd);
  if (r.code !== 0) throw new Error(`ingest failed: ${r.stderr || r.stdout}`);
  try {
    return JSON.parse(r.stdout);
  } catch {
    return { raw: r.stdout };
  }
}

export async function buildHour(
  bucket: string,
  opts: { skipIngest?: boolean; fromFixtures?: boolean; allowNonRth?: boolean } = {},
): Promise<unknown> {
  const cwd = scriptsDir();
  if (!opts.skipIngest && !opts.fromFixtures) {
    try {
      await ingestLiveFeeds();
    } catch (e) {
      console.warn("[news-bridge] ingest warning:", e instanceof Error ? e.message : e);
    }
  }
  const args = ["fetch_news.py", "build-hour", bucket];
  if (opts.allowNonRth) args.push("--allow-non-rth");
  if (opts.fromFixtures) {
    const fixture = path.join(fixturesDir(), "hourly", "news.json");
    if (fs.existsSync(fixture)) args.push("--from-fixture", fixture);
  }
  const r = await runPython(args, cwd);
  if (r.code !== 0) {
    // fixture fallback
    const fixture = path.join(fixturesDir(), "hourly", "news.json");
    if (fs.existsSync(fixture)) {
      const r2 = await runPython(
        ["fetch_news.py", "build-hour", bucket, "--from-fixture", fixture, "--allow-non-rth"],
        cwd,
      );
      if (r2.code === 0) {
        try {
          return JSON.parse(r2.stdout);
        } catch {
          return { raw: r2.stdout, mode: "fixture_fallback" };
        }
      }
    }
    throw new Error(`build-hour failed: ${r.stderr || r.stdout}`);
  }
  try {
    return JSON.parse(r.stdout);
  } catch {
    return { raw: r.stdout, store: storeRoot() };
  }
}
