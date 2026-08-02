// Unit tests for the China monitor's two selection rules – which model prices the
// "frontier price gap" is computed over, and which discovered Polymarket rows are
// admissible. Both replaced hardcoded lists that had rotted (2026-08-02); both are
// pure, so they are sliced out of the HTML and tested directly, the same way
// test-pure-helpers.mjs does it. There is no build step and no bundler.
//
//   node omen/test-china-helpers.mjs      (or: python3 -m pytest, which shells out to it)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HTML = join(dirname(fileURLToPath(import.meta.url)), "china-ai-monitor.html");
const SRC = readFileSync(HTML, "utf8");

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
  if (got === want) return;
  failures++;
  console.error(`  FAIL ${name}\n    got:  ${JSON.stringify(got)}\n    want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failures++;
  console.error(`  FAIL ${name}${detail ? " – " + detail : ""}`);
};

console.log("china monitor – flagship line resolution / market discovery filter\n");

const CONSTS = slice("const PM_SEED = [", "const EQ_SYMS");
const OMEN_STUB = { OMEN: { jsonList: (s) => { try { return JSON.parse(s || "[]"); } catch { return []; } } } };

/* ---------- resolveFamilies: pin the line, resolve the version ---------- */
{
  const { resolveFamilies, PRICE_FAMILIES_CN, PRICE_FAMILIES_US } = build(
    CONSTS + slice("function resolveFamilies(", "async function loadPrices(){"),
    ["resolveFamilies", "PRICE_FAMILIES_CN", "PRICE_FAMILIES_US"]);

  const m = (id, created, completion, prompt = 0.000001) =>
    ({ id, created, pricing: { prompt: String(prompt), completion: String(completion) } });

  // the bug of record: the page pinned claude-opus-4.8 and kept reporting it after
  // Opus 5 shipped, so the "US flagship" median was a generation behind
  {
    const r = resolveFamilies(
      [m("anthropic/claude-opus-4.8", 100, 0.000025), m("anthropic/claude-opus-5", 200, 0.000025)],
      [{ label: "Claude Opus", re: /^anthropic\/claude-opus-[\d.]+$/ }]);
    eq("resolves a line to its newest version", r.got[0].id, "anthropic/claude-opus-5");
    eq("newest-version resolution leaves nothing missing", r.missing.length, 0);
  }

  // ...and the mirror bug: google/gemini-3-pro stopped resolving entirely and silently
  // left the median rather than surfacing as a config error
  {
    const r = resolveFamilies([m("google/gemini-3.6-flash", 10, 0.0000075)],
      [{ label: "Gemini Pro", re: /^google\/gemini-[\d.]+-pro$/ }]);
    eq("a line with no live model is reported, not dropped", r.missing[0], "Gemini Pro");
    eq("...and contributes no price", r.got.length, 0);
  }

  // price must never be the tiebreak: Chinese labs ship their newest flagship cheaper
  // than the model it replaces, so max-price would pick the previous generation
  {
    const r = resolveFamilies(
      [m("deepseek/deepseek-v3.1-terminus", 100, 0.000001), m("deepseek/deepseek-v4-pro", 300, 0.00000087)],
      [{ label: "DeepSeek (pro)", re: /^deepseek\/deepseek-v[\d.]+-(pro|terminus)$/ }]);
    eq("cheaper-but-newer wins", r.got[0].id, "deepseek/deepseek-v4-pro");
  }

  {
    const r = resolveFamilies(
      [m("z-ai/glm-5.2", 100, 0), m("z-ai/glm-5.1", 50, 0.00000304)],
      [{ label: "GLM (Z.ai)", re: /^z-ai\/glm-[\d.]+$/ }]);
    eq("a zero-priced entry cannot become the flagship", r.got[0].id, "z-ai/glm-5.1");
  }
  {
    const r = resolveFamilies(
      [m("moonshotai/kimi-k3:free", 900, 0.000015), m("moonshotai/kimi-k3", 100, 0.000015)],
      [{ label: "Kimi", re: /^moonshotai\/kimi-k[\d.]+(:free)?$/ }]);
    eq("free variants are excluded", r.got[0].id, "moonshotai/kimi-k3");
  }
  eq("resolveFamilies tolerates an empty catalogue",
     resolveFamilies([], PRICE_FAMILIES_CN).got.length, 0);
  eq("...and reports every line as missing",
     resolveFamilies(null, PRICE_FAMILIES_CN).missing.length, PRICE_FAMILIES_CN.length);

  // the shipped patterns must not match sibling modalities or tiers
  const pat = (label, list) => {
    const f = list.find((x) => x.label === label);
    if (!f) throw new Error(`no shipped family labelled ${label} – rename the test or the family`);
    return f.re;
  };
  ok("Gemini Flash does not match the image variant",
     !pat("Gemini Flash", PRICE_FAMILIES_US).test("google/gemini-2.5-flash-image"));
  ok("Gemini Flash does not match flash-lite",
     !pat("Gemini Flash", PRICE_FAMILIES_US).test("google/gemini-3.5-flash-lite"));
  ok("Qwen Max does not match qwen3.7-flash",
     !pat("Qwen Max", PRICE_FAMILIES_CN).test("qwen/qwen3.7-flash"));
  ok("DeepSeek flash matches a dated point release",
     pat("DeepSeek (flash)", PRICE_FAMILIES_CN).test("deepseek/deepseek-v4-flash-0731"));
  ok("Kimi line does not swallow Kimi Code",
     !pat("Kimi (Moonshot)", PRICE_FAMILIES_CN).test("moonshotai/kimi-k2.7-code"));
  ok("Kimi Code line matches only the -code tier",
     pat("Kimi Code", PRICE_FAMILIES_CN).test("moonshotai/kimi-k2.7-code"));
  ok("DeepSeek pro line does not match the flash tier",
     !pat("DeepSeek (pro)", PRICE_FAMILIES_CN).test("deepseek/deepseek-v4-flash"));
  ok("Claude Opus does not match the -fast tier",
     !pat("Claude Opus", PRICE_FAMILIES_US).test("anthropic/claude-opus-5-fast"));
}

/* ---------- pmAccept: what discovery is allowed to put in the table ---------- */
{
  const { pmAccept, PM_DISCOVER, PM_MIN_VOL } = build(
    CONSTS + slice('const GAMMA = "https://gamma-api.polymarket.com"', "async function loadPM(){"),
    ["pmAccept", "PM_DISCOVER", "PM_MIN_VOL"], OMEN_STUB);

  const spec = PM_DISCOVER[0];
  const ev = { title: "Best Chinese AI model", slug: "best-chinese-ai-model-august" };
  const mk = (over = {}) => ({
    id: 2954946, question: "Will Alibaba have the best Chinese AI model at the end of August 2026?",
    outcomePrices: '["0.655","0.345"]', volumeNum: 22410, closed: false, ...over,
  });

  const good = pmAccept(spec, ev, mk(), new Set());
  ok("accepts a liquid market in the monthly cohort", good !== null);
  eq("...and reads its price", good && good.p, 0.655);
  eq("...and tags it as discovered", good && good.found, true);
  eq("...and takes the event slug for the link", good && good.slug, "best-chinese-ai-model-august");

  // the placeholder outcomes Polymarket seeds every one of these events with: they sit
  // at exactly 50c on no volume and are not anybody's opinion
  eq("rejects unnamed placeholder outcomes",
     pmAccept(spec, ev, mk({ id: 2954958, question: "Will Company A have the best Chinese AI model at the end of August 2026?", volumeNum: 0 }), new Set()), null);
  eq("rejects the 'any other company' catch-all",
     pmAccept(spec, ev, mk({ id: 2954957, question: "Will any other company have the best Chinese AI model at the end of August 2026?" }), new Set()), null);
  // "Chinese AI" also matches the Chinese-Military-Companies list markets
  eq("rejects off-topic markets that merely mention China",
     pmAccept(spec, { title: "Chinese Military Companies list" },
              mk({ id: 2914102, question: "Will Alibaba be removed from Chinese Military Companies list by June 30?" }), new Set()), null);
  eq("rejects a resolved market", pmAccept(spec, ev, mk({ closed: true }), new Set()), null);
  eq("rejects an illiquid rung", pmAccept(spec, ev, mk({ volumeNum: PM_MIN_VOL - 1 }), new Set()), null);
  eq("accepts exactly at the volume floor",
     pmAccept(spec, ev, mk({ volumeNum: PM_MIN_VOL }), new Set()) !== null, true);
  eq("never duplicates a curated row",
     pmAccept(spec, ev, mk(), new Set(["2954946"])), null);
  eq("tolerates a market with no volume field",
     pmAccept(spec, ev, { id: 1, question: ev.title, outcomePrices: "[]" }, new Set()), null);
  eq("survives malformed outcomePrices",
     pmAccept(spec, ev, mk({ outcomePrices: "not json" }), new Set()).p, null);
}

console.log(failures ? `\n${failures} failure(s)` : "\nall passed");
process.exit(failures ? 1 : 0);
