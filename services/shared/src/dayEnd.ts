import * as fs from "node:fs";
import { formatDay, parseDay, previousTradingDay } from "./calendar.js";
import { readJson } from "./env.js";
import { dayEndAnalysisPath } from "./paths.js";

export type DayEndAnalysis = {
  date: string;
  generated_at?: string;
  for_next_session?: string;
  stats?: Record<string, unknown>;
  lessons?: string[];
  [key: string]: unknown;
};

export function loadDayEndAnalysis(day: string): DayEndAnalysis | null {
  const p = dayEndAnalysisPath(day);
  if (!fs.existsSync(p)) return null;
  try {
    return readJson<DayEndAnalysis>(p);
  } catch {
    return null;
  }
}

/** Walk back up to 10 trading days to find the latest day-end analysis before `beforeDay`. */
export function previousTradingDayAnalysis(beforeDay: string): DayEndAnalysis | null {
  let d = parseDay(beforeDay);
  for (let i = 0; i < 10; i++) {
    d = previousTradingDay(d);
    const hit = loadDayEndAnalysis(formatDay(d));
    if (hit) return hit;
  }
  return null;
}
