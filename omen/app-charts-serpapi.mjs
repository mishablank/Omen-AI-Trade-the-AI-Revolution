// SerpApi fallback for the Android half of the consumer-app family.
//
// update-app-charts.mjs reads Play's charts through google-play-scraper, a
// reverse-engineered scrape of Play's internal batchexecute endpoint. When that payload
// shape breaks (every year or two), the scraper writes nothing and the family degrades to
// iOS-only until the library is patched. This fills the gap from SerpApi's Google Play
// engine, which needs a key (SERPAPI_KEY), so it runs as its OWN workflow step: the
// scraper step executes third-party code and deliberately has no secrets in scope, and
// this file imports nothing but node built-ins.
//
// Quota math. SerpApi's free tier is ~100 searches a month; one search is one country's
// chart, and refresh.yml runs ~33 times a day. So the fallback is gated three ways:
//   1. only when the primary scraper wrote nothing this run (its file is not fresh);
//   2. at most once per MIN_GAP_H hours (a previous SerpApi write is still recent);
//   3. core markets only - 3 countries x 1 run/day x 30 days = 90 searches/month,
//      leaving ~10 for manual reruns.
// It relies on app-charts.json being committed every run (refresh.yml does), because
// that file's source + timestamp is the only memory the gate has.
//
// Output schema is identical to the primary's ({hits: [{label, store:"android", country,
// rank, appId, title}]}), so android_hits() in update-china-data.py needs no change.
// One honest difference: SerpApi's chart parameter returns at most 50 apps, so ranks
// 51-200 are invisible to the fallback; `depth` records it.
//
// Run: node omen/app-charts-serpapi.mjs   (no npm install needed)
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const ENDPOINT = "https://serpapi.com/search.json";
export const CORE_COUNTRIES = ["us", "gb", "de"];
export const MIN_GAP_H = 20;
export const PRIMARY_FRESH_H = 1;
export const DEPTH = 50;
// Keep in sync with update-app-charts.mjs and APP_BASKET in update-china-data.py
// (test_update_china_data.py asserts all three agree).
export const BASKET = [
  ["DeepSeek", /deepseek/i],
  ["Qwen", /\bqwen\b|tongyi/i],
  ["Doubao", /doubao|\bcici\b/i],
  ["Kimi", /\bkimi\b|kimichat/i],
  ["MiniMax", /talkie|hailuo|minimax|weaver\.app/i],
];

export function label(title, appId) {
  const text = `${title || ""} ${appId || ""}`;
  for (const [name, rx] of BASKET) if (rx.test(text)) return name;
  return null;
}

export function chartUrl(country, key) {
  const q = new URLSearchParams({ engine: "google_play", store: "apps", chart: "topselling_free",
                                  gl: country, hl: "en", api_key: key });
  return `${ENDPOINT}?${q}`;
}

// SerpApi payload -> the ranked app list, flattened across sections in order.
export function chartItems(payload) {
  const items = [];
  for (const sec of payload?.organic_results || []) {
    for (const it of sec?.items || []) items.push(it);
  }
  return items.slice(0, DEPTH);
}

export function serpHits(payload, country) {
  const hits = [];
  chartItems(payload).forEach((a, i) => {
    const lbl = label(a.title, a.product_id);
    if (lbl) hits.push({ label: lbl, store: "android", country, rank: i + 1, appId: a.product_id, title: a.title });
  });
  return hits;
}

// prev = the app-charts.json already on disk (or null). -> {run, reason}
export function shouldRun(prev, nowMs) {
  const age = prev?.updated ? (nowMs - Date.parse(prev.updated)) / 3600e3 : Infinity;
  if (prev?.source === "google-play-scraper" && age < PRIMARY_FRESH_H)
    return { run: false, reason: "primary scraper wrote this run" };
  if (prev?.source === "serpapi" && age < MIN_GAP_H)
    return { run: false, reason: `last SerpApi pull ${age.toFixed(1)}h ago (quota gate: ${MIN_GAP_H}h)` };
  return { run: true, reason: "primary scraper wrote nothing fresh" };
}

export function buildOut(hits, countriesOk, now) {
  return {
    updated: now.toISOString().replace(/\.\d+Z$/, "Z"),
    source: "serpapi",
    store: "android",
    depth: DEPTH,
    countries_ok: countriesOk,
    countries: CORE_COUNTRIES,
    hits,
  };
}

async function main() {
  const key = process.env.SERPAPI_KEY;
  if (!key) { console.log("SERPAPI_KEY not set - fallback skipped"); return 0; }
  const path = new URL("./app-charts.json", import.meta.url);
  let prev = null;
  try { prev = JSON.parse(readFileSync(path, "utf8")); } catch { /* first run */ }
  const gate = shouldRun(prev, Date.now());
  console.log(`serpapi fallback: ${gate.run ? "running" : "skipped"} (${gate.reason})`);
  if (!gate.run) return 0;
  const hits = [];
  let ok = 0;
  for (const country of CORE_COUNTRIES) {
    try {
      const r = await fetch(chartUrl(country, key));
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const payload = await r.json();
      if (payload.error) throw new Error(payload.error);
      if (!chartItems(payload).length) throw new Error("empty chart");
      ok++;
      hits.push(...serpHits(payload, country));
    } catch (e) {
      console.error(`  ${country}: FAILED (${e.message})`);
    }
  }
  if (ok === 0) {
    console.error("all SerpApi queries failed - not writing app-charts.json");
    return 1;
  }
  writeFileSync(path, JSON.stringify(buildOut(hits, ok, new Date()), null, 1) + "\n");
  console.log(`wrote app-charts.json via SerpApi: ${hits.length} CN-app hits across ${ok}/${CORE_COUNTRIES.length} core markets`);
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exitCode = await main();
}
