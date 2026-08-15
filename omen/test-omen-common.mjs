// Unit tests for omen-common.js — the helpers every page shares. These were previously
// copy-pasted per page and therefore untestable as one thing; now there is one copy, so
// there is one place to assert against.
//
//   node omen/test-omen-common.mjs        (or: python3 -m pytest, which shells out to it)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
// Loaded the same way the pages load it — as a plain script that publishes one global.
const OMEN = new Function(
  readFileSync(join(HERE, "omen-common.js"), "utf8") + "\nreturn OMEN;")();

let failures = 0;
const eq = (name, got, want) => {
  if (got === want) return;
  failures++;
  console.error(`  FAIL ${name}\n    got:  ${JSON.stringify(got)}\n    want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failures++;
  console.error(`  FAIL ${name}${detail ? " — " + detail : ""}`);
};

console.log("omen-common — esc / safeUrl / Polymarket shapes / regime / index math / sparkSvg\n");

/* ---------- esc: the null guard one page had lost ---------- */
{
  const { esc } = OMEN;
  eq("esc/null renders empty", esc(null), "");
  eq("esc/undefined renders empty", esc(undefined), "");
  eq("esc/zero is not swallowed", esc(0), "0");
  eq("esc/angle brackets", esc("<script>"), "&lt;script&gt;");
  eq("esc/ampersand first", esc("a&b"), "a&amp;b");
  eq("esc/double quote", esc('a"b'), "a&quot;b");
  eq("esc/single quote", esc("a'b"), "a&#39;b");
  // the whole point: a hostile market title cannot close the attribute it sits in
  const hostile = '"><img src=x onerror=alert(1)>';
  ok("esc/no raw quote survives", !esc(hostile).includes('"'), esc(hostile));
  ok("esc/no raw angle survives", !/[<>]/.test(esc(hostile)), esc(hostile));
  console.log("  esc");
}

/* ---------- safeUrl: esc() protects the attribute, not the scheme ---------- */
{
  const { safeUrl } = OMEN;
  eq("safeUrl/https passes", safeUrl("https://polymarket.com/event/ai-bubble"),
    "https://polymarket.com/event/ai-bubble");
  eq("safeUrl/http passes", safeUrl("http://example.com/x"), "http://example.com/x");
  eq("safeUrl/relative path passes unchanged", safeUrl("/polymarket-ai-index/markets#p-breadth"),
    "/polymarket-ai-index/markets#p-breadth");
  eq("safeUrl/bare anchor passes unchanged", safeUrl("#gauge"), "#gauge");

  // the schemes that turn an href into code execution
  eq("safeUrl/javascript rejected", safeUrl("javascript:alert(1)"), "#");
  eq("safeUrl/javascript is case-insensitive", safeUrl("JaVaScRiPt:alert(1)"), "#");
  eq("safeUrl/leading whitespace does not smuggle it", safeUrl("  javascript:alert(1)"), "#");
  eq("safeUrl/embedded tab does not smuggle it", safeUrl("java\tscript:alert(1)"), "#");
  eq("safeUrl/embedded newline does not smuggle it", safeUrl("java\nscript:alert(1)"), "#");
  eq("safeUrl/data URL rejected", safeUrl("data:text/html;base64,PHNjcmlwdD4="), "#");
  eq("safeUrl/vbscript rejected", safeUrl("vbscript:msgbox"), "#");
  eq("safeUrl/file rejected", safeUrl("file:///etc/passwd"), "#");

  eq("safeUrl/null becomes #", safeUrl(null), "#");
  eq("safeUrl/undefined becomes #", safeUrl(undefined), "#");
  eq("safeUrl/empty becomes #", safeUrl(""), "#");
  eq("safeUrl/whitespace-only becomes #", safeUrl("   "), "#");

  // an allowed URL is still escaped, so a slug cannot break out of the attribute
  eq("safeUrl/escapes quotes in an allowed URL",
    safeUrl('https://polymarket.com/event/x" onmouseover="alert(1)'),
    "https://polymarket.com/event/x&quot; onmouseover=&quot;alert(1)");
  ok("safeUrl/output never contains a raw quote",
    !safeUrl('https://x/"><script>').includes('"'));
  console.log("  safeUrl");
}

/* ---------- Polymarket shapes ---------- */
{
  const { outcomeYes, bookSpread, isClosed, jsonList } = OMEN;
  // a two-sided book is read at the mid, not the last trade
  eq("outcomeYes/uses book mid", outcomeYes({ bestBid: "0.40", bestAsk: "0.50", outcomePrices: '["0.99"]' }), 0.45);
  eq("outcomeYes/falls back to last trade", outcomeYes({ outcomePrices: '["0.31"]' }), 0.31);
  eq("outcomeYes/one-sided book falls back", outcomeYes({ bestBid: "0.4", outcomePrices: '["0.31"]' }), 0.31);
  eq("outcomeYes/zero ask is not a book", outcomeYes({ bestBid: "0", bestAsk: "0", outcomePrices: '["0.2"]' }), 0.2);
  // the guard that matters: malformed JSON used to throw out of the caller's whole loop
  eq("outcomeYes/malformed outcomePrices yields 0", outcomeYes({ outcomePrices: "not json" }), 0);
  eq("outcomeYes/missing outcomePrices yields 0", outcomeYes({}), 0);

  eq("bookSpread/two-sided", +bookSpread({ bestBid: "0.40", bestAsk: "0.50" }).toFixed(2), 0.10);
  eq("bookSpread/one-sided is null", bookSpread({ bestBid: "0.40" }), null);

  eq("isClosed/closed flag", isClosed({ closed: true }), true);
  eq("isClosed/inactive counts as closed", isClosed({ active: false }), true);
  eq("isClosed/open market", isClosed({ closed: false, active: true }), false);

  eq("jsonList/parses", jsonList('["a","b"]').join(","), "a,b");
  eq("jsonList/malformed yields empty", jsonList("{oops").length, 0);
  eq("jsonList/non-array yields empty", jsonList('{"a":1}').length, 0);
  eq("jsonList/undefined yields empty", jsonList(undefined).length, 0);
  console.log("  polymarket shapes");
}

/* ---------- regime: the thresholds all three pages now read ---------- */
{
  const { regimeOf, REGIME } = OMEN;
  eq("regime/quiet is calm", regimeOf(10, 5, 2), "calm");
  // gauge band edges
  eq("regime/gauge at elevated edge", regimeOf(REGIME.GAUGE_ELEVATED, 0, 0), "elevated");
  eq("regime/gauge just under elevated", regimeOf(REGIME.GAUGE_ELEVATED - 0.01, 0, 0), "calm");
  eq("regime/gauge at stressed edge", regimeOf(REGIME.GAUGE_STRESSED, 0, 0), "stressed");
  eq("regime/gauge just under stressed", regimeOf(REGIME.GAUGE_STRESSED - 0.01, 0, 0), "elevated");
  // crash-basket band edges
  eq("regime/level at stressed edge", regimeOf(0, REGIME.LEVEL_STRESSED, 0), "stressed");
  eq("regime/level at elevated edge", regimeOf(0, REGIME.LEVEL_ELEVATED, 0), "elevated");
  // a lone market caps at Elevated — it must never trip red on its own
  eq("regime/bubble market at its edge", regimeOf(0, 0, REGIME.SIGNAL_ELEVATED), "elevated");
  eq("regime/bubble market at 99% still only elevated", regimeOf(0, 0, 99), "elevated");
  console.log("  regime thresholds");
}

/* ---------- index math ---------- */
{
  let MARKETS = [
    { side: "bull", theme: "tech", closed: false, yes: 0.6, d1: 0.02 },
    { side: "bull", theme: "cap", closed: false, yes: 0.4, d1: null },
    { side: "bear", theme: "mkt", closed: false, yes: 0.2, d1: -0.01 },
    { side: "bear", theme: "gov", closed: true, yes: 0.9, d1: 0.5 },
  ];
  const { indexOf, d1Of, pairShare } = OMEN.indexMath(() => MARKETS);
  eq("indexMath/equal-weight mean x100", indexOf("bull"), 50);
  eq("indexMath/closed constituents excluded", indexOf("bear"), 20);
  eq("indexMath/theme selects one sleeve", indexOf("bull", "tech"), 60);
  eq("indexMath/empty side is 0", indexOf("nobody"), 0);
  eq("indexMath/d1 skips nulls", +d1Of("bull").toFixed(4), 2);
  // the pair is normalized: the two shares always sum to 1
  eq("indexMath/pair sums to one", +(pairShare("bull") + pairShare("bear")).toFixed(10), 1);
  eq("indexMath/pair share", +pairShare("bull").toFixed(4), 0.7143);
  // reads through the getter, so a live refresh mutating MARKETS is picked up
  MARKETS = [{ side: "bull", closed: false, yes: 1, d1: 0 }];
  eq("indexMath/reads current markets", indexOf("bull"), 100);
  console.log("  index math");
}

/* ---------- sparkSvg ---------- */
{
  const { sparkSvg } = OMEN;
  const svg = sparkSvg([1, 2, 3], 300, 52, "#e3a63c", true);
  ok("sparkSvg/renders an svg", svg.startsWith("<svg"), svg.slice(0, 40));
  ok("sparkSvg/no NaN in output", !svg.includes("NaN"), svg);
  ok("sparkSvg/fill adds the area path", svg.includes("<path"));
  ok("sparkSvg/omits area when not filled", !sparkSvg([1, 2], 10, 10, "#fff", false).includes("<path"));
  ok("sparkSvg/hidden from assistive tech", svg.includes('aria-hidden="true"'));
  // the guard: one point divides by zero, none makes Math.min() Infinity
  eq("sparkSvg/single point draws nothing", sparkSvg([1], 300, 52, "#fff", true), "");
  eq("sparkSvg/empty draws nothing", sparkSvg([], 300, 52, "#fff", true), "");
  eq("sparkSvg/undefined draws nothing", sparkSvg(undefined, 300, 52, "#fff", true), "");
  // a flat series must not divide by a zero range
  ok("sparkSvg/flat series is finite", !sparkSvg([5, 5, 5], 300, 52, "#fff", true).includes("NaN"));

  // the domain floor: a ±0.1% wiggle must not render full-height. With the default 4%
  // floor a [0.690, 0.691] series spans ~2.7% of the panel, not 100% of it.
  {
    const ys = [...sparkSvg([0.690, 0.691], 100, 100, "#fff", false, { mean: false })
      .matchAll(/points="([\d.,\s]+)"/g)][0][1].split(" ").map((p) => +p.split(",")[1]);
    const used = Math.abs(ys[0] - ys[1]), avail = 100 - 8 - 3;
    ok("sparkSvg/domain floor damps near-flat series", used < avail * 0.1, `used ${used}px of ${avail}px`);
  }
  ok("sparkSvg/mean line drawn by default", sparkSvg([1, 2, 3], 300, 52, "#fff", false).includes("stroke-dasharray"));
  ok("sparkSvg/mean line can be omitted", !sparkSvg([1, 2, 3], 300, 52, "#fff", false, { mean: false }).includes("stroke-dasharray"));
  ok("sparkSvg/explicit minSpan respected", !sparkSvg([5, 5, 5], 300, 52, "#fff", false, { minSpan: 2 }).includes("NaN"));
  console.log("  sparkSvg");
}

/* ---------- parseSnapshots: the daily history the landing page charts ---------- */
{
  const { parseSnapshots } = OMEN;
  const csv = [
    "date,bull,bull_n,bear,bear_n,crash,crash_n,reg,reg_n,gauge,lead,conf,comp",
    "2026-07-11,45.18,11,16.6,9,8.8,3,20.5,6,27.3,,,1087074,653788",
    "2026-07-12,44.95,11,16.22,9,9.17,3,19.75,6,,30.0,24.3,1087074",  // gauge cell empty
    "2026-07-13,,11,16.22,9,9.17,3,19.75,6,27.7,30.0,24.3,1087074",   // bull cell empty
  ].join("\n");
  const rows = parseSnapshots(csv);
  eq("parseSnapshots/keeps parsable rows", rows.length, 2);
  eq("parseSnapshots/date", rows[0].date, "2026-07-11");
  eq("parseSnapshots/share is bull over pair", +rows[0].share.toFixed(4), +(45.18 / (45.18 + 16.6)).toFixed(4));
  eq("parseSnapshots/crash", rows[0].crash, 8.8);
  eq("parseSnapshots/gauge", rows[0].gauge, 27.3);
  eq("parseSnapshots/empty gauge becomes null", rows[1].gauge, null);
  eq("parseSnapshots/empty input", parseSnapshots("").length, 0);
  eq("parseSnapshots/header only", parseSnapshots("date,bull,bear").length, 0);
  eq("parseSnapshots/missing pair columns", parseSnapshots("date,foo\n2026-01-01,1").length, 0);
  console.log("  parseSnapshots");
}

/* ---------- pairShareSeries: shared CLOB-history resampler ---------- */
{
  const { pairShareSeries } = OMEN;
  // two flat bull markets at 0.6, two flat bear markets at 0.2 → share 0.75 everywhere
  const flat = (p) => [{ t: 0, p }, { t: 50, p }, { t: 100, p }];
  const hist = { b1: flat(0.6), b2: flat(0.6), x1: flat(0.2), x2: flat(0.2) };
  const r = pairShareSeries(hist, { bull: ["b1", "b2"], bear: ["x1", "x2"] }, 5);
  ok("pairShareSeries/returns a result", !!r);
  eq("pairShareSeries/bucket count", r.share.bull.length, 5);
  eq("pairShareSeries/share level", +r.share.bull[2].toFixed(4), 0.75);
  eq("pairShareSeries/shares sum to one", +(r.share.bull[0] + r.share.bear[0]).toFixed(10), 1);
  // a sparse series is resampled as a step function: last trade holds
  const step = { b1: [{ t: 0, p: 0.4 }, { t: 100, p: 0.8 }], b2: flat(0.6), x1: flat(0.2), x2: flat(0.2) };
  const r2 = pairShareSeries(step, { bull: ["b1", "b2"], bear: ["x1", "x2"] }, 3);
  ok("pairShareSeries/step resample holds last trade", r2.share.bull[1] > r2.share.bull[0] - 1e-9);
  // one lone market per side is not an index
  eq("pairShareSeries/needs two histories per side",
    pairShareSeries({ b1: flat(0.6), x1: flat(0.2), x2: flat(0.2) }, { bull: ["b1", "b2"], bear: ["x1", "x2"] }, 5), null);
  // an empty common window (histories that do not overlap) is rejected
  const late = [{ t: 200, p: 0.5 }, { t: 300, p: 0.5 }];
  eq("pairShareSeries/no overlap is null",
    pairShareSeries({ b1: flat(0.6), b2: late, x1: flat(0.2), x2: flat(0.2) }, { bull: ["b1", "b2"], bear: ["x1", "x2"] }, 5), null);
  console.log("  pairShareSeries");
}

/* ---------- capex live-tape derivations ---------- */
{
  const { ocfGrowth, tokenDemand, repricingGap, serveFloorPerM, impliedMargin, newestPriced } = OMEN;

  // ocfGrowth: YoY over complete cohorts only, partial quarter named not quoted
  const fund = {
    quarters: ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"],
    ocf_b:    [100,      110,      120,      130,      131,      99],
    n_firms:  [5,        5,        5,        5,        5,        4],
  };
  const og = ocfGrowth(fund);
  ok("ocfGrowth/returns a result", !!og);
  eq("ocfGrowth/latest complete quarter", og.latest.q, "2026Q1");
  eq("ocfGrowth/latest yoy", +og.latest.yoy.toFixed(1), 31);
  eq("ocfGrowth/partial quarter named", og.partial_q, "2026Q2");
  eq("ocfGrowth/partial cohort size", og.partial_n, 4);
  ok("ocfGrowth/no prior complete pair yet", og.prior === null && og.accel_pp === null);
  const fund2 = { quarters: ["2024Q4", "2025Q1", "2025Q4", "2026Q1"],
                  ocf_b: [90, 100, 117, 131], n_firms: [5, 5, 5, 5] };
  const og2 = ocfGrowth(fund2);
  eq("ocfGrowth/acceleration in pp", +og2.accel_pp.toFixed(1), 1);
  eq("ocfGrowth/needs a year-ago quarter", ocfGrowth({ quarters: ["2026Q1"], ocf_b: [1], n_firms: [5] }), null);
  eq("ocfGrowth/null fund is null", ocfGrowth(null), null);
  console.log("  ocfGrowth");

  // tokenDemand: growth windows appear only when the series can support them
  const wk = (n) => Array.from({ length: n }, (_, i) => ({ x: "w" + i, tot: 100 * Math.pow(1.1, i) }));
  const td = tokenDemand(wk(6));
  eq("tokenDemand/latest week", td.week, "w5");
  eq("tokenDemand/wow pct", +td.wow_pct.toFixed(1), 10);
  eq("tokenDemand/4w pct", +td.w4_pct.toFixed(1), 46.4);
  eq("tokenDemand/yoy needs 53 weeks", td.yoy_pct, null);
  ok("tokenDemand/53 weeks yields yoy", tokenDemand(wk(53)).yoy_pct > 0);
  eq("tokenDemand/zero-token weeks dropped", tokenDemand([{ x: "a", tot: 0 }, { x: "b", tot: 5 }]), null);
  console.log("  tokenDemand");

  // repricingGap / serveFloorPerM / impliedMargin: the one-line economics
  eq("repricingGap/spot above contract", +repricingGap(3.9, 2.5).toFixed(0), 56);
  eq("repricingGap/spot below contract", +repricingGap(2.2, 4.4).toFixed(0), -50);
  eq("repricingGap/zero contract is null", repricingGap(2.2, 0), null);
  eq("serveFloorPerM/$2.20 at 1M tok/hr", serveFloorPerM(2.2, 1), 2.2);
  eq("serveFloorPerM/zero throughput is null", serveFloorPerM(2.2, 0), null);
  eq("impliedMargin/frontier", +impliedMargin(25, 2.2).toFixed(1), 91.2);
  ok("impliedMargin/cost above price goes negative", impliedMargin(0.18, 2.2) < 0);
  eq("impliedMargin/zero price is null", impliedMargin(0, 2.2), null);
  console.log("  repricingGap / serveFloorPerM / impliedMargin");

  // newestPriced: newest live match wins; :free and unpriced entries are ignored
  const models = [
    { id: "anthropic/claude-opus-4", created: 1, pricing: { prompt: "0.000015", completion: "0.000075" } },
    { id: "anthropic/claude-opus-5", created: 9, pricing: { prompt: "0.000005", completion: "0.000025" } },
    { id: "anthropic/claude-opus-5:free", created: 99, pricing: { prompt: "0", completion: "0" } },
    { id: "deepseek/deepseek-v4-pro", created: 5, pricing: { prompt: "0.00000043", completion: "0.00000087" } },
  ];
  const np = newestPriced(models, /^anthropic\/claude-opus/);
  eq("newestPriced/newest live match", np.id, "anthropic/claude-opus-5");
  eq("newestPriced/output $ per M", np.outP, 25);
  eq("newestPriced/no match is null", newestPriced(models, /^openai\//), null);
  console.log("  newestPriced");
}

/* ---------- gaugeRefText: the house minus survives a negative bound ---------- */
{
  const { gaugeRefText, GAUGE_REFS } = OMEN;
  // Until the fragility rows landed, no ref had a negative bound, so the plain/pt/pct
  // branches interpolated r.lo raw and nothing ever noticed. cred_gap_z (lo −1) is the
  // first, and it printed an ASCII hyphen next to a U+2212 in the same sentence.
  const negatives = Object.keys(GAUGE_REFS).filter((k) => GAUGE_REFS[k].lo < 0 || GAUGE_REFS[k].hi < 0);
  ok("gaugeRefText/a negative bound exists to test", negatives.length > 0);
  for (const k of negatives) {
    ok(`gaugeRefText/${k} uses U+2212 not ASCII hyphen`,
      !/(^|[\s(])-\d/.test(gaugeRefText(k)), gaugeRefText(k));
  }
  eq("gaugeRefText/level branch negates with U+2212",
    gaugeRefText("cred_gap_z"), "HY−IG gap z −1–2");
  console.log("  gaugeRefText");
}

console.log(failures ? `\n${failures} failure(s)` : "\nall omen-common tests passed");
process.exit(failures ? 1 : 0);
