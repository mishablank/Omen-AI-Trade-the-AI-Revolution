# Backlog

## Cloudflare R2 is disabled on the account – uploads *and* deploys fail

**Status:** Open – needs the Cloudflare dashboard; no code change can fix it
**Component:** Cloudflare account, `wrangler.jsonc` (`r2_buckets` → `omen-data`), `.github/workflows/refresh.yml`, `.github/workflows/deploy.yml`
**Priority:** Critical

### Problem

Since 2026-09-11 every `refresh.yml` run fails at "Upload data to R2" with
`10042: Please enable R2 through the Cloudflare Dashboard`, and the one production deploy
since then (2026-09-20, the AA backlog commit) failed at "Deploy the Worker" with the same
cause from the other side: `R2 binding error for bucket 'omen-data': Please enable R2
through the Cloudflare Dashboard. [code: 10136]`. So the live site is frozen twice over:
the Worker cannot read fresh data out of R2, and no deploy can ship a newer bundled
fallback because the Worker's R2 binding itself is rejected. Every merge to `main` will
go red at deploy until this is fixed.

The data half is now contained in git (`fix/commit-data-when-r2-fails`): the commit step
runs when the R2 upload is the only failure, and re-seeds `market-data.json` daily
instead of weekly while R2 is down. The site itself stays frozen until R2 is back.

### Acceptance Criteria

- [ ] Re-enable R2 on the Cloudflare account (Dashboard → R2 → enable / accept terms), or
      find out why it was turned off (billing lapse? plan change?). The bucket name the
      Worker binds is `omen-data`.
- [ ] Confirm the bucket and its objects survived; if not, the next refresh re-creates
      every object, and `seed-market-data.py` already treats a missing R2 copy as
      "keep the committed seed".
- [ ] Re-run the latest failed Deploy (`gh run rerun --failed <id>`) and one manual
      `refresh.yml` dispatch; both should go green.
- [ ] Only if R2 is being abandoned on purpose: make `worker.js` tolerate a missing
      `env.DATA` binding and drop `r2_buckets` from `wrangler.jsonc` – a production
      architecture change, deliberately not made unattended.

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

**Status:** Built, waiting on the key (2026-09-26, `feat/app-charts-serpapi-fallback`) –
`omen/app-charts-serpapi.mjs` (node built-ins only) runs as its own `refresh.yml` step, gated on
`HAS_SERPAPI`, so the scraper step keeps running with no secrets in scope. Self-gating: skips when
the scraper wrote this run, skips when its own last pull is <20h old, and pulls 3 core markets
(US/GB/DE → ≈90 searches/month, quota math in the header). Same output schema; `depth: 50` records
SerpApi's chart cap. Tests: `test-app-charts.mjs` (parsing, gate, schema) and a Python test holding
all three basket copies in sync. **To go live:** add the `SERPAPI_KEY` secret. Known gap: the Python
side's apps note still says "Play top-200" when the fallback wrote the file.
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

**Status:** Done (2026-08-07) — 174 call sites rewritten to the `--bg`/`--ink` family across the
three monitor-family pages (plus `--delta-up`/`--delta-down` → `--pos`/`--neg`, the same
duplication); alias block deleted from `omen.css` (`--border` stays, it never had a twin).
Each pair was proven to resolve to the identical literal and no page overrode either name;
all eight pages render-verified in headless Chrome after the sweep.
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

**Status:** Partly done (2026-09-26, `feat/capex-ai-spend-per-fte`) – curated "AI spend per employee"
watchlist on the live tape, under Paid adoption: the three ILTB data points tagged *podcast*
(unnamed firms, not attributed to anyone), plus two disclosed company rows already cited on China
Watch (Uber's $1,500/month engineer cap, Coinbase's ≈50% cut – both CNBC, Jul 2026) and a Watch
row for Ramp. **Still open:** Ramp publishes only the adoption CSV as of 2026-09-26 (no spend-level
series), so the third criterion waits on Ramp.
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

**Status:** Partly done (2026-09-26, `feat/china-arena-boards`) — four boards (text/image-to-video,
text-to-image, image edit) fetched from the official dataset with a per-board arena.ai scrape
fallback and per-board carry-forward, summarized best-CN vs best-non-CN (a Chinese model held #1
on image-to-video), rendered as a "Media arenas" table under Leaderboard proximity. Index
treatment decided: context only, pinned by a test. **Still open:** the $/min and $/image join,
blocked on the AA key.
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
survey (see `docs/updates/UPDATES-2026-08-06-supply-side.md` for the first five).

### Acceptance Criteria

- [ ] Extend the updater's arena family: try the official `lmarena-ai/leaderboard-dataset`
      configs for text-to-video / text-to-image first (same datasets-server call as text),
      fall back to scraping the server-rendered `arena.ai/leaderboard/<category>` tables —
      the existing `arena()` parser pattern.
- [ ] Store per modality: best CN model + rank + score, Elo gap to the leader, CN count in
      the top 10. Reuse `arena_summary()` — it is already org-driven, not model-driven.
- [ ] Join $/min or $/1k-images from Artificial Analysis' media endpoints rather than
      scraping: the Data API covers the media arenas
      (`/api/v2/media/text-to-video/models`, `/api/v2/media/text-to-image/models` and the
      image-to-video / image-editing / speech siblings), so this rides the same key as the
      text pull. Label the source and keep it batch.
- [ ] Render as one "Media arenas" panel next to Leaderboard proximity, one row per
      modality; note in-panel that Elo scales are not comparable across sites or boards.
- [ ] Decide index treatment explicitly: either keep it context-only (like the supply-side
      panels) or give it a small weight with a documented reference range — do not let it
      silently ride the existing LMArena family.

## China AI Monitor — coding and agentic leaderboards

**Status:** Partly done (2026-09-26, `feat/china-arena-boards`) — WebDev (Elo; arena.ai `/leaderboard/code`
fallback) and Agent (task score, dataset only: its page has no Elo to scrape) as a second stat
row on the Leaderboard-proximity card, with the not-comparable caveat. Also fixed a latent bug
on the way: the dataset spells Z.ai `zai`, so GLM had never counted as Chinese on the text board
either. **Still open:** the AA coding/agentic index cut, blocked on the key.
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
- [ ] Answered (Sep 2026): it does. The models payload's `evaluations` object carries
      `artificial_analysis_coding_index` and `artificial_analysis_agentic_index` beside
      `artificial_analysis_intelligence_index`, plus component benchmarks
      (`terminalbench_hard`, `scicode`, `tau2_telecom`). So add the coding cut to the
      `aa_frontier` value stats from the call the updater already makes – no second
      request, no scrape. Blocked on the key below.
- [ ] Note in the caveats that agentic boards are young and their scoring (%-success, not
      Elo) is not comparable to the arena numbers beside them.

## China AI Monitor — live capex asymmetry (US vs CN platforms)

**Status:** Done, with one deviation (2026-09-26, `feat/capex-asymmetry-us-cn`) – `capex_asymmetry` in
`capex-data.json`: big-5 trailing-4Q capex (read from `market-data.json`'s XBRL fundamentals, written
earlier in the same job) vs Alibaba + Tencent + Baidu, converted at FRED's `DEXCHUS`; a three-stat row
in the China thesis section reading that feed, UBS kept as the framing citation, caveat in-panel.
**Deviation:** Alibaba could not ride EDGAR – it tags its capex line with a company extension the
`companyconcept` API does not serve (its us-gaap capex tag stops in 2020) – so it is hand-keyed in
`MANUAL["cn_capex"]` beside Tencent, from each company's results release (8 quarters, 2025Q3–2026Q2,
verified against the releases). Baidu is live but annual-only (20-F), labelled as such. Add each new
quarter as Tencent/Alibaba report (mid-Nov next).
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

**Status:** Done (2026-09-26, `feat/china-investment-gap`) — `MANUAL["investment"]` (US $285.9B vs
CN $12.4B, calendar 2025, AI Index 2026, figures re-verified against the report) with the
guidance-fund caveat (~$184B 2000–2023, Stanford SCCEI) carried in the data itself; rendered as a
three-stat "Capital input" card in the supply-side block, year + edition date in the label; April
refresh documented in the caveats footer. Next refresh: April 2027 (calendar 2026).
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

**Status:** Partly done (2026-09-26, `feat/china-safety-grades`) – `MANUAL["safety"]`: FLI AI Safety Index
Summer 2026 (Z.ai D- 0.88, Alibaba Cloud D- 0.87, DeepSeek F 0.47; anchors Anthropic C+ 2.66, OpenAI
C 2.28; plus current-harms and existential-safety domain grades – verified against FLI's page) and
Concordia AI's 2026 Q2 headline (average Risk Index YoY: cyber 4.4×, bio 6.6×, loss-of-control 2.4×).
Rendered as a compact table directly under the prediction-markets card; cadence, method churn and
no-weight caveats in-panel and in the footer. **Still open:** Concordia's per-model Risk Index values –
airiskmonitor.net refused an automated fetch (as expected), so the ~8 numbers need keying by hand into
`MANUAL["safety"]["concordia"]["per_model"]`; the page already notes they are pending.
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

## Artificial Analysis – the Data API is written but was never connected

**Status:** Open – blocked on the key and the redistribution answer; the code side is ready
(2026-09-26, `feat/aa-shared-module-token-prices`): the fetch moved to `omen/aa_data.py`, which
tries the documented `/api/v2/language/models` first and falls back to the legacy path on a 404
only, logs per-field coverage of the four fields the code reads, and records the endpoint that
answered – so the first keyed run pins the URL question in its own log.
**Component:** `omen/update-china-data.py`, `.github/workflows/refresh.yml`, repo secrets
**Priority:** High

### Problem

`artificial_analysis()` returns `None` on its first line unless `ARTIFICIAL_ANALYSIS_API_KEY`
is set, and it never has been: the repo carries exactly two secrets, `CLOUDFLARE_API_TOKEN`
and `CLOUDFLARE_ACCOUNT_ID`. The integration shipped in the 2026-07-20 update
(`docs/updates/UPDATES-2026-07-20.md` still ends with the "add it as a repo secret to go
live" instruction) and the step was wired into `refresh.yml`, but the key was never created,
so the API path has not run once. Two separate things are broken by it, and only one is
visible as a fallback:

- `china-data.json.artificial_analysis` is still the `MANUAL` literal – GLM-5.2 at 51 vs
  Claude Fable 5 at 60, `asof` 2026-07-12. The leaderboard panel's "Artificial Analysis
  index" stat therefore shows a hand-typed figure that has not moved in two months, next to
  a source note promising it is "live via its free Data API when the updater has a key".
  Technically true, and misleading in practice.
- `aa_frontier` is absent from `china-data.json` entirely. It has no `MANUAL` fallback by
  design, so the whole frontier block – the monthly CN/US index series, `gap_points`, the
  Epoch-style `lag_months`, and the near-frontier `value` price ratio – has never rendered.
  `aa_points()`, `aa_value()` and `aa_frontier()` and their unit tests in
  `test_update_china_data.py` are dead code against the live site, and the panel they feed
  (`china-ai-monitor.html:1303`) is the supply-side survey's headline gap #1.

Two facts in the code comments have also drifted. The docstring claims a free tier of
"1,000 req/day"; the published free tier is 100 requests per 24 hours as of Sep 2026 –
still ample for one daily call, but wrong as written. And `AA_URL` points at
`/api/v2/data/llms/models` while the current API reference documents `/api/v2/language/models`.
That may be an alias rather than a break – it cannot be settled without a key, because AA
checks auth before routing and returns `401 Invalid API key` for every path, real or invented.

### Acceptance Criteria

- [ ] Create an Artificial Analysis Insights Platform account, generate a key, and add
      `ARTIFICIAL_ANALYSIS_API_KEY` as a repo secret. No code change is needed to go live –
      `refresh.yml` already injects it, on the China step only.
- [ ] With the key in hand, confirm whether `AA_URL` still resolves or has moved to
      `/api/v2/language/models`, and pin whichever answers. Assert the fields the code
      actually reads (`model_creator.name`, `evaluations.artificial_analysis_intelligence_index`,
      `release_date`, `pricing.price_1m_blended_3_to_1`) rather than just a 200.
- [ ] Settle redistribution before the first public render. The free tier is documented as
      attribution-required and internal-use, and the pricing page says "For data
      redistribution or external use, contact us" – a public dashboard is arguably external
      use. The site already credits and links AA, which covers attribution but not
      redistribution. Get it in writing, or keep the panel to derived statistics (gap, lag,
      ratio) rather than republishing AA's scores as a table.
- [x] Fix the `1,000 req/day` comment; one daily run is one request, and the ceiling is 100.
      (Done: the real cadence is ~33 runs/day, one request each, and the capex updater now
      reads the China step's cached response instead of spending a second one.)
- [ ] Decide `MANUAL["artificial_analysis"]`'s fate once the feed is live. `pick_aa` keeps it
      as a last-resort fallback, but a dated 2026-07 literal silently standing in for a live
      feed is exactly the drift `test_docs_truth.py` and `test_documented_secrets.py` exist to
      catch. Either date it in the page label so staleness is visible, or drop it and let the
      row go blank.
- [ ] Verify `aa_frontier` renders end to end on a real payload – series, gap, lag and value
      ratio – not merely that the JSON key appeared.
- [ ] Note the prerequisite: `refresh.yml` has failed every run since 2026-09-11 at "Upload
      data to R2" (`10042: Please enable R2 through the Cloudflare Dashboard`), and the
      commit step used to be skipped with it, so no refreshed data landed for over two
      weeks. The commit is now decoupled from the upload (see the R2 item at the top), but
      adding the key still changes nothing on the live site until R2 is re-enabled.

## AI CapEx – token-price deflation from the AA Data API (thesis #1)

**Status:** Built, waiting on the key (2026-09-26, `feat/aa-shared-module-token-prices`) – shared
`aa_data.py` (one keyed request per run: the China step fetches and caches in the runner's temp
dir, outside the assets directory; the capex step reads the cache and never holds the key),
`token_prices` block (bands ≥60/≥50/≥40, cheapest blended $/M by month, YoY, and "tokens per
coupon $"), carry-forward and tests, a hidden-until-data "Token deflation vs fixed debt" panel on
the live tape with all three caveats, and the theses-doc contradiction fixed (row 1 marked in
flight). **Still open:** first render on a real payload once the key exists.
**Component:** `omen/update-capex-data.py`, `omen/ai-capex.html`, `omen/update-china-data.py`
**Priority:** Medium

### Problem

Row 1 of `ai-capex-theses.md` – token deflation against fixed debt, the duration-mismatch
argument – is the Kedrosky thesis with the cleanest free source ("OpenRouter API pricing
history; Artificial Analysis") and no implementation. `capex-data.json` carries `tsmc`,
`issuance`, `ramp`, `aei`, `eia`, `capex_gdp` and `agents`, and nothing at all about the
price of a unit of intelligence. The tape can show hyperscalers levering up and cannot show
the revenue line per token collapsing underneath the debt, which is the whole claim.

The machinery already exists one file over, written for a different question. `aa_points()`
in `update-china-data.py` yields `(side, month, index, blended $/M)` per model, and
`aa_value()` picks the cheapest model within 3 index points of a frontier. Cut by capability
band instead of by country, those same rows are the deflation series – no new source, no new
request.

### Acceptance Criteria

- [ ] Factor the AA pull out of `update-china-data.py` into a small shared module both
      updaters import, so one keyed request per run serves both pages. The free tier is 100
      requests/day; do not spend two where one will do, and do not duplicate the parser.
- [ ] Emit a `token_prices` block into `capex-data.json`: for each of 2–3 fixed capability
      bands (e.g. index >= 60, >= 50, >= 40), the cheapest blended $/1M tokens by month, plus
      the YoY percentage change. Reuse `aa_points()`; the band simply replaces `aa_value()`'s
      country cut.
- [ ] Carry-forward and tests like every other capex family – the value must survive a failed
      fetch the way `fetch_ramp` and `fetch_860m` do.
- [ ] Render on `ai-capex.html` against the fixed debt-service framing the thesis needs, so
      the two lines are read together rather than as another price chart.
- [ ] Caveat in-panel, honestly: AA's catalogue is current-only, so delisted models vanish
      from history and a reconstructed series is survivorship-biased toward what is still
      sold – the same caveat `aa_frontier` already carries on the China page. AA also
      re-bases its index across major versions, so a fixed band is only comparable inside the
      `AA_FRONTIER_SINCE` (2024-01) window. Blended 3:1 is a convention, not a bill.
- [ ] Blocked on the key above; the shared module is worth writing either way.
- [ ] While in the file, fix `ai-capex-theses.md`'s internal contradiction: the header says
      "Rows 1–5 are shipped", the integration notes say rows 3, 4, 5, 7 and 9. The keys in
      `capex-data.json` back the notes. Mark row 1 in flight when this lands.
