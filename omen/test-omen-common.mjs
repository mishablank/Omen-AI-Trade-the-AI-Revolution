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
  console.log("  sparkSvg");
}

console.log(failures ? `\n${failures} failure(s)` : "\nall omen-common tests passed");
process.exit(failures ? 1 : 0);
