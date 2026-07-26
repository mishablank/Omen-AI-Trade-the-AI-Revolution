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
  function sparkSvg(vals, w, h, color, fill) {
    if (!vals || vals.length < 2) return "";
    const mn = Math.min(...vals), mx = Math.max(...vals), r = (mx - mn) || 1;
    const pts = vals.map((v, i) => [i / (vals.length - 1) * w, h - 3 - (v - mn) / r * (h - 8)]);
    const line = pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
    const area = `M0,${h} L${line.replace(/ /g, " L")} L${w},${h} Z`;
    return `<svg width="100%" height="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    ${fill ? `<path d="${area}" fill="${color}" opacity=".12"/>` : ""}
    <polyline points="${line}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <circle cx="${pts[pts.length - 1][0]}" cy="${pts[pts.length - 1][1]}" r="3" fill="${color}"/></svg>`;
  }

  root.OMEN = {
    $, esc, safeUrl,
    outcomeYes, jsonList, isClosed, bookSpread,
    REGIME, regimeOf, REGIME_META,
    indexMath, sparkSvg,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
