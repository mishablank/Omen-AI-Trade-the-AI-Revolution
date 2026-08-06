# Backlog

## China AI Monitor — Community Mentions (w=10)

**Status:** Open
**Component:** `china-ai-monitor.html`, `update-china-data.py`
**Priority:** Medium

### Problem

The "Community mentions" family in the Chinese AI Adoption Index is hardcoded to `null`:

```js
IDX.social = { w:10, val: null, detail: "Reddit/X mentions - no public API, not tracked" };
```

It is excluded from the weighted composite and displayed as an empty row with a dash. Reddit and X/Twitter have no public, key-free, CORS-accessible API for counting model mentions, so this slot was never wired to a data source — unlike OpenRouter, HuggingFace, GitHub, LMArena, and Polymarket, which are all fetched live or via the updater script.

### Acceptance Criteria

- [ ] Implement a data source for Reddit and/or X mention counts of Chinese AI models (DeepSeek, Qwen, GLM, Kimi, MiniMax, MiMo).
- [ ] If using OAuth APIs (Reddit API, X API), fetch server-side and store results in `china-data.json` via `update-china-data.py` — same pattern as LMArena/GitHub snapshots.
- [ ] Normalize the mention volume to a 0–100 score with a documented reference range.
- [ ] Assign the computed value to `IDX.social.val` in the page JS so the row renders a real score and is included in the weighted composite (weight renormalization adjusts automatically).
- [ ] Update the methodology footer text to reflect the new live source instead of "not tracked, no public API."

## China AI Monitor — SerpApi fallback for Android app charts (w=10, apps family)

**Status:** Open
**Component:** `update-app-charts.mjs`, `.github/workflows/refresh.yml`
**Priority:** Low

### Problem

The consumer-app family now pulls Android chart presence from `update-app-charts.mjs`, which uses `google-play-scraper` — a reverse-engineered scrape of Play's internal `batchexecute` endpoint. Google ships no key-free charts API, so this is the only free option, but the payload shape breaks every year or two and the whole family then degrades to iOS-only (Apple RSS) until the library is patched. iOS presence alone understates Chinese-app reach because Android is the larger install base in most non-US Western markets.

### Acceptance Criteria

- [ ] Add SerpApi's Google Play engine (`engine=google_play`, `store=apps`) as a keyed fallback for `update-app-charts.mjs`: try `google-play-scraper` first, fall back to SerpApi when it returns zero countries, gate on a `SERPAPI_KEY` secret (surface it in `refresh.yml`'s job env like `XAI_API_KEY`).
- [ ] SerpApi's free tier is ~100 searches/month; one daily 10-country pull ≈ 300/month, so either cap the fallback to the core markets (US/GB/DE/JP) or run it only when the primary scraper is down. Document the quota math in a comment.
- [ ] Keep the output schema identical (`{ hits: [{label, store:"android", country, rank, appId, title}] }`) so `android_hits()` in `update-china-data.py` needs no change.
- [ ] No behavioural change when `SERPAPI_KEY` is unset — the primary scraper path must stay the default.

## Front end — converge the two CSS token vocabularies

**Status:** Open
**Component:** `omen.css`, `polymarket-ai-index.html`, `china-ai-monitor.html`, `influencers.html`
**Priority:** Low

### Problem

The eight pages' `:root` blocks were hoisted into a single `omen.css`, but they arrived
carrying *two* names for the same palette. The landing/index/gauge/capex/methodology pages
use `--bg` / `--panel` / `--ink` / `--mut` / `--line` / `--line2`; the monitor, China and
influencer pages use `--page` / `--surface-1` / `--text-primary` / `--text-secondary` /
`--grid` / `--baseline`. Every overlapping value was verified identical before hoisting, so
this is naming duplication rather than a behavioural risk — but `omen.css` now has to
declare both sets, and a palette change means editing two aliases in lockstep.

Converging them means rewriting every `var()` call site in three large files, which is a
mechanical but wide diff with no test coverage behind it, so it was left out of the change
that created `omen.css`.

### Acceptance Criteria

- [ ] Pick the canonical set (the `--bg`/`--ink` family is used by more pages).
- [ ] Rewrite `var(--page)`, `var(--surface-1)`, `var(--text-primary)`, `var(--text-secondary)`,
      `var(--grid)`, `var(--baseline)` and `var(--muted)` call sites in the three monitor-family
      pages to the canonical names.
- [ ] Delete the alias block from `omen.css`; the file should declare each colour once.
- [ ] Verify with a before/after render diff (headless Chromium, compare `innerText`,
      `scrollHeight` and the computed `background-color`/`color` of `body`) that all eight
      pages are unchanged.

## Front end — chart accessibility

**Status:** Open
**Component:** `polymarket-ai-index.html`, `index.html`, `gauge.html`, `indexes.html`
**Priority:** Medium

### Problem

The gauges, dials, sparklines and line/area charts are raw SVG injected via `innerHTML` with
no text alternative, so a screen reader gets nothing from them. `OMEN.sparkSvg` now marks its
output `aria-hidden` (honest: it is decorative next to the number it accompanies), but the
larger charts carry real information that exists nowhere else on the page. Separately, signal
direction is encoded by colour alone (`.up`/`.down`), and the sortable table headers in the
monitor use a bare `th.onclick` with no `role`, `tabindex` or keyboard handler.

### Acceptance Criteria

- [ ] Give each information-bearing chart an `aria-label` or an adjacent visually-hidden
      summary stating the series, range and latest value.
- [ ] Pair the up/down colour with a non-colour cue (arrow or sign glyph).
- [ ] Make the sortable headers real `<button>`s, or add `role="button"`, `tabindex="0"` and
      Enter/Space handling, plus `aria-sort` reflecting the current state.

## AI CapEx – Memory price index (DRAM/HBM spot + contract, LTA coverage)

**Status:** Open
**Component:** `omen/ai-capex.html`, `omen/update-capex-data.py`
**Priority:** Medium

### Problem

Gavin Baker's ILTB episode (Aug 2026) makes the memory market – LTA game theory, soaring
DRAM/HBM spot – a core leg of the AI-cycle read, and the site's only memory signals today are
MU's equity drawdown and the hand-updated Korea 20-day export line (`MANUAL["korea"]`, still
`None`). Daily DRAM spot (DRAMeXchange/TrendForce) is paywalled, so this was never wired to a
live source alongside TSMC/vast.ai/XBRL.

### Acceptance Criteria

- [ ] Add a memory-price family to the capex live tape: DRAM spot trend, HBM contract
      direction, and Korea 20-day semiconductor exports as the keyless pulse.
- [ ] Automate what is public: Korea customs 20-day release (scrape the press-release page or
      hand-update on its ~1st/11th/21st cadence with the asof enforced), TrendForce free press
      releases for the quarterly contract-price direction.
- [ ] Document the paywall boundary in the srcline: spot levels are curated until a licensed
      feed exists; trends and YoY direction are the tracked metric.
- [ ] Wire the values through `capex-data.json` (updater + carry-forward + tests), not page JS.

## AI CapEx – AI spend per FTE / token spend as share of compensation

**Status:** Open
**Component:** `omen/ai-capex.html`
**Priority:** Low

### Problem

Baker's demand-side claim – AI-native firms spending 20–25% (up to 50%) of total compensation
on tokens – has no public dataset. Ramp's public AI Index (already on the tape) gives adoption
share, not spend-per-employee; the per-FTE figures exist only as disclosures and anecdotes.

### Acceptance Criteria

- [ ] Add a curated watchlist panel in the ai-capex.html style (like the equity-events table):
      company, disclosed AI/token spend share of comp or per-FTE spend, date, source link.
- [ ] Seed with the ILTB data points (20–25% typical, 30% one case, 50% max reported) clearly
      marked as podcast-sourced, replaceable as filings/reports name real numbers.
- [ ] Watch Ramp for a spend-level (not adoption-share) series; wire it into
      `update-capex-data.py` if one ships – that upgrade retires the curated table.

## AI CapEx – Lab economics tracker (EV/ARR for OpenAI, Anthropic, xAI)

**Status:** Open
**Component:** `omen/ai-capex.html`, `omen/polymarket-ai-index.html`
**Priority:** Medium

### Problem

The monitor's "AI valuation brackets" card prices OpenAI/Anthropic valuation odds with no
revenue anchor, so the euphoria gauge cannot say whether multiples are expanding or the
denominator is catching up. Disclosed ARR run-rates (e.g. Baker cites Grok 4.5 + Cursor at
~$10B) appear only in press reports – public, but not API-fed.

### Acceptance Criteria

- [ ] Curated table: lab, latest disclosed ARR run-rate (date + source), latest valuation
      (round or Polymarket bracket midpoint), implied EV/ARR, with the time series kept as
      rows rather than overwritten.
- [ ] Join against the existing valuation-bracket markets so the implied multiple updates
      live as the bracket odds move, even between ARR disclosures.
- [ ] Honesty note: press-reported ARR is unaudited, often annualized from a single month,
      and labs choose when to leak it – the series is directional, not accounting.
