// Parity contract for the monitor's gauge - the JS half of the pair with
// test_gauge_parity.py. computeGauge() is the one decision rule on the monitor that
// had no coverage: it is also the rule that quietly grew a sixth family (macro) and
// a three-component pred while the server gauge (update-market-data.py) stayed
// five-family, bubble-only. Both suites evaluate their implementation against the
// SAME fixture (fixtures/gauge-parity.json): the four shared families must match to
// 1e-9, and the two intended divergences are pinned as numbers so any further drift
// - or a deliberate convergence - fails a test until the fixture is updated with it.
//
// Sliced out of the HTML by marker, same as test-pure-helpers.mjs, because there is
// no build step and no bundler.
//
//   node omen/test-gauge-parity.mjs        (or: python3 -m pytest, which shells out to it)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(HERE, "polymarket-ai-index.html"), "utf8");
const FIX = JSON.parse(readFileSync(join(HERE, "fixtures", "gauge-parity.json"), "utf8"));

// Slice [start, end) out of the source. Fails loudly if a marker moves, rather than
// silently testing nothing.
function slice(start, end) {
  const a = SRC.indexOf(start);
  if (a < 0) throw new Error(`start marker not found: ${start}`);
  const b = SRC.indexOf(end, a);
  if (b < 0) throw new Error(`end marker not found: ${end}`);
  return SRC.slice(a, b);
}
function build(code, names, stubs = {}) {
  const keys = Object.keys(stubs);
  const fn = new Function(...keys, `${code}\nreturn {${names.join(",")}};`);
  return fn(...keys.map((k) => stubs[k]));
}

let failures = 0;
const TOL = 1e-9;
const near = (name, got, want) => {
  if (got != null && want != null && Math.abs(got - want) <= TOL) return;
  failures++;
  console.error(`  FAIL ${name}\n    got:  ${JSON.stringify(got)}\n    want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failures++;
  console.error(`  FAIL ${name}${detail ? " — " + detail : ""}`);
};

console.log("gauge parity — computeGauge vs the shared fixture\n");

// The page's own drawdown, not a reimplementation: the credit and equity families
// must be tested through the code the browser actually runs.
const { drawdown } = build(slice("function drawdown(series)", "\nfunction computeSignals"), ["drawdown"]);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x)); // page line: const clamp = ...

// computeGauge's free variables, stubbed from the fixture. markets carries only the
// bubble market - pred's other two components and all of macro enter through their
// accessor functions, which is exactly how the page wires them.
const J = FIX.js_inputs;
function gaugeFor(weighting) {
  return build(
    slice("// blended crash-pressure gauge", "const GAUGE_BANDS"),
    ["computeGauge"],
    {
      clamp,
      drawdown,
      markets: new Map([["691340", { closed: false, yes: FIX.prices["691340"] }]]),
      BUBBLE_ID: "691340",
      mkt: FIX.mkt,
      nvdaTailProb: () => J.nvda_tail_pct,
      h100Sub2: () => J.h100_sub2_pct,
      macroRecession: () => J.recession_pct,
      macroFedCuts: () => J.fed_cuts_pct,
      chinaTop3: () => J.china_top3_pct,
      weighting,
    },
  ).computeGauge();
}

const g = gaugeFor("equal");

/* ---------- the parity contract: shared families equal the fixture ---------- */
{
  for (const [k, want] of Object.entries(FIX.expected.shared_fam)) {
    if (k.startsWith("_")) continue;
    near(`shared/${k}`, g.fam[k].v, want);
  }
  console.log("  shared families (opt/vol/credit/equity)");
}

/* ---------- the documented divergences, pinned as numbers ---------- */
{
  near("js/pred is three components", g.fam.pred.v, FIX.expected.js.pred);
  ok("js/pred differs from the server's bubble-only pred",
    Math.abs(g.fam.pred.v - FIX.expected.python.pred) > TOL,
    "if the implementations were converged on purpose, update the fixture");
  near("js/macro family exists and scores", g.fam.macro.v, FIX.expected.js.macro);
  ok("js/six families total", g.total === 6, `got ${g.total}`);
  console.log("  divergences (pred components, macro family)");
}

/* ---------- blended score, both weightings, and the lead/conf split ---------- */
{
  near("js/score equal-weight", g.score, FIX.expected.js.score_equal);
  near("js/lead includes macro", g.lead, FIX.expected.js.lead);
  near("js/conf", g.conf, FIX.expected.js.conf);
  const t = gaugeFor("thesis");
  near("js/score thesis-weight", t.score, FIX.expected.js.score_thesis);
  ok("js/thesis differs from equal", Math.abs(t.score - g.score) > TOL);
  console.log("  score / weighting / lead-conf");
}

/* ---------- headlineGauge: the chip reads the server gauge, not this card ---------- */
{
  // The convergence rule: the monitor's regime chip states the fetcher's server_gauge
  // (the number the landing page and the alert already use) and falls back to the
  // page's own six-family score only when the payload is missing or stale.
  const HG = slice("function headlineGauge()", "\n// The rule inputs");
  const sig = { gauge: { score: 40.2 } };
  const iso = (agoMs) => new Date(Date.now() - agoMs).toISOString();
  const FRESH_MS = 2 * 3600000;
  const hg = (mkt) => build(HG, ["headlineGauge"], { mkt, sig, FRESH_MS }).headlineGauge();

  const fresh = hg({ server_gauge: { score: 36.25 }, updated: iso(10 * 60000) });
  ok("headline/fresh server gauge wins", fresh.score === 36.25 && fresh.source === "server",
    JSON.stringify(fresh));

  const stale = hg({ server_gauge: { score: 36.25 }, updated: iso(3 * 3600000) });
  ok("headline/stale payload falls back to the client score",
    stale.score === 40.2 && stale.source === "client", JSON.stringify(stale));

  ok("headline/no server_gauge falls back",
    hg({ updated: iso(10 * 60000) }).source === "client");
  ok("headline/null server score falls back",
    hg({ server_gauge: { score: null }, updated: iso(10 * 60000) }).source === "client");
  ok("headline/no updated stamp cannot prove freshness, falls back",
    hg({ server_gauge: { score: 36.25 } }).source === "client");
  ok("headline/no payload at all falls back",
    hg(null).source === "client" && hg(null).score === 40.2);
  console.log("  headlineGauge (server-first, stale fallback)");
}

/* ---------- degradation: a dark family drops out of the mean ---------- */
{
  const dark = build(
    slice("// blended crash-pressure gauge", "const GAUGE_BANDS"),
    ["computeGauge"],
    {
      clamp, drawdown,
      markets: new Map(),               // bubble market gone
      BUBBLE_ID: "691340",
      mkt: { ...FIX.mkt, vol: {} },     // vol complex gone too
      nvdaTailProb: () => null,
      h100Sub2: () => null,
      macroRecession: () => null,
      macroFedCuts: () => null,
      chinaTop3: () => null,
      weighting: "equal",
    },
  ).computeGauge();
  ok("dark/pred null when all components dark", dark.fam.pred.v === null);
  ok("dark/vol null", dark.fam.vol.v === null);
  ok("dark/macro null", dark.fam.macro.v === null);
  ok("dark/available count drops to 3", dark.n === 3, `got ${dark.n}`);
  const want = (FIX.expected.shared_fam.opt + FIX.expected.shared_fam.credit
    + FIX.expected.shared_fam.equity) / 3;
  near("dark/score is the mean of the remaining families", dark.score, want);
  console.log("  degradation (dark families drop from the mean)");
}

if (failures) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall gauge-parity tests passed");
