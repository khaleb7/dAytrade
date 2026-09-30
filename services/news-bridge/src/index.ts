import { spawn, spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fixturesDir, scriptsDir, storeRoot } from "@daytrade/shared";

interface PyCmd {
  bin: string;
  prefix: string[];
}

let cachedPy: PyCmd | null = null;

/** Resolve a working Python on Windows (py -3) and Unix (python3/python). */
export function resolvePython(): PyCmd {
  if (cachedPy) return cachedPy;
  const envBin = process.env["DAYTRADE_PYTHON"] || process.env["PYTHON"] || "";
  const candidates: PyCmd[] = [];
  if (envBin) {
    // DAYTRADE_PYTHON=py → still need -3 on Windows launcher
    if (envBin === "py" || /[/\\]py(\.exe)?$/i.test(envBin)) {
      candidates.push({ bin: envBin, prefix: ["-3"] });
    } else {
      candidates.push({ bin: envBin, prefix: [] });
    }
  }
  candidates.push(
    { bin: "py", prefix: ["-3"] },
    { bin: "python", prefix: [] },
    { bin: "python3", prefix: [] },
  );

  for (const c of candidates) {
    try {
      const r = spawnSync(c.bin, [...c.prefix, "-c", "import sys; print(sys.version)"], {
        encoding: "utf8",
        timeout: 15_000,
        windowsHide: true,
      });
      if (r.status === 0) {
        cachedPy = c;
        console.log(`[news-bridge] using Python: ${c.bin} ${c.prefix.join(" ")}`.trim());
        return c;
      }
    } catch {
      /* try next */
    }
  }
  // Last resort — will fail with a clear spawn error
  cachedPy = { bin: envBin || "python3", prefix: [] };
  return cachedPy;
}

function runPython(args: string[], cwd: string): Promise<{ code: number; stdout: string; stderr: string }> {
  const py = resolvePython();
  return new Promise((resolve) => {
    const child = spawn(py.bin, [...py.prefix, ...args], {
      cwd,
      env: process.env,
      windowsHide: true,
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));
    child.on("error", (err) => {
      resolve({
        code: 1,
        stdout,
        stderr: stderr || `spawn failed (${py.bin}): ${err.message}`,
      });
    });
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

export async function fetchMarketSignals(bucket?: string): Promise<unknown> {
  const cwd = scriptsDir();
  const args = ["fetch_signals.py"];
  if (bucket) args.push("--bucket", bucket);
  try {
    const r = await runPython(args, cwd);
    if (r.code !== 0) {
      console.warn("[news-bridge] signals warning:", r.stderr || r.stdout);
      return { ok: false, error: r.stderr || r.stdout };
    }
    try {
      return JSON.parse(r.stdout);
    } catch {
      return { raw: r.stdout };
    }
  } catch (e) {
    console.warn("[news-bridge] signals failed soft:", e instanceof Error ? e.message : e);
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
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
  // Soft-fail market signals (VIX / bonds / oil) before packs read cache
  const signals = await fetchMarketSignals(bucket);

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
          const news = JSON.parse(r2.stdout);
          return { ...news, signals, mode: news.mode || "fixture_fallback" };
        } catch {
          return { raw: r2.stdout, mode: "fixture_fallback", signals };
        }
      }
    }
    throw new Error(`build-hour failed: ${r.stderr || r.stdout}`);
  }
  try {
    const news = JSON.parse(r.stdout);
    return typeof news === "object" && news ? { ...news, signals } : { news, signals };
  } catch {
    return { raw: r.stdout, store: storeRoot(), signals };
  }
}
