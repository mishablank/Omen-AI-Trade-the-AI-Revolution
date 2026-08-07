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

**Status:** Done (2026-08-07) — labels composed from live data in `lineChart`/`multiPanelChart`,
the verdict tape and dial; decorative sparklines `aria-hidden`; monitor headers tabbable with
`aria-sort` and Enter/Space; the sign-not-colour rule pinned in `test-a11y.mjs` (direction was
already signed everywhere via `deltaSpan`/`sn`/`chgTxt`).
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

## China AI Monitor — media-generation arenas (video/image)

**Status:** Open
**Component:** `china-ai-monitor.html`, `update-china-data.py`
**Priority:** Medium

### Problem

The monitor is text-LLM-only, but media generation is a second substitution front and the
one where Chinese labs already hold podium positions: on Arena's text-to-video board,
Chinese models (Seedance, MiniMax, HappyHorse) hold 3 of the top 5 slots, and on Artificial
Analysis 8 of the top 10 — at roughly 1/4 to 1/2 of Veo's $/minute. Image is still US-led
(Chinese entries at #5–8). None of that reaches the page, so a Chinese video-model
breakthrough — the Kling/Seedance dynamic — would be invisible to the adoption index and
to the leaderboard-proximity card. Remaining gap #4 of 10 from the Aug-2026 peer-dashboard
survey (see `UPDATES-2026-08-06-supply-side.md` for the first five).

### Acceptance Criteria

- [ ] Extend the updater's arena family: try the official `lmarena-ai/leaderboard-dataset`
      configs for text-to-video / text-to-image first (same datasets-server call as text),
      fall back to scraping the server-rendered `arena.ai/leaderboard/<category>` tables —
      the existing `arena()` parser pattern.
- [ ] Store per modality: best CN model + rank + score, Elo gap to the leader, CN count in
      the top 10. Reuse `arena_summary()` — it is already org-driven, not model-driven.
- [ ] Optionally join $/min or $/1k-images from Artificial Analysis' server-rendered media
      leaderboards for a media price-gap stat; label the source and keep it batch.
- [ ] Render as one "Media arenas" panel next to Leaderboard proximity, one row per
      modality; note in-panel that Elo scales are not comparable across sites or boards.
- [ ] Decide index treatment explicitly: either keep it context-only (like the supply-side
      panels) or give it a small weight with a documented reference range — do not let it
      silently ride the existing LMArena family.

## China AI Monitor — coding and agentic leaderboards

**Status:** Open
**Component:** `china-ai-monitor.html`, `update-china-data.py`
**Priority:** Medium

### Problem

The leaderboard-proximity card reads the overall text arena, but the enterprise-switching
evidence in the thesis section (Coinbase → GLM/Kimi, Lindy → DeepSeek) is coding-agent
workloads. On Arena's WebDev board Chinese models sit at #2 and #4 (Kimi K3-Max, Qwen
3.8-Max) — materially stronger than their overall-text standings — and the new Agent Arena
scores behavioural task success. Overall Elo under-measures exactly the segment where the
substitution money moves first. Remaining gap #5 of 10 from the Aug-2026 survey.

### Acceptance Criteria

- [ ] Fetch the WebDev (and, when stable, Agent) boards in the updater: official dataset
      config first, `arena.ai/leaderboard/webdev` scrape fallback, same dual-source shape
      as the text family.
- [ ] Store best CN rank/score and gap-to-leader per board; surface as extra stats on the
      Leaderboard-proximity card (or a small sibling card if it crowds the statrow).
- [ ] Check whether the AA free Data API exposes the Coding Agent Index alongside the
      intelligence index; if yes, add a coding cut to the `aa_frontier` value stats — if
      not, skip rather than scrape a JS-only page.
- [ ] Note in the caveats that agentic boards are young and their scoring (%-success, not
      Elo) is not comparable to the arena numbers beside them.

## China AI Monitor — live capex asymmetry (US vs CN platforms)

**Status:** Open
**Component:** `update-capex-data.py`, `china-ai-monitor.html`, `ai-capex.html`
**Priority:** Medium

### Problem

The capex asymmetry is the monitor's stated equity exposure, but it lives as prose with
hand-typed numbers ("~$400B in 2025 ... vs ~$57B for China's major platforms (UBS)").
Meanwhile `update-capex-data.py` already pulls SEC XBRL fundamentals for the US
hyperscalers — the US half of the comparison exists as a live series on the capex tape.
The China half doesn't: Alibaba and Baidu file XBRL on EDGAR as foreign private issuers
(free, same `companyconcept` API already used), Tencent files HKEX PDFs only.
Remaining gap #7 of 10 from the Aug-2026 survey.

### Acceptance Criteria

- [ ] Extend `update-capex-data.py` with BABA and BIDU capex pulls via the existing EDGAR
      `companyconcept` path (purchases of property/equipment; 20-F/6-K facts are annual
      or semiannual — store what exists, do not interpolate).
- [ ] Add Tencent as a hand-updated `MANUAL` entry (quarterly capex from its HKEX results
      PDFs), dated, same convention as the Korea-exports/LBNL rows.
- [ ] Emit a `capex_asymmetry` block into `capex-data.json`: trailing-4-quarter US
      hyperscaler capex, CN platform capex, and the ratio.
- [ ] Replace the hand-typed numbers in the china monitor's thesis section with a small
      stat row reading from the shared `capex-data.json` feed (same cross-page pattern as
      `market-data.json`), keeping the UBS figure only as a citation for the framing.
- [ ] Caveat in-panel: CN platform disclosures lag a quarter or more and Tencent is
      hand-keyed, so the ratio is directional.

## China AI Monitor — private AI investment gap (annual context stat)

**Status:** Open
**Component:** `update-china-data.py`, `china-ai-monitor.html`
**Priority:** Low

### Problem

The capital-input gap explains *why* Chinese labs play the open-weights game the whole
monitor measures, and it appears nowhere: AI Index 2026 puts 2025 private AI investment at
US $285.9B vs China $12.4B (23x), with the standing caveat that China's state guidance
funds (~$184B deployed 2000–2023) sit outside private-investment data. The sources are
annual and public (AI Index raw-data drive; ETO's Crunchbase-derived Country Activity
Metrics on Zenodo) — this is a once-a-year hand refresh, not a feed. Remaining gap #9 of
10 from the Aug-2026 survey.

### Acceptance Criteria

- [ ] Add an `investment` entry to the updater's `MANUAL` dict: US and CN private AI
      investment (USD B), year, source string, and the guidance-fund caveat — surfaced
      as-is into `china-data.json` like the other MANUAL families.
- [ ] Render as a small context stat inside the supply-side block (statrow, no chart);
      link the AI Index and ETO CAT sources in the note.
- [ ] Document the annual refresh (each April, when the AI Index ships) in the caveats
      footer, and date the stat in its label so staleness is visible on the page.

## China AI Monitor — Chinese frontier-model safety/risk scores

**Status:** Open
**Component:** `update-china-data.py`, `china-ai-monitor.html`
**Priority:** Low

### Problem

The page already trades on regulatory tail risk — the Polymarket "US government removes
public access to a major Chinese AI model in 2026" row — but carries no data on the
safety profile that would trigger it. Concordia AI's airiskmonitor.net scores ~50 CN+US
frontier models quarterly on capability/safety/risk across cyber, bio, chem and
loss-of-control; FLI's AI Safety Index grades labs semiannually (Z.ai D-, Alibaba Cloud
D-, DeepSeek F vs Anthropic C+). A DeepSeek F-grade next to a 20% ban-market price is the
pairing this monitor exists to show. Remaining gap #10 of 10 from the Aug-2026 survey.

### Acceptance Criteria

- [ ] Treat both sources as batch, low-cadence: airiskmonitor.net bot-shields plain
      fetchers, so start as a hand-keyed `MANUAL` entry (~8 numbers per quarter: risk
      index per domain for the top CN models + a US reference model) and only attempt a
      fetcher (honest UA, their `/doc/en/report/<q>` pages) if it proves stable.
- [ ] Add FLI's per-lab letter grades for the Chinese labs + 2 US anchors, semiannual,
      with edition date.
- [ ] Render as compact rows adjacent to the prediction-markets card so the grade sits
      next to the ban-market probability it contextualizes; date both sources in the
      label.
- [ ] Caveats: quarterly/semiannual cadence, methodology churn between editions, and no
      index weight — context only.
