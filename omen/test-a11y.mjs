// Accessibility invariants (BACKLOG "Front end — chart accessibility").
//
// Three rules are pinned here so they cannot regress silently:
//   1. Direction is never colour-only: every delta helper emits a sign character, so
//      .up/.down spans read correctly without their colour.
//   2. Information-bearing charts carry a live text alternative (role="img" +
//      aria-label composed from the plotted data); decorative sparklines are
//      aria-hidden instead.
//   3. The monitor's sortable headers are keyboard controls: tabbable, Enter/Space
//      activated, current order in aria-sort.
//
// The helpers are sliced and *executed*; the render-time setAttribute calls are
// asserted as source markers, same loud-failure convention as the other suites.
//
//   node omen/test-a11y.mjs        (or: python3 -m pytest, which shells out to it)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (f) => readFileSync(join(HERE, f), "utf8");
const MONITOR = read("polymarket-ai-index.html");
const INDEX = read("index.html");
const CAPEX = read("ai-capex.html");

function slice(src, start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error(`start marker not found: ${start}`);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error(`end marker not found: ${end}`);
  return src.slice(a, b);
}
function build(code, names, stubs = {}) {
  const keys = Object.keys(stubs);
  const fn = new Function(...keys, `${code}\nreturn {${names.join(",")}};`);
  return fn(...keys.map((k) => stubs[k]));
}

let failures = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failures++;
  console.error(`  FAIL ${name}${detail ? " — " + detail : ""}`);
};

console.log("a11y — signed deltas, chart text alternatives, keyboard sort\n");

/* ---------- 1. direction always carries a sign, not just a colour ---------- */
{
  const { deltaSpan } = build(slice(MONITOR, "function deltaSpan", "\nfunction hbar"), ["deltaSpan"]);
  ok("deltaSpan/positive is signed", deltaSpan(3.2).includes("+3.2"), deltaSpan(3.2));
  ok("deltaSpan/positive class up", deltaSpan(3.2).includes('class="up"'));
  ok("deltaSpan/negative is signed", deltaSpan(-3.2).includes("-3.2"), deltaSpan(-3.2));
  ok("deltaSpan/negative class down", deltaSpan(-3.2).includes('class="down"'));
  ok("deltaSpan/badWhenUp flips class, keeps sign",
    deltaSpan(3.2, 1, "", true).includes('class="down"') && deltaSpan(3.2, 1, "", true).includes("+3.2"));
  ok("deltaSpan/zero is dim, not directional", deltaSpan(0).includes('class="dim"'));

  const { chgTxt } = build(slice(INDEX, "function chgTxt", "\n"), ["chgTxt"]);
  ok("chgTxt/positive signed", chgTxt(2.2).startsWith("+"));
  ok("chgTxt/negative signed with real minus", chgTxt(-2.2).startsWith("−"));

  // MINUS is the page's typographic-minus constant, defined a few lines above the slice
  const { sn } = build(slice(CAPEX, "function sn(", "\nfunction "), ["sn"], { MINUS: "−" });
  ok("sn/positive signed", String(sn(3.2, 1, "%")).startsWith("+"), sn(3.2, 1, "%"));
  ok("sn/negative signed with real minus", String(sn(-3.2, 1, "%")).startsWith("−"), sn(-3.2, 1, "%"));
  console.log("  signed deltas (deltaSpan / chgTxt / sn)");
}

/* ---------- 2. charts: labelled when informative, hidden when decorative ---------- */
{
  // OMEN.sparkSvg executes for real; its output must stay explicitly decorative.
  const OMEN = new Function(read("omen-common.js") + "\nreturn OMEN;")();
  const svg = OMEN.sparkSvg([1, 2, 3, 2, 4], 100, 30, "#fff", false);
  ok("sparkSvg/output is aria-hidden", svg.includes('aria-hidden="true"'));
  ok("sparkSvg/not focusable", svg.includes('focusable="false"'));

  // Render-time attributes, asserted as source markers (loud failure if renamed).
  const roleImg = (MONITOR.match(/setAttribute\("role","img"\)/g) || []).length;
  ok("monitor/lineChart + multiPanelChart set role=img", roleImg >= 2, `found ${roleImg}`);
  ok("monitor/lineChart labels series and latest",
    MONITOR.includes('svg.setAttribute("aria-label",`Line chart of ${series.map('));
  ok("monitor/multiPanelChart labels panels",
    MONITOR.includes('svg.setAttribute("aria-label",`Small-multiples chart: ${panels.map('));
  ok("monitor/spark is aria-hidden",
    slice(MONITOR, "function spark(", "\nfunction ").includes('setAttribute("aria-hidden","true")'));
  ok("index/verdict tape carries a text alternative",
    INDEX.includes('$("tapeCells").setAttribute("aria-label"'));
  ok("index/dial is labelled in markup",
    /<svg class="dial"[^>]*role="img"[^>]*aria-label/.test(INDEX));
  console.log("  chart text alternatives (labelled or hidden)");
}

/* ---------- 3. sortable headers are keyboard controls ---------- */
{
  const table = slice(MONITOR, "const arrow=k=>", "function renderCoverage");
  ok("th/tabbable button role", table.includes('role="button" tabindex="0"'));
  ok("th/aria-sort reflects state", table.includes('aria-sort="${st.k===k?(st.dir<0?"descending":"ascending"):"none"}"'));
  ok("th/Enter and Space activate", table.includes('e.key==="Enter"||e.key===" "'));
  ok("th/arrow glyph hidden from readers", table.includes('<span class="arrow" aria-hidden="true">'));
  ok("th/focus survives the re-render", table.includes("?.focus()"));
  console.log("  keyboard-sortable headers");
}

if (failures) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall a11y tests passed");
