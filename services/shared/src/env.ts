import * as fs from "node:fs";
import * as path from "node:path";
import { storeRoot } from "./paths.js";

const DEFAULT_CANDIDATES = (): string[] => {
  const home = process.env["USERPROFILE"] || process.env["HOME"] || "";
  return [
    process.env["DAYTRADE_ENV_FILE"] || "",
    path.join(home, ".daytrade", "alpaca.env"),
    path.join(home, ".daytrade", "daytrade.env"),
    path.join(home, "daytrade", "alpaca.env"),
  ].filter(Boolean);
};

/** Load KEY=VALUE into process.env (setdefault). Refuses files under store. */
export function loadEnvFile(filePath?: string): string | null {
  const candidates = filePath ? [filePath] : DEFAULT_CANDIDATES();
  const root = path.resolve(storeRoot());
  for (const p of candidates) {
    if (!p || !fs.existsSync(p)) continue;
    const resolved = path.resolve(p);
    if (resolved === root || resolved.startsWith(root + path.sep)) {
      console.error(`refusing env file inside Project store: ${resolved}`);
      continue;
    }
    const text = fs.readFileSync(resolved, "utf8");
    for (const line of text.split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith("#") || !t.includes("=")) continue;
      const i = t.indexOf("=");
      const k = t.slice(0, i).trim();
      let v = t.slice(i + 1).trim();
      if (
        (v.startsWith('"') && v.endsWith('"')) ||
        (v.startsWith("'") && v.endsWith("'"))
      ) {
        v = v.slice(1, -1);
      }
      if (
        (k.startsWith("APCA_") || k.startsWith("DAYTRADE_") || k.startsWith("CURSOR_")) &&
        process.env[k] === undefined
      ) {
        process.env[k] = v;
      }
    }
    return resolved;
  }
  return null;
}

export function readJson<T = unknown>(filePath: string): T {
  let text = fs.readFileSync(filePath, "utf8");
  // Windows PowerShell Set-Content -Encoding utf8 writes a BOM
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  return JSON.parse(text) as T;
}

export function writeJson(filePath: string, data: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + "\n", "utf8");
}

export function isoZ(d = new Date()): string {
  return d.toISOString().replace(/\.\d{3}Z$/, "Z").replace(/Z$/, "Z");
}
