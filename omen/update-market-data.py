#!/usr/bin/env python3
"""Fetch the non-Polymarket data feeds for the AI Crash dashboard into market-data.json.

Sources (all free / unauthenticated unless noted):
  - Equity closes (Yahoo chart): NVDA, SOXX, AI-capex basket, SPY benchmark
  - Volatility complex (Yahoo chart): ^VXN, ^VIX, ^VIX3M, ^SKEW, ^VVIX
  - Options skew + IV term structure (Nasdaq OPRA-composite chains): NVDA, SOXX
  - LEAPS-implied 1y tail probabilities (same chains, Breeden-Litzenberger): NVDA, SOXX
  - Credit proxies (Yahoo chart): HYG, LQD, JNK
  - Credit spreads (FRED, keyless CSV): HY OAS, CCC OAS, NFCI
  - Hyperscaler capex fundamentals (SEC XBRL companyconcept): MSFT, GOOGL, AMZN, META, ORCL
  - Contracted backlog / RPO (same API, instant facts): MSFT, GOOGL, ORCL, CRWV
  - Cross-venue (Kalshi public API + Manifold public API + Metaculus, token optional)
  - Insider activity (SEC EDGAR Form 4): NVDA, AVGO, ORCL, CRWV
  - Realized GPU spot rent (vast.ai public bundles API): H100 SXM $/GPU-hr
  - NVDA trailing-P/E percentile (SEC XBRL diluted EPS x Yahoo monthly closes):
    the "decade-low multiple" claim as an auditable 10-year percentile
  - Kalshi GPU compute markets (H100/H200/B200/A100): second venue on the same
    rents, settled on the Ornn index — the cross-venue basis check for vast.ai

Optional env: METACULUS_TOKEN enables the Metaculus forecaster-crowd panel
(create a free account at metaculus.com, token from the profile page).

Also:
  --snapshot   append a chain-linkable snapshot (2 Polymarket indexes + gauge) to snapshots.csv
  --alert      compute the crash-pressure gauge server-side and push a Telegram/ntfy
               notification when the regime escalates (state kept in alert-state.json)
  --watch N    refresh every N seconds

Env for --alert (all optional): TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, and/or NTFY_TOPIC.

No third-party dependencies. Run it from the folder that serves the dashboard.
"""
import urllib.request, urllib.error, urllib.parse, json, datetime, re, sys, os, time, math, gzip
import html, io, zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "market-data.json")
SNAP = os.path.join(HERE, "snapshots.csv")
BUNDLE = os.path.join(HERE, "market-data.js")
ALERT_STATE = os.path.join(HERE, "alert-state.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
SEC_UA = {"User-Agent": "Mikhail Blank blank.mikhail@gmail.com"}

CORE = ["NVDA", "SOXX", "CRWV", "ORCL"]
# breadth basket: hyperscalers, semis, networking, power, neoclouds
BASKET = ["NVDA", "MSFT", "GOOGL", "AMZN", "META", "AVGO", "MU", "ANET",
          "VST", "CEG", "NBIS", "IREN", "CRWV", "ORCL", "SMCI"]
BENCH = ["SPY"]
# D4 (handover 2026-08-13): Korea and Taiwan join the drawdown family. KOSPI is ~50%
# semis – the same AI hardware trade – and fell 43.93% in 27 days against SOXX's 28.73%
# in the July event, so it is the higher-beta read on identical risk, not a new one.
ASIA_SEMI = ["^KS11", "EWY", "TSM"]
EQUITY = sorted(set(CORE + BASKET + BENCH + ASIA_SEMI))
VOL = {"^VXN": "VXN", "^VIX": "VIX", "^VIX3M": "VIX3M", "^SKEW": "SKEW", "^VVIX": "VVIX"}
# HYG/LQD/JNK are the leveraged-credit proxies; BIZD (VanEck BDC ETF) is the
# private-credit / direct-lending channel Kedrosky flags — where pensions and
# insurers hold AI-data-center / neocloud debt that never touches the HY index.
CREDIT = ["HYG", "LQD", "JNK", "BIZD"]
# most debt-dependent AI-infra names (neoclouds + capex-heavy power/DB); their
# equity is the market's read on financing risk before it shows in credit spreads.
LEVERED_AI = ["CRWV", "ORCL", "NBIS", "IREN"]
# power/electricity: XLU proxies data-center power-demand pull (kept OUT of the
# breadth basket so it never moves that signal); ELEC_CPI is residents' bills.
POWER_PROXY = ["XLU"]
# ---- Rosenberg/Bernstein cross-check tape (handover 2026-08-12) ----
# Rate-sensitive real economy: homebuilders are the cleanest listed read on the part
# of the economy that AI capex is NOT holding up. Weakness here while the AI basket
# runs is the fragility Rosenberg points at ("without AI we'd be in recession").
REAL_ECON = ["ITB", "XHB"]
# Rotation confirmation: ACWI-ex-US. Sustained ex-US leadership over the AI basket is
# Bernstein's regime-change tell, so it is a relative-strength line, not a level.
ROTATION = ["ACWX"]
# Correlation breadth: the eleven S&P sector SPDRs, rolled against the AI basket. The
# claim under test is that only health care and staples are still uncorrelated — that
# is a count of sectors above a threshold, which needs every sector, not a sample.
# XLU is already fetched as the power proxy; the fetch list is deduped, the mapping is not.
SECTORS = {"XLK": "technology", "XLF": "financials", "XLV": "health care",
           "XLP": "staples", "XLE": "energy", "XLI": "industrials",
           "XLY": "discretionary", "XLU": "utilities", "XLB": "materials",
           "XLRE": "real estate", "XLC": "communication"}
# Gold-silver froth (macro strip, backdrop only): the ratio is the classic
# speculative-metals tell and needs no new venue — both are liquid US ETFs.
FROTH = ["GLD", "SLV"]
# ---- Berg turning-point tape (handover 2026-08-13) ----
# Tickers carrying the turn panel: OHLCV at 1y for the crash-low and gap logic, plus a
# 10y close history for the ROC percentile ranks. Korea earns its place because KOSPI is
# roughly half semis – the same AI hardware trade, and it fell 43.9% in 27 days against
# SOXX's 28.7% in the July event, so it is the higher-beta read on the identical risk.
TURN_TICKERS = ["^GSPC", "^NDX", "SOXX", "^KS11"]
# D1 divergence spread: each index against its OWN peak, side by side.
DIVERGENCE_TICKERS = ["^GSPC", "^NDX", "SOXX", "RSP", "^RUT"]
# A5 deviation-from-trend thrust: an equal-weight multi-cap composite, the free clone of
# the NDR index Berg quotes. Large + mid + small, equally weighted.
THRUST_TICKERS = ["SPY", "MDY", "IWM"]
# The turn tape needs no prune_payload entry: its bars are fetched into a local in
# build() and only conclusions plus a 90-bar display series are ever written. Publishing
# the raw input would have cost 752 KB across eight tickers against a 178 KB file.
# ASIA_SEMI is the deliberate exception – D4 puts those three in the drawdown family,
# which charts them, so they publish like any other EQUITY name.
# Fetched only to feed a computed block — nothing charts their closes, and market-data.json
# is rewritten into R2 every 30 minutes, so their series are dropped before the file is
# written (prune_payload). Publishing all of them raised the file 173 KB -> 326 KB; the
# eleven sector SPDRs alone were 45 KB of closes behind eleven published correlations.
# XLU is deliberately absent: it is also POWER_PROXY, which the power panel does chart.
TRANSIENT_EQUITY = frozenset(set(SECTORS) - set(POWER_PROXY) | set(FROTH) | set(ROTATION))
# Same idea on the FRED side: these are inputs to a derived block, and what the pages read
# is the block. HH_EQ_FIN keeps its series (the household-allocation chart runs on it) and
# IG_OAS keeps its own (the HY−IG gap is charted); the rest publish last value only.
FRED_SUMMARY_ONLY = frozenset({"RES_CONS", "INV_EQUIP", "INV_IP", "REAL_GDP", "HH_EQ_TOT",
                               "HOUST", "ALTSALES", "TRIM_PCE", "TERM_PREM",
                               "FEDFUNDS", "NROU"})
FRED = {"BAMLH0A0HYM2": "HY_OAS", "BAMLH0A3HYC": "CCC_OAS", "NFCI": "NFCI",
        "GDP": "GDP", "CUSR0000SEHF01": "ELEC_CPI",
        # claims-watch tape (singularity claims panel): core goods CPI (deflation claim),
        # unemployment + prime-age LFPR (displacement claim), realized real GDP growth SAAR
        "CUSR0000SACL1E": "CORE_GOODS_CPI", "UNRATE": "UNRATE",
        "LNS11300060": "LFPR_PRIME", "A191RL1Q225SBEA": "GDP_GROWTH",
        # ---- Rosenberg/Bernstein parameter set (handover 2026-08-12) ----
        # Credit family extension: the IG leg. HY_OAS alone is a level; HY minus IG is
        # the compensation demanded for leverage specifically, which is the thing that
        # widens first when the financing bid for AI infrastructure thins out.
        "BAMLC0A0CM": "IG_OAS",
        # Capital misallocation (Bernstein): private residential construction is the
        # denominator of the data-center/housing ratio. The data-center numerator is
        # NOT on FRED — despite the handover saying it mirrors both — so it is parsed
        # from the Census C30 workbook directly; see census_c30_series().
        "PRRESCONS": "RES_CONS",
        # Ex-AI capex residual: BEA nonresidential fixed investment in equipment and in
        # intellectual-property products, the two lines AI capex actually lands in.
        # Read off FRED rather than the BEA API so no key is needed.
        "Y033RC1Q027SBEA": "INV_EQUIP", "Y001RC1Q027SBEA": "INV_IP",
        # Real GDP level, for the GDP-ex-AI contribution arithmetic (GDP_GROWTH above
        # is the SAAR rate; this is the chained level the AI share is subtracted from).
        "GDPC1": "REAL_GDP",
        # Positioning: Fed Z.1 B.101 households — directly and indirectly held corporate
        # equities as a % of financial assets (and of total assets). This is the
        # "record household equity allocation" leg, back to 1945 so a percentile means
        # something. Note the transcript's 73% uses a narrower denominator (equities
        # over equities+bonds+cash); these two are the published Z.1 measures.
        "BOGZ1FL153064486Q": "HH_EQ_FIN", "BOGZ1FL153064476Q": "HH_EQ_TOT",
        # Real-economy check: rate-sensitive demand while AI runs.
        "HOUST": "HOUST", "ALTSALES": "ALTSALES",
        # Macro context strip (backdrop only, never a gauge input): Dallas Fed
        # trimmed-mean PCE, the ACM 10y fitted term premium (this IS the NY Fed
        # ACM series, published on FRED, so the .xls download the handover lists is
        # not needed), and the policy rate the Taylor-rule gap is measured against.
        "PCETRIM12M159SFRBDAL": "TRIM_PCE", "THREEFYTP10": "TERM_PREM",
        "FEDFUNDS": "FEDFUNDS", "NROU": "NROU"}
SKEW_SYMS = ["NVDA", "SOXX"]
# LEAPS tail: drawdown levels per symbol; the last one is the bubble-market trigger level
TAIL_LEVELS = {"NVDA": [-30, -50], "SOXX": [-25, -40]}
TAIL_RATE = 0.04          # risk-free rate for discounting / implied-vol inversion
TAIL_MIN_DTE = 250        # only expiries at least this far out qualify as "1y"
TAIL_MIN_SPREAD = 5.0     # absolute floor for the put-spread half-width; see digital_put
TAIL_SPREAD_FRAC = 0.04   # ...and the same as a fraction of spot, whichever is larger
# Expiry windows (days from today) requested per symbol: one near-dated for the 25d skew
# and the IV term ratio, one ~1y out for the LEAPS tail. Two small calls beat pulling
# every expiry, and Nasdaq's endpoint takes a date range directly.
SKEW_WINDOW = (20, 130)
TAIL_WINDOW = (TAIL_MIN_DTE, 430)
INSIDER_TICKERS = ["NVDA", "AVGO", "ORCL", "CRWV"]
# hyperscaler / AI-capex fundamentals via SEC XBRL (calendar-quarter aggregation)
FUND_CIKS = {"MSFT": "0000789019", "GOOGL": "0001652044", "AMZN": "0001018724",
             "META": "0001326801", "ORCL": "0001341439"}
FUND_TAGS = {"capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
                       "PaymentsToAcquireProductiveAssets"],       # AMZN's tag since 2017
             "ocf": ["NetCashProvidedByUsedInOperatingActivities",
                     "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
             # D&A cash-flow addback; firms use different tags, sec_concept merges them.
             # Depreciation lagging capex = cost recognition trailing the cash spend,
             # the accounting tell of the fast-obsolescing GPU buildout.
             "dep": ["DepreciationDepletionAndAmortization",
                     "DepreciationAmortizationAndAccretionNet",
                     "DepreciationAmortizationAndImpairment",
                     "DepreciationAndAmortization", "Depreciation"]}
# Remaining performance obligation: contracted revenue not yet recognised — the
# backlog the capex is being built against. Only the filers below report it
# non-dimensionally via the XBRL API: AMZN stopped after 2020-06-30 and META has
# never tagged it, so both are absent by design, not by oversight. CRWV is here
# though it is not a capex filer — neocloud backlog concentration is the point.
# Financing-channel proceeds for the same filers plus CoreWeave — theses i and iii of
# the AI CapEx page in audited numbers instead of press tallies. sec_concept() merges
# candidate tags in order and the LAST one wins a contested quarter, so the more
# specific tag goes last (ORCL files both, and its Senior line is the benchmark-bond
# figure; the generic tag on that filer stops at 2011 plus two near-zero stubs).
ISSUANCE_CIKS = {"MSFT": "0000789019", "GOOGL": "0001652044", "AMZN": "0001018724",
                 "META": "0001326801", "ORCL": "0001341439", "CRWV": "0001769628"}
ISSUANCE_TAGS = {"debt": ["ProceedsFromNotesPayable",
                          "ProceedsFromIssuanceOfUnsecuredDebt",
                          "ProceedsFromIssuanceOfLongTermDebt",
                          "ProceedsFromIssuanceOfSeniorLongTermDebt"],
                 "equity": ["ProceedsFromIssuanceOrSaleOfEquity",
                            "ProceedsFromIssuanceOfCommonStock"]}
RPO_TAG = "RevenueRemainingPerformanceObligation"
RPO_CIKS = {"MSFT": "0000789019", "GOOGL": "0001652044",
            "ORCL": "0001341439", "CRWV": "0001769628"}
METACULUS_TERMS = ["AI bubble", "AI winter", "artificial general intelligence"]
KALSHI_SERIES = {
    "KXACQUIREMISTRAL": "AI lab acquisition (Mistral)",
    "KXRECSSNBER": "US recession (macro backdrop)",
    "KXBIGTECHLAYOFF": "Big tech layoffs",
    "KXOAIANTH": "OpenAI vs Anthropic",
    "KXUSOPENAIANTH": "US stake in OpenAI & Anthropic",
}
MANIFOLD_TERMS = ["AI bubble", "NVIDIA crash", "AI winter"]
# Kalshi GPU compute markets (launched 2026-07-14): the second venue pricing the
# same GPU rents Polymarket brackets do, settled on the Ornn index rather than
# vast.ai's ask tape — so the two venues disagree partly on basis, not just view.
#   *W   weekly  — directional "price to beat"; its strike IS the Ornn reference
#                  print at open_time (not live), which is how we read Ornn for free.
#   *MON monthly — terminal ladder on the month-end value; the only real forward point.
#   *MAX yearly  — resolves "above $X BY Dec 31" (running max, upward-biased).
#                  Deliberately NOT fetched: it is not comparable to a terminal forward.
KALSHI_GPU = {
    "H100": {"label": "H100 SXM", "weekly": "KXH100W", "monthly": "KXH100MON"},
    "H200": {"label": "H200", "weekly": "KXH200W", "monthly": "KXH200MON"},
    "B200": {"label": "B200", "weekly": "KXB200W", "monthly": "KXB200MON"},
    "A100": {"label": "A100 SXM4", "weekly": "KXA100W", "monthly": "KXA100MON"},
}
# a ladder strike wider than this is a quote, not a price
KALSHI_MAX_SPREAD = 0.15
# CFTC Commitments of Traders (legacy futures-only, weekly: Tuesday positions,
# Friday release). Non-commercial = large speculators; their net (long minus
# short) as a share of open interest is the positioning/crowding read the rest of
# the site lacks — it prices leverage, not just level or vol. VIX net-short is the
# crowded short-vol trade whose forced unwind is the mechanical accelerant that
# turns a vol spike into a crash. Filtered by the stable contract-market code, not
# the display name (which the CFTC has renamed before).
COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
COT_WEEKS = 156          # ~3y window for the positioning percentile / z-score
COT_CONTRACTS = {
    "ndx": {"code": "209742", "label": "E-mini Nasdaq-100", "venue": "CME"},
    "spx": {"code": "13874A", "label": "E-mini S&P 500", "venue": "CME"},
    "vix": {"code": "1170E1", "label": "VIX futures", "venue": "CFE"},
}
# FINRA consolidated short interest (bi-monthly settlement: mid-month and month-end),
# the single-name companion to the index-level COT above. FINRA's own distribution
# (cdn.finra.org) and Nasdaq Trader are both WAF-blocked to a stdlib client, but
# api.nasdaq.com — the host the caps card already uses — redistributes the same
# FINRA-collected figures for Nasdaq-listed names (NYSE-listed ORCL/VST are not
# covered here). Focus is the levered AI-infra / neocloud names, where a rising short
# and a lengthening days-to-cover is the financing-risk bet expressed in cash equity.
SHORT_INTEREST = ["NVDA", "CRWV", "NBIS", "IREN", "SMCI"]
NASDAQ_SI_URL = "https://api.nasdaq.com/api/quote/{sym}/short-interest?assetClass=stocks"
# Bear (OMN-X) is the short side: the union of two sleeves, priced as one flat
# equal-weight basket of 9. The sleeves are series-identical to the indexes Bear
# replaced – MKT to the old AI-Crash, GOV to the old AI-Regulation – which is what
# lets the crash-pressure gauge and the lead-lag study keep reading MKT unchanged.
BEAR_SLEEVES = {
    "mkt": ["691340", "676827", "676846"],
    "gov": ["2787889", "2787891", "2787890", "2698575", "676842", "2839991"],
}
POLY_IDS = {
    "bull": ["676829", "653788", "676837", "1087074", "656312", "656313", "2413330", "2109881", "676804", "2487206", "2255930"],
    "bear": BEAR_SLEEVES["mkt"] + BEAR_SLEEVES["gov"],
}
BUBBLE_ID = "691340"


def index_level(price, side):
    """100 x the equal-weight mean of the constituents we have a live price for."""
    vals = [price[i] for i in POLY_IDS[side] if i in price]
    return sum(vals) / len(vals) * 100 if vals else None


def sleeve_level(price, sleeve):
    vals = [price[i] for i in BEAR_SLEEVES[sleeve] if i in price]
    return sum(vals) / len(vals) * 100 if vals else None


# ---------- fetching ----------
# Transient-failure policy for every outbound request. A single dropped fetch does not
# just blank one panel: compute_gauge reads the equity/vol/skew/credit/fred keys directly,
# so a lost request can remove a whole family from the blended score and flip the regime an
# alert fires on. Retry what is worth retrying — network blips, 429s, 5xx — and fail fast on
# a 4xx, which is a real answer that will not change on a second ask.
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
RETRIES = 2               # total attempts = RETRIES + 1
RETRY_BACKOFF = 1.5       # seconds before the first retry, doubled each attempt
RETRY_AFTER_CAP = 30.0    # never honour a Retry-After longer than this
# Whole-process ceiling on time spent sleeping between retries. Retrying is the right
# answer for the one flaky endpoint this is built for, but the run touches ~40 URLs: if
# the network is down wholesale, per-request retries would add minutes of pure sleep to a
# job that runs every 30 minutes. Once the budget is gone the fetcher degrades to
# single-attempt behaviour and the carry-forward policy in build() takes over — which is
# the correct response to a broad outage anyway.
RETRY_BUDGET = 60.0
_retry_spent = 0.0


def retry_budget_left():
    return max(0.0, RETRY_BUDGET - _retry_spent)


def reset_retry_budget():
    """--watch runs many refreshes in one process; each gets its own budget."""
    global _retry_spent
    _retry_spent = 0.0


def retryable(e):
    """Is this exception worth another attempt? HTTPError first — it subclasses URLError."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code in RETRY_STATUS
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError))


def retry_wait(e, attempt):
    """Exponential backoff, widened to the server's Retry-After when it sends one."""
    wait = RETRY_BACKOFF * (2 ** attempt)
    if isinstance(e, urllib.error.HTTPError):
        try:
            wait = max(wait, min(RETRY_AFTER_CAP, float(e.headers.get("Retry-After") or 0)))
        except (TypeError, ValueError):
            pass
    return wait


def get_bytes(url, timeout=25, headers=None, data=None, retries=RETRIES):
    """Fetch a URL as bytes, retrying transient failures and decompressing gzip.

    Several hosts (api.nasdaq.com in particular) gzip by default, so the decode is done
    here once rather than in each caller.
    """
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=headers or UA,
                                     data=data.encode() if isinstance(data, str) else data)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as e:
            global _retry_spent
            if attempt == retries or not retryable(e):
                raise
            wait = min(retry_wait(e, attempt), retry_budget_left())
            if wait <= 0:          # budget spent — treat as non-retryable from here on
                raise
            _retry_spent += wait
            print(f"  retry {attempt + 1}/{retries} in {wait:.1f}s: {url.split('?')[0]} ({e})")
            time.sleep(wait)


def get(url, timeout=25, headers=None, data=None, retries=RETRIES):
    return get_bytes(url, timeout=timeout, headers=headers, data=data, retries=retries).decode()


def nasdaq_get(url, timeout=30):
    """GET api.nasdaq.com JSON. The endpoint gzips by default; get_bytes handles that."""
    return json.loads(get_bytes(url, timeout=timeout,
                                headers={**UA, "Accept": "application/json",
                                         "Accept-Encoding": "gzip"}))


def nasdaq_caps(symbols):
    """Live market caps for the stack-comparison card, one keyless request.

    Nasdaq's screener endpoint returns every US-listed common stock (NYSE +
    Nasdaq, incl. foreign private issuers like IREN/NBIS that SEC XBRL covers
    only annually) with marketCap and last sale. Yahoo's quote endpoint would
    be the obvious source but is crumb-gated; this one is not.
    """
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&download=true"
    rows = nasdaq_get(url, timeout=40)["data"]["rows"]
    want = set(symbols)
    out = {}
    for row in rows:
        sym = row.get("symbol")
        if sym not in want:
            continue
        try:
            cap = float(row["marketCap"].replace(",", ""))
            px = float(row["lastsale"].replace("$", "").replace(",", ""))
        except (KeyError, ValueError, AttributeError):
            continue
        if cap > 0:
            out[sym] = {"cap": cap, "px": px}
    return out


def yahoo_series(sym, rng="6mo"):
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"))
    res = j["chart"]["result"][0]
    ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
    # Yahoo's timestamps are epoch seconds; read them as UTC explicitly. utcfromtimestamp()
    # is deprecated in 3.12 (the CI interpreter) and returns a naive datetime that claims
    # nothing about its zone. strftime output is unchanged.
    return [{"d": datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d"),
             "c": round(c, 2)}
            for t, c in zip(ts, cl) if c is not None]


def yahoo_bars(sym, rng="1y"):
    """Full OHLCV bars – the gap rules, intraday-low tests and volume flags need the
    extremes that yahoo_series() throws away.

    Deliberately a second function rather than a widened yahoo_series(): that shape is
    read by data["equity"], data["credit"] and data["vol"][*]["series"], by both client
    pages and by a large slice of the existing suite, and none of them want OHLCV. A bar
    missing any leg is skipped whole – a bar with a close but no high cannot be gapped
    against."""
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"))
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if o is None or h is None or l is None or c is None:
            continue
        out.append({"d": datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d"),
                    "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2),
                    "v": q["volume"][i] or 0})
    return out


def yahoo_monthly(sym, rng="10y"):
    """Monthly closes as [(YYYY-MM, close)] – the long-horizon leg of the P/E percentile.
    Yahoo appends a same-month row for the latest trading day next to the partial month;
    the dict dedupe keeps the newest print per month."""
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1mo"))
    res = j["chart"]["result"][0]
    ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
    months = {datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m"): round(c, 2)
              for t, c in zip(ts, cl) if c is not None}
    return sorted(months.items())


# ---------- NVDA trailing-P/E percentile ----------
# Baker's "lowest multiple in a decade" claim, rebuilt from primary sources. Trailing
# (not forward) on purpose – consensus forward EPS has no free public API, and a trailing
# series is auditable end to end. The EPS proxy is TTM net income over TODAY's diluted
# share count, not as-reported EPS: XBRL EPS facts are never split-restated while Yahoo
# closes are split-adjusted, so raw EPS vs adjusted price breaks across NVDA's 2021 and
# 2024 splits (and its EPS frames stop printing in 2020 anyway). Net income is
# split-invariant, and a fixed share count keeps the series consistent with adjusted
# prices – at the cost of ignoring buyback/dilution drift, which the srcline owns.
NVDA_CIK = "0001045810"


def ni_ttm_series(quarters):
    """sec_concept() quarters ({'YYYYQn': net_income}) -> [(YYYY-MM, ttm)] ascending,
    dated to the calendar quarter's end month. A gap in the quarter history breaks the
    4-quarter window rather than summing across it."""
    def qnum(q):
        y, n = q.split("Q")
        return int(y) * 4 + int(n) - 1
    qs = sorted(quarters or {})
    out = []
    for i in range(3, len(qs)):
        w = qs[i - 3:i + 1]
        if qnum(w[-1]) - qnum(w[0]) == 3:
            y, n = w[-1].split("Q")
            out.append((f"{y}-{int(n) * 3:02d}", sum(quarters[q] for q in w)))
    return out


def latest_share_count(entries):
    """Newest diluted weighted-average share count from a companyconcept 'shares' unit
    list – the fixed denominator of the EPS proxy."""
    best = None
    for e in entries or []:
        if e.get("val") and e.get("end") and (best is None or e["end"] > best[0]):
            best = (e["end"], e["val"])
    return best[1] if best else None


def pe_series(monthly_close, ttm_eps):
    """Trailing P/E per month: each close over the newest TTM EPS known by then.
    Months before the first TTM window, and months where TTM EPS <= 0, are skipped."""
    out = []
    for ym, c in monthly_close or []:
        eps = None
        for end, v in ttm_eps or []:
            if end[:7] <= ym:
                eps = v
            else:
                break
        if eps and eps > 0 and c:
            out.append([ym, round(c / eps, 1)])
    return out


def percentile_of_last(vals, min_n=12):
    """Share of the series at or below the latest value, 0-100. None until the series
    is a year long – a percentile of six points is noise wearing a suit."""
    if not vals or len(vals) < min_n:
        return None
    cur = vals[-1]
    return round(100.0 * sum(1 for v in vals if v <= cur) / len(vals), 1)


def nvda_valuation():
    ttm_ni = ni_ttm_series(sec_concept(NVDA_CIK, ["NetIncomeLoss"]))
    j = json.loads(get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{NVDA_CIK}"
                       "/us-gaap/WeightedAverageNumberOfDilutedSharesOutstanding.json",
                       headers=SEC_UA))
    shares = latest_share_count((j.get("units") or {}).get("shares"))
    if not ttm_ni or not shares:
        return None
    ttm_eps = [(ym, ni / shares) for ym, ni in ttm_ni]
    series = pe_series(yahoo_monthly("NVDA"), ttm_eps)
    if not series:
        return None
    vals = [p for _, p in series]
    return {"sym": "NVDA", "pe_ttm": vals[-1], "asof": series[-1][0],
            "pct_10y": percentile_of_last(vals),
            "lo_10y": min(vals), "hi_10y": max(vals),
            "eps_ttm": round(ttm_eps[-1][1], 2), "eps_asof": ttm_eps[-1][0],
            "shares_b": round(shares / 1e9, 3),
            "n_months": len(vals), "series": series[-121:]}


# ---------- FRED (keyless CSV endpoint) ----------
def parse_fred_csv(text, keep=140):
    """fredgraph.csv -> [{'d': iso date, 'c': float}], skipping missing ('.') observations."""
    out = []
    for line in text.strip().split("\n")[1:]:
        parts = line.split(",")
        if len(parts) != 2 or parts[1] in (".", ""):
            continue
        try:
            out.append({"d": parts[0], "c": float(parts[1])})
        except ValueError:
            continue
    return out[-keep:]


def fred_series(series_id):
    # FRED tarpits browser-spoofing UAs on this endpoint; an honest UA responds instantly
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    return parse_fred_csv(get(url, headers={"User-Agent": "ai-crash-monitor/1.0 (blank.mikhail@gmail.com)"}))


# ---------- Nasdaq: OPRA-composite option chains (keyless) ----------
# Replaces Cboe's cdn.cboe.com delayed_quotes JSON. That endpoint carries an explicit
# notice forbidding automated download and threatening to block the IP of anyone doing
# it, which is exactly what this cron was doing every 30 minutes. Nasdaq's quote API is
# the same OPRA composite tape - its own filter list labels excode "oprac" as
# "Composite" - and returns identical bid/ask/open-interest for the same contracts
# (verified on the 2027-06-17 NVDA puts: $100 strike 1.68/1.88 OI 18,730 on both).
#
# What Nasdaq does not return is implied vol or greeks, so both are computed below.
# That is an improvement rather than a cost: the old code fed Cboe's `iv` (which Cboe
# derives off the session close) and Cboe's `current_price` (an intraday quote, 198.98
# against a 200.75 close) into the same formula. Inverting 2,416 contracts showed the
# published IVs reproduce to 0.26 vol points off the close and only 1.34 off
# current_price. Everything here is now priced off one spot.

NASDAQ_ASSETCLASS = {"SOXX": "etf"}       # everything else is "stocks"
NASDAQ_CHAIN = ("https://api.nasdaq.com/api/quote/{sym}/option-chain?assetclass={ac}"
                "&limit=1000&fromdate={frm}&todate={to}&excode=oprac&callput=&money=all&type=all")


def _num(x):
    """Nasdaq renders absent values as '--' or ''; everything is a string."""
    if x in (None, "", "--"):
        return None
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def nasdaq_options(sym, days_from, days_to):
    """OPRA-composite chain rows for expiries in [today+days_from, today+days_to].

    Returns (spot, rows) where each row is one strike carrying both sides:
    {exp, dte, strike, c_bid, c_ask, p_bid, p_ask, c_oi, p_oi}.

    Nasdaq groups the table by expiry: a header row carries `expirygroup` and the
    strike rows that follow carry an empty one, so the current group is tracked while
    walking the table in order.
    """
    today = datetime.date.today()
    url = NASDAQ_CHAIN.format(sym=sym, ac=NASDAQ_ASSETCLASS.get(sym, "stocks"),
                              frm=(today + datetime.timedelta(days=days_from)).isoformat(),
                              to=(today + datetime.timedelta(days=days_to)).isoformat())
    j = nasdaq_get(url)
    if (j.get("status") or {}).get("rCode") != 200:
        raise RuntimeError(f"nasdaq option-chain {sym}: {(j.get('status') or {}).get('bCodeMessage')}")
    d = j["data"] or {}

    # "LAST TRADE: $200.75 (AS OF JUL 30, 2026)" - the only spot the endpoint gives.
    spot = None
    m = re.search(r"\$\s*([\d,]+\.?\d*)", d.get("lastTrade") or "")
    if m:
        spot = _num(m.group(1))

    rows, group = [], None
    for r in (d.get("table") or {}).get("rows") or []:
        if r.get("expirygroup"):
            group = r["expirygroup"]
            continue
        if not r.get("strike") or not group:
            continue
        try:
            # noqa DTZ007: this is a calendar expiry ("June 17, 2027"), not an instant —
            # it is reduced to a date on the same line and never compared across zones.
            exp = datetime.datetime.strptime(group, "%B %d, %Y").date()  # noqa: DTZ007
        except ValueError:
            continue
        strike = _num(r.get("strike"))
        if not strike:
            continue
        rows.append({"exp": exp, "dte": (exp - today).days, "strike": strike,
                     "c_bid": _num(r.get("c_Bid")), "c_ask": _num(r.get("c_Ask")),
                     "p_bid": _num(r.get("p_Bid")), "p_ask": _num(r.get("p_Ask")),
                     "c_oi": _num(r.get("c_Openinterest")), "p_oi": _num(r.get("p_Openinterest"))})
    return spot, rows


# ---------- Black-Scholes: implied vol and delta, computed here rather than vendored ----------
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(spot, strike, iv, t, typ, r=TAIL_RATE):
    if not (spot and strike and iv and iv > 0 and t > 0):
        return None
    d1 = (math.log(spot / strike) + (r + iv * iv / 2) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    if typ == "C":
        return spot * norm_cdf(d1) - strike * math.exp(-r * t) * norm_cdf(d2)
    return strike * math.exp(-r * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)


def implied_vol(price, spot, strike, t, typ, r=TAIL_RATE):
    """Invert Black-Scholes by bisection. None when the quote is below intrinsic or
    outside the bracket - a wide deep-OTM quote is often both."""
    if price is None or price <= 0 or not (spot and strike and t > 0):
        return None
    intrinsic = max(0.0, (spot - strike) if typ == "C" else (strike - spot)) * math.exp(-r * t)
    if price < intrinsic - 1e-6:
        return None
    lo, hi = 1e-4, 5.0
    if (bs_price(spot, strike, hi, t, typ, r) or 0) < price:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if (bs_price(spot, strike, mid, t, typ, r) or 0) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def bs_delta(spot, strike, iv, t, typ, r=TAIL_RATE):
    if not (spot and strike and iv and iv > 0 and t > 0):
        return None
    d1 = (math.log(spot / strike) + (r + iv * iv / 2) * t) / (iv * math.sqrt(t))
    return norm_cdf(d1) if typ == "C" else norm_cdf(d1) - 1.0


def _mid(row, typ):
    b, a = (row["c_bid"], row["c_ask"]) if typ == "C" else (row["p_bid"], row["p_ask"])
    if b is None or a is None or a <= 0:
        return None
    return (b + a) / 2


def _quotes(rows, dte, typ, spot):
    """[(strike, iv, delta)] for one expiry and side, priced off the bid-ask midpoint."""
    t = dte / 365.0
    out = []
    for r in rows:
        if r["dte"] != dte:
            continue
        px = _mid(r, typ)
        iv = implied_vol(px, spot, r["strike"], t, typ)
        if iv is None:
            continue
        dl = bs_delta(spot, r["strike"], iv, t, typ)
        if dl is None:
            continue
        out.append((r["strike"], iv, dl))
    return out


def iv_at(quotes, target):
    """IV interpolated to |delta| == target along one expiry's smile."""
    pts = sorted((abs(dl), iv) for _, iv, dl in quotes)
    for i in range(len(pts) - 1):
        (d0, v0), (d1, v1) = pts[i], pts[i + 1]
        if d0 <= target <= d1 and d1 != d0:
            return v0 + (v1 - v0) * (target - d0) / (d1 - d0)
    return None


def skew_and_term(sym, spot, rows):
    """25-delta risk reversal on the front expiry, plus the front/back ATM IV ratio."""
    today = datetime.date.today().isoformat()
    dtes = sorted(set(r["dte"] for r in rows if r["dte"] >= 25))
    if not dtes or not spot:
        return None, None
    front = dtes[0]
    fp, fc = _quotes(rows, front, "P", spot), _quotes(rows, front, "C", spot)
    p25, c25, atm_f = iv_at(fp, 0.25), iv_at(fc, 0.25), iv_at(fp, 0.50)
    skew = {"spot": spot, "dte": front,
            "put25": round(p25, 4) if p25 else None,
            "call25": round(c25, 4) if c25 else None,
            "atm": round(atm_f, 4) if atm_f else None,
            "rr": round(p25 - c25, 4) if (p25 and c25) else None,
            "date": today}
    term = None
    backs = [d for d in dtes if d >= 80]
    if backs and atm_f:
        back = backs[0]
        atm_b = iv_at(_quotes(rows, back, "P", spot), 0.50)
        if atm_b:
            term = {"front_dte": front, "back_dte": back,
                    "iv_front": round(atm_f, 4), "iv_back": round(atm_b, 4),
                    "ratio": round(atm_f / atm_b, 4), "date": today}
    return skew, term


# ---------- LEAPS-implied tail probabilities (Breeden-Litzenberger) ----------
def digital_put(puts_by_strike, strike, dte, spot=None, min_h=None, r=TAIL_RATE):
    """Risk-neutral P(S_T < K) as a put-spread digital: e^{rT} * dPut/dK.

    The old code used N(-d2) with the single strike's own implied vol. That ignores the
    slope of the volatility smile, and the identity it omits is
        Q(S_T <= K) = N(-d2) + e^{rT} * vega * dSigma/dK
    With equity downside skew dSigma/dK is negative, so N(-d2) runs *high* - measured at
    10.1% against ~7% for the 2027-06-17 NVDA $100 put, and ~2.1-2.4x too high in the
    deep tail of the Dec-2026 chain. A centred difference over listed strikes is
    model-free and prices the smile in automatically.

    The half-width is deliberately not the adjacent strike: ~47% of $1-wide butterflies
    on this chain violate convexity, which yields negative densities. It also has to
    scale with the underlying, not be a flat dollar amount. SOXX trades near $505 with
    $5 strikes, and a $5 floor there gave P(-25%) = 17.6% against P(-40%) = 16.6% - a
    CDF running backwards, because a $10 window on a $505 name is pure quote noise (its
    319d put mids are not even monotone: 270 -> 12.95 but 275 -> 12.85). At 4% of spot
    both names are stable across a 2.5%-12.5% sweep: SOXX 32-34% / 18.5-21%, NVDA
    21% / 6-7%.
    """
    if min_h is None:
        min_h = max(TAIL_MIN_SPREAD, TAIL_SPREAD_FRAC * (spot or 0))
    ks = sorted(puts_by_strike)
    lo = [k for k in ks if k <= strike - min_h]
    hi = [k for k in ks if k >= strike + min_h]
    if not lo or not hi:
        return None
    k_lo, k_hi = lo[-1], hi[0]
    p_lo, p_hi = puts_by_strike[k_lo], puts_by_strike[k_hi]
    if p_lo is None or p_hi is None or k_hi <= k_lo:
        return None
    p = math.exp(r * dte / 365.0) * (p_hi - p_lo) / (k_hi - k_lo)
    return min(1.0, max(0.0, p))


def options_tail(sym, spot, rows, prev):
    """1y-ish LEAPS-implied probability of finishing below each drawdown level."""
    if not spot:
        return None
    dtes = sorted(set(r["dte"] for r in rows if r["dte"] >= TAIL_MIN_DTE))
    if not dtes:
        return None
    dte = min(dtes, key=lambda d: abs(d - 365))
    puts = {r["strike"]: _mid(r, "P") for r in rows if r["dte"] == dte and _mid(r, "P") is not None}
    if len(puts) < 3:
        return None
    today = datetime.date.today().isoformat()
    t = dte / 365.0
    levels = []
    for pct in TAIL_LEVELS.get(sym, [-30, -50]):
        target = spot * (1 + pct / 100.0)
        listed = sorted(puts, key=lambda k: abs(k - target))
        best = listed[0] if listed else None
        if best is None or abs(best - target) > 0.12 * target:
            levels.append({"pct": pct, "strike": None, "iv": None, "p": None})
            continue
        p = digital_put(puts, best, dte, spot)
        iv = implied_vol(puts[best], spot, best, t, "P")
        levels.append({"pct": pct, "strike": best,
                       "iv": round(iv, 4) if iv is not None else None,
                       "p": round(p, 4) if p is not None else None})
    trig = levels[-1]["p"] if levels else None
    hist = [h for h in ((prev or {}).get("history") or []) if h["date"] != today]
    if trig is not None:
        hist.append({"date": today, "p_trig": trig})
    return {"date": today, "dte": dte, "spot": spot, "levels": levels,
            "trigger_pct": TAIL_LEVELS.get(sym, [-30, -50])[-1], "history": hist[-365:]}


# ---------- SEC XBRL fundamentals (hyperscaler capex vs operating cash flow) ----------
def quarterlize(entries):
    """XBRL cash-flow entries are cumulative from fiscal-year start (Q1, 6mo, 9mo, FY).
    Return {calendar 'YYYYQn' of the period END: single-quarter value} by differencing
    successive cumulatives within each fiscal-year group."""
    ded = {}
    for e in entries:
        if e.get("start") and e.get("end") and e.get("val") is not None:
            ded[(e["start"], e["end"])] = e["val"]     # later filings overwrite earlier
    groups = {}
    for (start, end), val in ded.items():
        groups.setdefault(start, []).append((end, val))
    out = {}
    for start, evs in groups.items():
        evs.sort()
        d0 = datetime.date.fromisoformat(start)
        prev_end, prev_val = None, 0.0
        for end, val in evs:
            d1 = datetime.date.fromisoformat(end)
            span = (d1 - (datetime.date.fromisoformat(prev_end) if prev_end else d0)).days
            if 75 <= span <= 105:                      # a clean single quarter
                q = f"{d1.year}Q{(d1.month - 1) // 3 + 1}"
                out[q] = val - prev_val
            prev_end, prev_val = end, val
    return out


def instantize(entries):
    """Instant (point-in-time) XBRL facts -> {calendar 'YYYYQn' of the instant: value}.

    RPO is a *balance*, not a flow, so it must never go through quarterlize()'s
    cumulative differencing — that would subtract one quarter's backlog from the
    next and report growth as if it were the level. Instant facts carry an `end`
    and no `start`; anything with a `start` is a duration fact and is skipped.
    Restatements of the same instant resolve to the latest-filed value."""
    best = {}
    for e in entries:
        if e.get("start") or e.get("end") is None or e.get("val") is None:
            continue
        try:
            d = datetime.date.fromisoformat(e["end"])
        except ValueError:
            continue
        q = f"{d.year}Q{(d.month - 1) // 3 + 1}"
        filed = e.get("filed") or ""
        if q not in best or filed >= best[q][0]:
            best[q] = (filed, e["val"])
    return {q: v for q, (_, v) in best.items()}


def sec_instant(cik, tags):
    """instantize() counterpart to sec_concept, for point-in-time concepts."""
    out = {}
    for tag in tags:
        try:
            j = json.loads(get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json",
                               headers=SEC_UA))
            entries = j.get("units", {}).get("USD", [])
            if entries:
                out.update(instantize(entries))
        except Exception:
            continue
    return out


def backlog():
    """Remaining performance obligation (contracted, not-yet-recognised revenue) for
    the filers that disclose it. RPO is the bull case in one number: it is the demand
    the capex is being built against. Capex accelerating while RPO flattens is the
    thesis breaking; the panel exists to catch that divergence early.

    Reported per firm, never summed into an aligned series — fiscal calendars differ
    (ORCL's quarters end Feb/May/Aug/Nov), so a combined per-quarter total would be
    lumpy fiction. The headline is an explicit sum of each firm's latest report."""
    per, names = {}, []
    for sym, cik in RPO_CIKS.items():
        vals = sec_instant(cik, [RPO_TAG])
        time.sleep(0.15)
        if not vals:
            continue
        quarters = sorted(vals)
        last = quarters[-1]
        yr, qn = int(last[:4]), last[-1]
        prior = f"{yr - 1}Q{qn}"
        base = vals.get(prior)
        per[sym] = {
            "series": [[q, round(vals[q] / 1e9, 2)] for q in quarters[-12:]],
            "latest_q": last,
            "latest_b": round(vals[last] / 1e9, 2),
            "yoy_pct": round((vals[last] / base - 1) * 100, 1) if base else None,
        }
        names.append(sym)
        print(f"backlog {sym}: {len(quarters)} quarters, latest {last} "
              f"${per[sym]['latest_b']:.1f}B")
    if not per:
        return None
    return {"names": names, "per": per,
            "total_latest_b": round(sum(p["latest_b"] for p in per.values()), 2),
            "asof": datetime.date.today().isoformat()}


def sec_concept(cik, tags):
    """Merge quarterly values across candidate tags (companies switch tags over time,
    e.g. AMZN moved capex to PaymentsToAcquireProductiveAssets in 2017)."""
    out = {}
    for tag in tags:
        try:
            j = json.loads(get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json",
                               headers=SEC_UA))
            entries = j.get("units", {}).get("USD", [])
            if entries:
                out.update(quarterlize(entries))
        except Exception:
            continue
    return out


def fundamentals():
    """Aggregate quarterly capex and operating cash flow across the AI-capex filers.
    Capex/OCF is the classic capex-bubble fundamental (dot-com telecoms ran >100%)."""
    per = {}
    for sym, cik in FUND_CIKS.items():
        capex = sec_concept(cik, FUND_TAGS["capex"])
        ocf = sec_concept(cik, FUND_TAGS["ocf"])
        dep = sec_concept(cik, FUND_TAGS["dep"])
        if capex:
            per[sym] = {"capex": capex, "ocf": ocf, "dep": dep}
            print(f"fundamentals {sym}: {len(capex)} quarters (dep {len(dep)})")
        time.sleep(0.15)
    if not per:
        return None
    allq = sorted(set(q for v in per.values() for q in v["capex"]))[-10:]
    quarters, capex, ocf, dep, count = [], [], [], [], []
    for q in allq:
        syms = [s for s in per if q in per[s]["capex"]]
        if len(syms) < len(per) - 1:     # allow one laggard (off-cycle fiscal years)
            continue
        quarters.append(q)
        capex.append(round(sum(per[s]["capex"][q] for s in syms) / 1e9, 2))
        o = [per[s]["ocf"].get(q) for s in syms if per[s]["ocf"].get(q) is not None]
        ocf.append(round(sum(o) / 1e9, 2) if len(o) == len(syms) else None)
        # depreciation aggregated over the same firms present for capex this quarter;
        # None unless every one of them reported a D&A line (so dep/capex is comparable)
        d = [per[s]["dep"].get(q) for s in syms if per[s]["dep"].get(q) is not None]
        dep.append(round(sum(d) / 1e9, 2) if len(d) == len(syms) else None)
        count.append(len(syms))
    if not quarters:
        return None
    return {"names": list(per.keys()), "quarters": quarters, "capex_b": capex,
            "ocf_b": ocf, "dep_b": dep, "n_firms": count,
            "per_filer": filer_ttm(per),
            "asof": datetime.date.today().isoformat()}


TTM_QUARTERS = 4


def filer_ttm(per, n=TTM_QUARTERS):
    """Per-filer trailing-{n}-quarter capex, OCF, capex/OCF and free cash flow.

    Each filer's window is its own last n quarters, never a window shared across
    filers: ORCL's fiscal quarters end Feb/May/Aug/Nov and META reports a quarter
    behind the rest, so one aligned window would compare different 12-month periods
    and present it as a like-for-like ranking. The window is returned per filer so
    the page can label what it is showing.

    Only quarters carrying *both* capex and OCF count. Taking a capex quarter whose
    OCF is missing would silently understate that filer's cash generation and push
    capex/OCF up — the exact direction the page's thesis is arguing, so it has to be
    the case that cannot happen by accident."""
    out = {}
    for sym, v in per.items():
        both = sorted(set(v["capex"]) & set(v.get("ocf") or {}))
        if len(both) < n:
            continue
        window = both[-n:]
        capex = sum(v["capex"][q] for q in window) / 1e9
        ocf = sum(v["ocf"][q] for q in window) / 1e9
        out[sym] = {"quarters": window,
                    "capex_ttm_b": round(capex, 1),
                    "ocf_ttm_b": round(ocf, 1),
                    "capex_over_ocf": round(capex / ocf, 2) if ocf else None,
                    "fcf_ttm_b": round(ocf - capex, 1)}
    if not out:
        return None
    capex_t = sum(v["capex_ttm_b"] for v in out.values())
    ocf_t = sum(v["ocf_ttm_b"] for v in out.values())
    return {"per": out,
            "totals": {"capex_ttm_b": round(capex_t, 1),
                       "ocf_ttm_b": round(ocf_t, 1),
                       "fcf_ttm_b": round(ocf_t - capex_t, 1),
                       "n_fcf_negative": sum(1 for v in out.values() if v["fcf_ttm_b"] < 0),
                       "n_filers": len(out)}}


FULL_YEAR_DAYS = 330       # a cumulative window this long is a year for these purposes
MAX_PERIOD_DAYS = 400      # anything longer is multi-year, not a period figure


def latest_period_fact(entries):
    """Most recent duration fact of at most a year, latest restatement wins.

    The fallback for filers that never tag a clean quarter. Multi-year spans are
    excluded: some filers carry a since-inception cumulative under the same concept,
    and counting it as a period figure would report years of history as this year's
    raise."""
    ded = {}
    for e in entries:
        if not e.get("start") or not e.get("end") or e.get("val") is None:
            continue
        try:
            days = (datetime.date.fromisoformat(e["end"])
                    - datetime.date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if not 0 < days <= MAX_PERIOD_DAYS:
            continue
        key = (e["start"], e["end"])
        if key not in ded or (e.get("filed") or "") >= ded[key][0]:
            ded[key] = (e.get("filed") or "", e["val"], days)
    if not ded:
        return None
    (start, end), (_filed, val, days) = max(ded.items(), key=lambda kv: (kv[0][1], kv[1][2]))
    return {"val": val, "start": start, "end": end, "days": days}


def quarter_window(end_q, n):
    """The n calendar quarters ending at end_q, e.g. ('2026Q2', 4) -> 2025Q3..2026Q2."""
    year, qn = int(end_q[:4]), int(end_q[-1])
    out = []
    for back in range(n - 1, -1, -1):
        i = (year * 4 + qn - 1) - back
        out.append(f"{i // 4}Q{i % 4 + 1}")
    return out


FALLBACK_MAX_STALE_Q = 5   # a cumulative fact older than this is history, not a raise


def issuance_ttm(per, n=TTM_QUARTERS, asof_q=None):
    """Debt and equity proceeds per filer, from XBRL cash flows.

    The window is a CALENDAR one — the n quarters ending at the most recent quarter in
    the data — not "the last n quarters this filer happened to tag". These concepts are
    tagged sparsely, only in periods with an issuance, so summing the last four tagged
    quarters produced windows like META's 2023Q4–2025Q4: four real numbers spanning two
    years, added together and labelled a trailing twelve months.

    A filer that tagged nothing inside the window falls back to its latest cumulative
    fact, if that fact is recent — Alphabet tags common-stock proceeds only as a
    fiscal-year-to-date cumulative, and quarterising alone drops the one number thesis
    iii exists to show. Stale facts are discarded rather than presented as current.

    Totals sum full-year windows only. A six-month figure added to twelve-month figures
    is not a TTM total, so partial filers are named separately instead.

    A channel with nothing to report stays None rather than 0.0 — "Alphabet raised no
    secondary equity for a decade" and "Alphabet does not tag the concept" are
    different claims, and only the first is evidence."""
    seen = sorted({q for chans in per.values() for c in chans.values()
                   for q in (c.get("quarters") or {})})
    if asof_q is None:
        ends = [c["fact"]["end"] for chans in per.values() for c in chans.values()
                if c.get("fact")]
        if seen:
            asof_q = seen[-1]
        elif ends:
            d = max(ends)
            asof_q = f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"
        else:
            return None
    window = quarter_window(asof_q, n)
    oldest_ok = quarter_window(asof_q, FALLBACK_MAX_STALE_Q)[0]
    out = {}
    for sym, chans in per.items():
        row = {}
        for chan in ("debt", "equity"):
            c = chans.get(chan) or {}
            qs = c.get("quarters") or {}
            inside = [q for q in window if q in qs]
            fact = c.get("fact")
            if fact and f"{fact['end'][:4]}Q{(int(fact['end'][5:7]) - 1) // 3 + 1}" < oldest_ok:
                fact = None
            if inside:
                row[f"{chan}_ttm_b"] = round(sum(qs[q] for q in inside) / 1e9, 1)
                row[f"{chan}_window"] = f"{window[0]}–{window[-1]}"
                row[f"{chan}_full_year"] = True
            elif fact:
                row[f"{chan}_ttm_b"] = round(fact["val"] / 1e9, 1)
                row[f"{chan}_window"] = f"{fact['start']}→{fact['end']}"
                row[f"{chan}_full_year"] = fact["days"] >= FULL_YEAR_DAYS
            else:
                row[f"{chan}_ttm_b"] = None
                row[f"{chan}_window"] = None
                row[f"{chan}_full_year"] = False
        if row["debt_ttm_b"] is not None or row["equity_ttm_b"] is not None:
            out[sym] = row
    if not out:
        return None
    totals = {}
    for chan in ("debt", "equity"):
        full = [v[f"{chan}_ttm_b"] for v in out.values()
                if v[f"{chan}_ttm_b"] is not None and v[f"{chan}_full_year"]]
        totals[f"{chan}_ttm_b"] = round(sum(full), 1) if full else None
        totals[f"{chan}_partial"] = [s for s, v in out.items()
                                     if v[f"{chan}_ttm_b"] is not None
                                     and not v[f"{chan}_full_year"]]
    return {"names": list(out), "per": out, "totals": totals}


def sec_channel(cik, tags):
    """Quarterised series plus the raw cumulative fallback for one concept family."""
    quarters, entries = {}, []
    for tag in tags:
        try:
            j = json.loads(get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json",
                               headers=SEC_UA))
            rows = j.get("units", {}).get("USD", [])
            if rows:
                quarters.update(quarterlize(rows))
                entries += rows
        except Exception:
            continue
    return {"quarters": quarters, "fact": latest_period_fact(entries)}


def issuance():
    """Debt and equity proceeds per AI-capex filer (theses i and iii).

    Deliberately one-sided: the page's "hyperscalers passed the banks" comparison is
    NOT computed here. JPM and WFC tag no debt-issuance concept the XBRL API exposes,
    so a big-6 bank total would silently omit two of six and flatter the very claim it
    is meant to test. The bank figure stays curated and labelled as such."""
    per = {}
    for sym, cik in ISSUANCE_CIKS.items():
        chans = {chan: sec_channel(cik, tags) for chan, tags in ISSUANCE_TAGS.items()}
        if any(c["quarters"] or c["fact"] for c in chans.values()):
            per[sym] = chans
            print(f"issuance {sym}: debt {len(chans['debt']['quarters'])}q "
                  f"equity {len(chans['equity']['quarters'])}q")
        time.sleep(0.15)
    out = issuance_ttm(per)
    if out:
        out["asof"] = datetime.date.today().isoformat()
    return out


def quarter_of(iso_date):
    """Map a FRED quarterly observation date (quarter START, e.g. 2025-04-01)
    to a calendar quarter label matching the fundamentals panel ('2025Q2')."""
    d = datetime.date.fromisoformat(iso_date)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def macro_capex_gdp(fund, gdp_series):
    """Combined AI-capex as a share of the economy and of GDP growth (Kedrosky's
    scale argument). fund['capex_b'] is single-quarter capex ($B); FRED GDP is a
    seasonally-adjusted ANNUAL rate, so capex is annualized (x4) before the ratio."""
    if not fund or not fund.get("quarters") or not gdp_series:
        return None
    gdp = {quarter_of(p["d"]): p["c"] for p in gdp_series if p.get("c")}
    quarters, capex_ann, gdp_b, pct = [], [], [], []
    for q, cq in zip(fund["quarters"], fund["capex_b"]):
        if q not in gdp:
            continue
        ann = round(cq * 4, 2)
        quarters.append(q)
        capex_ann.append(ann)
        gdp_b.append(gdp[q])
        pct.append(round(ann / gdp[q] * 100, 3))
    if not quarters:
        return None
    growth = [None]
    for i in range(1, len(quarters)):
        dg = gdp_b[i] - gdp_b[i - 1]
        dc = capex_ann[i] - capex_ann[i - 1]
        growth.append(round(dc / dg * 100, 1) if dg > 0 else None)
    return {"quarters": quarters, "capex_ann_b": capex_ann, "gdp_b": gdp_b,
            "pct_gdp": pct, "growth_share": growth,
            "asof": datetime.date.today().isoformat()}


# ---------- Metaculus (optional token; forecaster crowd, no capital at risk) ----------
def metaculus():
    tok = os.environ.get("METACULUS_TOKEN")
    if not tok:
        return {"enabled": False, "note": "Set METACULUS_TOKEN (free account) to enable the forecaster-crowd panel.", "questions": []}
    seen, out = set(), []
    for term in METACULUS_TERMS:
        try:
            j = json.loads(get("https://www.metaculus.com/api/posts/?"
                               + urllib.parse.urlencode({"search": term, "limit": 6,
                                                         "statuses": "open", "forecast_type": "binary"}),
                               headers={"User-Agent": "omen-ai/1.0", "Authorization": f"Token {tok}"}))
        except Exception as e:
            print(f"metaculus '{term}': FAIL {e}")
            continue
        for post in j.get("results", []):
            pid = post.get("id")
            if pid in seen:
                continue
            q = post.get("question") or {}
            prob = None
            try:
                agg = (q.get("aggregations") or {}).get("recency_weighted") or {}
                latest = agg.get("latest") or {}
                centers = latest.get("centers") or []
                prob = centers[0] if centers else latest.get("means", [None])[0]
            except Exception:
                prob = None
            if prob is None:
                prob = q.get("community_prediction") if isinstance(q.get("community_prediction"), (int, float)) else None
            n = post.get("nr_forecasters") or q.get("nr_forecasters")
            if prob is None:
                continue
            seen.add(pid)
            out.append({"theme": term, "title": post.get("title") or q.get("title"),
                        "url": f"https://www.metaculus.com/questions/{pid}/",
                        "prob": round(float(prob), 3), "forecasters": n})
    out.sort(key=lambda x: -(x["forecasters"] or 0))
    return {"enabled": True, "questions": out[:8]}


# ---------- Kalshi ----------
KALSHI_B = "https://api.elections.kalshi.com/trade-api/v2"


def _fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def kalshi_mid(m):
    """(mid, spread) in probability from a Kalshi market, or (None, None).

    Kalshi's quote fields are *_dollars and already denominated in dollars
    (0.23 = 23c), not cents. A book quoted at the bounds (bid 0 / ask 1) is
    empty, not a coin flip, so it yields no price.
    """
    b, a = _fnum(m.get("yes_bid_dollars")), _fnum(m.get("yes_ask_dollars"))
    if b is None or a is None or b <= 0.0 or a >= 1.0 or a < b:
        return None, None
    return (b + a) / 2, a - b


def kalshi_price(m):
    """Mid where the book is two-sided, else the last print. Display only."""
    mid, _ = kalshi_mid(m)
    if mid is not None:
        return mid
    last = _fnum(m.get("last_price_dollars"))
    return last if last else None


def kalshi_ladder(markets, max_spread=KALSHI_MAX_SPREAD):
    """Strike ladder as a survival curve P(value > strike), cleaned.

    Drops one-sided and wide books, then enforces monotonicity: survival cannot
    increase with strike, so a higher print is a stale/thin quote, not news.
    """
    rows = []
    for m in markets:
        k = _fnum(m.get("floor_strike"))
        mid, spread = kalshi_mid(m)
        if k is None or mid is None or spread > max_spread:
            continue
        rows.append({"k": k, "p": mid, "spread": round(spread, 4)})
    rows.sort(key=lambda r: r["k"])
    last = 1.0
    for r in rows:
        r["p"] = round(min(r["p"], last), 4)
        last = r["p"]
    return rows


def implied_median(rows):
    """Strike where the survival curve crosses 50%, linearly interpolated.

    None when the crossing lies outside the quoted strikes — the median is then
    simply unknown, and inventing one from the edge of the ladder is the exact
    artifact this guards against.
    """
    for i in range(len(rows) - 1):
        k1, p1 = rows[i]["k"], rows[i]["p"]
        k2, p2 = rows[i + 1]["k"], rows[i + 1]["p"]
        if p1 >= 0.5 >= p2 and p1 != p2:
            return k1 + (p1 - 0.5) * (k2 - k1) / (p1 - p2)
    return None


def kalshi_markets(series_ticker):
    j = json.loads(get(KALSHI_B + f"/markets?series_ticker={series_ticker}&status=open&limit=200",
                       timeout=20))
    return j.get("markets") or []


def kalshi_gpu():
    """GPU compute prices from Kalshi, the second venue on the same underlying.

    Returns per-chip: the Ornn reference print (weekly strike), the month-end
    implied median where the ladder can carry one, and the ladder itself.
    """
    out = {"source": "Kalshi public API (settles on Ornn index)", "chips": []}
    for chip, cfg in KALSHI_GPU.items():
        row = {"chip": chip, "label": cfg["label"], "ref": None, "ref_date": None,
               "implied": None, "strikes": 0, "expiry": None, "url": None, "note": None}
        try:
            wk = kalshi_markets(cfg["weekly"])
        except Exception:
            wk = []
        # the weekly directional strike is set at the Ornn print when the market
        # opens, so it dates to open_time — it is a reference, never a live spot.
        for m in wk:
            k = _fnum(m.get("floor_strike"))
            if k is None:
                continue
            row["ref"] = k
            row["ref_date"] = (m.get("open_time") or "")[:10]
            row["ref_above"] = kalshi_price(m)
            row["url"] = f"https://kalshi.com/markets/{cfg['weekly'].lower()}"
            break
        try:
            mo = kalshi_markets(cfg["monthly"])
        except Exception:
            mo = []
        if mo:
            row["expiry"] = (mo[0].get("close_time") or "")[:10]
            lad = kalshi_ladder(mo)
            row["strikes"] = len(lad)
            row["implied"] = implied_median(lad)
            if row["implied"] is None:
                row["note"] = ("book too thin to imply a month-end median"
                               if len(lad) < 3 else "median sits outside the quoted strikes")
        out["chips"].append(row)
    return out


def kalshi():
    out = {"authed": False, "note": "", "markets": []}
    for st, theme in KALSHI_SERIES.items():
        try:
            j = json.loads(get(KALSHI_B + f"/events?with_nested_markets=true&series_ticker={st}",
                               timeout=20))
        except Exception:
            continue
        for e in j.get("events", []):
            title = e.get("title", "")
            for m in e.get("markets", [])[:1]:
                out["markets"].append({
                    "theme": theme, "ticker": m.get("ticker"), "title": title,
                    "subtitle": m.get("yes_sub_title") or m.get("subtitle") or "",
                    "price": kalshi_price(m),
                    "volume": _fnum(m.get("volume_fp")),
                    "url": f"https://kalshi.com/markets/{st.lower()}",
                })
            break
    if any(x["price"] is not None for x in out["markets"]):
        out["authed"] = True
    else:
        out["note"] = "No live quotes on the tracked Kalshi series right now."
    return out


# ---------- Manifold ----------
def manifold():
    seen, out = set(), []
    for term in MANIFOLD_TERMS:
        try:
            j = json.loads(get("https://api.manifold.markets/v0/search-markets?"
                               + urllib.parse.urlencode({"term": term, "limit": 8, "sort": "liquidity"})))
        except Exception:
            continue
        for m in j:
            if (m.get("isResolved") or m.get("outcomeType") != "BINARY"
                    or m.get("token") != "MANA" or m["id"] in seen):
                continue
            if (m.get("uniqueBettorCount") or 0) < 15:
                continue
            seen.add(m["id"])
            out.append({"theme": term, "title": m["question"], "url": m["url"],
                        "price": round(m["probability"], 3),
                        "bettors": m.get("uniqueBettorCount"),
                        "closeTime": m.get("closeTime")})
    out.sort(key=lambda x: -(x["bettors"] or 0))
    return out[:8]


# ---------- SEC EDGAR Form 4 insider activity ----------
def parse_form4_xml(xml_text):
    """Return (sells_usd, buys_usd) for open-market S/P transactions in one Form 4."""
    sells = buys = 0.0
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return 0.0, 0.0
    for tx in root.iter("nonDerivativeTransaction"):
        code = tx.findtext("./transactionCoding/transactionCode")
        if code not in ("S", "P"):
            continue
        sh = tx.findtext("./transactionAmounts/transactionShares/value")
        px = tx.findtext("./transactionAmounts/transactionPricePerShare/value")
        try:
            usd = float(sh) * float(px)
        except (TypeError, ValueError):
            continue
        if code == "S":
            sells += usd
        else:
            buys += usd
    return sells, buys


def edgar_insiders(days=90, per_ticker=15):
    try:
        tickers = json.loads(get("https://www.sec.gov/files/company_tickers.json", headers=SEC_UA))
    except Exception as e:
        print("edgar tickers: FAIL", e)
        return {}
    cik = {v["ticker"]: f"{v['cik_str']:010d}" for v in tickers.values()}
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    out = {}
    for sym in INSIDER_TICKERS:
        if sym not in cik:
            continue
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik[sym]}.json", headers=SEC_UA))
            r = sub["filings"]["recent"]
            accs = [(r["accessionNumber"][i], r["filingDate"][i])
                    for i, f in enumerate(r["form"]) if f == "4" and r["filingDate"][i] >= cutoff][:per_ticker]
            sells = buys = 0.0
            n = 0
            for acc, _date in accs:
                acc_nodash = acc.replace("-", "")
                base = f"https://www.sec.gov/Archives/edgar/data/{int(cik[sym])}/{acc_nodash}"
                try:
                    idx = json.loads(get(f"{base}/index.json", headers=SEC_UA, timeout=15))
                    xml_name = next((it["name"] for it in idx["directory"]["item"]
                                     if it["name"].endswith(".xml") and not it["name"].startswith("primary_doc")), None) \
                        or next((it["name"] for it in idx["directory"]["item"] if it["name"].endswith(".xml")), None)
                    if not xml_name:
                        continue
                    s, b = parse_form4_xml(get(f"{base}/{xml_name}", headers=SEC_UA, timeout=15))
                    sells += s; buys += b; n += 1
                except Exception:
                    continue
                time.sleep(0.15)  # stay well under SEC's 10 req/s
            out[sym] = {"window_days": days, "n_filings": len(accs), "n_parsed": n,
                        "sells_usd": round(sells), "buys_usd": round(buys),
                        "net_usd": round(buys - sells)}
            print(f"insiders {sym}: {len(accs)} filings, net ${out[sym]['net_usd']:,}")
        except Exception as e:
            print(f"insiders {sym}: FAIL {e}")
    return out


# ---------- vast.ai realized H100 spot rent ----------
def gpu_spot(prev):
    q = json.dumps({"gpu_name": {"eq": "H100 SXM"}, "rentable": {"eq": True},
                    "type": "ask", "limit": 200, "order": [["dph_total", "asc"]]})
    j = json.loads(get("https://console.vast.ai/api/v0/bundles", data=q,
                       headers={**UA, "Content-Type": "application/json"}))
    per_gpu = sorted(o["dph_total"] / o["num_gpus"] for o in j.get("offers", [])
                     if o.get("num_gpus") and o.get("dph_total"))
    if not per_gpu:
        return None
    n = len(per_gpu)
    med = per_gpu[n // 2] if n % 2 else (per_gpu[n // 2 - 1] + per_gpu[n // 2]) / 2
    today = datetime.date.today().isoformat()
    hist = [h for h in (prev or {}).get("history", []) if h["date"] != today]
    hist.append({"date": today, "median": round(med, 3), "p10": round(per_gpu[n // 10], 3)})
    return {"source": "vast.ai H100 SXM asks", "date": today, "n_offers": n,
            "median_dph": round(med, 3), "min_dph": round(per_gpu[0], 3),
            "p10_dph": round(per_gpu[n // 10], 3), "history": hist[-365:]}


# ---------- server-side gauge (mirrors the dashboard; pred family = bubble only) ----------
# The calm→stress range every component is normalized against. This is a mirror of the
# `server: true` rows of GAUGE_REFS in omen/omen-common.js, which the two browser
# implementations (the monitor's live gauge and its 90-day reconstruction) and the
# published reference-range prose all read. test_gauge_refs.py parses that file and fails
# if a number here disagrees, or if either side gains or loses a component — so the ranges
# can be edited in one place and the copy is checked, never trusted.
GAUGE_REFS = {
    "pred_bubble": (0, 40),
    "opt_nvda_rr": (1, 10),
    "opt_soxx_rr": (4, 15),
    "vol_term": (0.82, 1.05),
    "vol_vxn": (18, 40),
    "vol_skew": (115, 160),
    "vol_vvix": (90, 130),
    "credit_hyg_dd": (0, 8),
    "credit_hyig_dd": (0, 6),
    "credit_hy_oas": (2.5, 5),
    "credit_ccc_oas": (8.5, 14),
    "equity_nvda_dd": (0, 50),
    "equity_soxx_dd": (0, 40),
    # ---- structural fragility (Rosenberg/Bernstein) — a SECOND composite, not the gauge ----
    # These mirror the `frag: true` rows of GAUGE_REFS in omen-common.js. They are scored
    # by compute_fragility() and published under data["fragility"]; compute_gauge() does
    # not read them, so the headline crash-pressure score and every snapshot ever taken of
    # it stay comparable. See the note on the JS table for why they are kept apart.
    "mis_dc_housing": (0.03, 0.12),
    "mis_ex_ai_capex": (-8, 4),
    "mis_gdp_ex_ai": (-3, 0),
    "pos_hh_equity": (50, 100),
    "pos_margin_yoy": (0, 30),
    "pos_fund_cash": (-5, -1.5),
    "pos_fms_gap": (0, 13),
    "pos_cot_ndx": (50, 100),
    "val_cape_sigma": (1, 3),
    "val_corr_breadth": (20, 90),
    "val_spec_blur": (5, 30),
    "cred_gap_z": (-1, 2),
}
# The rows above that belong to the fragility composite rather than the crash gauge, named
# rather than derived from the key prefix: "credit_hy_oas" and "cred_gap_z" differ by two
# characters, and a prefix rule that silently reclassified one of them would move the
# headline gauge without changing a single number. test_gauge_refs.py pins both sides.
FRAG_REFS = frozenset({
    "mis_dc_housing", "mis_ex_ai_capex", "mis_gdp_ex_ai",
    "pos_hh_equity", "pos_margin_yoy", "pos_fund_cash", "pos_fms_gap", "pos_cot_ndx",
    "val_cape_sigma", "val_corr_breadth", "val_spec_blur",
    "cred_gap_z",
})


def sc(x, ref):
    """Normalize x onto 0-100 against the named GAUGE_REFS range."""
    lo, hi = GAUGE_REFS[ref]
    if x is None:
        return None
    return max(0.0, min(100.0, (x - lo) / (hi - lo) * 100))


def drawdown(series):
    if not series:
        return None
    hi = max(p["c"] for p in series)
    return (series[-1]["c"] / hi - 1) * 100


def mean_or_none(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def poly_prices():
    allids = [i for v in POLY_IDS.values() for i in v]
    qs = "&".join("id=" + i for i in allids)
    arr = json.loads(get(f"https://gamma-api.polymarket.com/markets?{qs}&limit={len(allids)}"))
    price = {}
    for m in arr:
        if m.get("closed"):
            continue
        price[str(m["id"])] = float(json.loads(m.get("outcomePrices") or '["0"]')[0])
    return price


def compute_gauge(data, price):
    bubble = price.get(BUBBLE_ID)
    nrr = (data.get("skew", {}).get("NVDA") or {}).get("rr")
    srr = (data.get("skew", {}).get("SOXX") or {}).get("rr")
    fam = {
        "pred": mean_or_none([sc(bubble * 100 if bubble is not None else None, "pred_bubble")]),
        "opt": mean_or_none([sc(nrr * 100 if nrr is not None else None, "opt_nvda_rr"),
                             sc(srr * 100 if srr is not None else None, "opt_soxx_rr")]),
    }
    V = data.get("vol", {})
    ts = (V["VIX"]["last"] / V["VIX3M"]["last"]) if V.get("VIX") and V.get("VIX3M") else None
    fam["vol"] = mean_or_none([sc(ts, "vol_term"),
                               sc((V.get("VXN") or {}).get("last"), "vol_vxn"),
                               sc((V.get("SKEW") or {}).get("last"), "vol_skew"),
                               sc((V.get("VVIX") or {}).get("last"), "vol_vvix")])
    C, F = data.get("credit", {}), data.get("fred", {})
    hyig = None
    if C.get("HYG") and C.get("LQD"):
        # Join on the trading date, not on array position. Both series are carried forward
        # independently when a fetch fails, so one can be a session (or a whole run) behind
        # the other; zip() then paired Monday's HYG against Friday's LQD and read the step
        # as a move in the HY/IG ratio. Extra dates on either side are dropped, not guessed.
        lqd = {q["d"]: q["c"] for q in C["LQD"]}
        r = [p["c"] / lqd[p["d"]] for p in C["HYG"] if p["d"] in lqd and lqd[p["d"]]]
        if r:
            hyig = (r[-1] / max(r) - 1) * 100
    hyg_dd = drawdown(C.get("HYG"))
    oas = (F.get("HY_OAS") or {}).get("last")
    ccc = (F.get("CCC_OAS") or {}).get("last")
    fam["credit"] = mean_or_none([sc(-hyg_dd if hyg_dd is not None else None, "credit_hyg_dd"),
                                  sc(-hyig if hyig is not None else None, "credit_hyig_dd"),
                                  sc(oas, "credit_hy_oas"), sc(ccc, "credit_ccc_oas")])
    E = data.get("equity", {})
    ndd = drawdown(E.get("NVDA")) if E.get("NVDA") else None
    sdd = drawdown(E.get("SOXX")) if E.get("SOXX") else None
    fam["equity"] = mean_or_none([sc(-ndd if ndd is not None else None, "equity_nvda_dd"),
                                  sc(-sdd if sdd is not None else None, "equity_soxx_dd")])
    score = mean_or_none(list(fam.values()))
    return score, fam


def gauge_groups(fam):
    """Split the five families into ex-ante vs coincident sub-scores.
    Leading = priced before the fact (prediction markets, options skew, credit);
    Confirming = moves with or after prices (vol complex, equity drawdown)."""
    lead = mean_or_none([fam.get("pred"), fam.get("opt"), fam.get("credit")])
    conf = mean_or_none([fam.get("vol"), fam.get("equity")])
    return lead, conf


# The two blended-gauge bands, mirroring OMEN.REGIME in omen-common.js. compute_regime
# below still spells them out inline (with the reasoning that goes with each); these are
# named so the credit-leads-equity clock can say "the credit family reads stressed" in
# the same numbers the regime does, instead of inventing a third threshold.
REGIME_STRESSED = 55
REGIME_ELEVATED = 35


def compute_regime(gauge, price):
    bubble = (price.get(BUBBLE_ID) or 0) * 100
    # deliberately the MKT sleeve, not the Bear composite: these bands are calibrated to
    # priced *crash* risk, and MKT is the old crash basket unchanged. Reading the
    # composite here would let regulatory odds trip a crash regime.
    level = sleeve_level(price, "mkt") or 0
    # Stressed requires a broad or confirmed metric — the blended gauge (mean of all
    # families) or the crash basket average. A single market (the bubble-burst market
    # included) can raise Elevated but never trips red on its own, so an escalation alert
    # can't fire on one market spiking. Matches the two pages' regime rules.
    if (gauge is not None and gauge >= 55) or level >= 40:
        return "stressed"
    if (gauge is not None and gauge >= 35) or level >= 25 or bubble >= 15:
        return "elevated"
    return "calm"


# ---------- snapshots ----------
# `crash`/`reg` are kept past the Bear merge: they are exactly the MKT/GOV sleeve reads,
# so the stored series stays comparable across the merge date and `bear` can be
# backfilled from them for the rows that predate the column.
SNAP_HEADER = ["date", "bull", "bull_n", "bear", "bear_n", "crash", "crash_n", "reg", "reg_n",
               "gauge", "lead", "conf", "comp"]


def snapshot_row(price):
    """One snapshot row: Bear as the flat 9-market union, sleeves alongside it."""
    row = {"date": datetime.date.today().isoformat()}
    for side, ids in POLY_IDS.items():
        lvl = index_level(price, side)
        row[side] = round(lvl, 2) if lvl is not None else ""
        row[side + "_n"] = len([i for i in ids if i in price])
    for sleeve, col in (("mkt", "crash"), ("gov", "reg")):
        lvl = sleeve_level(price, sleeve)
        row[col] = round(lvl, 2) if lvl is not None else ""
        row[col + "_n"] = len([i for i in BEAR_SLEEVES[sleeve] if i in price])
    return row


def backfill_bear(d):
    """Bear for a pre-merge row: the flat union rebuilt from the two sleeve levels.
    Counts are the live membership at that timestamp, so this is the same equal-weight
    mean the composite computes now – the merge introduces no splice step."""
    if d.get("bear") or not (d.get("crash") and d.get("reg")):
        return d.get("bear", "")
    try:
        cn, rn = int(d["crash_n"]), int(d["reg_n"])
        if cn + rn == 0:
            return ""
        return round((cn * float(d["crash"]) + rn * float(d["reg"])) / (cn + rn), 2)
    except (ValueError, KeyError):
        return ""


def append_snapshot(data=None, price=None):
    """Append today's snapshot row. `price` is the run's single Polymarket read, threaded in
    from build() so the stored gauge matches the one embedded in market-data.json; it is
    fetched here only when called standalone."""
    if price is None:
        try:
            price = poly_prices()
        except Exception as e:
            print("  snapshot skipped:", e)
            return
    row = snapshot_row(price)
    gauge = lead = conf = ""
    if data:
        g, fam = compute_gauge(data, price)
        gauge = round(g, 1) if g is not None else ""
        gl, gc = gauge_groups(fam)
        lead = round(gl, 1) if gl is not None else ""
        conf = round(gc, 1) if gc is not None else ""
    row["gauge"] = gauge
    row["lead"] = lead
    row["conf"] = conf
    row["comp"] = ",".join(sorted(price.keys()))
    existing = {}
    if os.path.exists(SNAP):
        with open(SNAP) as f:
            lines = f.read().strip().split("\n")
        old_header = lines[0].split(",") if lines else []
        for line in lines[1:]:
            parts = line.split(",", len(old_header) - 1)
            if parts and parts[0]:
                d = dict(zip(old_header, parts))
                d["bear"] = backfill_bear(d)
                if d["bear"] != "" and not d.get("bear_n"):
                    d["bear_n"] = int(d.get("crash_n") or 0) + int(d.get("reg_n") or 0)
                existing[parts[0]] = ",".join(str(d.get(h, "")) for h in SNAP_HEADER)
    existing[row["date"]] = ",".join(str(row[h]) for h in SNAP_HEADER)
    with open(SNAP, "w") as f:
        f.write(",".join(SNAP_HEADER) + "\n")
        for d in sorted(existing):
            f.write(existing[d] + "\n")
    print(f"  snapshot: bull {row['bull']} bear {row['bear']} "
          f"(mkt {row['crash']} · gov {row['reg']}) gauge {gauge} -> {SNAP}")


# ---------- CFTC Commitments of Traders (speculator positioning) ----------
def _inty(x):
    """Socrata returns numbers as strings (sometimes decimals); coerce or None."""
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def pctile_rank(vals, x):
    """Percentile of x within vals, 0..100, counting values <= x (ties as below)."""
    if not vals:
        return None
    return round(100.0 * sum(v <= x for v in vals) / len(vals), 1)


def zscore(vals, x):
    """Standard score of x against the sample. None below 2 points; 0 at zero
    variance (a flat series has no scale, not an infinite one)."""
    n = len(vals)
    if n < 2:
        return None
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / n)
    return 0.0 if sd == 0 else round((x - m) / sd, 2)


def cot_reduce(label, venue, rows):
    """Socrata COT rows (any order) -> non-commercial net positioning + percentile.

    net = noncomm long - noncomm short, reported as a share of open interest so
    contracts of different size compare on one axis. Percentile and z-score locate
    the latest week's net%OI inside the returned ~3y window. Rows missing a leg or
    with zero open interest are dropped rather than guessed."""
    hist = []
    for r in rows:
        oi = _inty(r.get("open_interest_all"))
        lng = _inty(r.get("noncomm_positions_long_all"))
        sht = _inty(r.get("noncomm_positions_short_all"))
        date = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]
        if not date or oi is None or lng is None or sht is None or oi <= 0:
            continue
        net = lng - sht
        hist.append({"date": date, "net": net, "net_pct_oi": round(100.0 * net / oi, 2)})
    if not hist:
        return None
    hist.sort(key=lambda h: h["date"])            # oldest -> newest
    latest = hist[-1]
    vals = [h["net_pct_oi"] for h in hist]
    return {"label": label, "venue": venue, "date": latest["date"],
            "net": latest["net"], "net_pct_oi": latest["net_pct_oi"],
            "pctile": pctile_rank(vals, latest["net_pct_oi"]),
            "z": zscore(vals, latest["net_pct_oi"]), "n_weeks": len(hist),
            "history": [{"d": h["date"], "v": h["net_pct_oi"]} for h in hist[-104:]]}


def cot_fetch(code, weeks=COT_WEEKS):
    q = urllib.parse.urlencode({
        "$select": "report_date_as_yyyy_mm_dd,open_interest_all,"
                   "noncomm_positions_long_all,noncomm_positions_short_all",
        "$where": f"cftc_contract_market_code='{code}'",
        "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": str(weeks)})
    return json.loads(get(COT_URL + "?" + q, timeout=30))


def cot():
    out = {"source": "CFTC Commitments of Traders — legacy futures-only, weekly "
                     "(Tue positions, Fri release)", "contracts": []}
    for key, cfg in COT_CONTRACTS.items():
        try:
            red = cot_reduce(cfg["label"], cfg["venue"], cot_fetch(cfg["code"]))
        except Exception as e:
            print(f"  cot {key}: FAIL {e}")
            continue
        if red:
            red["key"] = key
            out["contracts"].append(red)
    return out if out["contracts"] else None


# ---------- FINRA short interest (single-name short crowding, via api.nasdaq.com) ----------
def si_num(x):
    """'80,963,200' / '$12.30' -> float; None on junk or empty."""
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def short_interest_reduce(sym, rows):
    """api.nasdaq.com short-interest rows (newest settlement first) -> latest short
    interest and days-to-cover, the change since the prior settlement, and a short
    trend history. Days-to-cover = shares short / avg daily volume: how many normal
    sessions it would take to buy the short back — squeeze fuel and the depth of
    bearish conviction in one number. Rows without a date or a level are dropped."""
    hist = []
    for r in rows:
        si = si_num(r.get("interest"))
        date = r.get("settlementDate")
        if si is None or not date:
            continue
        hist.append({"date": date, "si": si, "dtc": si_num(r.get("daysToCover"))})
    if not hist:
        return None
    latest, prev = hist[0], (hist[1] if len(hist) > 1 else None)
    chg = (latest["si"] / prev["si"] - 1) * 100 if prev and prev["si"] else None
    return {"sym": sym, "date": latest["date"], "si": latest["si"], "dtc": latest["dtc"],
            "chg_pct": round(chg, 1) if chg is not None else None,
            "history": [{"d": h["date"], "si": h["si"], "dtc": h["dtc"]} for h in hist[:13]][::-1]}


def short_interest():
    out = {"source": "FINRA consolidated short interest (bi-monthly), via api.nasdaq.com",
           "names": []}
    for sym in SHORT_INTEREST:
        try:
            j = nasdaq_get(NASDAQ_SI_URL.format(sym=sym))
            rows = ((j.get("data") or {}).get("shortInterestTable") or {}).get("rows") or []
            red = short_interest_reduce(sym, rows)
        except Exception as e:
            print(f"  short_interest {sym}: FAIL {e}")
            continue
        if red:
            out["names"].append(red)
    if not out["names"]:
        return None
    out["asof"] = out["names"][0]["date"]     # settlements align across names
    return out


# ================= Rosenberg/Bernstein parameter set (handover 2026-08-12) =================
# Source: David Rosenberg & Rich Bernstein, "What Ends the AI Trade – And What They Own
# Instead" (Excess Returns). Everything below is Tier 1 in the handover's own taxonomy —
# free, keyless, and fetched here — except the four fields in SURVEY_MANUAL, which have no
# machine-readable free source and follow update-capex-data.py's MANUAL idiom instead.
#
# Two corrections to the handover's source table, both verified against the live endpoints:
#   - FRED does NOT mirror the Census data-center construction series (PRDCCON, PRDCCONS,
#     TLDCCONS and two more all 404). The number is parsed out of the C30 workbook.
#   - The NY Fed ACM term premium does not need the .xls download: it is FRED THREEFYTP10.
# And one substitution: Shiller's ie_data.xls is OLE2/BIFF, which no stdlib module reads,
# so CAPE comes from multpl.com's monthly table of the same Shiller series.

# Census "Value of Private Construction Put in Place", SA annual rate. Same workbook
# update-capex-data.py reads for its latest-month tile; here the whole row is kept so the
# data-center/housing ratio has a history to trend.
C30_URL = "https://www.census.gov/construction/c30/xlsx/privsa.xlsx"
C30_DC_ROW = "Data center"          # nested under "Office"; an loose match hits the parent
C30_HEADER_CELL = "Type of Construction:"
# FINRA customer margin balances. The 2021-03 path is just where the file was first
# uploaded — FINRA overwrites it in place every month, so it is the live series.
FINRA_MARGIN_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
FINRA_MARGIN_COL = "Debit Balances in Customers' Securities Margin Accounts"
# OCC clears every listed US option; this is the whole market's contract volume, free.
OCC_VOLUME_URL = "https://marketdata.theocc.com/mdapi/volume-totals"
# Shiller CAPE, monthly back to 1871.
CAPE_URL = "https://www.multpl.com/shiller-pe/table/by-month"
CAPE_EPOCH = 1900                   # the handover's comparison window: "vs. 1900+ history"
# Speculation-blur ratio: Polymarket event volume that is entertainment against event
# volume that is a financial-macro hedge. Gamma caps a page at 100 events, so both legs are
# deliberately "top 100 events per tag, deduped by event id" — a stable like-for-like
# ratio, not a claim about total venue volume. Tag slugs verified live 2026-08-13;
# "economics" and "entertainment" exist but return ~nothing, so they are not used.
POLY_SPEC_TAGS = ["sports", "politics", "pop-culture"]
POLY_HEDGE_TAGS = ["economy", "finance", "business", "fed", "inflation", "stocks"]
POLY_TAG_LIMIT = 100
# Credit–price divergence: "AI basket at/near highs WHILE credit spreads widen".
DIVERGENCE_NEAR_HIGH_PCT = 2.0      # within this much of the window high counts as "at highs"
DIVERGENCE_WEEKS = 8                # the M in "≥ N bp over M weeks"
DIVERGENCE_BP = 25                  # the N
CREDIT_CLOCK_MONTHS = 12            # Rosenberg: credit figures it out ~a year before equity
CORR_WINDOW = 60                    # trading days in the rolling sector correlation
CORR_HOT = 0.7                      # "count of sectors with corr > 0.7"
ROTATION_WINDOW = 63                # ~one quarter of ex-US-vs-AI relative strength
# Fields with no keyless machine-readable source. The handover puts the first three in
# Tier 2/3 and names the press/manual route; they are published here as explicit nulls with
# their provenance so a panel can say "not updated" instead of quietly implying it is live.
SURVEY_MANUAL = {
    "ici_cash_pct": {"value": 1.6, "asof": "2026-05",
                     "note": "ICI Trends in Mutual Fund Investing, equity-fund liquidity "
                             "ratio. Monthly HTML release, no API — update by hand.",
                     "src": "https://www.ici.org/research/stats"},
    "fms_recession_pct": {"value": 2.0, "asof": "2026-05",
                          "note": "BofA Global Fund Manager Survey, share of PMs expecting "
                                  "a downturn. Subscription product; the headline is "
                                  "reported in the press within ~1–2 days.",
                          "src": "https://www.bofaml.com"},
    "fms_base_rate_pct": {"value": 15.0, "asof": "historical",
                          "note": "Long-run base rate the survey reading is measured "
                                  "against, per the transcript.",
                          "src": "https://www.bofaml.com"},
    "umich_stock_up_pctile": {"value": None, "asof": None,
                              "note": "U. Michigan Surveys of Consumers, probability of a "
                                      "stock-market increase, as a percentile of its own "
                                      "history. Free data tables, no API — update by hand.",
                              "src": "https://data.sca.isr.umich.edu/data-archive/mine.php"},
}


# ---------- xlsx (a second, narrower reader than update-capex-data.py's) ----------
# update-capex-data.py carries xlsx_sheets/xlsx_strings/xlsx_rows for the EIA-860M and C30
# workbooks. They are not shared because this repo has no local-import convention between
# the fetchers (each is a standalone stdlib script), and because that reader only looks at
# <v> elements: it returns None for every t="inlineStr" cell, which is exactly how FINRA
# writes its date column. Keep both readers honest — if one grows a fix, check the other.
XLNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XLREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
XLRID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def xl_col(ref):
    """'AB12' -> 27. Empty cells are omitted from the XML, so position has to be read
    off the cell reference; counting siblings shifts every later column left."""
    n = 0
    for ch in ref or "":
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def xl_sheet_paths(zf):
    rels = {r.get("Id"): r.get("Target") for r in
            ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")).iter(XLREL + "Relationship")}
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    return ["xl/" + rels[s.get(XLRID)].lstrip("/")
            for s in wb.iter(XLNS + "sheet") if rels.get(s.get(XLRID))]


def xl_shared(zf):
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(XLNS + "t")) for si in root]


def xl_rows(zf, path, shared):
    """One sheet as lists of cell values. Handles the three ways a cell carries text:
    a shared-string index (t="s"), an inline string (t="inlineStr"), and a bare <v>."""
    with zf.open(path) as f:
        for _event, el in ET.iterparse(f, events=("end",)):
            if el.tag != XLNS + "row":
                continue
            row = []
            for c in el:
                if c.get("t") == "inlineStr":
                    node = c.find(XLNS + "is")
                    val = "".join(t.text or "" for t in node.iter(XLNS + "t")) if node is not None else None
                else:
                    v = c.find(XLNS + "v")
                    if v is None or v.text is None:
                        continue
                    val = shared[int(v.text)] if c.get("t") == "s" else v.text
                i = xl_col(c.get("r"))
                if i < 0:
                    continue
                row += [None] * (i + 1 - len(row))
                row[i] = val
            yield row
            el.clear()


def open_xlsx(blob):
    """(zipfile, shared strings) or (None, None) when the bytes are not a workbook.
    A 200 with an HTML error page is the normal failure here, not an exception."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
        return zf, xl_shared(zf)
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return None, None


# ---------- Census C30: the data-center construction row, as a series ----------
def c30_month(text):
    """'May\n2026p' -> '2026-05'. The revision/preliminary suffix is not part of it."""
    m = re.match(r"\s*([A-Za-z]{3,})\s*\n?\s*(\d{4})[pr]?\s*$", text or "")
    if not m:
        return None
    name = m.group(1).lower()[:3]
    hit = next((i for i, mo in enumerate(C30_MONTHS) if mo.startswith(name)), None)
    return f"{m.group(2)}-{hit + 1:02d}" if hit is not None else None


C30_MONTHS = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]


def c30_value_columns(header_cells, pct_col):
    """{column index: 'YYYY-MM'} for the *dollar* columns of a C30 header row.

    The sheet is two tables sharing one header: six months of values, then a "Percent
    change Jun 2026 from -" block whose sub-columns are headed with a month too ("May
    2026", "Jun 2025"). Those parse as months and are not dollars — reading them as the
    year-ago level turned a +53% year into a +156,386% one.

    Two independent guards, because the banner text is not a contract: everything at or
    right of the "Percent change" banner is dropped, and scanning stops at the first
    repeated month. The percent block's sub-columns are by construction the prior month
    and the year-ago month, so both of them are always already in the value block."""
    months, seen = {}, set()
    for i, cell in enumerate(header_cells):
        if not i or (pct_col is not None and i >= pct_col):
            continue
        ym = c30_month(cell)
        if not ym:
            continue
        if ym in seen:
            break
        seen.add(ym)
        months[i] = ym
    return months


def parse_c30_series(blob):
    """Every month of data-center construction put in place in the workbook (SAAR $M).

    Matched on the exact stripped label: "Data center" is nested under "Office", and a
    substring match picks the parent row up and overstates the series by ~1.8x."""
    zf, shared = open_xlsx(blob)
    if zf is None:
        return None
    for path in xl_sheet_paths(zf):
        months, row, pct_col = None, None, None
        for cells in xl_rows(zf, path, shared):
            if not cells:
                continue
            if months is None:
                hit = next((i for i, c in enumerate(cells)
                            if isinstance(c, str) and c.strip().startswith("Percent change")), None)
                if hit is not None:
                    pct_col = hit
            if not isinstance(cells[0], str):
                continue
            if months is None and cells[0].strip() == C30_HEADER_CELL:
                months = c30_value_columns(cells, pct_col)
            elif months is not None and cells[0].strip() == C30_DC_ROW:
                row = cells
                break
        if not months or not row:
            continue
        out = []
        for i in sorted(months, key=lambda k: months[k]):
            try:
                out.append({"d": months[i] + "-01", "c": float(row[i])})
            except (IndexError, TypeError, ValueError):
                continue
        return out or None
    return None


def census_dc_construction():
    return parse_c30_series(get_bytes(C30_URL))


# ---------- FINRA customer margin debt ----------
def parse_finra_margin(blob):
    """[{'d': 'YYYY-MM-01', 'c': debit balances $M}] oldest-first.

    The workbook is one sheet, newest month first, with the date column written as an
    inline string ("2026-06") rather than a date serial."""
    zf, shared = open_xlsx(blob)
    if zf is None:
        return None
    for path in xl_sheet_paths(zf):
        col, out = None, []
        for cells in xl_rows(zf, path, shared):
            if col is None:
                if cells and FINRA_MARGIN_COL in [str(c).strip() if c else c for c in cells]:
                    col = [str(c).strip() if c else c for c in cells].index(FINRA_MARGIN_COL)
                continue
            if not cells or not isinstance(cells[0], str):
                continue
            ym = re.fullmatch(r"(\d{4})-(\d{2})", cells[0].strip())
            if not ym:
                continue
            try:
                out.append({"d": f"{cells[0].strip()}-01", "c": float(cells[col])})
            except (IndexError, TypeError, ValueError):
                continue
        if out:
            return sorted(out, key=lambda r: r["d"])
    return None


def finra_margin():
    return parse_finra_margin(get_bytes(FINRA_MARGIN_URL))


# ---------- OCC total options volume ----------
def occ_volume():
    """Whole-market cleared option contract volume, with OCC's own 52-week bounds.

    The options-to-share ratio the handover asks for needs a total US share-volume leg,
    which has no free keyless feed; contract volume against its own 52-week range is the
    part that is honestly available, and it is what the panel says it is."""
    j = json.loads(get(f"{OCC_VOLUME_URL}?report_date={datetime.date.today().isoformat()}"))
    e = j.get("entity") or {}
    opts, hi, lo = e.get("optionsVolume"), e.get("fiftytwo_week_high"), e.get("fiftytwo_week_low")
    if not opts or not hi or not lo or hi <= lo:
        return None
    return {"options": int(opts), "futures": int(e.get("futuresVolume") or 0),
            "wk52_high": int(hi), "wk52_low": int(lo),
            "monthly_avg": int(e.get("monthlyDailyAverage") or 0),
            "yearly_avg": int(e.get("yearlyDailyAverage") or 0),
            "pct_of_range": round((opts - lo) / (hi - lo) * 100, 1),
            "vs_year_avg_pct": (round((opts / e["yearlyDailyAverage"] - 1) * 100, 1)
                                if e.get("yearlyDailyAverage") else None)}


# ---------- Shiller CAPE ----------
def parse_cape_table(html_text):
    """multpl.com's monthly Shiller-CAPE table -> [{'d','c'}] oldest-first.

    Entities are unescaped first: the value cell is prefixed with an en-space written as
    &#x2002;, and a regex run over the raw markup reads that entity's digits as the value."""
    text = html.unescape(html_text)
    rows = re.findall(r"<td>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</td>\s*<td>\s*(-?[\d.]+)\s*</td>",
                      text)
    out = []
    for date_txt, val in rows:
        try:
            # noqa DTZ007: a calendar month-stamp ("Aug 13, 2026"), not an instant — it is
            # reduced to a date on the same line and never compared across zones.
            d = datetime.datetime.strptime(date_txt, "%b %d, %Y").date()  # noqa: DTZ007
            out.append({"d": d.isoformat(), "c": float(val)})
        except ValueError:
            continue
    return sorted(out, key=lambda r: r["d"]) or None


def shiller_cape():
    return parse_cape_table(get(CAPE_URL))


# ---------- Polymarket speculation-blur ----------
def poly_tag_volume(slug, limit=POLY_TAG_LIMIT):
    """{event id: volume} for one tag's top events by volume. Keyed by id so the caller
    can union several tags without double-counting an event that carries both."""
    url = ("https://gamma-api.polymarket.com/events?closed=false&order=volume"
           f"&ascending=false&limit={limit}&tag_slug={urllib.parse.quote(slug)}")
    out = {}
    for e in json.loads(get(url)):
        try:
            vol = float(e.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if vol > 0 and e.get("id"):
            out[str(e["id"])] = vol
    return out


def spec_blur():
    """Entertainment betting volume over financial-hedging volume on Polymarket.

    Bernstein's "speculation blurs into everything" tell, made countable. A tag that
    fails to fetch is dropped and named rather than treated as zero volume, because a
    zero on either leg moves the ratio far more than a missing tag should."""
    legs, missing = {}, []
    for name, tags in (("spec", POLY_SPEC_TAGS), ("hedge", POLY_HEDGE_TAGS)):
        merged = {}
        for slug in tags:
            try:
                merged.update(poly_tag_volume(slug))
            except Exception as e:
                missing.append(slug)
                print(f"  spec_blur {slug}: FAIL {e}")
        legs[name] = merged
    spec_v = sum(legs["spec"].values())
    hedge_v = sum(legs["hedge"].values())
    if not spec_v or not hedge_v:
        return None
    return {"spec_usd": round(spec_v), "hedge_usd": round(hedge_v),
            "spec_events": len(legs["spec"]), "hedge_events": len(legs["hedge"]),
            "ratio": round(spec_v / hedge_v, 2),
            "spec_tags": POLY_SPEC_TAGS, "hedge_tags": POLY_HEDGE_TAGS,
            "missing_tags": missing, "limit": POLY_TAG_LIMIT}


# ---------- derived: pure math, unit-tested in test_update_market_data.py ----------
def pearson(xs, ys):
    """Correlation of two equal-length samples. None when either has no variance —
    a flat series has no correlation, and 0 would read as "uncorrelated", which is a
    different and much stronger claim."""
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    xs, ys = xs[-n:], ys[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def returns(series):
    """Close series -> simple returns. Zero/absent prior closes are skipped, not
    turned into infinities."""
    out = []
    for prev, cur in zip(series, series[1:]):
        if prev.get("c"):
            out.append({"d": cur["d"], "r": cur["c"] / prev["c"] - 1})
    return out


def basket_series(equity, syms):
    """Equal-weight price index of syms, based at 100 on the first shared date.

    Joined on trading date, never on array position: the per-symbol series are carried
    forward independently when a fetch fails, so one can be a session behind another."""
    have = [s for s in syms if equity.get(s) and len(equity[s]) > 1]
    if len(have) < 2:
        return None
    dates = set.intersection(*[{p["d"] for p in equity[s]} for s in have])
    if len(dates) < 2:
        return None
    by = {s: {p["d"]: p["c"] for p in equity[s]} for s in have}
    days = sorted(dates)
    base = {s: by[s][days[0]] for s in have}
    out = []
    for d in days:
        vals = [by[s][d] / base[s] for s in have if base[s]]
        if vals:
            out.append({"d": d, "c": sum(vals) / len(vals) * 100})
    return out or None


def near_high_pct(series):
    """How far below its own window high the series is, in percent (0 = at the high)."""
    if not series:
        return None
    hi = max(p["c"] for p in series)
    return (series[-1]["c"] / hi - 1) * 100 if hi else None


def spread_change_bp(series, weeks):
    """Change in a percentage-point spread series over `weeks`, in basis points."""
    if not series or len(series) < 2:
        return None
    last = series[-1]
    try:
        cutoff = (datetime.date.fromisoformat(last["d"])
                  - datetime.timedelta(weeks=weeks)).isoformat()
    except ValueError:
        return None
    older = [p for p in series if p["d"] <= cutoff]
    if not older:
        return None
    return (last["c"] - older[-1]["c"]) * 100


def credit_price_divergence(basket, hy, ig):
    """Rosenberg's "credit figures it out about a year before equity", as a state.

    Divergence = the AI basket is within DIVERGENCE_NEAR_HIGH_PCT of its window high
    while the HY−IG spread has widened at least DIVERGENCE_BP over DIVERGENCE_WEEKS.
    Both legs are required: a widening spread in a falling market is just a selloff,
    and it is the *combination* that the transcript treats as the warning."""
    if not basket or not hy or not ig:
        return None
    by_ig = {p["d"]: p["c"] for p in ig}
    gap = [{"d": p["d"], "c": p["c"] - by_ig[p["d"]]} for p in hy if p["d"] in by_ig]
    if len(gap) < 2:
        return None
    prox = near_high_pct(basket)
    widen = spread_change_bp(gap, DIVERGENCE_WEEKS)
    if prox is None or widen is None:
        return None
    at_highs = prox >= -DIVERGENCE_NEAR_HIGH_PCT
    widening = widen >= DIVERGENCE_BP
    return {"basket_vs_high_pct": round(prox, 2),
            "hy_ig_gap": round(gap[-1]["c"], 2),
            "gap_change_bp": round(widen, 1),
            "gap_z": zscore([p["c"] for p in gap], gap[-1]["c"]),
            "at_highs": at_highs, "widening": widening,
            "diverging": bool(at_highs and widening),
            "weeks": DIVERGENCE_WEEKS, "bp_threshold": DIVERGENCE_BP,
            "near_high_pct": DIVERGENCE_NEAR_HIGH_PCT}


def credit_clock(credit_score, prev_clock, today):
    """12-month countdown that starts the first time the credit family reads stressed.

    State, not a level, so it is carried in market-data.json between runs: the whole
    point is the date of the *first* crossing. It clears when credit falls back under
    the elevated band — a clock that never resets is a clock nobody believes."""
    from_prev = (prev_clock or {}).get("started")
    if credit_score is None:
        return prev_clock
    if credit_score < REGIME_ELEVATED:
        return None
    started = from_prev
    if started is None:
        if credit_score < REGIME_STRESSED:
            return None
        started = today
    try:
        elapsed = (datetime.date.fromisoformat(today)
                   - datetime.date.fromisoformat(started)).days / 30.44
    except ValueError:
        return None
    return {"started": started, "months_elapsed": round(elapsed, 1),
            "months_left": round(max(0.0, CREDIT_CLOCK_MONTHS - elapsed), 1),
            "horizon_months": CREDIT_CLOCK_MONTHS}


def dc_housing_ratio(dc_series, res_series):
    """Data-center construction over private residential construction, both SAAR $M.

    Bernstein's capital-misallocation measure: the economy pouring concrete for compute
    instead of for houses. Joined on month; the two come from different publishers of the
    same Census survey and are not always released in the same week."""
    if not dc_series or not res_series:
        return None
    res = {p["d"][:7]: p["c"] for p in res_series}
    pairs = [(p["d"][:7], p["c"] / res[p["d"][:7]])
             for p in dc_series if res.get(p["d"][:7])]
    if not pairs:
        return None
    pairs.sort()
    hist = [{"d": m + "-01", "c": round(r, 4)} for m, r in pairs]
    latest = pairs[-1][1]
    year_ago = f"{int(pairs[-1][0][:4]) - 1}{pairs[-1][0][4:]}"
    base = next((r for m, r in pairs if m == year_ago), None)
    return {"ratio": round(latest, 4), "asof": pairs[-1][0],
            "dc_saar_b": round(dc_series[-1]["c"] / 1000, 1),
            "res_saar_b": round(res_series[-1]["c"] / 1000, 1),
            "yoy_pct": round((latest / base - 1) * 100, 1) if base else None,
            "history": hist[-60:]}


def ex_ai_capex(inv_equip, inv_ip, fund):
    """BEA equipment + IP investment less the AI filers' capex, and its year-over-year.

    The residual is deliberately crude and the numbers do not line up perfectly: BEA is
    domestic investment, the filers' capex is worldwide, so the subtraction takes a bit
    too much out. It is still the right sign and the right turning point, which is what
    "ex-AI capex growth < 0" is being asked for — the note field says so on the page."""
    if not inv_equip or not inv_ip or not fund:
        return None
    equip = {p["d"][:7]: p["c"] for p in inv_equip}
    ip = {p["d"][:7]: p["c"] for p in inv_ip}
    quarters = fund.get("quarters") or []
    capex = fund.get("capex_b") or []
    rows = []
    for q, cx in zip(quarters, capex):
        month = quarter_start_month(q)
        if month is None or cx is None or month not in equip or month not in ip:
            continue
        # filer capex is one quarter's cash; BEA is a seasonally adjusted annual rate
        rows.append({"q": q, "total_b": equip[month] + ip[month],
                     "ai_b": cx * 4, "ex_ai_b": equip[month] + ip[month] - cx * 4})
    if len(rows) < 5:
        return None
    idx = {r["q"]: r for r in rows}
    latest = rows[-1]
    base = idx.get(f"{int(latest['q'][:4]) - 1}{latest['q'][4:]}")
    yoy = ((latest["ex_ai_b"] / base["ex_ai_b"] - 1) * 100
           if base and base["ex_ai_b"] else None)
    return {"quarter": latest["q"], "total_b": round(latest["total_b"], 1),
            "ai_b": round(latest["ai_b"], 1), "ex_ai_b": round(latest["ex_ai_b"], 1),
            "ai_share_pct": round(latest["ai_b"] / latest["total_b"] * 100, 1)
            if latest["total_b"] else None,
            "yoy_pct": round(yoy, 1) if yoy is not None else None,
            "history": [{"q": r["q"], "ex_ai_b": round(r["ex_ai_b"], 1)} for r in rows[-20:]]}


def quarter_start_month(q):
    """'2026Q2' -> '2026-04', the month BEA stamps that quarter's observation with."""
    m = re.fullmatch(r"(\d{4})Q([1-4])", q or "")
    return f"{m.group(1)}-{(int(m.group(2)) - 1) * 3 + 1:02d}" if m else None


def gdp_ex_ai(gdp_growth, real_gdp, fund):
    """Trailing 4-quarter real GDP growth, less the arithmetic contribution of AI capex.

    Contribution = the year-over-year *change* in annualized AI capex over the level of
    GDP. Rosenberg's "without AI we would be in recession" is exactly this residual, and
    the handover's fragile threshold is under ~0.5%."""
    if not gdp_growth or not real_gdp or not fund:
        return None
    recent = [p["c"] for p in gdp_growth[-4:]]
    if len(recent) < 4:
        return None
    avg = sum(recent) / 4
    quarters, capex = fund.get("quarters") or [], fund.get("capex_b") or []
    if len(quarters) < 5 or len(capex) < 5:
        return None
    pairs = {q: c for q, c in zip(quarters, capex) if c is not None}
    latest_q = quarters[-1]
    base_q = f"{int(latest_q[:4]) - 1}{latest_q[4:]}"
    if latest_q not in pairs or base_q not in pairs:
        return None
    level = real_gdp[-1]["c"]
    if not level:
        return None
    contrib = (pairs[latest_q] - pairs[base_q]) * 4 / level * 100
    return {"quarter": latest_q, "gdp_4q_avg_pct": round(avg, 2),
            "ai_contrib_pp": round(contrib, 2),
            "ex_ai_pct": round(avg - contrib, 2),
            "gdp_level_b": round(level, 1)}


def correlation_breadth(equity, basket, sectors, window=CORR_WINDOW, hot=CORR_HOT):
    """How much of the S&P now trades as one AI bet.

    Rolling-window correlation of each sector SPDR's daily returns to the AI basket's.
    The transcript's claim under test is that only health care and staples are still
    uncorrelated, so the headline is the count above `hot` and the detail is per sector."""
    if not basket:
        return None
    bret = {r["d"]: r["r"] for r in returns(basket)}
    rows = []
    for sym, label in sorted(sectors.items()):
        s = equity.get(sym)
        if not s or len(s) < window:
            continue
        sret = returns(s)
        dates = [r["d"] for r in sret if r["d"] in bret][-window:]
        if len(dates) < window // 2:
            continue
        by = {r["d"]: r["r"] for r in sret}
        c = pearson([by[d] for d in dates], [bret[d] for d in dates])
        if c is not None:
            rows.append({"sym": sym, "name": label, "corr": round(c, 3), "n": len(dates)})
    if not rows:
        return None
    rows.sort(key=lambda r: -r["corr"])
    return {"window": window, "threshold": hot, "sectors": rows,
            "n_hot": sum(r["corr"] > hot for r in rows), "n_total": len(rows),
            "cool": [r["name"] for r in rows if r["corr"] <= hot]}


def rotation_rs(equity, basket, sym="ACWX", window=ROTATION_WINDOW):
    """Relative strength of ACWI-ex-US against the AI basket.

    Bernstein's regime-change confirmation is *sustained* ex-US leadership, so this
    reports the change in the RS line over the window, not today's ratio."""
    s = equity.get(sym)
    if not s or not basket or len(s) < 2:
        return None
    by = {p["d"]: p["c"] for p in basket}
    line = [{"d": p["d"], "c": p["c"] / by[p["d"]]} for p in s if by.get(p["d"])]
    if len(line) < 3:
        return None
    back = line[max(0, len(line) - 1 - window)]
    if not back["c"]:
        return None
    chg = (line[-1]["c"] / back["c"] - 1) * 100
    return {"sym": sym, "window": window, "change_pct": round(chg, 2),
            "leading": chg > 0, "from": back["d"], "to": line[-1]["d"],
            "history": [{"d": p["d"], "c": round(p["c"], 5)} for p in line[-120:]]}


def cape_sigma(series, epoch=CAPE_EPOCH):
    """Shiller CAPE as standard deviations above its own post-`epoch` mean.

    The handover's bands: calm under 1σ, elevated at 2σ (Grantham's bubble line),
    stressed at 3σ. Reported with the percentile because sigma on a right-skewed
    series flatters the tails."""
    if not series:
        return None
    hist = [p["c"] for p in series if p["d"][:4].isdigit() and int(p["d"][:4]) >= epoch]
    if len(hist) < 60:
        return None
    last = series[-1]["c"]
    mean = sum(hist) / len(hist)
    sd = math.sqrt(sum((v - mean) ** 2 for v in hist) / len(hist))
    if sd <= 0:
        return None
    return {"cape": round(last, 2), "asof": series[-1]["d"], "epoch": epoch,
            "mean": round(mean, 2), "sd": round(sd, 2),
            "sigma": round((last - mean) / sd, 2),
            "pctile": pctile_rank(hist, last), "n": len(hist)}


def taylor_gap(fed_funds, trim_pce, unrate, nrou, r_star=2.0, target=2.0):
    """Taylor-rule prescription minus the actual funds rate, in percentage points.

    rule = r* + π + 0.5(π − π*) + 0.5·(output gap), with the output gap taken from the
    unemployment gap through Okun's law (2 points of output per point of unemployment).
    NROU is a CBO projection that runs a decade into the future, so it is read at the
    unemployment print's own date rather than at the end of the series — taking its last
    observation would measure today's rate against the 2036 natural rate."""
    if not fed_funds or not trim_pce or not unrate or not nrou:
        return None
    pi, u, ffr = trim_pce[-1]["c"], unrate[-1]["c"], fed_funds[-1]["c"]
    at = [p for p in nrou if p["d"] <= unrate[-1]["d"]]
    if not at:
        return None
    rule = r_star + pi + 0.5 * (pi - target) + 1.0 * (at[-1]["c"] - u)
    return {"rule_pct": round(rule, 2), "actual_pct": round(ffr, 2),
            "gap_pp": round(rule - ffr, 2), "inflation_pct": round(pi, 2),
            "unrate_pct": round(u, 2), "nrou_pct": round(at[-1]["c"], 2),
            "asof": unrate[-1]["d"], "stance": "tight" if rule < ffr else "loose"}


def series_percentile(series, keep=None):
    """Latest observation of a FRED series located in its own history."""
    if not series:
        return None
    vals = [p["c"] for p in series][-keep:] if keep else [p["c"] for p in series]
    if len(vals) < 8:
        return None
    return {"value": round(vals[-1], 2), "asof": series[-1]["d"], "n": len(vals),
            "pctile": pctile_rank(vals, vals[-1]), "z": zscore(vals, vals[-1]),
            "min": round(min(vals), 2), "max": round(max(vals), 2)}


def ratio_of(a, b):
    return a / b if a is not None and b else None


def dig(obj, *path):
    """obj["a"]["b"]["c"] where any level may be None or missing."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def compute_fragility(data):
    """The structural-fragility composite: four families, equal-weighted, 0–100.

    Same arithmetic as compute_gauge — every component normalized onto a written-down
    calm→stress range, averaged inside its family, families averaged with equal weight so
    none dominates (the handover's §5 rule). What it deliberately does NOT do is join the
    crash-pressure gauge: these read at an extreme for years, and a permanently-high
    headline is a headline nobody reads. Fragility answers "how far is there to fall",
    the gauge answers "is it starting". Published side by side, never blended.

    Returns None rather than a score built from one surviving family — a composite of
    one family is not a composite, and it would swing wildly as feeds come and go."""
    mis = dig(data, "misalloc") or {}
    pos = dig(data, "positioning") or {}
    survey = pos.get("survey") or {}
    cape = dig(data, "cape") or {}
    corr = dig(data, "corr_breadth") or {}

    fms_gap = None
    base, now_pct = dig(survey, "fms_base_rate_pct", "value"), dig(survey, "fms_recession_pct", "value")
    if base is not None and now_pct is not None:
        fms_gap = base - now_pct
    cot_ndx = next((c.get("pctile") for c in (dig(data, "cot", "contracts") or [])
                    if c.get("key") == "ndx"), None)
    breadth_pct = None
    if corr.get("n_total"):
        breadth_pct = corr["n_hot"] / corr["n_total"] * 100

    # Pulled into locals before scoring, one per line, so that the reference name is the
    # only quoted string in each sc() call. test_gauge_refs.py reads those call sites with
    # a regex to prove every declared range is actually scored; a nested dig(x, "key")
    # inside the call reads as the range name and the proof silently checks the wrong thing.
    dc_ratio = dig(mis, "dc_housing", "ratio")
    # negated: falling ex-AI capex and falling ex-AI GDP growth are the stressed end
    ex_ai_yoy = neg(dig(mis, "ex_ai_capex", "yoy_pct"))
    gdp_ex_ai_pct = neg(dig(mis, "gdp_ex_ai", "ex_ai_pct"))
    hh_pctile = dig(pos, "hh_equity_fin", "pctile")
    margin_yoy = dig(pos, "margin_debt", "yoy_pct")
    fund_cash = neg(dig(survey, "ici_cash_pct", "value"))
    cape_sig = cape.get("sigma")
    blur = dig(data, "spec_blur", "ratio")
    gap_z = dig(data, "credit_div", "gap_z")

    fam = {
        "mis": mean_or_none([sc(dc_ratio, "mis_dc_housing"),
                             sc(ex_ai_yoy, "mis_ex_ai_capex"),
                             sc(gdp_ex_ai_pct, "mis_gdp_ex_ai")]),
        "pos": mean_or_none([sc(hh_pctile, "pos_hh_equity"),
                             sc(margin_yoy, "pos_margin_yoy"),
                             sc(fund_cash, "pos_fund_cash"),
                             sc(fms_gap, "pos_fms_gap"),
                             sc(cot_ndx, "pos_cot_ndx")]),
        "val": mean_or_none([sc(cape_sig, "val_cape_sigma"),
                             sc(breadth_pct, "val_corr_breadth"),
                             sc(blur, "val_spec_blur")]),
        "cred": mean_or_none([sc(gap_z, "cred_gap_z")]),
    }
    live = [v for v in fam.values() if v is not None]
    if len(live) < 2:
        return None
    return {"score": round(sum(live) / len(live), 1),
            "fam": {k: (round(v, 1) if v is not None else None) for k, v in fam.items()},
            "n_families": len(live)}


def neg(x):
    """Negate, keeping None as None. For the ranges whose stressed end is the low end."""
    return None if x is None else -x


# ---------- alerting ----------
def send_alert(title, body):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    sent = False
    if tok and chat:
        try:
            # retries=0: this is a POST, and a timeout after delivery would double-send.
            # A genuinely failed push is reported below rather than retried blind.
            get(f"https://api.telegram.org/bot{tok}/sendMessage",
                data=urllib.parse.urlencode({"chat_id": chat, "text": f"{title}\n{body}"}),
                retries=0)
            sent = True
        except Exception as e:
            print("telegram alert failed:", e)
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(),
                                         headers={"Title": title, "Priority": "high"})
            urllib.request.urlopen(req, timeout=15).read()
            sent = True
        except Exception as e:
            print("ntfy alert failed:", e)
    if not sent:
        print("alert (no channel configured):", title, "|", body)


def check_alert(data, price=None):
    """Escalation check on the same prices the stored gauge was built from (see build())."""
    if price is None:
        try:
            price = poly_prices()
        except Exception as e:
            print("alert skipped:", e)
            return
    gauge, fam = compute_gauge(data, price)
    regime = compute_regime(gauge, price)
    prev = {}
    if os.path.exists(ALERT_STATE):
        try:
            prev = json.load(open(ALERT_STATE))
        except Exception:
            prev = {}
    rank = {"calm": 0, "elevated": 1, "stressed": 2}
    if rank[regime] > rank.get(prev.get("regime", "calm"), 0):
        gtxt = f"{gauge:.0f}" if gauge is not None else "?"
        bubble = (price.get(BUBBLE_ID) or 0) * 100
        lead, conf = gauge_groups(fam)
        send_alert(f"AI Crash Monitor: regime -> {regime.upper()}",
                   f"Gauge {gtxt}/100 (leading {lead and round(lead)} / confirming {conf and round(conf)}) "
                   f"· bubble market {bubble:.1f}% · families: "
                   + ", ".join(f"{k} {v:.0f}" for k, v in fam.items() if v is not None))
    # The stamp is written as naive-UTC + "Z", the format alert-state.json has always used
    # and the pages parse. now(timezone.utc) is the non-deprecated read; dropping tzinfo
    # again before isoformat() keeps the trailing "Z" rather than emitting "+00:00".
    at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    json.dump({"regime": regime, "gauge": gauge, "at": at}, open(ALERT_STATE, "w"))
    print(f"regime: {regime} (gauge {gauge and round(gauge, 1)})")


# ---------- build ----------
# One failure policy for every panel. These used to differ: caps/cot/short_interest fell back
# to the previous run, everything else silently dropped its key. That is not cosmetic —
# compute_gauge reads data["equity"], ["vol"], ["skew"], ["credit"] and ["fred"] directly, so a
# dropped key removes a whole family from the blended mean, moves the headline score, and can
# escalate or suppress an alert on nothing worse than a transient Yahoo blip. Carrying the last
# good value keeps the gauge on a constant basis until the source recovers, and the staleness
# stays visible because every panel carries its own asof/date.
def carry(data, prev, key, e):
    """Log a panel failure, then fall back to the previous run's value. True if carried."""
    print(f"{key}: FAIL {e}")
    old = prev.get(key)
    if old is None:
        return False
    data[key] = old
    print(f"{key}: carried previous value")
    return True


def carry_sub(data, prev, section, key, e=None):
    """Same, for the per-symbol sections (equity/vol/credit/fred/skew/term/tail)."""
    if e is not None:
        print(f"{section} {key}: FAIL {e}")
    old = (prev.get(section) or {}).get(key)
    if old is None:
        return False
    data[section][key] = old
    print(f"{section} {key}: carried previous value")
    return True


# ---------- Berg turning-point metrics (handover 2026-08-13) ----------
# Every family OMEN already scores measures how bad it is getting. None measure whether
# the flush is COMPLETE. Berg's claim is that bottoms are the detectable event – V-shaped,
# panic-driven, statistically rare – while tops roll and are not. These metrics are
# therefore neither leading nor confirming in OMEN's existing split: they fire after the
# damage, about the recovery. Group tag: turn.
#
# The thresholds below are transcriptions of rules stated on the record, not fitted
# parameters, and none are verified against the source recording. They sit in one block
# so methodology.html can print them and a reader can reject one number without
# reverse-engineering the panel.
TURN_PARAMS_VERSION = "2026-08-13"
# A1: what counts as a panic. One global 15%/30d finds NOTHING on ^GSPC or ^NDX across
# five years of tape, which would render the panel permanently empty on the two headline
# indices; Berg's own worked examples run off ~9% index declines. So the drop is per
# ticker class, not global.
PANIC_DROP_PCT = {"^GSPC": 9.0, "^NDX": 10.0, "^RUT": 12.0, "SOXX": 15.0,
                  "^KS11": 15.0, "EWY": 15.0}
PANIC_DROP_DEFAULT = 12.0
PANIC_WINDOW = 30
BOUNCE_DAYS = 3              # sessions off the low before the low is fixed as reference
BERG_DAY_MARKS = (8, 9, 12, 16, 19)
BERG_UP_TRIGGERS = ((8, 8), (8, 9), (16, 19))
ROC_EXTREME_PCTILE = 99.0
BREAKAWAY_MIN_DAYS_BELOW = 42
VXN_SHORT_MA = 4
VXN_LONG_MA = 15
VXN_COMPLACENT_DEV = -20.0
BOTTOM_WINDOW = 120          # C1: bottoms in the recent tape, not across all history
TURN_DISPLAY_BARS = 90       # how much series the payload carries per ticker
# §2's bad-tick filter is calibrated to PRICE tickers and is never applied to the vol
# complex. Across 5y, ^GSPC's |low/close-1| maxes at 0.093, so a 0.15 band only ever
# catches a genuine bad print; ^VXN's runs to a p99 of 0.369 and a max of 0.794, so the
# same band would "repair" 58 of its 1,254 real sessions. Vol feeds neither the crash-low
# nor the gap logic, so it is simply not filtered.
SANITY_MAX_DEV = 0.15


def clean_bars(bars, max_dev=SANITY_MAX_DEV):
    """Clamp bad intraday ticks to their own close, keeping the session.

    Dropping the bar would shift every day count in A2/A3, so the extreme is clamped and
    the repair counted – the panel discloses the count rather than hiding it."""
    out, repaired = [], 0
    for b in bars or []:
        c, nb, touched = b.get("c"), dict(b), False
        for k in ("h", "l"):
            v = b.get(k)
            if c and v is not None and abs(v / c - 1) > max_dev:
                nb[k] = c
                touched = True
        repaired += 1 if touched else 0
        out.append(nb)
    return out, repaired


def crash_low_integrity(bars, drop_pct=PANIC_DROP_DEFAULT, window=PANIC_WINDOW,
                        bounce_days=BOUNCE_DAYS):
    """The reference panic low, and how far spot sits above each of its two levels.

    Berg's rule: a crash low gets TESTED on a closing basis – that is the normal path –
    but a break of the panic day's INTRADAY low invalidates the crash-low thesis and is a
    regime change. Both levels are reported; only the intraday break sets regime_change.

    The reference is sticky. Once price has held for bounce_days the low is fixed, and a
    later marginal new closing low is a violation of that reference rather than a new
    reference. The episode resets only when price regains the pre-decline peak, which is
    what makes a genuinely separate panic a new anchor."""
    bars = list(bars or [])
    if len(bars) < 2:
        return None
    closes = [b["c"] for b in bars]
    ep = None
    for j, c in enumerate(closes):
        seg = closes[max(0, j - window):j + 1]
        peak = max(seg)
        declined = (c / peak - 1) * 100 <= -drop_pct and c == min(seg)
        if ep is not None and c >= ep["peak"]:
            ep = None                      # regained the pre-decline peak: episode over
        if ep is None:
            if declined:
                ep = {"peak": peak, "low_i": j, "fixed": False}
        elif not ep["fixed"]:
            if bars[j]["l"] < bars[ep["low_i"]]["l"]:
                ep["low_i"] = j            # still carving the low
            elif j - ep["low_i"] >= bounce_days:
                ep["fixed"] = True         # held long enough to be the reference
    if ep is None:
        return None
    i = ep["low_i"]
    low_bar, spot, after = bars[i], closes[-1], bars[i + 1:]
    close_low, intraday_low = low_bar["c"], low_bar["l"]
    broke_intraday = any(b["l"] < intraday_low for b in after)
    return {"index": i, "date": low_bar.get("d"),
            "close_low": round(close_low, 2), "intraday_low": round(intraday_low, 2),
            "to_close_low_pct": round((close_low / spot - 1) * 100, 2),
            "to_intraday_low_pct": round((intraday_low / spot - 1) * 100, 2),
            "close_low_violated": any(b["c"] < close_low for b in after),
            "intraday_low_violated": broke_intraday,
            "regime_change": broke_intraday,
            "fixed": ep["fixed"],
            "decline_pct": round((close_low / ep["peak"] - 1) * 100, 2)}


def days_off_low(bars, low_idx):
    """Trading days since the reference low with the CLOSING low unbroken.

    The counter freezes at the break rather than resetting – "held 12 days then broke" is
    the fact worth showing, and a zero would erase it."""
    bars = list(bars or [])
    if not bars or low_idx >= len(bars) - 1:
        return {"days": 0, "intact": True, "milestone": None}
    close_low, days, intact = bars[low_idx]["c"], 0, True
    for b in bars[low_idx + 1:]:
        if b["c"] < close_low:
            intact = False
            break
        days += 1
    return {"days": days, "intact": intact,
            "milestone": days if intact and days in BERG_DAY_MARKS else None}


def up_days_in_window(bars, low_idx, n):
    """Up closes in the n sessions after the low. Flat closes are not up closes."""
    bars = list(bars or [])
    win = bars[low_idx + 1:low_idx + 1 + n]
    up, prev = 0, bars[low_idx]["c"] if low_idx < len(bars) else None
    for b in win:
        if prev is not None and b["c"] > prev:
            up += 1
        prev = b["c"]
    return {"up": up, "n": len(win)}


def up_day_trigger(up, n):
    """The Berg cluster this (up, n) pair satisfies, as its display label."""
    for t_up, t_n in BERG_UP_TRIGGERS:
        if n == t_n and up >= t_up:
            return f"{t_up} of {t_n}"
    return None


def roc_percentile(closes, n, lookbacks=(252, 1260)):
    """Current n-day rate of change, ranked against its own trailing distribution.

    The rarity is the signal, not the return. A lookback the history cannot fill ranks
    None rather than ranking against a short window and overstating the rarity – note
    Yahoo's range=5y returns 1,254 bars, six short of 1,260, so the long rank needs 10y."""
    closes = list(closes or [])
    if n < 1 or len(closes) <= n:
        return None
    rocs = [(closes[i] / closes[i - n] - 1) * 100
            for i in range(n, len(closes)) if closes[i - n]]
    if not rocs:
        return None
    cur, ranks = rocs[-1], {}
    for lb in lookbacks:
        if len(rocs) < lb:
            ranks[lb] = None
            continue
        hist = rocs[-lb:]
        ranks[lb] = round(sum(1 for v in hist if v <= cur) / len(hist) * 100, 2)
    return {"n": n, "roc": round(cur, 2), "ranks": ranks,
            "extreme": any(r is not None and r >= ROC_EXTREME_PCTILE for r in ranks.values())}


def gap_events(bars):
    """Berg's mechanical gap: the session must hold the gap for the WHOLE session.

    Upside = open above the prior high AND the low of day never trades back below it. An
    open above the prior high that fills intraday is not a gap."""
    bars = list(bars or [])
    out = []
    for i in range(1, len(bars)):
        p, c = bars[i - 1], bars[i]
        if c["o"] > p["h"] and c["l"] > p["h"]:
            out.append({"i": i, "d": c.get("d"), "dir": "up",
                        "size_pct": round((c["l"] / p["h"] - 1) * 100, 2)})
        elif c["o"] < p["l"] and c["h"] < p["l"]:
            out.append({"i": i, "d": c.get("d"), "dir": "down",
                        "size_pct": round((c["h"] / p["l"] - 1) * 100, 2)})
    return out


def breakaway_gap_to_ath(bars, min_days_below=BREAKAWAY_MIN_DAYS_BELOW):
    """Index spent >= 2 months below its ATH, then broke it with an upside gap.

    Rare and dateable, which is why it ships as a badge and not a score. Berg's ~80%
    follow-through claim is his, unverified here, and the UI says so."""
    bars = list(bars or [])
    if len(bars) < 2:
        return None
    prior, cur = bars[:-1], bars[-1]
    ath_i = max(range(len(prior)), key=lambda k: prior[k]["h"])
    ath = prior[ath_i]["h"]
    days_below = len(prior) - 1 - ath_i
    if days_below < min_days_below or cur["c"] <= ath:
        return None
    gaps = gap_events(bars[-2:])
    if not gaps or gaps[0]["dir"] != "up":
        return None
    return {"d": cur.get("d"), "ath": round(ath, 2), "ath_date": prior[ath_i].get("d"),
            "days_below": days_below, "gap_pct": gaps[0]["size_pct"]}


def rsp_spy_spread(rsp, spy, bottom_window=BOTTOM_WINDOW):
    """RSP vs SPY: the cheapest real breadth read OMEN lacks.

    Joined on the trading date, never on array position – either leg is carried forward
    independently when its fetch fails, exactly the trap the HY/IG ratio already hit.

    Bottoms are searched inside a trailing window. Unwindowed against 5y of tape this
    returns the 2022 bear lows (RSP 2022-09-30, SPY 2022-10-12) – true, and useless as a
    read on the current turn."""
    s_by_d = {p["d"]: p["c"] for p in spy or []}
    pairs = [(p["d"], p["c"], s_by_d[p["d"]]) for p in rsp or []
             if p["d"] in s_by_d and s_by_d[p["d"]]]
    if not pairs:
        return None
    ratio = [{"d": d, "c": round(r / s, 5)} for d, r, s in pairs]
    r_c = [r for _, r, _ in pairs]
    s_c = [s for _, _, s in pairs]
    last = len(pairs) - 1
    lo = max(0, len(pairs) - bottom_window)
    r_bot = min(range(lo, len(r_c)), key=lambda k: r_c[k])
    s_bot = min(range(lo, len(s_c)), key=lambda k: s_c[k])
    return {"ratio": ratio[-1]["c"], "series": ratio[-TURN_DISPLAY_BARS:],
            "days_since_ath": {"RSP": last - max(range(len(r_c)), key=lambda k: r_c[k]),
                               "SPY": last - max(range(len(s_c)), key=lambda k: s_c[k])},
            "bottom_dates": {"RSP": pairs[r_bot][0], "SPY": pairs[s_bot][0]},
            # positive = equal-weight bottomed first, which is the lead signal
            "bottom_lead_days": s_bot - r_bot}


def divergence_spread(series_by_sym):
    """Each index's distance below its OWN peak, with that peak's date, worst first.

    The late-cycle tell OMEN lacks: one index at a new high while the next is double
    digits below a peak set two months ago. It reads at lows too – a higher low against a
    lower low next door is the positive divergence."""
    out = []
    for sym, s in (series_by_sym or {}).items():
        s = list(s or [])
        if not s:
            continue
        top = max(range(len(s)), key=lambda k: s[k]["c"])
        peak = s[top]["c"]
        out.append({"sym": sym, "peak_date": s[top]["d"],
                    "off_peak_pct": round((s[-1]["c"] / peak - 1) * 100, 2) if peak else 0.0})
    out.sort(key=lambda x: x["off_peak_pct"])
    return out


def compute_turn(bars_by_sym, data, now):
    """Assemble the whole turn block from one OHLCV history per ticker.

    Publishes conclusions and a 90-bar display series, never the 10y input – see the
    fetch site in build() for why."""
    by = {}
    for sym in TURN_TICKERS:
        raw = bars_by_sym.get(sym)
        if not raw:
            continue
        bars, repaired = clean_bars(raw)
        closes = [b["c"] for b in bars]
        drop = PANIC_DROP_PCT.get(sym, PANIC_DROP_DEFAULT)
        cl = crash_low_integrity(bars, drop_pct=drop)
        entry = {"panic_drop_pct": drop, "repaired_bars": repaired, "crash_low": cl,
                 "roc": {str(n): roc_percentile(closes, n) for n in (5, 10)},
                 "breakaway": breakaway_gap_to_ath(bars),
                 "gaps": gap_events(bars)[-10:],
                 "series": [{"d": b["d"], "c": b["c"]} for b in bars[-TURN_DISPLAY_BARS:]]}
        if cl:
            entry["days_off_low"] = days_off_low(bars, cl["index"])
            u = up_days_in_window(bars, cl["index"], 19)
            u["trigger"] = up_day_trigger(u["up"], u["n"])
            entry["up_days"] = u
        else:
            entry["days_off_low"] = {"days": 0, "intact": True, "milestone": None}
            entry["up_days"] = {"up": 0, "n": 0, "trigger": None}
        by[sym] = entry

    def closes_of(sym):
        return [{"d": b["d"], "c": b["c"]} for b in (bars_by_sym.get(sym) or [])]

    breadth = {}
    if bars_by_sym.get("RSP") and bars_by_sym.get("SPY"):
        breadth["rsp_spy"] = rsp_spy_spread(closes_of("RSP"), closes_of("SPY"))
    vxn = ((data.get("vol") or {}).get("VXN") or {}).get("series") or []
    return {"params_version": TURN_PARAMS_VERSION,
            "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "by": by,
            "divergence": divergence_spread(
                {s: closes_of(s) for s in DIVERGENCE_TICKERS if bars_by_sym.get(s)}),
            "breadth": breadth,
            "vol": {"vxn_dev": vxn_deviation([p["c"] for p in vxn])},
            "active": turn_conditions(by, breadth)}


def turn_conditions(by, breadth):
    """Berg operates on clusters of simple conditions, not a composite, so the headline is
    a count: "N of 12 turning-point conditions active".

    Deliberately not blended into a 0-100 score. A mean would let four half-true
    conditions outvote one that actually fired, and the whole point of the panel is that
    the conditions are individually legible and individually falsifiable."""
    out = []

    def add(key, label, on):
        out.append({"key": key, "label": label, "on": bool(on)})

    for sym in TURN_TICKERS:
        t = (by or {}).get(sym) or {}
        cl, dl, ud = t.get("crash_low"), t.get("days_off_low"), t.get("up_days")
        add(f"{sym}:low_intact", f"{sym} crash low intact",
            cl and cl.get("fixed") and not cl.get("intraday_low_violated"))
        add(f"{sym}:day_mark", f"{sym} held the low {(dl or {}).get('days', 0)} days",
            dl and dl.get("milestone") is not None)
        add(f"{sym}:up_cluster", f"{sym} up-day cluster", (ud or {}).get("trigger"))
        add(f"{sym}:roc_rare", f"{sym} rate-of-change in the top 1%",
            any((t.get("roc") or {}).get(str(n), {}).get("extreme") for n in (5, 10)))
        add(f"{sym}:breakaway", f"{sym} breakaway gap to a new high", t.get("breakaway"))
    add("breadth:ew_led", "equal-weight bottomed before cap-weight",
        breadth and (breadth.get("rsp_spy") or {}).get("bottom_lead_days", 0) > 0)
    return {"n": sum(1 for c in out if c["on"]), "of": len(out), "conditions": out}


def vxn_deviation(closes, short=VXN_SHORT_MA, long=VXN_LONG_MA):
    """Short VXN mean vs its ~3-week mean; a sharp collapse of short vs long is the
    complacency read.

    NOTE this is a LEADING signal sitting inside `vol`, a family OMEN labels confirming.
    It is annotated wherever it renders rather than being silently averaged into a
    confirming score."""
    closes = [c for c in (closes or []) if c is not None]
    if short < 1 or long < short or len(closes) < long:
        return None
    s_ma = sum(closes[-short:]) / short
    l_ma = sum(closes[-long:]) / long
    if not l_ma:
        return None
    dev = (s_ma / l_ma - 1) * 100
    return {"short_ma": round(s_ma, 2), "long_ma": round(l_ma, 2), "dev_pct": round(dev, 2),
            "complacent": dev <= VXN_COMPLACENT_DEV}


def build():
    prev = {}
    if os.path.exists(OUT):
        try:
            with open(OUT) as f:
                prev = json.load(f)
        except Exception:
            prev = {}
    now = datetime.datetime.now(datetime.timezone.utc)
    data = {"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_date": now.strftime("%Y-%m-%d"),
            "basket": BASKET, "bench": "SPY",
            "equity": {}, "vol": {}, "skew": {}, "term": {}, "tail": {}, "credit": {},
            "fred": {}, "kalshi": {}, "kalshi_gpu": None, "manifold": [], "metaculus": None,
            "fundamentals": None, "backlog": None, "macro": None, "issuance": None,
            "insiders": {}, "gpu": None, "cot": None, "short_interest": None,
            # Rosenberg/Bernstein parameter set
            "occ": None, "spec_blur": None, "credit_div": None, "misalloc": None,
            "positioning": None, "cape": None, "corr_breadth": None, "rotation": None,
            "real_econ": None, "macro_strip": None, "fragility": None, "turn": None}

    # Deduped: XLU is both the power proxy and the utilities sector in SECTORS, and the
    # cross-check tape must not cost a second download of a series already in hand.
    tape = EQUITY + POWER_PROXY + REAL_ECON + ROTATION + list(SECTORS) + FROTH
    for sym in sorted(dict.fromkeys(tape)):
        try:
            data["equity"][sym] = yahoo_series(sym)
            print(f"equity {sym}: {len(data['equity'][sym])} pts")
        except Exception as e:
            carry_sub(data, prev, "equity", sym, e)

    # market caps for the stack-comparison card (ETFs have no cap; skip the benchmarks)
    cap_syms = [s for s in EQUITY if s not in ("SOXX", "SPY")]
    try:
        caps = nasdaq_caps(cap_syms)
        data["caps"] = {"asof": data["updated"], "by": caps}
        print(f"caps: {len(caps)}/{len(cap_syms)} names (NVDA ${caps.get('NVDA', {}).get('cap', 0) / 1e12:.2f}T)")
        missing = sorted(set(cap_syms) - set(caps))
        if missing:
            print(f"caps missing: {missing}")
    except Exception as e:
        carry(data, prev, "caps", e)   # last good snapshot, original asof intact

    for ysym, name in VOL.items():
        try:
            s = yahoo_series(ysym, "3mo")
            data["vol"][name] = {"last": s[-1]["c"], "series": s}
            print(f"vol {name}: {s[-1]['c']}")
        except Exception as e:
            carry_sub(data, prev, "vol", name, e)

    # ---- Berg turn block (handover 2026-08-13) ----
    # Runs after the vol loop on purpose: D2 reads data["vol"]["VXN"]["series"], and
    # computing this earlier would silently publish a null deviation every run.
    #
    # One 10y OHLCV call per ticker serves every turn metric – the bars feed the crash-low
    # and gap logic, the closes off the same bars feed the ROC percentile ranks. 10y and
    # not 5y because range=5y returns 1,254 bars, six short of the 1,260-day lookback, so
    # the long rank would be None on every ticker forever. The raw bars stay local and are
    # never written: 5y OHLCV across eight tickers measured 752 KB against a 178 KB file.
    turn_bars = {}
    for sym in sorted(set(TURN_TICKERS) | set(DIVERGENCE_TICKERS)
                      | set(THRUST_TICKERS) | {"RSP", "SPY"}):
        try:
            turn_bars[sym] = yahoo_bars(sym, "10y")
        except Exception as e:
            print(f"turn bars {sym}: FAIL {e}")
    try:
        turn = compute_turn(turn_bars, data, now)
        if turn["by"] or turn["divergence"]:
            data["turn"] = turn
            a = turn["active"]
            print(f"turn: {a['n']}/{a['of']} conditions active "
                  f"({len(turn['by'])} tickers, params {TURN_PARAMS_VERSION})")
            for sym, t in sorted(turn["by"].items()):
                cl = t.get("crash_low")
                if cl:
                    print(f"turn {sym}: panic {cl['date']} {cl['decline_pct']}% · held "
                          f"{t['days_off_low']['days']}d · close-low {cl['to_close_low_pct']}% "
                          f"intraday {cl['to_intraday_low_pct']}% · "
                          f"regime_change={cl['regime_change']}")
                else:
                    print(f"turn {sym}: no qualifying panic low at -{t['panic_drop_pct']}%")
        else:
            # every leg failed: hold the last computed block rather than publish an empty
            # panel, same policy as misalloc/macro_strip above
            data["turn"] = prev.get("turn")
            print("turn: no usable tape, carried previous block")
    except Exception as e:
        carry(data, prev, "turn", e)

    for sym in SKEW_SYMS:
        try:
            # Two windows rather than one whole-chain download: the near expiries for
            # skew/term, the ~1y ones for the tail. The tail window is fetched inside its
            # own try so a LEAPS failure cannot take skew and term down with it.
            spot, near = nasdaq_options(sym, *SKEW_WINDOW)
            sk, term = skew_and_term(sym, spot, near)
            try:
                _, far = nasdaq_options(sym, *TAIL_WINDOW)
                tail = options_tail(sym, spot, far, prev.get("tail", {}).get(sym))
                if tail:
                    data["tail"][sym] = tail
                    trig = tail["levels"][-1]
                    print(f"tail {sym}: P({trig['pct']}% @ {tail['dte']}d) = "
                          f"{trig['p'] * 100:.1f}%" if trig["p"] is not None else f"tail {sym}: no quote at trigger")
            except Exception as e:
                carry_sub(data, prev, "tail", sym, e)
            if sk:
                hist = (prev.get("skew", {}).get(sym, {}) or {}).get("history", [])
                hist = [h for h in hist if h["date"] != sk["date"]]
                hist.append({"date": sk["date"], "rr": sk["rr"], "atm": sk["atm"]})
                sk["history"] = hist[-120:]
                data["skew"][sym] = sk
                print(f"skew {sym}: RR={sk['rr']} (dte {sk['dte']})")
            if term:
                thist = (prev.get("term", {}).get(sym, {}) or {}).get("history", [])
                thist = [h for h in thist if h["date"] != term["date"]]
                thist.append({"date": term["date"], "ratio": term["ratio"]})
                term["history"] = thist[-120:]
                data["term"][sym] = term
                print(f"term {sym}: {term['ratio']} ({term['front_dte']}d/{term['back_dte']}d)")
        except Exception as e:
            # the near-window download feeds skew and term; losing it loses the tail too,
            # since the tail is priced off the same spot
            print(f"skew {sym}: FAIL {e}")
            for section in ("skew", "term", "tail"):
                carry_sub(data, prev, section, sym)

    for sym in CREDIT:
        try:
            data["credit"][sym] = yahoo_series(sym)
            print(f"credit {sym}: {data['credit'][sym][-1]['c']}")
        except Exception as e:
            carry_sub(data, prev, "credit", sym, e)

    for series_id, name in FRED.items():
        try:
            s = fred_series(series_id)
            data["fred"][name] = {"last": s[-1]["c"], "last_date": s[-1]["d"], "series": s}
            print(f"fred {name}: {s[-1]['c']} ({s[-1]['d']})")
        except Exception as e:
            carry_sub(data, prev, "fred", name, e)

    try:
        data["kalshi"] = kalshi()
        print(f"kalshi: {len(data['kalshi']['markets'])} markets, authed={data['kalshi']['authed']}")
    except Exception as e:
        if not carry(data, prev, "kalshi", e):
            data["kalshi"] = {"authed": False, "markets": [], "note": str(e)}

    try:
        data["kalshi_gpu"] = kalshi_gpu()
        for c in data["kalshi_gpu"]["chips"]:
            imp = f"${c['implied']:.2f}" if c["implied"] else f"n/a ({c['note']})"
            print(f"kalshi_gpu {c['chip']}: ref ${c['ref']} ({c['ref_date']}) "
                  f"month-end {imp}, {c['strikes']} usable strikes")
    except Exception as e:
        carry(data, prev, "kalshi_gpu", e)

    try:
        data["manifold"] = manifold()
        print(f"manifold: {len(data['manifold'])} markets")
    except Exception as e:
        carry(data, prev, "manifold", e)

    try:
        data["metaculus"] = metaculus()
        print(f"metaculus: {len(data['metaculus']['questions'])} questions, enabled={data['metaculus']['enabled']}")
    except Exception as e:
        carry(data, prev, "metaculus", e)

    try:
        data["fundamentals"] = fundamentals()
        if data["fundamentals"]:
            f = data["fundamentals"]
            print(f"fundamentals: {len(f['quarters'])} quarters, latest capex ${f['capex_b'][-1]}B")
    except Exception as e:
        carry(data, prev, "fundamentals", e)

    try:
        data["issuance"] = issuance()
        if data["issuance"]:
            t = data["issuance"]["totals"]
            print(f"issuance: debt ${t['debt_ttm_b']}B, equity ${t['equity_ttm_b']}B TTM")
    except Exception as e:
        carry(data, prev, "issuance", e)

    try:
        data["backlog"] = backlog()
        if data["backlog"]:
            b = data["backlog"]
            print(f"backlog: {len(b['names'])} filers, ${b['total_latest_b']:.0f}B combined")
    except Exception as e:
        carry(data, prev, "backlog", e)

    try:
        gdp = (data["fred"].get("GDP") or {}).get("series")
        data["macro"] = macro_capex_gdp(data.get("fundamentals"), gdp)
        if data["macro"]:
            m = data["macro"]
            print(f"macro: capex {m['pct_gdp'][-1]}% of GDP, {m['growth_share'][-1]}% of GDP growth ({m['quarters'][-1]})")
    except Exception as e:
        carry(data, prev, "macro", e)

    try:
        data["gpu"] = gpu_spot(prev.get("gpu"))
        if data["gpu"]:
            print(f"gpu: H100 median ${data['gpu']['median_dph']}/hr ({data['gpu']['n_offers']} offers)")
    except Exception as e:
        carry(data, prev, "gpu", e)

    try:
        data["valuation"] = nvda_valuation() or prev.get("valuation")
        if data.get("valuation"):
            v = data["valuation"]
            print(f"valuation: NVDA trailing P/E {v['pe_ttm']} = p{v['pct_10y']} "
                  f"of 10y ({v['n_months']} months, EPS ttm {v['eps_ttm']})")
    except Exception as e:
        carry(data, prev, "valuation", e)

    try:
        data["insiders"] = edgar_insiders()
    except Exception as e:
        carry(data, prev, "insiders", e)

    try:
        data["cot"] = cot() or prev.get("cot")
        if data.get("cot"):
            for c in data["cot"]["contracts"]:
                print(f"cot {c['key']}: net {c['net']:+d} ({c['net_pct_oi']:+.1f}% OI) "
                      f"pctile {c['pctile']} z {c['z']} [{c['n_weeks']}w]")
    except Exception as e:
        carry(data, prev, "cot", e)

    try:
        data["short_interest"] = short_interest() or prev.get("short_interest")
        if data.get("short_interest"):
            for n in data["short_interest"]["names"]:
                print(f"short_interest {n['sym']}: {n['si'] / 1e6:.0f}M sh "
                      f"dtc {n['dtc']} chg {n['chg_pct']}% ({n['date']})")
    except Exception as e:
        carry(data, prev, "short_interest", e)

    # ---------- Rosenberg/Bernstein parameter set ----------
    # Raw pulls first, each isolated: these are five unrelated publishers, and one of them
    # being down must not cost the other four. Only summaries and trimmed histories are
    # kept — the CAPE table alone is 1,867 monthly points, and market-data.json is
    # rewritten into R2 every 30 minutes.
    raw = {}
    for key, fn in (("c30_dc", census_dc_construction), ("margin", finra_margin),
                    ("cape", shiller_cape)):
        try:
            raw[key] = fn()
            print(f"{key}: {len(raw[key] or [])} pts"
                  + (f", last {raw[key][-1]}" if raw[key] else ""))
        except Exception as e:
            raw[key] = None
            print(f"{key}: FAIL {e}")

    try:
        data["occ"] = occ_volume() or prev.get("occ")
        if data.get("occ"):
            print(f"occ: {data['occ']['options'] / 1e6:.1f}M contracts, "
                  f"{data['occ']['pct_of_range']}% of 52w range")
    except Exception as e:
        carry(data, prev, "occ", e)

    try:
        data["spec_blur"] = spec_blur() or prev.get("spec_blur")
        if data.get("spec_blur"):
            s = data["spec_blur"]
            print(f"spec_blur: {s['ratio']}x (${s['spec_usd'] / 1e6:.0f}M entertainment "
                  f"vs ${s['hedge_usd'] / 1e6:.0f}M hedging)")
    except Exception as e:
        carry(data, prev, "spec_blur", e)

    F = data.get("fred", {})
    fs = lambda name: (F.get(name) or {}).get("series")     # noqa: E731 - one-liner accessor
    ai_basket = basket_series(data.get("equity", {}), BASKET)

    # A. credit family extensions
    try:
        div = credit_price_divergence(ai_basket, fs("HY_OAS"), fs("IG_OAS"))
        if div:
            clock = credit_clock((prev.get("server_gauge") or {}).get("fam", {}).get("credit"),
                                 (prev.get("credit_div") or {}).get("clock"),
                                 now.strftime("%Y-%m-%d"))
            div["clock"] = clock
            data["credit_div"] = div
            print(f"credit_div: basket {div['basket_vs_high_pct']}% off high, "
                  f"HY−IG {div['hy_ig_gap']}pp ({div['gap_change_bp']:+}bp/"
                  f"{DIVERGENCE_WEEKS}w) diverging={div['diverging']}")
    except Exception as e:
        carry(data, prev, "credit_div", e)

    # B. capital misallocation
    try:
        mis = {"dc_housing": dc_housing_ratio(raw.get("c30_dc"), fs("RES_CONS")),
               "ex_ai_capex": ex_ai_capex(fs("INV_EQUIP"), fs("INV_IP"),
                                          data.get("fundamentals")),
               "gdp_ex_ai": gdp_ex_ai(fs("GDP_GROWTH"), fs("REAL_GDP"),
                                      data.get("fundamentals"))}
        # The C30 workbook only publishes ~13 months of columns, so the ratio's history
        # is grown across runs the way the skew/term histories are, not re-derived.
        if mis["dc_housing"]:
            old = ((prev.get("misalloc") or {}).get("dc_housing") or {}).get("history") or []
            seen = {p["d"] for p in mis["dc_housing"]["history"]}
            mis["dc_housing"]["history"] = sorted(
                [p for p in old if p["d"] not in seen] + mis["dc_housing"]["history"],
                key=lambda p: p["d"])[-120:]
        # prune_payload strips the BEA/Census input series from the published file, so a
        # failed fetch next run cannot rebuild this from a carry-forward — hold the last
        # computed block instead. Same reason on macro_strip and real_econ below.
        if not any(mis.values()):
            data["misalloc"] = prev.get("misalloc")
        else:
            data["misalloc"] = mis
            dch, exa = mis["dc_housing"], mis["ex_ai_capex"]
            if dch:
                print(f"misalloc: DC/housing {dch['ratio']} ({dch['yoy_pct']}% YoY), "
                      f"DC ${dch['dc_saar_b']}B vs residential ${dch['res_saar_b']}B")
            if exa:
                print(f"misalloc: ex-AI capex ${exa['ex_ai_b']}B {exa['yoy_pct']}% YoY "
                      f"({exa['quarter']}, AI is {exa['ai_share_pct']}% of the line)")
    except Exception as e:
        carry(data, prev, "misalloc", e)

    # C. positioning & sentiment extremes
    try:
        pos = {"hh_equity_fin": series_percentile(fs("HH_EQ_FIN")),
               "hh_equity_tot": series_percentile(fs("HH_EQ_TOT")),
               "margin_debt": None, "survey": SURVEY_MANUAL}
        if raw.get("margin"):
            mseries = raw["margin"]
            vals = [p["c"] for p in mseries]
            yoy = None
            if len(mseries) > 12 and mseries[-13]["c"]:
                yoy = round((mseries[-1]["c"] / mseries[-13]["c"] - 1) * 100, 1)
            pos["margin_debt"] = {
                "usd_m": mseries[-1]["c"], "asof": mseries[-1]["d"][:7],
                "yoy_pct": yoy, "pctile": pctile_rank(vals, vals[-1]),
                "history": [{"d": p["d"], "c": p["c"]} for p in mseries[-120:]]}
        if any(v for k, v in pos.items() if k != "survey"):
            data["positioning"] = pos
            hh = pos["hh_equity_fin"]
            if hh:
                print(f"positioning: household equities {hh['value']}% of financial "
                      f"assets, p{hh['pctile']} of {hh['n']}q ({hh['asof']})")
            if pos["margin_debt"]:
                print(f"positioning: margin debt ${pos['margin_debt']['usd_m'] / 1e6:.2f}T "
                      f"({pos['margin_debt']['yoy_pct']}% YoY)")
    except Exception as e:
        carry(data, prev, "positioning", e)

    # E. valuation / contagion cross-checks
    try:
        cape = cape_sigma(raw.get("cape"))
        if cape and raw.get("cape"):
            cape["history"] = [{"d": p["d"], "c": p["c"]} for p in raw["cape"][-240:]]
        data["cape"] = cape or prev.get("cape")
        if data.get("cape"):
            print(f"cape: {data['cape']['cape']} = {data['cape']['sigma']}σ, "
                  f"p{data['cape']['pctile']} of {data['cape']['epoch']}+")
    except Exception as e:
        carry(data, prev, "cape", e)

    try:
        data["corr_breadth"] = correlation_breadth(data.get("equity", {}), ai_basket, SECTORS)
        if data.get("corr_breadth"):
            c = data["corr_breadth"]
            print(f"corr_breadth: {c['n_hot']}/{c['n_total']} sectors > {CORR_HOT} "
                  f"(uncorrelated: {', '.join(c['cool']) or 'none'})")
    except Exception as e:
        carry(data, prev, "corr_breadth", e)

    try:
        data["rotation"] = rotation_rs(data.get("equity", {}), ai_basket)
        if data.get("rotation"):
            print(f"rotation: ACWX vs AI basket {data['rotation']['change_pct']:+}% "
                  f"over {ROTATION_WINDOW}d")
    except Exception as e:
        carry(data, prev, "rotation", e)

    try:
        E = data.get("equity", {})
        real = {"builders": [{"sym": s, "dd_pct": round(drawdown(E[s]), 2)}
                             for s in REAL_ECON if E.get(s) and drawdown(E[s]) is not None],
                "housing_starts": series_percentile(fs("HOUST")),
                "auto_sales": series_percentile(fs("ALTSALES"))}
        if not (real["builders"] or real["housing_starts"]):
            data["real_econ"] = prev.get("real_econ")
        else:
            data["real_econ"] = real
            print("real_econ: " + ", ".join(f"{b['sym']} {b['dd_pct']}%"
                                            for b in real["builders"]))
    except Exception as e:
        carry(data, prev, "real_econ", e)

    # F. macro context strip — backdrop only, never a gauge input
    try:
        E = data.get("equity", {})
        gold, silver = E.get("GLD"), E.get("SLV")
        gs = None
        if gold and silver:
            sv = {p["d"]: p["c"] for p in silver}
            line = [g["c"] / sv[g["d"]] for g in gold if sv.get(g["d"])]
            if len(line) > 8:
                gs = {"ratio": round(line[-1], 2), "pctile": pctile_rank(line, line[-1]),
                      "n": len(line)}
        strip = {"taylor": taylor_gap(fs("FEDFUNDS"), fs("TRIM_PCE"),
                                      fs("UNRATE"), fs("NROU")),
                 "trimmed_pce": series_percentile(fs("TRIM_PCE")),
                 "term_premium": series_percentile(fs("TERM_PREM")),
                 "gold_silver": gs}
        if not any(strip.values()):
            data["macro_strip"] = prev.get("macro_strip")
        else:
            data["macro_strip"] = strip
            if strip["taylor"]:
                t = strip["taylor"]
                print(f"macro_strip: Taylor rule {t['rule_pct']}% vs FFR {t['actual_pct']}% "
                      f"(gap {t['gap_pp']:+}pp, {t['stance']})")
    except Exception as e:
        carry(data, prev, "macro_strip", e)

    try:
        data["fragility"] = compute_fragility(data) or prev.get("fragility")
        if data.get("fragility"):
            f = data["fragility"]
            print(f"fragility: {f['score']} over {f['n_families']} families "
                  + " ".join(f"{k}={v}" for k, v in f["fam"].items() if v is not None))
    except Exception as e:
        carry(data, prev, "fragility", e)

    # Server-side gauge + regime, embedded so the landing page and the monitor can never
    # disagree about the headline regime. This is also the run's single Polymarket read:
    # it is returned to main() and threaded into the snapshot and the alert, so all three
    # are computed from the same prices. Fetching it three times (as this used to) let the
    # gauge in the JSON, the row in snapshots.csv and the regime an alert fires on each see
    # a different tape.
    price = None
    try:
        price = poly_prices()
        score, fam = compute_gauge(data, price)
        lead, conf = gauge_groups(fam)
        mkt_level = sleeve_level(price, "mkt")
        data["server_gauge"] = {
            "score": round(score, 1) if score is not None else None,
            "lead": round(lead, 1) if lead is not None else None,
            "conf": round(conf, 1) if conf is not None else None,
            "fam": {k: (round(v, 1) if v is not None else None) for k, v in fam.items()},
            "regime": compute_regime(score, price),
            "bubble": price.get(BUBBLE_ID),
            # gauge context: still the crash basket (= Bear's MKT sleeve), not the composite
            "crash_level": round(mkt_level, 2) if mkt_level is not None else None,
            "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        print(f"server gauge: {data['server_gauge']['score']} ({data['server_gauge']['regime']}) "
              f"lead {data['server_gauge']['lead']} conf {data['server_gauge']['conf']}")
    except Exception as e:
        carry(data, prev, "server_gauge", e)   # stale, but its own `at` stamp says so

    prune_payload(data)
    with open(OUT, "w") as f:
        json.dump(data, f)
    print("written:", OUT)
    return data, price


def prune_payload(data):
    """Drop the raw series that exist only to feed a derived block.

    Runs after every computation and immediately before the write, so the arithmetic sees
    the full history and the file carries the conclusion. The trade is deliberate: a feed
    that fails on the next run cannot rebuild its block from a carried-forward series,
    which is why each affected block falls back to its own previous value instead."""
    equity = data.get("equity") or {}
    for sym in TRANSIENT_EQUITY:
        equity.pop(sym, None)
    for name in FRED_SUMMARY_ONLY:
        row = (data.get("fred") or {}).get(name)
        if isinstance(row, dict):
            row.pop("series", None)
    return data


def write_bundle():
    """Emit market-data.js so the dashboard works when opened directly via file://.
    Browsers block fetch() of sibling files under file://, but a <script src> tag loads
    fine; the page falls back to these globals when fetch fails."""
    try:
        data_txt = open(OUT).read()
    except OSError:
        return
    try:
        snap_txt = open(SNAP).read()
    except OSError:
        snap_txt = ""
    with open(BUNDLE, "w") as f:
        f.write("window.__MARKET_DATA__=" + data_txt + ";\n")
        f.write("window.__SNAPSHOTS_CSV__=" + json.dumps(snap_txt) + ";\n")
    print("written:", BUNDLE)


def main():
    args = sys.argv[1:]
    do_snap = "--snapshot" in args
    do_alert = "--alert" in args
    watch = None
    if "--watch" in args:
        i = args.index("--watch")
        watch = int(args[i + 1]) if i + 1 < len(args) and args[i + 1].isdigit() else 600
    while True:
        reset_retry_budget()
        try:
            data, price = build()
            if do_snap:
                append_snapshot(data, price)
            if do_alert:
                check_alert(data, price)
        except Exception as e:
            print("build error:", e)
        write_bundle()
        if not watch:
            break
        print(f"sleeping {watch}s (Ctrl-C to stop)…")
        time.sleep(watch)


if __name__ == "__main__":
    main()
