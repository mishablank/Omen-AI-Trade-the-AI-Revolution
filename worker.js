// OMEN Worker.
//
// Static assets (HTML, images, favicon) are served straight from ./omen by the
// [assets] binding. The *data* files, however, must never be the copy that
// was bundled at deploy time — they'd go stale between deploys. For those paths
// (listed under assets.run_worker_first in wrangler.jsonc) this Worker runs first
// and streams the object live from the R2 bucket the GitHub Action writes to, so
// the dashboard is always current with no redeploy.
//
// On an R2 miss (e.g. before the first Action upload) it falls back to the bundled
// asset via env.ASSETS, so the site never hard-breaks during bootstrap.

// The dashboard's views. These are not separate assets — they are the same document, so
// this set is the only place a route is declared. "today" is included so a guessed or
// bookmarked /polymarket-ai-index/today renders the Today view (the client reads it back
// from the path) instead of a bare 404; the in-app nav still links Today to the base path.
const DASHBOARD_VIEWS = new Set([
  "today",
  "markets",
  "gpu",
  "prediction-markets",
  "methodology",
]);

const DATA_FILES = {
  "/market-data.json": { key: "market-data.json", type: "application/json" },
  "/snapshots.csv":    { key: "snapshots.csv",    type: "text/csv" },
  "/influencers.json": { key: "influencers.json", type: "application/json" },
  "/capex-data.json":  { key: "capex-data.json",  type: "application/json" },
  "/china-data.json":  { key: "china-data.json",  type: "application/json" },
  "/china-metrics.csv": { key: "china-metrics.csv", type: "text/csv" },
};

// Edge-cache briefly: data refreshes on the order of tens of minutes, so ~60s keeps
// R2 read volume tiny while the dashboard still reads as live.
const CACHE_CONTROL = "public, max-age=0, s-maxage=60, must-revalidate";

// Security headers on everything this Worker hands out. The pages render remote API
// data through innerHTML behind esc()/safeUrl (omen-common.js); the CSP is the
// backstop for the one call site that misses them. It cannot stop inline-script
// injection — the pages ARE inline scripts, so script-src needs 'unsafe-inline' —
// but it does block external script loads, plugin content, framing, form posts and
// any exfil fetch to a host that is not one of the five APIs the pages actually use.
//
// connect-src is the audited inventory of client-side fetch targets (2026-08-07:
// Polymarket Gamma+CLOB on five pages, OpenRouter on capex+china, HuggingFace and
// api.github.com on china). A new external feed added to a page will fail loudly in
// the console until it is added here — that friction is the point. Note this also
// means any Cloudflare feature that injects scripts (Rocket Loader, Web Analytics,
// email obfuscation) would be blocked: none is enabled today, keep it that way or
// add its origin deliberately.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",   // every page is one inline script
  "style-src 'self' 'unsafe-inline'",    // inline style attributes throughout
  "img-src 'self' data:",
  "connect-src 'self'"
    + " https://gamma-api.polymarket.com"
    + " https://clob.polymarket.com"
    + " https://openrouter.ai"
    + " https://huggingface.co"
    + " https://api.github.com",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join("; ");

// Wrap a response with the security headers. CSP and the legacy frame header only
// make sense on documents, so they key off content-type; nosniff, referrer policy
// and HSTS go on everything, data files and 304s included. The copy via the
// Response constructor is required — asset responses arrive immutable.
function secured(resp) {
  const r = new Response(resp.body, resp);
  r.headers.set("x-content-type-options", "nosniff");
  r.headers.set("referrer-policy", "strict-origin-when-cross-origin");
  r.headers.set("strict-transport-security", "max-age=31536000");
  if ((r.headers.get("content-type") || "").includes("text/html")) {
    r.headers.set("content-security-policy", CSP);
    r.headers.set("x-frame-options", "DENY");
  }
  return r;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // The dashboard is one document with five views (Today + four deep dives). Serve the
    // same asset for every /polymarket-ai-index/<view> path and let the page read
    // location.pathname to pick the view: one fetch of the data, instant view switching,
    // and real shareable URLs. Unknown subpaths fall through to the normal 404.
    const view = url.pathname.match(/^\/polymarket-ai-index\/([a-z-]+)\/?$/);
    if (view && DASHBOARD_VIEWS.has(view[1])) {
      const asset = new URL("/polymarket-ai-index", url.origin);
      return secured(await env.ASSETS.fetch(new Request(asset, request)));
    }

    const spec = DATA_FILES[url.pathname];

    if (spec && env.DATA) {
      try {
        const obj = await env.DATA.get(spec.key);
        if (obj) {
          const headers = new Headers();
          obj.writeHttpMetadata(headers); // carries any stored content-type/etag
          headers.set("content-type", `${spec.type}; charset=utf-8`);
          headers.set("cache-control", CACHE_CONTROL);
          if (obj.httpEtag) headers.set("etag", obj.httpEtag);
          headers.set("x-omen-source", "r2");
          // honour conditional requests so the edge/browser can 304
          const inm = request.headers.get("if-none-match");
          if (inm && obj.httpEtag && inm === obj.httpEtag) {
            return secured(new Response(null, { status: 304, headers }));
          }
          return secured(new Response(obj.body, { headers }));
        }
      } catch (e) {
        // fall through to the bundled asset on any R2 error
      }
    }

    // everything else — and any R2 miss/error — is served from the bundled assets
    return secured(await env.ASSETS.fetch(request));
  },
};
