import type { TrackerContext } from "./types.js";

export async function fetchContext(baseUrl: string, asOf: string): Promise<TrackerContext> {
  const root = baseUrl.replace(/\/$/, "");
  const url = `${root}/v1/context?as_of=${encodeURIComponent(asOf)}`;
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  const text = await res.text();
  if (!res.ok) throw new Error(`Newstracker HTTP ${res.status}: ${text}`);
  const body = JSON.parse(text) as TrackerContext;
  if (!Array.isArray(body.articles) || !Array.isArray(body.bars)) {
    throw new Error("Newstracker context missing articles or bars");
  }
  return body;
}
