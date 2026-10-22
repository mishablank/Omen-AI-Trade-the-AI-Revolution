// The browser side of the constituent roll: OMEN.constituentsAt / bubbleIdAt / rollState /
// coverageSummary in omen-common.js, the chain-aware parseSnapshots, and the landing
// page's verdict rule honouring a rolling basket. The Python half (test_constituents.py)
// pins the file itself and the fetcher's watchdog; this half pins what the pages do with
// the same literal, loaded the way the pages load it.
//
//   node omen/test-constituents.mjs        (or: python3 -m pytest, which shells out to it)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const OMEN = new Function(
  readFileSync(join(HERE, "omen-common.js"), "utf8") + "\nreturn OMEN;")();
// constituents.js assigns to window.*; give it one, the same way the pages do
const DOC = new Function("window",
  readFileSync(join(HERE, "constituents.js"), "utf8") + "\nreturn window.OMEN_CONSTITUENTS;")({});

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

console.log("constituents — vintages / roll state / coverage / chained snapshots / verdict\n");

/* ---------- constituentsAt: the vintage rule ---------- */
{
  const day0 = OMEN.constituentsAt(DOC, "2026-07-11");
  eq("vintage/original twenty on curation day",
    [day0.filter((m) => m.side === "bull").length, day0.filter((m) => m.side === "bear").length], [11, 9]);
  const today = OMEN.constituentsAt(DOC, "2026-10-22");
  eq("vintage/three have left by 2026-10-22",
    [today.filter((m) => m.side === "bull").length, today.filter((m) => m.side === "bear").length], [9, 8]);
  ok("vintage/to is exclusive: gone on its own day",
    !OMEN.constituentsAt(DOC, "2026-09-04").some((m) => m.id === "676829")
    && OMEN.constituentsAt(DOC, "2026-09-03").some((m) => m.id === "676829"));
  ok("vintage/proposed rows are never members",
    !OMEN.constituentsAt(DOC, "2030-01-01").some((m) => m.proposed));
  ok("vintage/side filter", OMEN.constituentsAt(DOC, "2026-10-22", "bear").every((m) => m.side === "bear"));
  ok("vintage/china and macro ride along", today.some((m) => m.side === "china") && today.some((m) => m.side === "macro"));
  ok("vintage/defaults to today", OMEN.constituentsAt(DOC).length > 0);
  eq("bubble/today", OMEN.bubbleIdAt(DOC, "2026-10-22"), "691340");
  const active = { ...DOC, markets: DOC.markets.map((m) => ({ ...m, proposed: false })) };
  eq("bubble/the successor takes over on its from date", OMEN.bubbleIdAt(active, "2027-01-02"), "4838928");
  eq("bubble/none when no live member carries the role", OMEN.bubbleIdAt({ markets: [] }, "2026-10-22"), null);
  console.log("  constituentsAt / bubbleIdAt");
}

/* ---------- rollState ---------- */
{
  const mk = (side, n, closed = 0) => Array.from({ length: n }, (_, i) => ({ side, closed: i < closed }));
  const fine = OMEN.rollState([...mk("bull", 9), ...mk("bear", 8)], 3);
  eq("roll/healthy", fine, { floor: 3, live: { bull: 9, bear: 8 }, rolling: [] });
  const thin = OMEN.rollState([...mk("bull", 9, 7), ...mk("bear", 8)], 3);
  eq("roll/bull under the floor", thin.rolling, ["bull"]);
  eq("roll/live counts exclude closed", thin.live.bull, 2);
  eq("roll/at the floor is not rolling", OMEN.rollState([...mk("bull", 3), ...mk("bear", 3)], 3).rolling, []);
  eq("roll/both sides empty", OMEN.rollState([], 3).rolling, ["bull", "bear"]);
  console.log("  rollState");
}

/* ---------- coverageSummary ---------- */
{
  const now = Date.parse("2026-10-22T12:00:00Z");
  const ms = [
    ...Array.from({ length: 16 }, () => ({ closed: false, endDate: "2027-01-01T00:00:00Z" })),
    { closed: false, endDate: Date.parse("2028-01-01T00:00:00Z") },   // epoch ms, as the monitor keeps it
    { closed: true, endDate: "2026-09-30T00:00:00Z" },
    { closed: false, endDate: null },
  ];
  const c = OMEN.coverageSummary(ms, { now, horizonDays: 30 });
  eq("coverage/configured and live", [c.configured, c.live], [19, 18]);
  eq("coverage/cliff is the most populous end date", [c.cliff, c.cliffCount], ["2027-01-01", 16]);
  eq("coverage/days to the cliff", c.cliffDays, 71);
  eq("coverage/nothing inside 30 days yet", c.expiring, 0);
  eq("coverage/inside the horizon in December",
    OMEN.coverageSummary(ms, { now: Date.parse("2026-12-10T00:00:00Z"), horizonDays: 30 }).expiring, 16);
  eq("coverage/empty", OMEN.coverageSummary([], { now }).cliff, null);
  // a tie goes to the earlier date, the one that bites first
  const tie = OMEN.coverageSummary([{ endDate: "2027-03-01" }, { endDate: "2027-01-01" }], { now });
  eq("coverage/tie breaks earliest", tie.cliff, "2027-01-01");
  console.log("  coverageSummary");
}

/* ---------- parseSnapshots: chain columns ---------- */
{
  const csv = [
    "date,bull,bull_n,bear,bear_n,crash,crash_n,reg,reg_n,gauge,lead,conf,bull_chain,bear_chain,comp",
    "2026-10-21,28.02,9,10.94,8,4.75,3,14.66,5,35.4,34.8,36.2,,,1,2,3",
    "2026-10-22,27.86,9,11.46,8,4.87,3,15.41,5,35.6,35.2,36.2,27.86,11.46,1,2,3",
    "2027-01-02,40.00,3,20.00,3,5.00,3,15.00,5,30.0,30.0,30.0,27.5,11.5,4,5,6",
  ].join("\n");
  const rows = OMEN.parseSnapshots(csv);
  eq("snapshots/three rows", rows.length, 3);
  eq("snapshots/legacy row uses the raw share", [rows[0].chained, rows[0].share.toFixed(4)], [false, (28.02 / 38.96).toFixed(4)]);
  eq("snapshots/chained row uses the chain share", [rows[1].chained, rows[1].share.toFixed(4)], [true, (27.86 / 39.32).toFixed(4)]);
  // the roll day: raw share would jump to .667, the chained one stays near .70
  eq("snapshots/roll day does not jump", rows[2].share.toFixed(4), (27.5 / 39.0).toFixed(4));
  eq("snapshots/raw share still available", rows[2].shareRaw.toFixed(4), (40 / 60).toFixed(4));
  // the old header still parses, unchanged
  const old = OMEN.parseSnapshots("date,bull,bull_n,bear,bear_n,crash,crash_n,reg,reg_n,gauge,lead,conf,comp\n2026-07-11,45.18,11,16.6,9,8.8,3,20.5,6,27.3,,,1,2");
  eq("snapshots/old header", [old.length, old[0].chained, old[0].share.toFixed(4)], [1, false, (45.18 / 61.78).toFixed(4)]);
  console.log("  parseSnapshots (chain columns)");
}

/* ---------- the landing page's verdict rule honours a rolling basket ---------- */
{
  const SRC = readFileSync(join(HERE, "index.html"), "utf8");
  const a = SRC.indexOf("/* ================= verdict"), b = SRC.indexOf("/* ================= render", a);
  if (a < 0 || b < 0) throw new Error("verdict markers moved in index.html");
  const { verdictOf } = new Function("OMEN", SRC.slice(a, b) + "\nreturn {verdictOf};")(OMEN);
  eq("verdict/rolling is No edge whatever the share", verdictOf(0.9, "calm", true), "mixed");
  eq("verdict/rolling is No edge even when bearish", verdictOf(0.1, "stressed", true), "mixed");
  eq("verdict/not rolling: the matrix", verdictOf(0.9, "calm", false), "riskon");
  eq("verdict/two-argument calls unchanged", verdictOf(0.1, "calm"), "riskoff");
  ok("verdict/the page loads constituents.js before its own script",
    SRC.indexOf('<script src="constituents.js">') < SRC.indexOf("const MARKETS="));
  console.log("  verdictOf(rolling)");
}

if (failures) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall constituents tests passed");
