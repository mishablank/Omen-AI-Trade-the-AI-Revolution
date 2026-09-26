// Unit tests for app-charts-serpapi.mjs — the keyed SerpApi fallback for the Android
// half of the consumer-app family. The gate is the part that matters most: SerpApi's free
// tier is ~100 searches a month and the refresh runs ~33 times a day, so a gate that
// fails open burns the month's quota in an afternoon.
//
//   node omen/test-app-charts.mjs
//
// Imported, not sliced: it is a real module, and importing it must not run main().

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BASKET, CORE_COUNTRIES, DEPTH, MIN_GAP_H, buildOut, chartItems, chartUrl, label, serpHits, shouldRun,
} from "./app-charts-serpapi.mjs";

let failures = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) return;
  failures++;
  console.error(`  FAIL ${name}\n    got:  ${JSON.stringify(got)}\n    want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failures++;
  console.error(`  FAIL ${name}${detail ? " – " + detail : ""}`);
};

console.log("app-charts SerpApi fallback – parsing, gate, schema\n");

/* ---------- parsing ---------- */
{
  const payload = { organic_results: [
    { items: [
      { title: "ChatGPT", product_id: "com.openai.chatgpt" },
      { title: "DeepSeek - AI Assistant", product_id: "com.deepseek.chat" },
      { title: "Some game", product_id: "com.game" },
    ] },
    { items: [{ title: "Talkie: Creative AI Community", product_id: "com.weaver.app.prod" }] },
  ] };
  eq("ranks run across sections in order", serpHits(payload, "us"), [
    { label: "DeepSeek", store: "android", country: "us", rank: 2, appId: "com.deepseek.chat", title: "DeepSeek - AI Assistant" },
    { label: "MiniMax", store: "android", country: "us", rank: 4, appId: "com.weaver.app.prod", title: "Talkie: Creative AI Community" },
  ]);
  eq("a malformed payload is an empty chart, not a crash", chartItems({ organic_results: [null, {}] }), []);
  eq("no organic_results at all", chartItems({ error: "quota" }), []);
  const long = { organic_results: [{ items: Array.from({ length: 80 }, (_, i) => ({ title: "x" + i })) }] };
  eq("capped at the documented chart depth", chartItems(long).length, DEPTH);
  eq("label matches on appId too", label("Assistant", "com.moonshot.kimichat"), "Kimi");
  eq("label ignores the unrelated", label("Qwerty keyboard", "com.qwerty"), null);
}

/* ---------- request ---------- */
{
  const u = new URL(chartUrl("gb", "K"));
  eq("engine/store/chart/country", [u.searchParams.get("engine"), u.searchParams.get("store"),
      u.searchParams.get("chart"), u.searchParams.get("gl")], ["google_play", "apps", "topselling_free", "gb"]);
  ok("quota math: core markets x 1/day stays under 100/month", CORE_COUNTRIES.length * 30 <= 95,
     `${CORE_COUNTRIES.length} markets`);
  ok("quota gate is at least most of a day", MIN_GAP_H >= 20);
}

/* ---------- the gate ---------- */
{
  const now = Date.parse("2026-09-26T12:00:00Z");
  const at = (h) => new Date(now - h * 3600e3).toISOString();
  eq("runs on a first-ever run", shouldRun(null, now).run, true);
  eq("stays out when the scraper wrote this run",
     shouldRun({ source: "google-play-scraper", updated: at(0.2) }, now).run, false);
  eq("runs when the scraper's file is stale (it wrote nothing this run)",
     shouldRun({ source: "google-play-scraper", updated: at(3) }, now).run, true);
  eq("quota gate: a recent SerpApi pull blocks another",
     shouldRun({ source: "serpapi", updated: at(5) }, now).run, false);
  eq("quota gate reopens after MIN_GAP_H",
     shouldRun({ source: "serpapi", updated: at(MIN_GAP_H + 0.5) }, now).run, true);
  eq("an unparseable stamp does not wedge the gate shut",
     shouldRun({ source: "serpapi", updated: "garbage" }, now).run, true);
}

/* ---------- schema parity with the primary ---------- */
{
  const out = buildOut([], 2, new Date("2026-09-26T12:00:00.123Z"));
  eq("stamp format matches the primary's", out.updated, "2026-09-26T12:00:00Z");
  for (const k of ["updated", "source", "store", "depth", "countries_ok", "hits"])
    ok(`carries the primary's key ${k}`, k in out);
  eq("source says which path wrote it", out.source, "serpapi");
}

/* ---------- one basket across both JS fetchers ---------- */
{
  const here = dirname(fileURLToPath(import.meta.url));
  const primary = readFileSync(join(here, "update-app-charts.mjs"), "utf8");
  const pairs = [...primary.matchAll(/\["(\w+)", \/(.+?)\/i\]/g)].map((m) => [m[1], m[2]]);
  eq("BASKET matches update-app-charts.mjs", BASKET.map(([n, rx]) => [n, rx.source]), pairs);
}

console.log(failures ? `\n${failures} failure(s)` : "\nall passed");
process.exit(failures ? 1 : 0);
