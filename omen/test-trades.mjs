// Unit tests for the Trades page — the ten stance rules and the signal reader behind
// them. Sliced out of trades.html by comment marker, the same way test-verdict.mjs
// slices the landing page: no bundler, so a moved marker fails loudly rather than
// silently testing nothing.
//
// What is pinned here, and why:
//   1. Every card's rule is a function of the published thresholds (T) and the reading,
//      and the prose the card prints quotes those same thresholds — the page renders the
//      rule from T rather than typing the numbers twice, so this checks the join.
//   2. The verdict-driven cards (1 and 10) honour the shared matrix cell for cell,
//      including the rolling basket, through OMEN.verdictOf — not a local copy.
//   3. A missing reading is WATCH with a reason, never a guess.
//   4. readSignals turns the fetcher's payload into the flat object the rules consume:
//      the pair share from the live constituents, the decay legs from coverage, the
//      moratorium market found by label rather than by a hard-coded id.
//
//   node omen/test-trades.mjs        (or: python3 -m pytest, which shells out to it)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const OMEN = new Function(
  readFileSync(join(HERE, "omen-common.js"), "utf8") + "\nreturn OMEN;")();
const SRC = readFileSync(join(HERE, "trades.html"), "utf8");

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
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) return;
  failures++;
  console.error(`  FAIL ${name}\n    got:  ${JSON.stringify(got)}\n    want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failures++;
  console.error(`  FAIL ${name}${detail ? " — " + detail : ""}`);
};

console.log("trades — thresholds / stance rules / signal reader\n");

const { T, TBILL, TRADES, readSignals } = build(
  slice("/* ================= trades: thresholds", "/* ================= render"),
  ["T", "TBILL", "TRADES", "readSignals"],
  { OMEN, $: () => null, esc: OMEN.esc, safeUrl: OMEN.safeUrl, MINUS: "−" },
);

/* ---------- a reading like 2026-10-28's, hand-set so the cases are explicit ---------- */
function today(over = {}) {
  return Object.assign({
    at: "2026-10-24T16:22:22Z",
    gauge: 44.3, regime: "elevated", fam: { pred: 23.8, opt: 40.7, vol: 58.6, credit: 52.8, equity: 45.6 },
    lead: 39.1, conf: 52.1, bubble: 9.5,
    bullIdx: 26.67, bearIdx: 12.49, bullShare: 0.681, rolling: false, dir: "bull", verdict: "constructive",
    bullLegs: [
      { id: "656312", label: "OpenAI IPO by Dec 31, 2026", slug: "openai-ipo-by", yes: 3.45, days: 69 },
      { id: "656313", label: "OpenAI $1t+ IPO before 2027", slug: "openai-1t-ipo-before-2027", yes: 3.6, days: 69 },
      { id: "653788", label: "OpenAI announces AGI before 2027", slug: "x", yes: 9.5, days: 69 },
      { id: "2255930", label: "AI data center in space by Dec 31, 2027", slug: "y", yes: 4.0, days: 430 },
    ],
    moratorium: 32.4, bearGov: 17.2, bearMkt: 4.7,
    rrNvda: 6.0, ivNvda: 44.1, termNvda: 1.14, tailNvda: 6.2, tailDte: 328,
    hyOas: 3.4, cccOas: 13.4,
    cotNdx: 96.8, cotVix: 3.8, cotDate: "2026-10-20", vxn: 28.3, skewIdx: 151.8,
    dd: { NVDA: -11.8, SOXX: -27.0, MU: -27.7, ORCL: -49.2, MSFT: -3.5, CRWV: -60.7, VST: -17.1, CEG: -21.5, SPY: -2.5 },
    px: { NVDA: 210.96 },
    pe: 26.6, pePct: 6.7, insNvda: -967599313, insOrcl: -335496,
    pf: { ORCL: { capex_over_ocf: 1.61, fcf_ttm_b: -28.7 }, MSFT: { capex_over_ocf: 0.63, fcf_ttm_b: 67.0 } },
    growthShare: 20.2, pctGdp: 2.23, pctGdpPrev: 1.86, macroAsof: "2026-10-24",
    recession: 21.5, recessionTitle: "Recession in 2027?",
    gpu: 2.521,
    dram: { direction: "rise", lo: 10, hi: 15, quarter: "4Q26" }, korea: 259, koreaWin: "Sep 1-20",
    tsmcYoy: 54.6, eia: { planned_gw: 192.3, under_construction_gw: 97.9, canceled_gw: 185.4 }, dcYoy: 73.2,
    tbill: TBILL.apy,
  }, over);
}
const by = Object.fromEntries(TRADES.map((t) => [t.key, t]));
const stance = (key, S) => by[key].stance(S).state;

/* ---------- 1. shape: ten cards, four kinds, every part present ---------- */
{
  eq("shape/ten positions", TRADES.length, 10);
  eq("shape/unique keys", new Set(TRADES.map((t) => t.key)).size, 10);
  const sides = new Set(["bull", "bear", "neutral", "hedge"]);
  for (const t of TRADES) {
    ok(`shape/${t.key} side is one of four`, sides.has(t.side), t.side);
    ok(`shape/${t.key} has stance/rule/reads`, ["stance", "rule", "reads"].every((k) => typeof t[k] === "function"));
    const s = t.stance(today());
    ok(`shape/${t.key} stance is a known state`, ["on", "watch", "off", "check"].includes(s.state), s.state);
    ok(`shape/${t.key} stance carries a reason`, typeof s.why === "string" && s.why.length > 10, s.why);
    const r = t.rule(today());
    ok(`shape/${t.key} rule prose says ON`, /<b>ON<\/b>|Always <b>ON<\/b>/.test(r), r.slice(0, 60));
    const reads = t.reads(today());
    ok(`shape/${t.key} reads are rows`, Array.isArray(reads) && reads.length >= 3 && reads.every((x) => "label" in x && "value" in x));
  }
  // every card in the markup has a rule object and vice versa
  const ids = [...SRC.matchAll(/<article class="tcard rv" id="t-([a-z]+)"/g)].map((m) => m[1]);
  eq("shape/markup cards match TRADES", ids, TRADES.map((t) => t.key));
  ok("shape/markup card kinds match TRADES",
    TRADES.every((t) => SRC.includes(`id="t-${t.key}" data-side="${t.side}"`)));
  console.log("  shape");
}

/* ---------- 2. the rule prose quotes the thresholds it applies ---------- */
{
  const r = (k) => by[k].rule(today());
  ok("prose/core quotes both insurance sizes", r("core").includes(`${T.INSURE.calm}%`) && r("core").includes(`${T.INSURE.elevated}%`));
  ok("prose/core quotes the direction band edge", r("core").includes(`${(OMEN.DIRECTION.BULL * 100).toFixed(0)}%`));
  ok("prose/grid quotes the moratorium OFF", r("grid").includes(`${T.GRID_MORATORIUM_OFF}%`));
  ok("prose/carry quotes the hurdle", r("carry").includes(`${T.CARRY_HURDLE_PP}`) && r("carry").includes((TBILL.apy + T.CARRY_HURDLE_PP).toFixed(1)));
  ok("prose/pair quotes both gaps", r("pair").includes(`${T.PAIR_GAP_ON}×`) && r("pair").includes(`${T.PAIR_GAP_WATCH}×`));
  ok("prose/decay quotes cents and days", r("decay").includes(`${T.DECAY_MAX_CENTS}¢`) && r("decay").includes(`${T.DECAY_MAX_DAYS}`));
  ok("prose/crowd quotes both percentiles", r("crowd").includes(`${T.CROWD_ON}th`) && r("crowd").includes(`${T.CROWD_WATCH}th`));
  ok("prose/recession quotes all three", r("recession").includes(`${T.RECESSION_ON}¢`) && r("recession").includes(`${T.RECESSION_WATCH}¢`) && r("recession").includes(`${T.RECESSION_GROWTH_SHARE}%`));
  ok("prose/cash quotes the three sleeves", ["calm", "elevated", "stressed"].every((k) => r("cash").includes(`${T.CASH[k]}%`)));
  ok("prose/short quotes the bear edge and the RR", r("short").includes(`${(OMEN.DIRECTION.BEAR * 100).toFixed(0)}%`) && r("short").includes(`${T.SHORT_RR_WATCH}`));
  console.log("  rule prose quotes T");
}

/* ---------- 3. today's reading: the expected board ---------- */
{
  const S = today();
  eq("today/core ON", stance("core", S), "on");
  eq("today/memory ON", stance("memory", S), "on");
  eq("today/grid ON", stance("grid", S), "on");
  eq("today/carry CHECK (funding is a venue read)", stance("carry", S), "check");
  eq("today/pair ON", stance("pair", S), "on");
  eq("today/decay ON", stance("decay", S), "on");
  eq("today/crowd ON", stance("crowd", S), "on");
  eq("today/recession ON", stance("recession", S), "on");
  eq("today/cash ON", stance("cash", S), "on");
  eq("today/short OFF", stance("short", S), "off");
  ok("today/short says how far the trigger is", /23\.1<\/b> points/.test(by.short.stance(S).why), by.short.stance(S).why);
  ok("today/core insurance leg is the Elevated size", by.core.stance(S).why.includes(`${T.INSURE.elevated}%`));
  ok("today/cash sleeve is the Elevated share", by.cash.stance(S).why.includes(`${T.CASH.elevated}%`));
  console.log("  today's board");
}

/* ---------- 4. the verdict cells, through the shared matrix ---------- */
{
  const cell = (share, regime, rolling = false) => ({
    bullShare: share, dir: OMEN.dirOf(share), regime, rolling,
    verdict: OMEN.verdictOf(share, regime, rolling),
  });
  eq("cells/riskon: core ON", stance("core", today(cell(0.7, "calm"))), "on");
  ok("cells/riskon: insurance is the Calm size", by.core.stance(today(cell(0.7, "calm"))).why.includes(`${T.INSURE.calm}%`));
  eq("cells/constructive: core ON", stance("core", today(cell(0.7, "elevated"))), "on");
  eq("cells/caution: core OFF", stance("core", today(cell(0.7, "stressed"))), "off");
  eq("cells/mixed: core WATCH", stance("core", today(cell(0.5, "calm"))), "watch");
  eq("cells/riskoff: core OFF", stance("core", today(cell(0.3, "calm"))), "off");
  eq("cells/rolling: core WATCH whatever the share", stance("core", today(cell(0.9, "calm", true))), "watch");

  eq("cells/riskoff: short ON", stance("short", today(cell(0.3, "calm"))), "on");
  eq("cells/riskoff even when Stressed: short ON", stance("short", today(cell(0.44, "stressed"))), "on");
  eq("cells/caution: short WATCH", stance("short", today(cell(0.5, "stressed"))), "watch");
  ok("cells/caution with RR at the line: the options market agrees",
    by.short.stance(today(Object.assign(cell(0.5, "stressed"), { rrNvda: T.SHORT_RR_WATCH }))).why.includes("agrees"));
  ok("cells/caution with RR under the line: no agreement claimed",
    !by.short.stance(today(Object.assign(cell(0.5, "stressed"), { rrNvda: T.SHORT_RR_WATCH - 1 }))).why.includes("agrees"));
  eq("cells/riskon: short OFF", stance("short", today(cell(0.7, "calm"))), "off");
  eq("cells/rolling: short WATCH", stance("short", today(cell(0.1, "stressed", true))), "watch");

  eq("cells/cash sizes by regime", ["calm", "elevated", "stressed"].map((r) => by.cash.stance(today({ regime: r })).why.includes(`${T.CASH[r]}%`)), [true, true, true]);
  eq("cells/grid WATCH in Stressed", stance("grid", today({ regime: "stressed" })), "watch");
  eq("cells/memory OFF when the pair is bearish", stance("memory", today(cell(0.3, "calm"))), "off");
  eq("cells/memory WATCH when direction is mixed", stance("memory", today(cell(0.5, "calm"))), "watch");
  console.log("  verdict cells");
}

/* ---------- 5. each rule's own thresholds, both sides of the line ---------- */
{
  eq("memory/DRAM fall is OFF", stance("memory", today({ dram: { direction: "fall", lo: 3, hi: 8, quarter: "1Q27" } })), "off");
  eq("memory/DRAM flat is WATCH", stance("memory", today({ dram: { direction: "flat", lo: 0, hi: 0, quarter: "1Q27" } })), "watch");
  eq("memory/Korea at the floor is WATCH", stance("memory", today({ korea: T.MEM_KOREA_MIN })), "watch");

  eq("grid/moratorium at OFF line", stance("grid", today({ moratorium: T.GRID_MORATORIUM_OFF })), "off");
  eq("grid/moratorium just under stays ON", stance("grid", today({ moratorium: T.GRID_MORATORIUM_OFF - 0.1 })), "on");
  eq("grid/capex share flat is OFF", stance("grid", today({ pctGdp: 2.0, pctGdpPrev: 2.0 })), "off");
  eq("grid/no moratorium reading still runs", stance("grid", today({ moratorium: null })), "on");

  const gap = (o, m) => today({ pf: { ORCL: { capex_over_ocf: o, fcf_ttm_b: 0 }, MSFT: { capex_over_ocf: m, fcf_ttm_b: 0 } } });
  eq("pair/gap at ON line", stance("pair", gap(1.0 + T.PAIR_GAP_ON, 1.0)), "on");
  eq("pair/gap at WATCH line", stance("pair", gap(1.0 + T.PAIR_GAP_WATCH, 1.0)), "watch");
  eq("pair/gap under WATCH is OFF", stance("pair", gap(1.1, 1.0)), "off");

  eq("decay/legs filter by cents and days", by.decay.legs(today()).map((l) => l.id), ["656312", "656313"]);
  eq("decay/leg at the price line qualifies", by.decay.legs(today({ bullLegs: [{ id: "a", label: "a", yes: T.DECAY_MAX_CENTS, days: 10 }] })).length, 1);
  eq("decay/leg at the day line qualifies", by.decay.legs(today({ bullLegs: [{ id: "a", label: "a", yes: 1, days: T.DECAY_MAX_DAYS }] })).length, 1);
  eq("decay/leg with no days is skipped", by.decay.legs(today({ bullLegs: [{ id: "a", label: "a", yes: 1, days: null }] })).length, 0);
  eq("decay/no qualifying leg is OFF", stance("decay", today({ bullLegs: [{ id: "a", label: "a", yes: 20, days: 10 }] })), "off");
  ok("decay/reads list each leg's NO price and return",
    by.decay.reads(today()).some((r) => r.value.includes("NO at 96.") && r.value.includes("+3.6%")));

  eq("crowd/at ON line", stance("crowd", today({ cotNdx: T.CROWD_ON })), "on");
  eq("crowd/at WATCH line", stance("crowd", today({ cotNdx: T.CROWD_WATCH })), "watch");
  eq("crowd/under WATCH is OFF", stance("crowd", today({ cotNdx: T.CROWD_WATCH - 1 })), "off");
  ok("crowd/VIX crowd named when extreme", by.crowd.stance(today()).why.includes("VIX"));
  ok("crowd/VIX crowd not named when ordinary", !by.crowd.stance(today({ cotVix: 50 })).why.includes("VIX"));

  eq("recession/at ON line", stance("recession", today({ recession: T.RECESSION_ON })), "on");
  eq("recession/cheap but no correlation is WATCH", stance("recession", today({ growthShare: T.RECESSION_GROWTH_SHARE - 1 })), "watch");
  eq("recession/between lines is WATCH", stance("recession", today({ recession: T.RECESSION_ON + 1 })), "watch");
  eq("recession/over WATCH line is OFF", stance("recession", today({ recession: T.RECESSION_WATCH + 0.1 })), "off");

  ok("carry/hurdle is T-bill plus the spread", by.carry.stance(today()).why.includes((TBILL.apy + T.CARRY_HURDLE_PP).toFixed(1) + "%"));
  console.log("  thresholds, both sides");
}

/* ---------- 6. a missing reading is WATCH with a reason, never a guess ---------- */
{
  eq("missing/core without a verdict", stance("core", today({ verdict: null })), "watch");
  eq("missing/memory without DRAM", stance("memory", today({ dram: null })), "watch");
  eq("missing/grid without GDP share", stance("grid", today({ pctGdp: null })), "watch");
  eq("missing/pair without filers", stance("pair", today({ pf: {} })), "watch");
  eq("missing/decay without legs", stance("decay", today({ bullLegs: [] })), "watch");
  eq("missing/crowd without COT", stance("crowd", today({ cotNdx: null })), "watch");
  eq("missing/recession without the contract", stance("recession", today({ recession: null })), "watch");
  eq("missing/cash without a regime", stance("cash", today({ regime: null })), "watch");
  eq("missing/short without a verdict", stance("short", today({ verdict: null })), "watch");
  for (const t of TRADES) {
    const why = t.stance(today({ verdict: null, dram: null, pctGdp: null, pf: {}, bullLegs: [], cotNdx: null, recession: null, regime: null })).why;
    ok(`missing/${t.key} explains itself`, typeof why === "string" && why.length > 0);
  }
  console.log("  missing readings");
}

/* ---------- 7. readSignals: the fetcher payload → the flat reading ---------- */
{
  const constDoc = { markets: [
    { id: "b1", side: "bull", theme: "tech", label: "Bull one by Dec 31", from: "2026-07-10" },
    { id: "b2", side: "bull", theme: "capital", label: "Bull two by Dec 31", from: "2026-07-10" },
    { id: "b3", side: "bull", theme: "capital", label: "Bull three (gone)", from: "2026-07-10", to: "2026-09-04" },
    { id: "b4", side: "bull", theme: "tech", label: "Bull four (proposed)", from: "2026-07-10", proposed: true },
    { id: "x1", side: "bear", theme: "mkt", label: "AI bubble burst", from: "2026-07-10", role: "bubble" },
    { id: "x2", side: "bear", theme: "gov", label: "Any state enacts data center moratorium by Dec 31", from: "2026-07-10" },
    { id: "c1", side: "china", label: "not in the pair", from: "2026-07-12" },
  ] };
  const md = {
    updated: "2026-10-24T16:22:22Z",
    server_gauge: { score: 44.3, lead: 39.1, conf: 52.1, fam: { pred: 1 }, regime: "elevated", bubble: 0.095 },
    poly: { price: { b1: 0.04, b2: 0.80, b3: 0.5, b4: 0.5, x1: 0.095, x2: 0.324, c1: 0.9 } },
    coverage: { sides: { bull: { rolling: false }, bear: { rolling: false } },
      markets: [{ id: "b1", days_left: 69 }, { id: "b2", days_left: 69 }] },
    skew: { NVDA: { rr: 0.0602, atm: 0.441 } },
    term: { NVDA: { ratio: 1.1404 } },
    tail: { NVDA: { dte: 328, trigger_pct: -50, levels: [{ pct: -30, p: 0.1995 }, { pct: -50, p: 0.0622 }] } },
    fred: { HY_OAS: { last: 3.4 }, CCC_OAS: { last: 13.4 } },
    cot: { contracts: [{ key: "ndx", pctile: 96.8, date: "2026-10-20" }, { key: "vix", pctile: 3.8 }] },
    vol: { VXN: { last: 28.3 }, SKEW: { last: 151.8 } },
    equity: { NVDA: [{ d: "a", c: 240 }, { d: "b", c: 210 }], SPY: [{ d: "a", c: 100 }, { d: "b", c: 100 }] },
    valuation: { pe_ttm: 26.6, pct_10y: 6.7 },
    insiders: { NVDA: { net_usd: -5 } },
    fundamentals: { per_filer: { per: { ORCL: { capex_over_ocf: 1.61 }, MSFT: { capex_over_ocf: 0.63 } } } },
    macro: { growth_share: [null, 6.6, 20.2], pct_gdp: [1.86, 2.23], asof: "2026-10-24" },
    kalshi: { markets: [{ title: "Recession in 2027?", price: 0.215 }, { title: "Other", price: 0.5 }] },
    gpu: { median_dph: 2.521 },
  };
  const cd = { memory: { dram_contract: { direction: "rise", lo: 10, hi: 15, quarter: "4Q26" } },
    manual: { korea: { chip_exports_yoy_pct: 259, window: "Sep 1-20" } }, tsmc: { yoy_pct: 54.6 },
    eia: { planned_gw: 1, under_construction_gw: 2, canceled_gw: 3 }, capex_gdp: { dc_yoy_pct: 73.2 } };
  const S = readSignals(md, cd, constDoc);
  // the pair: live members only — the departed b3 and the proposed b4 are not averaged
  eq("read/bull index is the mean of the live legs", S.bullIdx.toFixed(2), "42.00");
  eq("read/bear index", S.bearIdx.toFixed(2), "20.95");
  eq("read/bull share", S.bullShare.toFixed(4), (42 / 62.95).toFixed(4));
  eq("read/direction + verdict through the shared matrix", [S.dir, S.verdict], ["bull", "constructive"]);
  eq("read/bull legs carry price in cents and days from coverage",
    S.bullLegs.map((l) => [l.id, l.yes, l.days]), [["b1", 4, 69], ["b2", 80, 69]]);
  eq("read/moratorium found by label, not id", S.moratorium, 32.4);
  eq("read/gov vs mkt sleeves", [S.bearGov, S.bearMkt].map((x) => x.toFixed(1)), ["32.4", "9.5"]);
  eq("read/RR in points, tail at the trigger level", [S.rrNvda.toFixed(2), S.tailNvda.toFixed(2), S.tailDte], ["6.02", "6.22", 328]);
  eq("read/COT by key", [S.cotNdx, S.cotVix, S.cotDate], [96.8, 3.8, "2026-10-20"]);
  eq("read/drawdown from the running high", S.dd.NVDA.toFixed(1), "-12.5");
  eq("read/flat series is zero drawdown", S.dd.SPY, 0);
  eq("read/macro takes the last non-null growth share and the last two GDP shares", [S.growthShare, S.pctGdp, S.pctGdpPrev], [20.2, 2.23, 1.86]);
  eq("read/recession contract found by title", [S.recession, S.recessionTitle], [21.5, "Recession in 2027?"]);
  eq("read/capex file: DRAM, Korea, TSMC", [S.dram.direction, S.korea, S.tsmcYoy], ["rise", 259, 54.6]);
  eq("read/T-bill is the curated constant", S.tbill, TBILL.apy);
  // degraded payloads: nothing throws, the fields are null
  const empty = readSignals({}, null, constDoc);
  eq("read/empty payload leaves the verdict null", [empty.verdict, empty.bullShare, empty.regime, empty.dram, empty.korea], [null, null, null, null, null]);
  eq("read/empty payload has no legs", empty.bullLegs.length, 0);
  // rolling: one side under the floor switches the verdict to No edge
  const rolling = readSignals(Object.assign({}, md, { coverage: { sides: { bull: { rolling: true } }, markets: [] } }), cd, constDoc);
  eq("read/rolling side → No edge", [rolling.rolling, rolling.verdict], [true, "mixed"]);
  console.log("  readSignals");
}

/* ---------- 8. the page wires what the rules need ---------- */
{
  ok("page/loads the shared module before its own script", SRC.indexOf('<script src="omen-common.js">') < SRC.indexOf("const T={"));
  ok("page/loads constituents.js", SRC.includes('<script src="constituents.js">'));
  ok("page/does not carry a constituent list of its own", !/"side":\s*"bull"/.test(SRC));
  ok("page/reads the same two data files as the capex page", SRC.includes('fetch("market-data.json"') && SRC.includes('fetch("capex-data.json"'));
  ok("page/uses the shared direction bands, not a local copy", !/0\.55|0\.45/.test(slice("/* ================= trades: thresholds", "/* ================= render")));
  ok("page/the advice disclaimer is in the hero, not only the footer", /<div class="notice">.*Not investment advice/s.test(SRC));
  console.log("  page wiring");
}

if (failures) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall trades tests passed");
