/* OMEN — helpers shared by every page.
 *
 * There is no bundler here and the pages are also openable straight off the filesystem,
 * so this is a plain classic script that hangs one namespace off the global object. Load
 * it with <script src="omen-common.js"></script> before a page's own inline script:
 *
 *   const $ = OMEN.$, esc = OMEN.esc, safeUrl = OMEN.safeUrl;
 *
 * Everything in here was previously copy-pasted per page — $ and esc in six files,
 * sparkSvg byte-for-byte in two, the regime thresholds encoded three separate times, and
 * the Polymarket price-parsing loop in five. Divergence between the copies was not
 * hypothetical: one page's esc() had lost its null guard and threw on a null field where
 * every other page degraded quietly.
 *
 * Node test suites load this file the same way they load the pages' inline code — read it
 * and eval it — so it is deliberately free of imports and DOM access at load time.
 */
(function (root) {
  "use strict";

  /* ================= DOM + escaping ================= */
  const $ = (id) => document.getElementById(id);

  // The null guard is load-bearing: these render remote fields that are routinely absent.
  const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESCAPES[c]);

  // esc() makes a string safe *inside* an attribute; it does not make it safe *as a URL*.
  // An escaped "javascript:alert(1)" is still a live URL, and these hrefs are built from
  // remote data — Polymarket event slugs, influencers.json, Kalshi/Metaculus/Manifold rows.
  // safeUrl allowlists the two schemes the site ever links with and sends anything else to
  // "#". Relative URLs have no scheme, are same-origin by construction, and are passed
  // through unchanged so internal links keep their exact form.
  function safeUrl(u) {
    const s = String(u == null ? "" : u).trim();
    if (!s) return "#";
    // Browsers strip control characters and whitespace before parsing a scheme, so
    // "java\tscript:…" resolves as javascript:. Reject them rather than try to normalize.
    if (/[\u0000-\u001f\u007f]/.test(s)) return "#";
    const scheme = /^([a-z][a-z0-9+.\-]*):/i.exec(s);
    if (scheme && !/^https?$/i.test(scheme[1])) return "#";
    return esc(s);
  }

  /* ================= Polymarket shapes ================= */
  // Gamma reports a last-trade price and a book. The book mid is the better read when both
  // sides quote; the last trade is the fallback. outcomePrices arrives as a JSON *string*,
  // and a malformed one used to throw straight out of the caller's loop, losing every
  // market after it — hence the guard.
  function outcomeYes(g) {
    const bid = parseFloat(g.bestBid), ask = parseFloat(g.bestAsk);
    if (isFinite(bid) && isFinite(ask) && ask > 0) return (bid + ask) / 2;
    const last = parseFloat(jsonList(g.outcomePrices)[0] ?? "0");
    return isFinite(last) ? last : 0;
  }

  // Parse one of Gamma's JSON-in-a-string list fields (outcomePrices, clobTokenIds).
  function jsonList(s) {
    try {
      const v = JSON.parse(s || "[]");
      return Array.isArray(v) ? v : [];
    } catch (e) {
      return [];
    }
  }

  const isClosed = (g) => !!g.closed || g.active === false;

  // Bid/ask spread, or null when the book is one-sided.
  function bookSpread(g) {
    const bid = parseFloat(g.bestBid), ask = parseFloat(g.bestAsk);
    return isFinite(bid) && isFinite(ask) && ask > 0 ? ask - bid : null;
  }

  /* ================= regime thresholds ================= */
  // The one place the bands are written down. index.html and gauge.html apply them via
  // regimeOf(); the monitor composes the same numbers into its richer explainer rule set.
  // They were previously re-typed in all three, free to drift apart silently.
  const REGIME = {
    GAUGE_STRESSED: 55,   // blended gauge trips Stressed
    LEVEL_STRESSED: 40,   // crash-basket average trips Stressed
    GAUGE_ELEVATED: 35,
    LEVEL_ELEVATED: 25,
    SIGNAL_ELEVATED: 15,  // any single market (bubble odds included) caps out here
    Z_STRESSED: 2,        // crash basket climbing unusually fast, with LEVEL_ELEVATED
    Z_ELEVATED: 1.5,
  };

  // A broad or confirmed metric is required for Stressed: a single market can raise
  // Elevated but never trips red on its own.
  function regimeOf(score, crashLevel, bubblePct) {
    if (score >= REGIME.GAUGE_STRESSED || crashLevel >= REGIME.LEVEL_STRESSED) return "stressed";
    if (score >= REGIME.GAUGE_ELEVATED || crashLevel >= REGIME.LEVEL_ELEVATED ||
        bubblePct >= REGIME.SIGNAL_ELEVATED) return "elevated";
    return "calm";
  }

  const REGIME_META = {
    calm: { word: "Calm", color: "var(--bullT)", border: "var(--bull)" },
    elevated: { word: "Elevated", color: "var(--regT)", border: "var(--reg)" },
    stressed: { word: "Stressed", color: "var(--crashT)", border: "var(--crash)" },
  };

  /* ================= gauge reference ranges ================= */
  // The calm→stress range each gauge component is normalized against, written down once.
  // They used to be re-typed in five places — compute_gauge() in update-market-data.py,
  // computeGauge() and computeGaugeHistory() in the monitor, and the reference-range prose
  // on gauge.html and in the monitor's methodology footer. The regime *thresholds* were
  // centralized into REGIME above after they drifted; these ranges were the same accident
  // waiting to happen, with a worse failure mode: a range that drifts changes the number
  // without changing any wording, so nothing looks wrong.
  //
  // Each row carries its own prose, so the published range and the computed range cannot
  // disagree: `name` and `fmt` render the phrasing, they do not restate the numbers.
  //   fmt "pct"   → "bubble 0–40%"          fmt "pt"    → "NVDA RR 1–10pt"
  //   fmt "level" → "VIX/VIX3M 0.82–1.05"   fmt "ddpct" → "NVDA 0→−50%"  (drawdown, negated)
  // `server` marks the rows update-market-data.py's five-family gauge also reads; the rest
  // are the monitor's exploratory-only components. test_gauge_refs.py parses this object
  // out of this file and fails if the Python mirror disagrees on a number or on that split.
  const GAUGE_REFS = {
    pred_bubble:      { fam: "pred",   name: "bubble",         lo: 0,    hi: 40,   fmt: "pct",   server: true },
    pred_nvda_tail:   { fam: "pred",   name: "NVDA tail",      lo: 0,    hi: 25,   fmt: "pct" },
    pred_h100_sub2:   { fam: "pred",   name: "H100 < $2",      lo: 0,    hi: 30,   fmt: "pct" },
    opt_nvda_rr:      { fam: "opt",    name: "NVDA RR",        lo: 1,    hi: 10,   fmt: "pt",    server: true },
    opt_soxx_rr:      { fam: "opt",    name: "SOXX",           lo: 4,    hi: 15,   fmt: "pt",    server: true },
    vol_term:         { fam: "vol",    name: "VIX/VIX3M",      lo: 0.82, hi: 1.05, fmt: "level", server: true },
    vol_vxn:          { fam: "vol",    name: "VXN",            lo: 18,   hi: 40,   fmt: "level", server: true },
    vol_skew:         { fam: "vol",    name: "SKEW",           lo: 115,  hi: 160,  fmt: "level", server: true },
    vol_vvix:         { fam: "vol",    name: "VVIX",           lo: 90,   hi: 130,  fmt: "level", server: true },
    credit_hyg_dd:    { fam: "credit", name: "HYG drawdown",   lo: 0,    hi: 8,    fmt: "ddpct", server: true },
    credit_hyig_dd:   { fam: "credit", name: "HY/IG drawdown", lo: 0,    hi: 6,    fmt: "ddpct", server: true },
    credit_hy_oas:    { fam: "credit", name: "HY OAS",         lo: 2.5,  hi: 5,    fmt: "pct",   server: true },
    credit_ccc_oas:   { fam: "credit", name: "CCC OAS",        lo: 8.5,  hi: 14,   fmt: "pct",   server: true },
    equity_nvda_dd:   { fam: "equity", name: "NVDA",           lo: 0,    hi: 50,   fmt: "ddpct", server: true },
    equity_soxx_dd:   { fam: "equity", name: "SOXX",           lo: 0,    hi: 40,   fmt: "ddpct", server: true },
    macro_recession:  { fam: "macro",  name: "recession",      lo: 5,    hi: 50,   fmt: "pct" },
    macro_fed_cuts:   { fam: "macro",  name: "Fed cuts",       lo: 0,    hi: 60,   fmt: "pct" },
    macro_china_top3: { fam: "macro",  name: "China top-3",    lo: 5,    hi: 50,   fmt: "pct" },
  };

  const GAUGE_FAM_NAMES = {
    pred: "prediction markets", opt: "options skew", vol: "vol complex",
    credit: "credit", equity: "equity drawdown", macro: "macro",
  };

  // Normalize x onto 0–100 against the named reference range. Every gauge component goes
  // through this, so a component can only be scored against a range that is written down.
  function gaugeScore(x, key) {
    const r = GAUGE_REFS[key];
    if (!r) throw new Error("unknown gauge ref: " + key);
    if (x == null) return null;
    return Math.max(0, Math.min(100, (x - r.lo) / (r.hi - r.lo) * 100));
  }

  // One component as published prose, e.g. "VXN 18–40". Numbers come from the row, never
  // from a second copy in a sentence. Emits literal – − → (the pages are UTF-8) and escapes
  // the name, which is the only part that could carry markup.
  function gaugeRefText(key) {
    const r = GAUGE_REFS[key], n = esc(r.name);
    if (r.fmt === "ddpct") return `${n} ${r.lo}→−${r.hi}%`;
    if (r.fmt === "pt") return `${n} ${r.lo}–${r.hi}pt`;
    if (r.fmt === "pct") return `${n} ${r.lo}–${r.hi}%`;
    return `${n} ${r.lo}–${r.hi}`;
  }

  // The reference ranges as one family-grouped sentence fragment:
  //   "prediction markets (bubble 0–40%), options skew (NVDA RR 1–10pt, SOXX 4–15pt), …"
  // scope "server" = the five-family headline gauge's rows; "extra" = the components only
  // the monitor's exploratory card adds; "all" = everything.
  function gaugeRefsProse(scope) {
    const want = (r) => (scope === "server" ? !!r.server : scope === "extra" ? !r.server : true);
    const order = ["pred", "opt", "vol", "credit", "equity", "macro"];
    return order.map((f) => {
      const keys = Object.keys(GAUGE_REFS).filter((k) => GAUGE_REFS[k].fam === f && want(GAUGE_REFS[k]));
      return keys.length ? `${GAUGE_FAM_NAMES[f]} (${keys.map(gaugeRefText).join(", ")})` : "";
    }).filter(Boolean).join(", ");
  }

  /* ================= index math ================= */
  // Bound to a getter rather than a value so a page can keep mutating its own MARKETS
  // array in place, which is how the live refresh works:
  //   const { indexOf, d1Of, pairShare, pairD1 } = OMEN.indexMath(() => MARKETS);
  function indexMath(getMarkets) {
    // theme is optional: pass it to read one sleeve (Bear's MKT/GOV, Bull's TECH/CAP)
    // instead of the whole index.
    function indexOf(side, theme) {
      const ms = getMarkets().filter((m) => m.side === side && !m.closed && (!theme || m.theme === theme));
      return ms.length ? ms.reduce((a, m) => a + m.yes, 0) / ms.length * 100 : 0;
    }
    function d1Of(side) {
      const ms = getMarkets().filter((m) => m.side === side && !m.closed && m.d1 != null);
      return ms.length ? ms.reduce((a, m) => a + m.d1, 0) / ms.length * 100 : 0;
    }
    // The pair prices like one two-sided market: each side's displayed price is its share
    // of the pair, so BULL + BEAR always sums to exactly 1.
    function pairShare(side) {
      const b = indexOf("bull"), x = indexOf("bear"), t = b + x;
      return t > 0 ? (side === "bull" ? b : x) / t : 0;
    }
    function pairD1(side) {
      const b = indexOf("bull") - d1Of("bull"), x = indexOf("bear") - d1Of("bear"), t = b + x;
      return t > 0 ? (pairShare(side) - (side === "bull" ? b : x) / t) * 100 : 0;
    }
    return { indexOf, d1Of, pairShare, pairD1 };
  }

  /* ================= sparkline ================= */
  // Returns "" rather than an SVG full of NaN when there is nothing to draw: one point
  // makes the i/(n-1) step divide by zero, and zero points make Math.min() Infinity.
  //
  // The y-domain is floored at opts.minSpan (default 4% of the series' mean magnitude):
  // raw min→max scaling renders a ±0.3% drift as a full-height mountain range, which
  // reads as volatility that is not there. A dotted line marks the period mean so a
  // genuinely flat week also *looks* flat; pass opts.mean:false to omit it.
  function sparkSvg(vals, w, h, color, fill, opts) {
    if (!vals || vals.length < 2) return "";
    opts = opts || {};
    let mn = Math.min(...vals), mx = Math.max(...vals);
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    const floor = opts.minSpan != null ? opts.minSpan : Math.abs(avg) * 0.04;
    if (mx - mn < floor) { const mid = (mx + mn) / 2; mn = mid - floor / 2; mx = mid + floor / 2; }
    const r = (mx - mn) || 1;
    const y = (v) => h - 3 - (v - mn) / r * (h - 8);
    const pts = vals.map((v, i) => [i / (vals.length - 1) * w, y(v)]);
    const line = pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
    const area = `M0,${h} L${line.replace(/ /g, " L")} L${w},${h} Z`;
    const meanLine = opts.mean === false ? "" :
      `<line x1="0" y1="${y(avg).toFixed(1)}" x2="${w}" y2="${y(avg).toFixed(1)}" stroke="${color}" opacity=".28" stroke-dasharray="2,4" vector-effect="non-scaling-stroke"/>`;
    return `<svg width="100%" height="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    ${fill ? `<path d="${area}" fill="${color}" opacity=".12"/>` : ""}${meanLine}
    <polyline points="${line}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <circle cx="${pts[pts.length - 1][0]}" cy="${pts[pts.length - 1][1]}" r="3" fill="${color}"/></svg>`;
  }

  /* ================= daily snapshots ================= */
  // Parse snapshots.csv — the GitHub Action appends one row a day (see
  // update-market-data.py --snapshot). Only the columns the pages chart are pulled out;
  // the trailing constituent-id list is ignored. Rows whose pair is empty are dropped
  // rather than rendered as 0/0 artifacts, and a malformed gauge cell becomes null so a
  // chart can skip the point instead of plotting NaN.
  function parseSnapshots(text) {
    const lines = String(text == null ? "" : text).trim().split(/\r?\n/);
    if (lines.length < 2) return [];
    const head = lines[0].split(",");
    const col = {};
    for (const k of ["bull", "bear", "crash", "gauge"]) col[k] = head.indexOf(k);
    if (col.bull < 0 || col.bear < 0) return [];
    const rows = [];
    for (let i = 1; i < lines.length; i++) {
      const c = lines[i].split(",");
      const bull = parseFloat(c[col.bull]), bear = parseFloat(c[col.bear]);
      if (!isFinite(bull) || !isFinite(bear) || bull + bear <= 0) continue;
      const crash = col.crash >= 0 ? parseFloat(c[col.crash]) : NaN;
      const gauge = col.gauge >= 0 ? parseFloat(c[col.gauge]) : NaN;
      rows.push({
        date: c[0],
        share: bull / (bull + bear),
        crash: isFinite(crash) ? crash : 0,
        gauge: isFinite(gauge) ? gauge : null,
      });
    }
    return rows;
  }

  /* ================= pair-share history ================= */
  // Resample per-market CLOB price histories onto N shared uniform buckets and price the
  // pair at each bucket: side level = equal-weight mean of its constituents (step-function
  // resample, so a sparse series holds its last trade), share = level / (sum of levels).
  // Requires ≥2 histories per side — one lone market's noise should not masquerade as an
  // index — and a non-empty common time window. Returns null when either fails.
  //   hist: { marketId: [{t, p}, ...] }   sideIds: { bull: [ids], bear: [ids] }
  function pairShareSeries(hist, sideIds, N) {
    const sides = Object.keys(sideIds);
    if (!sides.length || sides.some((s) => (sideIds[s] || []).filter((i) => hist[i] && hist[i].length > 1).length < 2)) return null;
    const ids = {};
    for (const s of sides) ids[s] = sideIds[s].filter((i) => hist[i] && hist[i].length > 1);
    const all = sides.flatMap((s) => ids[s]);
    const t0 = Math.max(...all.map((i) => hist[i][0].t));
    const t1 = Math.min(...all.map((i) => hist[i][hist[i].length - 1].t));
    if (!(t1 > t0)) return null;
    const lvl = {};
    for (const s of sides) {
      lvl[s] = [];
      for (let k = 0; k < N; k++) {
        const t = t0 + (t1 - t0) * k / (N - 1);
        let sum = 0;
        for (const i of ids[s]) {
          const h = hist[i];
          let lo = 0;
          while (lo < h.length - 1 && h[lo + 1].t <= t) lo++;
          sum += h[lo].p;
        }
        lvl[s].push(sum / ids[s].length);
      }
    }
    const share = {};
    for (const s of sides) {
      share[s] = lvl[s].map((v, k) => {
        const tot = sides.reduce((a, x) => a + lvl[x][k], 0);
        return tot > 0 ? v / tot : 0;
      });
    }
    return { share, t0, t1 };
  }

  /* ================= capex live-tape derivations ================= */
  // Pure helpers behind ai-capex.html's Baker-tape panels (cash-flow acceleration,
  // token demand, GPU repricing gap, inference-margin floor). Kept here so the math
  // is testable without a browser – same reason indexMath lives in this file.

  // Combined operating-cash-flow growth from market-data.json's fundamentals block.
  // YoY is only quoted when both quarters aggregate the full filer cohort
  // (n_firms == max): the newest quarter usually has a laggard fiscal-year filer,
  // and a 4-of-5 vs 5-of-5 comparison would read as a collapse that never happened.
  function ocfGrowth(fund) {
    if (!fund || !Array.isArray(fund.quarters) || !Array.isArray(fund.ocf_b)
        || !Array.isArray(fund.n_firms) || !fund.quarters.length) return null;
    const N = Math.max.apply(null, fund.n_firms);
    const idx = {};
    fund.quarters.forEach((q, i) => { idx[q] = i; });
    const yearAgo = (q) => (+q.slice(0, 4) - 1) + q.slice(4);
    const rows = [];
    for (const q of fund.quarters) {
      const i = idx[q], j = idx[yearAgo(q)];
      if (j == null) continue;
      const cur = fund.ocf_b[i], base = fund.ocf_b[j];
      if (cur == null || base == null || base <= 0) continue;
      rows.push({ q, yoy: (cur / base - 1) * 100,
                  complete: fund.n_firms[i] === N && fund.n_firms[j] === N });
    }
    const full = rows.filter((r) => r.complete);
    if (!full.length) return null;
    const latest = full[full.length - 1];
    const prior = full.length > 1 ? full[full.length - 2] : null;
    const tail = rows[rows.length - 1];
    return {
      latest, prior,
      accel_pp: prior ? latest.yoy - prior.yoy : null,
      // a newer quarter exists but its cohort is short – name it, never quote it
      partial_q: tail.complete ? null : tail.q,
      partial_n: tail.complete ? null : fund.n_firms[idx[tail.q]],
      n_firms: N,
    };
  }

  // Platform-wide token demand from OpenRouter's weekly market-share series
  // ([{x: "YYYY-MM-DD", tot: tokens}] ascending). Growth is null until the series
  // is long enough for that window – never extrapolated.
  function tokenDemand(series) {
    const s = (series || []).filter((w) => w && w.tot > 0 && w.x);
    if (s.length < 2) return null;
    const last = s[s.length - 1];
    const at = (k) => (s.length > k ? s[s.length - 1 - k] : null);
    const g = (a, b) => (a && b && b.tot > 0 ? (a.tot / b.tot - 1) * 100 : null);
    return { week: last.x, tot: last.tot, weeks: s.length,
             wow_pct: g(last, at(1)), w4_pct: g(last, at(4)), yoy_pct: g(last, at(52)) };
  }

  // Spot vs contracted $/GPU-hr, as the % the spot tape sits above (+) or below (−)
  // the vintage contract. Positive = the installed base is underearning vs market.
  function repricingGap(spot, contract) {
    return spot > 0 && contract > 0 ? (spot / contract - 1) * 100 : null;
  }

  // Serving-cost floor in $ per million output tokens: rent per GPU-hour divided by
  // throughput in millions of output tokens per GPU-hour. The throughput assumption
  // is the caller's to state on the page.
  function serveFloorPerM(dph, mtokPerGpuHr) {
    return dph > 0 && mtokPerGpuHr > 0 ? dph / mtokPerGpuHr : null;
  }

  // Implied gross margin (%) of a $/M-token price over a $/M-token serving cost.
  function impliedMargin(pricePerM, costPerM) {
    return pricePerM > 0 && costPerM != null && costPerM >= 0
      ? (1 - costPerM / pricePerM) * 100 : null;
  }

  // Newest priced model in OpenRouter's /api/v1/models catalogue matching re –
  // same selection rule as the China page's resolveFamilies, reduced to one line.
  function newestPriced(models, re) {
    const live = (models || []).filter((m) => m && m.id && re.test(m.id)
      && !m.id.endsWith(":free") && +((m.pricing || {}).completion) > 0);
    if (!live.length) return null;
    const m = live.reduce((a, b) => ((b.created || 0) > (a.created || 0) ? b : a));
    return { id: m.id, outP: +m.pricing.completion * 1e6, inP: +m.pricing.prompt * 1e6 };
  }

  root.OMEN = {
    $, esc, safeUrl,
    outcomeYes, jsonList, isClosed, bookSpread,
    REGIME, regimeOf, REGIME_META,
    GAUGE_REFS, GAUGE_FAM_NAMES, gaugeScore, gaugeRefText, gaugeRefsProse,
    indexMath, sparkSvg, parseSnapshots, pairShareSeries,
    ocfGrowth, tokenDemand, repricingGap, serveFloorPerM, impliedMargin, newestPriced,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
