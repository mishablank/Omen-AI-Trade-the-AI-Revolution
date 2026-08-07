// Behavioral tests for worker.js - the one piece of production code that until now
// was only ever parse-checked (`node --check` in test.yml). The Worker is a pure
// fetch(request, env) with two injected bindings, so everything it decides is
// testable with stubs: the view routing, the R2-first data serving, the etag/304
// path, and every fallback that keeps the site up when R2 misses or errors.
//
// worker.js is an ES module bundled by wrangler; here it is read and evaluated the
// same way the other suites evaluate page code, so the module-type of a root-level
// .js file never matters to the test run.
//
//   node omen/test-worker.mjs        (or: python3 -m pytest, which shells out to it)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(HERE, "..", "worker.js"), "utf8");

// `export default {...}` -> a returnable binding. Everything else in the file is
// plain JS with no imports, so one Function evaluation yields the real handler.
const WORKER = new Function(
  SRC.replace("export default", "const WORKER =") + "\nreturn WORKER;")();

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

// ---- stubs -----------------------------------------------------------------
// A minimal R2 object: body, etag, and the writeHttpMetadata the Worker calls to
// copy stored headers. storedType lets a test prove the Worker's own content-type
// wins over whatever the bucket has stored.
function r2obj(body, etag, storedType) {
  return {
    body,
    httpEtag: etag,
    writeHttpMetadata(h) { if (storedType) h.set("content-type", storedType); },
  };
}

function stubEnv({ r2 = {}, getThrows = false, noData = false } = {}) {
  const calls = { assets: [], gets: [] };
  const env = {
    ASSETS: {
      fetch(req) {
        calls.assets.push(new URL(req.url).pathname);
        return new Response("bundled:" + new URL(req.url).pathname, {
          headers: { "x-stub": "assets" },
        });
      },
    },
  };
  if (!noData) {
    env.DATA = {
      async get(key) {
        calls.gets.push(key);
        if (getThrows) throw new Error("r2 down");
        return r2[key] ?? null;
      },
    };
  }
  return { env, calls };
}

const run = (path, env, headers) =>
  WORKER.fetch(new Request("https://aititsup.com" + path, { headers }), env, {});

console.log("worker — routing, R2-first data, etag/304, fallbacks\n");

/* ---------- data paths: R2 hit ---------- */
{
  const { env, calls } = stubEnv({
    r2: { "market-data.json": r2obj('{"updated":"x"}', '"tag-1"', "application/octet-stream") },
  });
  const res = await run("/market-data.json", env);
  eq("r2-hit/status", res.status, 200);
  eq("r2-hit/body streams the R2 object", await res.text(), '{"updated":"x"}');
  eq("r2-hit/source header", res.headers.get("x-omen-source"), "r2");
  eq("r2-hit/content-type overrides the stored one",
    res.headers.get("content-type"), "application/json; charset=utf-8");
  eq("r2-hit/cache-control", res.headers.get("cache-control"),
    "public, max-age=0, s-maxage=60, must-revalidate");
  eq("r2-hit/etag", res.headers.get("etag"), '"tag-1"');
  eq("r2-hit/assets untouched", calls.assets.length, 0);
  console.log("  R2 hit");
}

/* ---------- data paths: conditional requests ---------- */
{
  const r2 = { "market-data.json": r2obj("{}", '"tag-1"') };
  const hit = await run("/market-data.json", stubEnv({ r2 }).env,
    { "if-none-match": '"tag-1"' });
  eq("304/status on matching etag", hit.status, 304);
  eq("304/body is empty", await hit.text(), "");

  const miss = await run("/market-data.json", stubEnv({ r2 }).env,
    { "if-none-match": '"tag-0"' });
  eq("304/mismatch serves the body", miss.status, 200);

  // No stored etag -> never 304, and no etag header invented.
  const bare = await run("/market-data.json",
    stubEnv({ r2: { "market-data.json": r2obj("{}", undefined) } }).env,
    { "if-none-match": '"tag-1"' });
  eq("304/absent etag still serves 200", bare.status, 200);
  eq("304/absent etag sets no header", bare.headers.get("etag"), null);
  console.log("  etag / 304");
}

/* ---------- data paths: every route in DATA_FILES ---------- */
{
  // The public contract, restated: URL path -> R2 key + served type. A new data
  // file added to worker.js without a row here fails the count check.
  const CONTRACT = [
    ["/market-data.json", "market-data.json", "application/json"],
    ["/snapshots.csv", "snapshots.csv", "text/csv"],
    ["/influencers.json", "influencers.json", "application/json"],
    ["/capex-data.json", "capex-data.json", "application/json"],
    ["/china-data.json", "china-data.json", "application/json"],
    ["/china-metrics.csv", "china-metrics.csv", "text/csv"],
  ];
  const declared = (SRC.match(/^\s*"\/[^"]+":\s*\{ key:/gm) || []).length;
  eq("contract/covers every declared data file", declared, CONTRACT.length);
  for (const [path, key, type] of CONTRACT) {
    const { env, calls } = stubEnv({ r2: { [key]: r2obj("body", '"e"') } });
    const res = await run(path, env);
    eq(`contract${path} -> R2 key`, calls.gets[0], key);
    eq(`contract${path} -> type`, res.headers.get("content-type"), `${type}; charset=utf-8`);
  }
  console.log("  DATA_FILES contract (6 routes)");
}

/* ---------- data paths: fallbacks keep the site up ---------- */
{
  const missing = stubEnv({});
  const res = await run("/china-data.json", missing.env);
  eq("fallback/R2 miss serves the bundled asset", await res.text(), "bundled:/china-data.json");
  eq("fallback/R2 miss asked R2 first", missing.calls.gets[0], "china-data.json");

  const broken = stubEnv({ getThrows: true });
  const res2 = await run("/china-data.json", broken.env);
  eq("fallback/R2 error swallowed, bundled asset served",
    await res2.text(), "bundled:/china-data.json");

  const unbound = stubEnv({ noData: true });
  const res3 = await run("/market-data.json", unbound.env);
  eq("fallback/no DATA binding serves the bundled asset",
    await res3.text(), "bundled:/market-data.json");
  console.log("  fallbacks (miss / error / unbound)");
}

/* ---------- security headers: on everything, CSP on documents only ---------- */
{
  // An HTML response gets the full set. The stub mimics the assets binding serving
  // a page, content-type and all.
  const env = {
    ASSETS: {
      fetch: () => new Response("<!doctype html>", {
        headers: { "content-type": "text/html; charset=utf-8" },
      }),
    },
  };
  const page = await run("/polymarket-ai-index", env);
  eq("sec/html nosniff", page.headers.get("x-content-type-options"), "nosniff");
  eq("sec/html referrer-policy", page.headers.get("referrer-policy"), "strict-origin-when-cross-origin");
  eq("sec/html hsts", page.headers.get("strict-transport-security"), "max-age=31536000");
  eq("sec/html x-frame-options", page.headers.get("x-frame-options"), "DENY");
  const csp = page.headers.get("content-security-policy") || "";
  ok("sec/html has a CSP", csp.length > 0);
  ok("sec/csp default-src self", csp.includes("default-src 'self'"));
  ok("sec/csp inline scripts stay allowed (the pages are inline scripts)",
    csp.includes("script-src 'self' 'unsafe-inline'"));
  ok("sec/csp frame-ancestors none", csp.includes("frame-ancestors 'none'"));
  // The audited fetch inventory: every host a page talks to, and nothing else.
  for (const host of ["https://gamma-api.polymarket.com", "https://clob.polymarket.com",
    "https://openrouter.ai", "https://huggingface.co", "https://api.github.com"]) {
    ok(`sec/csp connect-src ${host}`, csp.includes(host));
  }
  eq("sec/csp allows exactly five external hosts",
    (csp.match(/https:\/\//g) || []).length, 5);
  ok("sec/html body intact after wrapping", (await page.text()).startsWith("<!doctype"));

  // Data responses are not documents: no CSP, but nosniff/HSTS still apply —
  // including on a 304, which carries headers even without a body.
  const r2 = { "market-data.json": r2obj("{}", '"t"') };
  const data = await run("/market-data.json", stubEnv({ r2 }).env);
  eq("sec/data nosniff", data.headers.get("x-content-type-options"), "nosniff");
  ok("sec/data has HSTS", data.headers.get("strict-transport-security") !== null);
  eq("sec/data carries no CSP", data.headers.get("content-security-policy"), null);
  eq("sec/data existing headers survive", data.headers.get("x-omen-source"), "r2");

  const notMod = await run("/market-data.json", stubEnv({ r2 }).env, { "if-none-match": '"t"' });
  eq("sec/304 still nosniffed", notMod.headers.get("x-content-type-options"), "nosniff");
  eq("sec/304 status preserved through wrapping", notMod.status, 304);
  console.log("  security headers (CSP on HTML, nosniff/HSTS everywhere)");
}

/* ---------- view routing: five views, one document ---------- */
{
  for (const view of ["today", "markets", "gpu", "prediction-markets", "methodology"]) {
    const { env, calls } = stubEnv({});
    await run(`/polymarket-ai-index/${view}`, env);
    eq(`views/${view} serves the base document`, calls.assets[0], "/polymarket-ai-index");
  }
  const slash = stubEnv({});
  await run("/polymarket-ai-index/markets/", slash.env);
  eq("views/trailing slash accepted", slash.calls.assets[0], "/polymarket-ai-index");
  console.log("  view routing (5 views + trailing slash)");
}

/* ---------- view routing: everything else falls through ---------- */
{
  for (const [name, path] of [
    ["unknown view", "/polymarket-ai-index/bogus"],
    ["uppercase is not a view", "/polymarket-ai-index/Markets"],
    ["deeper path is not a view", "/polymarket-ai-index/markets/extra"],
    ["base path untouched", "/polymarket-ai-index"],
    ["root untouched", "/"],
  ]) {
    const { env, calls } = stubEnv({});
    await run(path, env);
    eq(`passthrough/${name}`, calls.assets[0], path);
  }
  console.log("  passthrough (unknown views, plain assets)");
}

if (failures) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall worker tests passed");
