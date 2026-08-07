
                ▄▄▄▄▄▄  ▄▄   ▄▄  ▄▄▄▄▄▄  ▄▄   ▄▄
                ██  ██  ███▄███  ██▄▄▄   ███▄ ██
                ██  ██  ██ ▀ ██  ██▀▀▀   ██ ▀███
                ▀▀▀▀▀▀  ▀▀   ▀▀  ▀▀▀▀▀▀  ▀▀   ▀▀

        ┌───────────────────────────────────────────────────┐
        │   A I   C Y C L E   B O O M  ·  A N D  ·  B U S T │
        │                  T R A C K E R                    │
        └───────────────────────────────────────────────────┘

     Prediction markets, options skew, credit spreads, GPU rents and
     hyperscaler filings — folded into one 0–100 crash-pressure gauge
             and one published, deterministic verdict.

                        Not investment advice.


================================================================================
  CONTENTS
================================================================================

    1.  What this is
    2.  The one-paragraph version
    3.  The verdict rule
    4.  The crash-pressure gauge
    5.  The pages
    6.  Where the numbers come from
    7.  Repository layout
    8.  Running it locally
    9.  Tests
   10.  How it is deployed
   11.  The refresh pipeline
   12.  Configuration (all optional)
   13.  Design notes worth knowing
   14.  Known gaps
   15.  License


================================================================================
  1.  WHAT THIS IS
================================================================================

OMEN is a dashboard that tries to answer one question honestly:

        "Is the AI capex cycle priced to keep running, or priced to break?"

It does that by blending what prediction markets think will happen with what
options, credit, volatility and equity markets are actually charging for
protection — plus the one non-market anchor that matters, hyperscaler capex
against operating cash flow, straight out of SEC XBRL.

Everything is free and keyless. There is no database, no framework, no build
step and no server-side rendering. It is static HTML, a handful of stdlib-only
Python fetchers, and a ~77-line Cloudflare Worker.

The whole thing is ~11,000 lines.


================================================================================
  2.  THE ONE-PARAGRAPH VERSION
================================================================================

A GitHub Action runs every ~30 minutes. It pulls ~40 free endpoints, computes a
crash-pressure gauge and a regime server-side, writes market-data.json, appends
one row to an append-only snapshot CSV, uploads everything to an R2 bucket, and
pushes a Telegram/ntfy alert if — and only if — the regime *escalates*. A
Cloudflare Worker serves the static pages from the repo and streams the data
files live from R2, so the dashboard is always current with no redeploy. The
browser fetches Polymarket directly for live odds and falls back to a baked
snapshot when anything is unreachable.

Nothing hard-fails. Every panel degrades to its last good value.


================================================================================
  3.  THE VERDICT RULE
================================================================================

The landing page exists to produce one of five states. It is deterministic,
published, and unit-tested cell by cell — no discretion, no vibes.

    DIRECTION (Bull share of the Bull/Bear pair)
    × STRESS  (the regime, from the gauge)
    → VERDICT

                 │  CALM          ELEVATED        STRESSED
    ─────────────┼───────────────────────────────────────────────
    Bullish      │  Risk-on       Constructive    Caution
     (≥ .55)     │                · hedged
    ─────────────┼───────────────────────────────────────────────
    Mixed        │  No edge       No edge         Caution
     (.45–.55)   │
    ─────────────┼───────────────────────────────────────────────
    Bearish      │  Risk-off      Risk-off        Risk-off
     (< .45)     │
    ─────────────┴───────────────────────────────────────────────

Read the bearish row carefully: stress cannot *soften* a bearish read. If the
market has already picked the bear side, a quiet gauge does not talk it back.

    Source of truth : omen/omen-common.js  (thresholds)
                      omen/index.html      (matrix)
    Tests           : omen/test-verdict.mjs — all nine cells, both band edges


================================================================================
  4.  THE CRASH-PRESSURE GAUGE
================================================================================

Five equally-weighted families, each normalized 0–100 against a fixed
calm→stress range, then averaged:

    ┌── LEADING (priced before the fact) ──────────────────────────┐
    │                                                              │
    │   PRED    Polymarket bubble-burst odds                       │
    │   OPT     25Δ risk reversals, NVDA + SOXX (Nasdaq/OPRA)      │
    │   CREDIT  HY OAS, CCC OAS, HYG drawdown, HYG/LQD ratio       │
    │                                                              │
    ├── CONFIRMING (moves with or after prices) ───────────────────┤
    │                                                              │
    │   VOL     VIX/VIX3M term structure, VXN, SKEW, VVIX          │
    │   EQUITY  NVDA and SOXX drawdown from the running high       │
    │                                                              │
    └──────────────────────────────────────────────────────────────┘

Only the leading side can warn. That split is the point: a gauge that goes red
because equities already fell is a thermometer, not a warning.

REGIME BANDS — the single place these numbers are written down is
`OMEN.REGIME` in omen/omen-common.js. All three pages read them from there.

    STRESSED   blended gauge ≥ 55        OR  crash basket ≥ 40
               OR  crash basket ≥ 25 with a z-score ≥ 2
    ELEVATED   blended gauge ≥ 35        OR  crash basket ≥ 25
               OR  crash z-score ≥ 1.5   OR  any single market ≥ 15%
    CALM       everything else

A single market — the bubble-burst market included — can raise Elevated but can
NEVER trip red on its own. That rule exists because it used to: one distress
market at 35% would paint the whole board red while the blended gauge sat calm.

The regime chip always states *which threshold fired*, in plain English, with
the live number interpolated. No pre-baked strings, no z-scores leaking into
prose. That explainer has its own 13-scenario test suite.


================================================================================
  5.  THE PAGES
================================================================================

  index.html ................ THE VERDICT
      The landing read in one viewport. Bull/Bear pair price, the gauge, the
      regime, and the five-state verdict with its reasoning.

  polymarket-ai-index.html .. THE MONITOR  (the big one, ~2,700 lines)
      One document, five views, served at /polymarket-ai-index/<view>:
        · today               the summary read
        · markets             options skew, IV term structure, credit, breadth
        · gpu                 H100 rents implied vs realized, fundamentals
        · prediction-markets  Polymarket depth, Kalshi/Metaculus/Manifold
        · methodology         the rules, restated in situ
      LEAPS tail panel: risk-neutral P(NVDA −50% / SOXX −40% in ~1y) via N(−d2)
      from long-dated puts — a deep-market cross-check on the thin
      Polymarket bubble book.

  gauge.html ................ THE GAUGE
      Family-by-family breakdown, leading vs confirming, 90-day reconstruction
      with regime bands.

  indexes.html .............. THE INDEXES
      Bull and Bear as one two-sided market that always sums to 1. Full
      constituent tables, 7-day sparklines. Bull splits TECH vs CAP; Bear
      splits MKT vs GOV — because technology progress can survive a financial
      unwind, and a regulatory clampdown is not a crash.

  ai-capex.html ............. AI CAPEX
      Eight fundamentals theses: debt saturation, AI credit stress, equity
      raises, capex vs GDP, stranded >1 GW projects, the dark-fiber
      overcapacity analogy, FCF erosion, reflexive treasury vehicles. Plus a
      live tape (TSMC monthly revenue, EDGAR issuance velocity, Ramp AI Index).

  china-ai-monitor.html ..... CHINA SUBSTITUTION
      Demand for Chinese LLMs (DeepSeek, Qwen, GLM, Kimi, MiniMax, MiMo) as a
      leading indicator of substitution pressure on US AI equities. Router
      share, HF downloads, GitHub velocity, LMArena, app-store presence.

  influencers.html .......... KOL BOARD
      Curated editorial snapshot, or auto-scored −100…+100 with evidence via
      Grok Live Search when XAI_API_KEY is set.

  methodology.html .......... METHODOLOGY
      Index curation, the gauge, the verdict rule, and an honesty section.


================================================================================
  6.  WHERE THE NUMBERS COME FROM
================================================================================

All free. All keyless unless marked.

    PANEL                          SOURCE
    ─────────────────────────────  ─────────────────────────────────────────
    Prediction markets, orderbook  Polymarket Gamma + CLOB
    Equity / vol / credit proxies  Yahoo Finance chart API
    25Δ risk reversal, IV term     Nasdaq chains (OPRA), IV/delta computed here
    LEAPS 1y tail — BL digital     Nasdaq chains (same windows)
    HY OAS, CCC OAS, NFCI          FRED fredgraph.csv   (honest UA required)
    Hyperscaler capex / OCF        SEC XBRL companyconcept (honest UA)
    Contracted backlog / RPO       SEC XBRL instant facts
    Insider net-selling            SEC EDGAR Form 4 (open-market S/P only)
    Realized H100 spot rent        vast.ai public bundles API
    Speculator positioning         CFTC Commitments of Traders (Socrata)
    Single-name short interest     FINRA, via api.nasdaq.com
    Market caps                    Nasdaq screener endpoint
    Cross-venue                    Kalshi, Manifold  (Metaculus: free token)
    TSMC monthly revenue           TWSE OpenAPI
    Issuance velocity              SEC EDGAR full-text search
    Paid AI adoption               Ramp AI Index CSV
    Generator pipeline             EIA-860M monthly workbook
    Chinese-model demand           OpenRouter, HuggingFace, GitHub, LMArena,
                                   Vercel AI Gateway, Ollama, PyPI, Play/App
                                   Store charts

A handful of fields have no free machine-readable source and are honestly
labelled as hand-updated: Korea 20-day semiconductor exports, PJM capacity
auction clears, LBNL interconnection-queue totals, per-CUSIP TRACE spreads.


================================================================================
  7.  REPOSITORY LAYOUT
================================================================================

    omen-ai/
    ├── worker.js ..................... Cloudflare Worker: static assets +
    │                                   live R2 streaming for the data paths
    ├── wrangler.jsonc ................ Worker config, assets + R2 bindings
    ├── readme.txt .................... this file
    ├── BACKLOG.md .................... open work, with acceptance criteria
    ├── UPDATES-*.md .................. dated change notes
    │
    ├── .github/workflows/
    │   ├── refresh.yml ............... the ~30-minute data pipeline
    │   └── test.yml .................. CI gate on push + pull request
    │
    └── omen/
        │  ── pages ──
        ├── index.html                  the verdict
        ├── polymarket-ai-index.html    the monitor (5 views, 1 document)
        ├── gauge.html, indexes.html, ai-capex.html,
        ├── china-ai-monitor.html, influencers.html, methodology.html
        │
        │  ── shared front end ──
        ├── omen-common.js .............. $ · esc · safeUrl · Polymarket
        │                                 shapes · REGIME thresholds ·
        │                                 index math · sparkSvg
        ├── omen.css .................... the design tokens
        │
        │  ── fetchers (stdlib only) ──
        ├── update-market-data.py ....... the main one; gauge, regime, alerts
        ├── update-china-data.py ........ China substitution monitor
        ├── update-capex-data.py ........ AI capex live tape
        ├── update-influencers.py ....... KOL scoring (needs XAI_API_KEY)
        ├── update-app-charts.mjs ....... Play charts (the only Node dep)
        │
        │  ── tests ──
        ├── test_update_market_data.py .. parsers, gauge, retry, carry-forward
        ├── test_update_china_data.py
        ├── test_update_capex_data.py
        ├── test_regime_explainer.py .... runs the Node suites under pytest
        ├── test-omen-common.mjs ........ the shared module, incl. safeUrl XSS
        ├── test-regime-explainer.mjs ... 13 regime scenarios, prose assertions
        ├── test-pure-helpers.mjs
        ├── test-verdict.mjs ............ all nine verdict cells
        │
        │  ── data (committed; see §11) ──
        ├── market-data.json ............ full state — R2 seed, ~weekly
        ├── snapshots.csv ............... append-only history, every run
        ├── china-*.json/csv, capex-*.json/csv, app-charts.json
        └── alert-state.json ............ alert dedup


================================================================================
  8.  RUNNING IT LOCALLY
================================================================================

No dependencies for the dashboard itself. Python 3.12 stdlib and a browser.

    # 1. fetch the data and append a snapshot row
    python3 omen/update-market-data.py --snapshot

    # 2. serve over HTTP — fetch() will not read siblings over file://
    cd omen && python3 -m http.server 8844

    # 3. open
    #    http://localhost:8844/index.html
    #    http://localhost:8844/polymarket-ai-index.html

    # optional: keep refreshing while you work
    python3 omen/update-market-data.py --watch 600 --snapshot

If you *do* open the files directly off disk, the pages fall back to
market-data.js — the same payload as a <script src>, because browsers block
fetch() under file:// but not script tags.

The other fetchers:

    python3 omen/update-china-data.py         # china-data.json
    python3 omen/update-capex-data.py         # capex-data.json
    cd omen && npm ci && node update-app-charts.mjs


================================================================================
  9.  TESTS
================================================================================

    python3 -m pytest omen/

One command, both languages. 135 tests. `test_regime_explainer.py` shells out
to the Node suites, so the browser JS is covered by the same invocation as the
fetchers. There is no bundler, so the Node suites slice the functions they test
out of the HTML by comment marker — and fail loudly if a marker moves, rather
than silently testing nothing.

CI runs this on every push and pull request, plus `node --check` over the
Worker and every .mjs file (there is no linter to lean on).

    cd omen && npm test        # the Node suites alone

What is covered: FRED and Form 4 parsing, the server-side gauge and regime, the
fetch retry policy and its budget, the carry-forward policy, COT and short
interest reducers, the verdict matrix, the regime explainer's prose across 13
scenarios, and the shared module — including safeUrl's rejection of
javascript:, data:, and control-character scheme smuggling.


================================================================================
  10.  HOW IT IS DEPLOYED
================================================================================

Cloudflare Worker with static assets, plus an R2 bucket.

The reasoning: the most valuable output here is *accumulated history*, and that
should not live on a laptop.

    ┌──────────────┐   every ~30 min   ┌──────────────┐
    │ GitHub Action├──────────────────>│  R2: omen-data│
    └──────┬───────┘   fresh JSON/CSV  └───────┬───────┘
           │                                   │ live read
           │ commit history                    │
           v                                   v
    ┌──────────────┐    assets         ┌──────────────┐
    │  git repo    ├──────────────────>│   Worker     │──> browser
    └──────────────┘   at deploy       └──────────────┘

worker.js runs *first* for /market-data.json, /snapshots.csv,
/influencers.json and /capex-data.json (declared in wrangler.jsonc under
assets.run_worker_first) and streams them from R2 — so the dashboard is current
with no redeploy. On an R2 miss it falls back to the bundled copy, so the site
never hard-breaks during bootstrap.

It also routes the monitor's five views: /polymarket-ai-index/<view> serves the
same document for every allowlisted view and lets the page read
location.pathname. One fetch, instant view switching, real shareable URLs.

Production is deployed by .github/workflows/deploy.yml, from main, and only from
CI: merge to main, the suite runs, the Worker ships. Do not run `wrangler deploy`
by hand — it bundles omen/ off disk, so it ships your working tree rather than a
commit, and a stale worktree goes live exactly as it sits. omen/deploy-guard.py
is the escape hatch, and refuses unless HEAD is origin/main and the tree clean.

    One-time setup:
      npx wrangler r2 bucket create omen-data
      npx wrangler r2 object put omen-data/market-data.json \
          --file omen/market-data.json --content-type application/json --remote


================================================================================
  11.  THE REFRESH PIPELINE
================================================================================

.github/workflows/refresh.yml — every 30 min during US market hours, hourly
overnight.

    fetch ──> snapshot ──> alert ──> upload to R2 ──> commit

WHAT GETS COMMITTED, AND WHY IT DIFFERS PER FILE:

    every run   snapshots.csv, china-snapshots.csv, capex-snapshots.csv
                  append-only history that exists nowhere else
                alert-state.json
                  alert dedup; ephemeral CI would re-alert without it
                china-data.json, china-history.json, app-charts.json
                  bundled-asset-only — not in R2, so the committed copy IS
                  the copy the site serves
                influencers.json, capex-data.json
                  in R2, but ~KB, so kept as a warm fallback

    ~weekly     market-data.json
                  171 KB rewritten in full every 30 minutes, and served live
                  from R2 — committing it per run was 86% of all data churn
                  and had made bot commits 74% of repo history. It stays
                  tracked because the Worker's R2-miss fallback needs a
                  bundled copy at deploy time, so the Action re-seeds it only
                  once the committed copy is over 7 days old.

    never       market-data.js
                  hand-refreshed file:// bundle

ALERTS work with the browser closed. `--alert` computes the gauge server-side
and pushes only when the regime *escalates* — state is deduped in
alert-state.json, so you get one ping per escalation, not one per run.


================================================================================
  12.  CONFIGURATION (ALL OPTIONAL)
================================================================================

Every secret below is optional. Without it the relevant panel degrades to a
dated snapshot or hides itself — nothing breaks.

    CLOUDFLARE_API_TOKEN          R2 upload (an R2-Edit token)
    CLOUDFLARE_ACCOUNT_ID

    TELEGRAM_BOT_TOKEN            regime-escalation alerts
    TELEGRAM_CHAT_ID
    NTFY_TOPIC                    ...or ntfy.sh instead

    METACULUS_TOKEN               forecaster-crowd panel (free account)
    XAI_API_KEY                   auto-scored KOL board
    ARTIFICIAL_ANALYSIS_API_KEY   AA scores on the China monitor
    CF_RADAR_TOKEN                Cloudflare Radar panel

Secrets are scoped to the individual workflow steps that need them — the step
that runs third-party scraper code deliberately runs with none in scope.


================================================================================
  13.  DESIGN NOTES WORTH KNOWING
================================================================================

  ONE PRICE READ PER RUN
      The gauge embedded in market-data.json, the row appended to
      snapshots.csv, and the regime an alert fires on are all computed from a
      single Polymarket fetch. Three separate fetches meant three tapes and
      three answers that could disagree.

  NOTHING HARD-FAILS
      Every panel carries the previous run's value forward when its source
      fails, because the gauge reads those keys directly — a dropped key does
      not blank one panel, it removes a whole family from the mean and can
      flip the regime. Requests retry with exponential backoff (honouring
      Retry-After, failing fast on 4xx) under a whole-process sleep budget, so
      a broad outage cannot stretch a 30-minute job.

  ESCAPING IS NOT URL SAFETY
      esc() makes a string safe inside an attribute. It does nothing about the
      scheme — an escaped "javascript:…" is still a live URL. Every href built
      from remote data goes through OMEN.safeUrl, which allowlists http/https.

  THE PAGES SHARE CODE
      omen-common.js and omen.css exist because the alternative had already
      cost something: one page's esc() had quietly lost its null guard and
      threw where every other page degraded cleanly.

  SLEEVES ARE READS, NOT SUB-INDEXES
      Bear is the flat equal-weight mean of all 9 constituents — not the mean
      of its two unequal sleeves. The sleeve tags are a lens on the basket.

  THE GAUGE READS MKT, NOT THE BEAR COMPOSITE
      Regime bands are calibrated to priced *crash* risk. Reading the
      composite would let regulatory odds trip a crash regime.


================================================================================
  14.  KNOWN GAPS
================================================================================

Tracked with acceptance criteria in BACKLOG.md:

    ·  China monitor "community mentions" (w=10) is hardcoded null — Reddit
       and X have no public, key-free, CORS-accessible API for this.
    ·  Android chart presence depends on a reverse-engineered scrape that
       breaks every year or two; a SerpApi fallback is specced.

Honest about the rest, too: some fundamentals fields are hand-updated (§6),
and the capex aggregate sums whichever hyperscalers reported in a given
quarter, so a 4-filer quarter sits next to a 5-filer quarter.


================================================================================
  15.  LICENSE
================================================================================

Boost Software License 1.0. See LICENSE.


                    ─────────────────────────────────

                        Not investment advice.

           This is a measurement instrument, not a recommendation.
        Every threshold is published so you can disagree with a number
                    rather than with a black box.

                    ─────────────────────────────────
