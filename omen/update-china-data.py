#!/usr/bin/env python3
"""Refresh china-data.json for the China AI Substitution Monitor.

Stdlib only, same pattern as update-market-data.py. The page works without
this file (it embeds a dated snapshot and fetches the fast-moving data live,
client-side); this script refreshes the slow-moving fields that have no
CORS-open API:

  - LMArena leaderboard            : lmarena-ai/leaderboard-dataset on Hugging Face
                                     (CC BY 4.0), arena.ai HTML scrape as fallback
  - GitHub star velocity           : server-side baseline in china-history.json; the
                                     repo basket itself is rediscovered each run via
                                     the search API (active repos only) and published
                                     as github.repos, because a pinned list decays into
                                     last generation's abandoned repos
  - OpenRouter weekly share        : appended to china-snapshots.csv (durable history)
  - Daily metrics history          : composite index, SPI, per-family shares and the
                                     frontier price gap appended to china-metrics.csv
                                     (one row per UTC day) so the page can chart
                                     trajectories, not just snapshots
  - Vercel AI Gateway lab share    : leaderboard-export endpoint (CC BY 4.0, 24h cache)
                                     - the second router, de-biases the OpenRouter SPI
  - Ollama pull counts             : ollama.com/library scrape; local/self-hosted
                                     adoption that no router or HF download sees
  - Kalshi prediction markets      : public trade-api v2 (no CORS -> fetched here)
  - HF fine-tune trees             : model-page scrape; ecosystem gravity per base model
  - PyPI SDK downloads             : pypistats.org weekly per-package totals
  - Google Trends search interest  : Chinese apps' share of US AI-assistant searches
                                     (unofficial API; datacenter IPs often 429 -> the
                                     previous trends value is carried forward)
  - Artificial Analysis scores     : free Data API when ARTIFICIAL_ANALYSIS_API_KEY is
                                     set (attribution required); MANUAL fallback below
  - Cloudflare Radar gen-AI ranks  : consumer traffic by 1.1.1.1 DNS volume when
                                     CF_RADAR_TOKEN is set (needs Radar read scope);
                                     skipped cleanly without it
  - AA frontier gap                : monthly US-vs-CN frontier intelligence series,
                                     lag-in-months and near-frontier price ratio,
                                     derived from the same AA Data API call (key only)
  - Epoch AI supply-side           : GPU-cluster capacity share, quarterly accelerator
                                     output by designer, notable-model release cadence
                                     (keyless CC-BY CSVs, refetched weekly not per-run)

Consumer-app figures fall back to MANUAL below when no live source is reachable.

Usage:
  python3 update-china-data.py                # one shot
  python3 update-china-data.py --watch 86400  # daily loop
After running, redeploy the site folder so the deployed china-data.json updates.
"""
import io, json, os, re, csv, html, sys, time, calendar, urllib.request, urllib.parse, urllib.error, http.cookiejar
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) omen-china-monitor/1.0"}

# ---- fields with no machine-readable source: update by hand when re-verified ----
MANUAL = {
    "artificial_analysis": {"cn_best": "GLM-5.2", "cn_score": 51,
                            "us_best": "Claude Fable 5", "us_score": 60, "asof": "2026-07-12"},
    # static fallback only - google_trends() overrides this when it succeeds
    "search_consumer": {"western_share_pct": 1, "asof": "2026-04",
                        "note": "Goodie AI-referral report: DeepSeek+Qwen <1% of Western AI referral traffic."},
    # static fallback only - compute_apps() (iOS RSS + Android Play charts) overrides this
    "apps": {"score": 20, "asof": "2026-01",
             "note": "Qwen app >200M MAU, Doubao >100M DAU, DeepSeek ~82M WAU - overwhelmingly domestic."},
}

# GitHub star velocity. The basket used to be a hardcoded list of flagship repos, which
# quietly became a list of *last generation's* flagship repos: by Aug 2026 five of the
# seven had not been pushed to in six months (DeepSeek-V3 last touched 2025-08, MiMo
# 2025-06), so the family measured the star drift of abandoned repos and read 11.8
# stars/day - 3.9 out of 100 on a 15%-weight gauge family, which is a measurement
# artefact, not an adoption signal. The seed below is only a fallback now; each run
# rediscovers each lab's currently-active repos via the search API.
GH_ORGS = ["deepseek-ai", "QwenLM", "zai-org", "MoonshotAI", "MiniMax-AI", "XiaomiMiMo"]
GH_SEED = ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "QwenLM/Qwen3", "zai-org/GLM-5",
           "MoonshotAI/Kimi-K2", "MiniMax-AI/MiniMax-M2", "XiaomiMiMo/MiMo"]
GH_PER_ORG = 2          # top-2 by stars keeps one org's monorepo from owning the basket
GH_ACTIVE_DAYS = 180    # "active" = pushed within this window
# Awesome-lists, docs and demo collections accumulate stars on a completely different
# curve from a model release and would swamp the velocity signal.
GH_EXCLUDE = re.compile(r"awesome|cookbook|docs?$|-docs|examples?$|tutorial|paper|guide", re.I)
CN_AUTHORS = {"deepseek", "qwen", "z-ai", "thudm", "moonshotai", "minimax", "xiaomi", "tencent",
              "stepfun", "baidu", "bytedance-seed", "baai", "inclusionai", "01-ai", "internlm", "openbmb"}
US_AUTHORS = {"openai", "anthropic", "google", "meta-llama", "x-ai", "nvidia", "microsoft", "amazon",
              "perplexity", "poolside", "inception", "liquid", "allenai", "ibm-granite", "openrouter"}

# Hugging Face download share. Fetched here server-side because HF's API is not
# reliably CORS-open to arbitrary browser origins (the live site's client fetch is
# blocked), so the page reads these totals from china-data.json instead.
HF_CN_ORGS = ["deepseek-ai", "Qwen", "moonshotai", "zai-org", "MiniMaxAI", "tencent", "XiaomiMiMo", "stepfun-ai"]
HF_US_ORGS = ["meta-llama", "openai", "google", "microsoft", "nvidia", "allenai"]
HF_US_FAMILY = re.compile(r"llama|gemma|gpt-oss|phi-|phi\d|nemotron|olmo|granite|dbrx", re.I)


def get(url, timeout=30, headers=None):
    h = {**UA, **(headers or {})}
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read()


def jget(url, timeout=30, headers=None):
    return json.loads(get(url, timeout, headers))


# LMArena's official leaderboard snapshots (CC BY 4.0). Orgs are lowercase here,
# unlike the display names the arena.ai HTML fallback sees.
LMARENA_DATASET_ROWS = ("https://datasets-server.huggingface.co/rows"
                        "?dataset=lmarena-ai/leaderboard-dataset&config=text_style_control"
                        "&split=latest&offset=0&length=100")
CN_ARENA_ORGS_LC = {o.lower() for o in
                    ("Alibaba", "Qwen", "DeepSeek", "Z.ai", "Zhipu", "Moonshot", "MoonshotAI",
                     "MiniMax", "Xiaomi", "Tencent", "StepFun", "Baidu", "ByteDance", "01.AI",
                     "iFlytek", "Meituan", "InternLM", "OpenBMB")}


def arena_summary(rows):
    """Rank-sorted [{model, org, rank, elo}] -> the lmarena dict the page renders."""
    rows = sorted(rows, key=lambda r: r["rank"])
    def is_cn(org):
        o = org.lower()
        return o in CN_ARENA_ORGS_LC or o.removesuffix(" ai") in CN_ARENA_ORGS_LC
    cn = [r for r in rows if is_cn(r["org"])]
    if not cn:
        raise ValueError("no Chinese models found on leaderboard")
    best, leader = cn[0], rows[0]
    return {"best_model": best["model"], "best_org": best["org"], "best_rank": best["rank"],
            "best_score": best["elo"], "us_leader": leader["model"], "us_leader_score": leader["elo"],
            "top10": sum(1 for r in cn if r["rank"] <= 10), "top20": sum(1 for r in cn if r["rank"] <= 20),
            # Per-model Elo feeds the page's price-vs-quality scatter, which joins
            # these names against OpenRouter's flagship price lines client-side.
            "models": [{"model": r["model"], "org": r["org"], "elo": r["elo"], "cn": is_cn(r["org"])}
                       for r in rows[:60]]}


def lmarena_dataset():
    """Primary source: the official leaderboard-dataset on HF (datasets-server API)."""
    d = jget(LMARENA_DATASET_ROWS, timeout=60)
    rows = [{"model": r["row"]["model_name"], "org": r["row"]["organization"],
             "rank": int(r["row"]["rank"]), "elo": round(r["row"]["rating"]),
             "asof": r["row"].get("leaderboard_publish_date")}
            for r in d["rows"] if r["row"].get("category") == "overall"]
    if not rows:
        raise ValueError("no overall-category rows in dataset")
    out = arena_summary(rows)
    out["asof"] = rows[0]["asof"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out["source"] = "lmarena-dataset"
    return out


def arena():
    """Fallback: parse the server-rendered arena.ai text leaderboard."""
    page = get("https://arena.ai/leaderboard/text", timeout=60).decode("utf-8", "replace")
    rows = []
    for chunk in page.split("<tr")[1:]:
        m = re.search(r'title="([^"]+)"', chunk)
        if not m:
            continue
        org = re.search(r'truncate text-xs">([^<]+)<', chunk)
        rank = re.search(r">(\d{1,3})<", chunk)
        elo = re.search(r">(\d{4})<", chunk)
        if org and rank and elo:
            rows.append({"model": html.unescape(m.group(1)), "org": org.group(1).split("·")[0].strip(),
                         "rank": int(rank.group(1)), "elo": int(elo.group(1))})
    if not rows:
        raise ValueError("no leaderboard rows parsed")
    out = arena_summary(rows)
    out["asof"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out["source"] = "arena-scrape"
    return out


def gh_headers():
    """api.github.com allows 60 req/hr unauthenticated, per egress IP - shared CI
    runners blow through that, which is how all seven repos once failed at once.
    Any token (Actions hands out `github.token` free) raises the ceiling to 1,000/hr."""
    tok = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def gh_active_repos(org, now=None):
    """The org's most-starred repos that are still being pushed to.

    Ranked by stars rather than by recency: a lab's flagship release is both, but
    ranking by recency alone surfaces whatever CI-config repo was touched this morning.
    """
    now = time.time() if now is None else now
    d = jget(f"https://api.github.com/search/repositories?q=org:{org}+fork:false"
             f"&sort=stars&order=desc&per_page=20", headers=gh_headers())
    picks = []
    for r in d.get("items", []):
        name = r.get("full_name") or ""
        if GH_EXCLUDE.search(name.split("/")[-1]):
            continue
        try:
            pushed = calendar.timegm(time.strptime(r["pushed_at"], "%Y-%m-%dT%H:%M:%SZ"))
        except (KeyError, ValueError):
            continue
        if (now - pushed) / 86400 > GH_ACTIVE_DAYS:
            continue
        picks.append(name)
        if len(picks) >= GH_PER_ORG:
            break
    return picks


def github_basket(now=None):
    """Rediscover the flagship-repo basket. Falls back to the static seed.

    A partial result is still used: one org's search failing costs that lab's repos for
    the run, and the velocity code below only measures repos present in both snapshots,
    so a shrinking basket cannot sign-flip the rate.
    """
    repos, failed = [], []
    for org in GH_ORGS:
        try:
            found = gh_active_repos(org, now=now)
            repos += found
            if not found:
                failed.append(org)
        except Exception as e:
            print(f"  github search {org}: {e}", file=sys.stderr)
            failed.append(org)
    if not repos:
        print("  every org search failed - falling back to the static seed basket",
              file=sys.stderr)
        return GH_SEED, "seed"
    if failed:
        print(f"  no active repos found for: {', '.join(failed)}", file=sys.stderr)
    return sorted(repos), "search"


def github_velocity(hist, repos=None):
    """Stars now vs last run -> (stars/day across the basket, stars, per-repo stars/day).

    The per-repo rates are published in china-data.json so the page's Δ/day column
    works on a first visit instead of waiting for a browser-local baseline to age."""
    now = time.time()
    stars = {}
    for repo in (GH_SEED if repos is None else repos):
        try:
            stars[repo] = jget(f"https://api.github.com/repos/{repo}",
                               headers=gh_headers())["stargazers_count"]
        except Exception as e:
            print(f"  github {repo}: {e}", file=sys.stderr)
    if not stars:
        # A run where every repo failed must not be written down as a baseline. One
        # did: it stored 0 stars, and because the reseed below only fired when the
        # key was *absent*, nothing could ever overwrite it - the page reported
        # -282,777 stars/day for five days straight.
        return None, stars, None
    prev = hist.get("github")
    base = (prev or {}).get("stars")
    per_day = None
    vel = None
    if base and now - prev["t"] >= 20 * 3600:
        # Only repos in both snapshots: when a fetch fails the basket has not lost
        # every star that repo held, we just cannot see it this run. Undercounting
        # a rate by one small repo is survivable; sign-flipping it is not.
        shared = [r for r in stars if r in base]
        days = (now - prev["t"]) / 86400
        if shared:
            per_day = sum(stars[r] - base[r] for r in shared) / days
            vel = {r: round((stars[r] - base[r]) / days, 1) for r in shared}
        hist["github"] = {"t": now, "stars": stars}
    elif not base:
        # seed, or reseed a baseline an all-failed run left empty; keep it until it
        # ages past 20h so frequent CI runs don't reset it to "now" every time and
        # never produce a velocity
        hist["github"] = {"t": now, "stars": stars}
    return per_day, stars, vel


def pick_github_velocity(per_day, prev, stars):
    """Fresh measured velocity, else the previous run's value. A measurement only
    happens on the ~1 run/day where the baseline has aged past 20h; without the
    carry, every other run drops the key and the page's GitHub gauge family goes
    dark for most of the day."""
    if per_day is not None:
        return round(per_day, 1)
    vel = (prev or {}).get("github_stars_per_day")
    total = sum(stars.values())
    if vel is not None and total and abs(vel) > total:
        # The basket cannot move more stars in a day than it holds, so this came from
        # a run measured against a broken baseline. Drop it rather than carry it
        # forever - with no basket to check against (a total outage) carry as usual.
        return None
    return vel


def huggingface():
    """30-day download totals by lab. Returns the shape the page's renderHF expects."""
    def org_repos(org):
        d = jget(f"https://huggingface.co/api/models?author={org}&sort=downloads&direction=-1&limit=50")
        return [{"id": m["id"], "dl": m.get("downloads") or 0} for m in d]
    cn_orgs, us_orgs = [], []
    for org in HF_CN_ORGS:
        try:
            dl = sum(m["dl"] for m in org_repos(org))
            if dl:
                cn_orgs.append({"org": org, "dl": dl})
        except Exception as e:
            print(f"  hf {org}: {e}", file=sys.stderr)
    for org in HF_US_ORGS:
        try:
            dl = sum(m["dl"] for m in org_repos(org) if HF_US_FAMILY.search(m["id"]))
            if dl:
                us_orgs.append({"org": org, "dl": dl})
        except Exception as e:
            print(f"  hf {org}: {e}", file=sys.stderr)
    cn = sum(o["dl"] for o in cn_orgs)
    us = sum(o["dl"] for o in us_orgs)
    if not cn or not us:
        raise ValueError("HF returned no usable data on one side")
    cn_orgs.sort(key=lambda o: -o["dl"])
    us_orgs.sort(key=lambda o: -o["dl"])
    return {"cnOrgs": cn_orgs, "usOrgs": us_orgs, "cn": cn, "us": us}


def openrouter_week():
    d = jget("https://openrouter.ai/api/frontend/v1/rankings/market-share")["data"]
    last = d[-1]
    cn = sum(v for k, v in last["ys"].items() if k in CN_AUTHORS)
    us = sum(v for k, v in last["ys"].items() if k in US_AUTHORS)
    tot = sum(last["ys"].values())
    return {"week": last["x"], "cn_share": round(cn / tot, 4), "us_share": round(us / tot, 4),
            "spi": round(cn / us, 3) if us else None, "total_tokens": tot}


# Google Trends: Chinese apps' share of US search interest across the main AI
# assistants. The unofficial API caps a comparison at 5 terms, so terms are
# fetched in batches that all share the anchor (ChatGPT) and are rescaled onto
# batch 0's scale via the anchor's ratio.
# "Llama AI" not bare "Llama": the bare string is dominated by the animal.
# "Meta AI" captures the consumer assistant product built on Llama.
TRENDS_TERMS_US = ["ChatGPT", "Gemini", "Claude", "Llama AI", "Meta AI"]
# "Kimi AI"/"GLM AI" not bare "Kimi"/"GLM": the bare strings are dominated by
# homonyms in US search (Kimi Antonelli/Raikkonen, generalized linear models).
TRENDS_TERMS_CN = ["DeepSeek", "Qwen", "Kimi AI", "GLM AI", "MiMo", "MiniMax", "Seed 1.6", "Seed 2.0"]
TRENDS_GEO = "US"
TRENDS_WINDOW = "today 3-m"
TRENDS_BATCH = 5


def parse_gjson(raw):
    """Google APIs prefix JSON bodies with an anti-scrape garbage line."""
    return json.loads(raw[raw.index(b"{"):])


def trends_batches():
    """Split US+CN terms into <=5-term batches, each led by the shared anchor."""
    anchor = TRENDS_TERMS_US[0]
    terms = TRENDS_TERMS_US + TRENDS_TERMS_CN
    batches, rest = [terms[:TRENDS_BATCH]], terms[TRENDS_BATCH:]
    while rest:
        batches.append([anchor] + rest[:TRENDS_BATCH - 1])
        rest = rest[TRENDS_BATCH - 1:]
    return batches


def trends_avgs(timeline, n):
    """timelineData -> per-term mean interest over the window."""
    if not timeline:
        raise ValueError("no timeline points")
    return [sum(p["value"][i] for p in timeline) / len(timeline) for i in range(n)]


def merge_anchored(batches, avg_lists):
    """Rescale every batch onto batch 0's scale via the shared anchor term."""
    merged = dict(zip(batches[0], avg_lists[0]))
    for terms, avgs in zip(batches[1:], avg_lists[1:]):
        if avgs[0] <= 0:
            raise ValueError(f"anchor has zero interest in batch {terms}")
        scale = avg_lists[0][0] / avgs[0]
        merged.update({t: a * scale for t, a in zip(terms[1:], avgs[1:])})
    return merged


def trends_search_consumer(merged):
    """Merged per-term averages -> search_consumer dict (share = CN / total)."""
    us = sum(merged[t] for t in TRENDS_TERMS_US)
    cn = sum(merged[t] for t in TRENDS_TERMS_CN)
    if us + cn <= 0:
        raise ValueError("all-zero interest")
    pct = round(cn / (us + cn) * 100, 1)
    return {"western_share_pct": pct,
            "asof": datetime.now(timezone.utc).strftime("%Y-%m"),
            "source": "google-trends",
            "terms_us": TRENDS_TERMS_US, "terms_cn": TRENDS_TERMS_CN,
            "note": f"Google Trends {TRENDS_GEO}, 90-day avg: {len(TRENDS_TERMS_CN)} Chinese AI terms = "
                    f"{pct}% of AI-assistant search interest vs {'+'.join(TRENDS_TERMS_US)}."}


def google_trends():
    """Fetch interest-over-time via the unofficial explore -> multiline flow.
    Needs the homepage NID cookie (/trends/explore itself 429s cookie-less bots)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def g(url):
        return opener.open(urllib.request.Request(url, headers=UA), timeout=30).read()

    def fetch_batch(terms):
        req = {"comparisonItem": [{"keyword": t, "geo": TRENDS_GEO, "time": TRENDS_WINDOW}
                                  for t in terms],
               "category": 0, "property": ""}
        q = urllib.parse.urlencode({"hl": "en-US", "tz": "0", "req": json.dumps(req)})
        raw = None
        for wait in (0, 5, 20):  # explore 429s readily; back off before giving up
            if wait:
                time.sleep(wait)
            try:
                raw = g(f"https://trends.google.com/trends/api/explore?{q}")
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or wait == 20:
                    raise
        widget = next(w for w in parse_gjson(raw)["widgets"] if w["id"] == "TIMESERIES")
        q2 = urllib.parse.urlencode({"hl": "en-US", "tz": "0",
                                     "req": json.dumps(widget["request"]), "token": widget["token"]})
        raw2 = g(f"https://trends.google.com/trends/api/widgetdata/multiline?{q2}")
        return trends_avgs(parse_gjson(raw2)["default"]["timelineData"], len(terms))

    g("https://trends.google.com/?geo=US")
    batches = trends_batches()
    avg_lists = []
    for i, terms in enumerate(batches):
        if i:
            time.sleep(3)  # be gentle - each batch is an explore + multiline pair
        avg_lists.append(fetch_batch(terms))
    return trends_search_consumer(merge_anchored(batches, avg_lists))


def pick_search_consumer(fresh, prev, manual):
    """Fresh trends value, else the previous run's trends value, else MANUAL."""
    if fresh:
        return fresh
    prev_sc = (prev or {}).get("search_consumer", {})
    if prev_sc.get("source") == "google-trends":
        return prev_sc
    return manual


# ---- consumer-app Western chart presence -------------------------------------
# Replaces the old judgmental "apps" score with a live signal: how present are the
# flagship Chinese AI apps in Western app-store top charts. iOS comes from Apple's
# keyless marketing RSS (fetched here); Android comes from app-charts.json, written
# by update-app-charts.mjs (google-play-scraper) because Play has no key-free charts
# API. Both stores feed the same basket/scoring below.
APPLE_RSS = "https://rss.applemarketingtools.com/api/v2/{country}/apps/top-free/100/apps.json"
APP_COUNTRIES = ["us", "gb", "de", "fr", "jp", "in", "br", "ca", "au", "kr"]
APP_FETCH_DEPTH = 200  # Play is fetched this deep so 101-200 ranks surface as near-misses;
# scoring itself is top-100 only (a rank in the long tail is not "top-chart presence").
# Basket order defines the composite; keep the patterns in sync with the regex in
# update-app-charts.mjs. Matched against "<title/name> <appId/artist>", case-insensitively.
APP_BASKET = [
    ("DeepSeek", re.compile(r"deepseek", re.I)),
    ("Qwen", re.compile(r"\bqwen\b|tongyi", re.I)),
    ("Doubao", re.compile(r"doubao|\bcici\b", re.I)),
    ("Kimi", re.compile(r"\bkimi\b|kimichat", re.I)),
    ("MiniMax", re.compile(r"talkie|hailuo|minimax|weaver\.app", re.I)),
]


def app_points(rank):
    """Top-100 chart rank -> 0..100 (#1 = 100, #100 = 1); ranks past top-100 score 0."""
    return max(0, 101 - rank)


def match_app(title, extra=""):
    """Return the basket label for a chart entry, or None if it is not a CN AI app."""
    text = f"{title} {extra}".lower()
    for label, rx in APP_BASKET:
        if rx.search(text):
            return label
    return None


def _fmt_hit(h):
    store = {"android": "Play", "ios": "iOS"}.get(h["store"], h["store"])
    return f'{h["label"]} #{h["rank"]} ({h["country"].upper()} {store})'


def apps_score(hits):
    """Combined iOS+Android hits -> apps dict (basket-mean of best per-app chart rank)."""
    best = {}
    for h in hits:
        if h["label"] not in best or h["rank"] < best[h["label"]]["rank"]:
            best[h["label"]] = h
    per_app = [app_points(best[lbl]["rank"]) if lbl in best else 0 for lbl, _ in APP_BASKET]
    score = round(sum(per_app) / len(APP_BASKET))
    charted = sorted(best.values(), key=lambda h: h["rank"])
    top100 = [h for h in charted if h["rank"] <= 100]
    if top100:
        lead = "; ".join(_fmt_hit(h) for h in top100[:3])
    elif charted:
        lead = "no Chinese AI app in any iOS or Play top-100 (nearest: " + _fmt_hit(charted[0]) + ")"
    else:
        lead = "no Chinese AI app in any iOS or Play top-100"
    return {
        "score": score,
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "app-charts",
        "best": [{"label": h["label"], "rank": h["rank"], "store": h["store"], "country": h["country"]}
                 for h in charted],
        "markets": APP_COUNTRIES,
        "detail": f"{lead}; basket-mean Western top-100 presence {score}/100 across {len(APP_COUNTRIES)} markets",
        "note": f"iOS Apple RSS top-100 + Android Play top-{APP_FETCH_DEPTH} across {len(APP_COUNTRIES)} markets; "
                "presence = basket-mean of best top-100 chart rank "
                "(DeepSeek/Qwen/Doubao/Kimi/MiniMax), #1=100 #100=1; ranks past top-100 score 0.",
    }


def apple_hits(countries):
    """Fetch Apple's keyless top-free RSS per country -> (hits, any_country_ok)."""
    hits, ok = [], False
    for c in countries:
        try:
            results = jget(APPLE_RSS.format(country=c))["feed"]["results"]
            ok = True
        except Exception:
            continue
        for i, a in enumerate(results):
            lbl = match_app(a.get("name", ""), a.get("artistName", ""))
            if lbl:
                hits.append({"label": lbl, "store": "ios", "country": c, "rank": i + 1})
    return hits, ok


def android_hits():
    """Read app-charts.json (written by update-app-charts.mjs); None if it never ran."""
    p = HERE / "app-charts.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("hits", [])


def compute_apps():
    """iOS + Android chart presence -> apps dict, or None if no store was reachable."""
    ios, ios_ok = apple_hits(APP_COUNTRIES)
    andr = android_hits()
    if not ios_ok and andr is None:
        return None
    return apps_score(ios + (andr or []))


def pick_apps(fresh, prev, manual):
    """Fresh computed value, else the previous run's computed value, else MANUAL."""
    if fresh:
        return fresh
    prev_a = (prev or {}).get("apps", {})
    if prev_a.get("source") == "app-charts":
        return prev_a
    return manual


# ---- Vercel AI Gateway: the second router --------------------------------------
# Daily lab-level token share from production apps on Vercel's gateway (CC BY 4.0,
# cached 24h server-side). Different user base than OpenRouter (deployed web apps vs
# hobbyist/price-sensitive routing), so it de-biases the headline SPI.
VERCEL_EXPORT = "https://vercel.com/api/ai/leaderboard-export?dataset=labs&modality=text"
VERCEL_CN_LABS = CN_AUTHORS | {"alibaba", "zai", "zhipu", "moonshot", "bytedance", "minimaxai"}
VERCEL_US_LABS = US_AUTHORS | {"meta", "xai", "vercel"}


def vercel_days(rows):
    """Export rows -> date-sorted [{d, cn, us}] of token share (percentage points)."""
    days = {}
    for r in rows:
        if r.get("metric") != "tokens":
            continue
        day = days.setdefault(r["date"], {"cn": 0.0, "us": 0.0})
        lab = r["name"].lower()
        if lab in VERCEL_CN_LABS:
            day["cn"] += r["share_percent"]
        elif lab in VERCEL_US_LABS:
            day["us"] += r["share_percent"]
    if not days:
        raise ValueError("no token rows in export")
    return [{"d": d, "cn": round(v["cn"], 2), "us": round(v["us"], 2)}
            for d, v in sorted(days.items())]


def vercel_gateway():
    d = jget(VERCEL_EXPORT, timeout=60)
    series = vercel_days(d["rows"])
    last = series[-1]
    top_cn = sorted((r for r in d["rows"]
                     if r.get("metric") == "tokens" and r["date"] == last["d"]
                     and r["name"].lower() in VERCEL_CN_LABS),
                    key=lambda r: -r["share_percent"])
    return {"asof": last["d"], "cn_share": last["cn"], "us_share": last["us"],
            "spi": round(last["cn"] / last["us"], 3) if last["us"] else None,
            "top_cn": [{"lab": r["name"], "share": round(r["share_percent"], 2)} for r in top_cn[:6]],
            "series": series[-90:],
            "license": "AI Gateway Leaderboard Data (c) Vercel, CC BY 4.0"}


# ---- Ollama: local / self-hosted adoption ---------------------------------------
# Pull counts from the server-rendered ollama.com/library index. Lifetime cumulative
# totals (a stock, not a flow) - a per-day rate is derived from the baseline stored in
# china-history.json once two runs are >20h apart, same pattern as GitHub stars.
OLLAMA_CN = re.compile(r"deepseek|qwen|qwq|\bglm|kimi|minimax|internlm|ernie|hunyuan|doubao|baichuan|mimo|yi(?:$|[-:_])", re.I)
OLLAMA_US = re.compile(r"llama|gemma|gpt-oss|phi|nemotron|olmo|granite|dbrx", re.I)


def parse_count(s):
    """'117.3M' / '5,000' / '2.1K' -> int."""
    s = s.replace(",", "").strip()
    mult = {"K": 1e3, "M": 1e6, "B": 1e9}.get(s[-1:].upper())
    return int(float(s[:-1]) * mult) if mult else int(float(s))


def ollama_side(name):
    """Model page slug -> 'cn' | 'us' | None (families outside both baskets)."""
    if OLLAMA_CN.search(name):
        return "cn"
    if OLLAMA_US.search(name):
        return "us"
    return None


def ollama_models(page):
    """ollama.com/library HTML -> [{name, pulls}] (models with a parseable count)."""
    models = []
    for chunk in page.split('href="/library/')[1:]:
        name = chunk.split('"', 1)[0]
        m = re.search(r"<span[^>]*>\s*([\d.,]+[KMB]?)\s*</span>\s*<span[^>]*>(?:&nbsp;|\s)*Pulls", chunk)
        if m:
            models.append({"name": name, "pulls": parse_count(m.group(1))})
    if not models:
        raise ValueError("no pull counts parsed from library page")
    return models


def ollama_pulls(hist):
    page = get("https://ollama.com/library", timeout=60).decode("utf-8", "replace")
    models = ollama_models(page)
    cn = [m for m in models if ollama_side(m["name"]) == "cn"]
    us = [m for m in models if ollama_side(m["name"]) == "us"]
    cn_tot, us_tot = sum(m["pulls"] for m in cn), sum(m["pulls"] for m in us)
    if not cn_tot or not us_tot:
        raise ValueError("one side has zero pulls - classification broke")
    out = {"cn": cn_tot, "us": us_tot,
           "cn_top": sorted(cn, key=lambda m: -m["pulls"])[:6],
           "us_top": sorted(us, key=lambda m: -m["pulls"])[:3],
           "n_models": len(models),
           "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    now = time.time()
    prev = hist.get("ollama")
    if prev and now - prev["t"] >= 20 * 3600:
        days = (now - prev["t"]) / 86400
        out["cn_per_day"] = round((cn_tot - prev["cn"]) / days)
        out["us_per_day"] = round((us_tot - prev["us"]) / days)
        hist["ollama"] = {"t": now, "cn": cn_tot, "us": us_tot}
    elif not prev:
        hist["ollama"] = {"t": now, "cn": cn_tot, "us": us_tot}
    return out


# ---- Kalshi: regulated prediction markets ---------------------------------------
# Public trade-api v2 market data (no key needed, but not CORS-open -> fetched here).
# Complements the thin Polymarket AI markets the page fetches live.
KALSHI_MKTS = "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker={s}&status=open"
KALSHI_CN_BRANDS = re.compile(r"deepseek|qwen|kimi|ernie|glm|doubao|dola|minimax|hunyuan|yi\b", re.I)


def kalshi_price(m):
    """Market dict -> probability 0..1 from last_price_dollars (last_price is null
    on the public endpoint)."""
    p = m.get("last_price_dollars")
    return round(float(p), 4) if p not in (None, "") else None


def kalshi_pick(markets):
    """KXLLM1 markets -> the year-end (DEC31) event's Chinese-brand entries plus the
    top-priced US brand for scale."""
    yearend = [m for m in markets if "DEC31" in m.get("event_ticker", "")]
    cn = [m for m in yearend if KALSHI_CN_BRANDS.search(m.get("yes_sub_title") or "")]
    us = [m for m in yearend if m not in cn and kalshi_price(m) is not None]
    us.sort(key=lambda m: -(kalshi_price(m) or 0))
    return cn, us[:1]


def kalshi_markets():
    out = []
    best_cn = jget(KALSHI_MKTS.format(s="KXBESTLLMCHINA"), timeout=30)["markets"]
    for m in best_cn:
        out.append({"label": m.get("title") or m["ticker"], "p": kalshi_price(m),
                    "ticker": m["ticker"], "series": "kxbestllmchina"})
    llm1 = jget(KALSHI_MKTS.format(s="KXLLM1"), timeout=30)["markets"]
    cn, us_ref = kalshi_pick(llm1)
    for m in cn + us_ref:
        out.append({"label": f'Best AI at end of 2026: {m.get("yes_sub_title") or m["ticker"]}',
                    "p": kalshi_price(m), "ticker": m["ticker"], "series": "kxllm1"})
    if not out:
        raise ValueError("no Kalshi markets returned")
    return {"asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "markets": out}


# ---- Hugging Face fine-tune trees: ecosystem gravity ----------------------------
# Who builds ON your models is a stickier substitution signal than raw downloads.
# The exact tree size is only rendered on the model page ("N models" next to the
# Finetunes link); the list API paginates without totals.
HF_FT_CN_BASES = ["Qwen/Qwen3-8B", "deepseek-ai/DeepSeek-R1", "zai-org/GLM-4.5-Air",
                  "moonshotai/Kimi-K2-Instruct"]
HF_FT_US_BASES = ["meta-llama/Llama-3.1-8B", "google/gemma-3-12b-it", "openai/gpt-oss-20b",
                  "microsoft/phi-4"]


def parse_finetune_count(page, base):
    """Model-page HTML -> int fine-tune count from the model-tree card."""
    m = re.search(r'href="/models\?other=base_model:finetune:'
                  + re.escape(base) + r'"[^>]*>\s*([\d,]+)\s*models?', page)
    if not m:
        raise ValueError(f"no fine-tune count on page for {base}")
    return int(m.group(1).replace(",", ""))


def hf_finetunes():
    def counts(bases):
        got = []
        for b in bases:
            try:
                page = get(f"https://huggingface.co/{b}", timeout=30).decode("utf-8", "replace")
                got.append({"base": b, "n": parse_finetune_count(page, b)})
            except Exception as e:
                print(f"  hf-finetunes {b}: {e}", file=sys.stderr)
            time.sleep(1)
        return got
    cn, us = counts(HF_FT_CN_BASES), counts(HF_FT_US_BASES)
    if not cn or not us:
        raise ValueError("no fine-tune counts on one side")
    return {"cn": cn, "us": us,
            "cn_total": sum(x["n"] for x in cn), "us_total": sum(x["n"] for x in us),
            "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d")}


# ---- PyPI SDK downloads ----------------------------------------------------------
# Weekly installs of each lab's first-party Python SDK (pypistats.org, public).
# Caveat carried into the page note: Chinese APIs are OpenAI-compatible, so much CN
# usage rides the openai package - the CN side is a hard undercount.
SDK_CN = ["dashscope", "zhipuai", "zai-sdk"]
SDK_US = ["openai", "anthropic", "google-genai"]


def sdk_downloads():
    def wk(pkg):
        for wait in (0, 10):  # pypistats 429s bursts; one gentle retry
            if wait:
                time.sleep(wait)
            try:
                return jget(f"https://pypistats.org/api/packages/{pkg}/recent", timeout=30)["data"]["last_week"]
            except urllib.error.HTTPError as e:
                if e.code != 429 or wait:
                    raise
    def side(pkgs):
        got = []
        for p in pkgs:
            try:
                got.append({"pkg": p, "wk": wk(p)})
            except Exception as e:
                print(f"  pypistats {p}: {e}", file=sys.stderr)
            time.sleep(2)
        return got
    cn, us = side(SDK_CN), side(SDK_US)
    if not cn or not us:
        raise ValueError("pypistats returned no usable data on one side")
    return {"cn": cn, "us": us, "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d")}


# ---- Artificial Analysis Data API ------------------------------------------------
# Replaces the hand-refreshed MANUAL snapshot when ARTIFICIAL_ANALYSIS_API_KEY is set
# (free tier: 1,000 req/day, attribution required). Without the key the MANUAL value
# or the previous API-sourced value is carried, same pattern as trends/apps.
AA_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
AA_CN_CREATORS = re.compile(r"deepseek|alibaba|qwen|z\.?ai|zhipu|moonshot|minimax|xiaomi|tencent|stepfun|baidu|bytedance|01\.?ai", re.I)
AA_US_CREATORS = re.compile(r"openai|anthropic|google|xai|meta|amazon|nvidia|microsoft", re.I)


def aa_side(creator):
    """AA creator name -> 'cn' | 'us' | None."""
    return "cn" if AA_CN_CREATORS.search(creator) else "us" if AA_US_CREATORS.search(creator) else None


def aa_best(models):
    """AA model list -> best CN + best US by intelligence index."""
    best = {"cn": None, "us": None}
    for m in models:
        creator = ((m.get("model_creator") or {}).get("name")) or ""
        idx = (m.get("evaluations") or {}).get("artificial_analysis_intelligence_index")
        if idx is None:
            continue
        side = aa_side(creator)
        if side and (best[side] is None or idx > best[side][1]):
            best[side] = (m.get("name") or m.get("id"), idx)
    if not best["cn"] or not best["us"]:
        raise ValueError("could not find a best model on both sides")
    return {"cn_best": best["cn"][0], "cn_score": round(best["cn"][1]),
            "us_best": best["us"][0], "us_score": round(best["us"][1]),
            "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "source": "aa-api",
            "attribution": "Source: Artificial Analysis (artificialanalysis.ai)"}


# ---- AA frontier gap: the same API call, cut by country over time -----------------
# The gap SNAPSHOT above says where the race is today; the series below says which way
# it is moving, which is the actual thesis variable. Series start pinned to the modern
# index era - AA re-bases its index every major version, so pre-2024 scores are not
# comparable and a longer window would fabricate a trend.
AA_FRONTIER_SINCE = "2024-01"
AA_VALUE_BAND = 3   # "near-frontier" = within this many index points of a side's frontier


def month_add(m, n=1):
    """'2026-01' + n months -> 'YYYY-MM'."""
    y, mo = int(m[:4]), int(m[5:7]) - 1 + n
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


def months_between(a, b):
    """Whole months from month a to month b (positive when b is later)."""
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))


def aa_points(models):
    """AA model list -> [{side, d:'YYYY-MM', idx, name, usd}] for dated, scored models.

    usd is the blended $/1M tokens: the API's 3:1 blend when present, else recomputed
    from input/output prices, else None (the model still counts for the frontier, just
    not for the price pick)."""
    pts = []
    for m in models:
        creator = ((m.get("model_creator") or {}).get("name")) or ""
        side = aa_side(creator)
        idx = (m.get("evaluations") or {}).get("artificial_analysis_intelligence_index")
        d = (m.get("release_date") or m.get("first_release_date") or "")[:7]
        if not side or idx is None or len(d) != 7:
            continue
        p = m.get("pricing") or {}
        usd = p.get("price_1m_blended_3_to_1")
        if usd is None and p.get("price_1m_input_tokens") is not None \
                and p.get("price_1m_output_tokens") is not None:
            usd = (3 * float(p["price_1m_input_tokens"]) + float(p["price_1m_output_tokens"])) / 4
        pts.append({"side": side, "d": d, "idx": float(idx),
                    "name": m.get("name") or m.get("id"),
                    "usd": round(float(usd), 2) if usd is not None else None})
    return pts


def aa_value(pts, last):
    """Cheapest blended $/M within AA_VALUE_BAND points of each side's frontier.

    The headline price gap panel compares flagship list prices; this is the
    quality-adjusted version - what near-frontier intelligence actually costs on each
    side. Zero-priced (free-tier) entries are excluded: a $0 denominator is a promo,
    not an economy."""
    pick = {}
    for side in ("cn", "us"):
        cands = [p for p in pts
                 if p["side"] == side and p["usd"] and p["idx"] >= last[side] - AA_VALUE_BAND]
        if not cands:
            return None
        p = min(cands, key=lambda c: c["usd"])
        pick[side] = {"name": p["name"], "idx": round(p["idx"], 1), "usd": p["usd"]}
    return {**pick, "ratio": round(pick["us"]["usd"] / pick["cn"]["usd"], 1),
            "band": AA_VALUE_BAND}


def aa_frontier(models, today=None):
    """Monthly frontier intelligence by side + the lag/value stats the page renders.

    Reconstructed from the CURRENT catalogue's release dates, so a model AA delists
    drops out of history - fine for the gap trend, and stated in the page note. Lag is
    Epoch's us-vs-china-eci statistic computed on AA's index: months between a US model
    first reaching today's best Chinese score and the Chinese frontier getting there.
    If the US frontier was already past that level when the window opens, the lag is
    clipped to the window and understates - conservative in the right direction."""
    pts = aa_points(models)
    for side in ("cn", "us"):
        if sum(1 for p in pts if p["side"] == side) < 3:
            raise ValueError(f"too few dated {side} models for a frontier series")
    today = today or datetime.now(timezone.utc).strftime("%Y-%m")
    series, cur = [], max(AA_FRONTIER_SINCE, min(p["d"] for p in pts))
    while cur <= today:
        row = {"m": cur}
        for side in ("cn", "us"):
            best = max((p["idx"] for p in pts if p["side"] == side and p["d"] <= cur),
                       default=None)
            row[side] = round(best, 1) if best is not None else None
        series.append(row)
        cur = month_add(cur)
    if not series:
        raise ValueError("no frontier months in window")
    last = series[-1]
    if last["cn"] is None or last["us"] is None:
        raise ValueError("frontier series empty on one side")
    cn_reach = next(r["m"] for r in series if r["cn"] is not None and r["cn"] >= last["cn"])
    us_reach = next((r["m"] for r in series if r["us"] is not None and r["us"] >= last["cn"]), None)
    lag = max(0, months_between(us_reach, cn_reach)) if us_reach else 0
    now = {s: max((p for p in pts if p["side"] == s), key=lambda p: p["idx"]) for s in ("cn", "us")}
    out = {"asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "source": "aa-api",
           "attribution": "Source: Artificial Analysis (artificialanalysis.ai)",
           "series": series, "gap_points": round(last["us"] - last["cn"], 1),
           "lag_months": lag,
           "cn_now": {"name": now["cn"]["name"], "idx": round(now["cn"]["idx"], 1)},
           "us_now": {"name": now["us"]["name"], "idx": round(now["us"]["idx"], 1)}}
    val = aa_value(pts, last)
    if val:
        out["value"] = val
    return out


def artificial_analysis():
    """-> (best, frontier|None) when the key is set, else None.

    One API call feeds both: the best-model snapshot the leaderboard panel has always
    shown, and the frontier series. The series needs release_date and pricing fields
    the snapshot never used, so it degrades separately - a schema drift there must not
    take down the score snapshot."""
    key = os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY")
    if not key:
        return None
    models = jget(AA_URL, timeout=60, headers={"x-api-key": key}).get("data") or []
    best = aa_best(models)
    try:
        frontier = aa_frontier(models)
    except Exception as e:
        print(f"  aa frontier skipped ({e})", file=sys.stderr)
        frontier = None
    return best, frontier


def pick_aa(fresh, prev, manual):
    """Fresh API value, else the previous run's API value, else MANUAL."""
    if fresh:
        return fresh
    prev_aa = (prev or {}).get("artificial_analysis", {})
    if prev_aa.get("source") == "aa-api":
        return prev_aa
    return manual


# ---- Cloudflare Radar: consumer AI traffic by DNS volume -------------------------
# Ranks generative-AI services by 1.1.1.1 resolver traffic - actual visits, not
# search-term or app-chart proxies. Needs a (free) API token with Radar read scope
# in CF_RADAR_TOKEN; skipped cleanly without one.
RADAR_TOP = ("https://api.cloudflare.com/client/v4/radar/ranking/internet_services/top"
             "?serviceCategory=Generative%20AI&limit=20")
RADAR_CN = re.compile(r"deepseek|qwen|tongyi|kimi|moonshot|minimax|hailuo|talkie|doubao|glm|zhipu|z\.ai|ernie|hunyuan", re.I)


def radar_rows(result):
    """Radar API result -> [{rank, name, cn}] - tolerate either 'top_0' or any list."""
    rows = result.get("top_0") if isinstance(result, dict) else None
    if rows is None and isinstance(result, dict):
        rows = next((v for v in result.values() if isinstance(v, list)), None)
    if not rows:
        raise ValueError("no ranking rows in Radar response")
    out = []
    for i, r in enumerate(rows):
        name = r.get("service") or r.get("name") or "?"
        out.append({"rank": int(r.get("rank", i + 1)), "name": name,
                    "cn": bool(RADAR_CN.search(name))})
    return out


def radar_ai():
    tok = os.environ.get("CF_RADAR_TOKEN")
    if not tok:
        return None
    d = jget(RADAR_TOP, timeout=30, headers={"Authorization": f"Bearer {tok}"})
    if not d.get("success"):
        raise ValueError(f"Radar API error: {d.get('errors')}")
    rows = radar_rows(d.get("result") or {})
    cn_rows = [r for r in rows if r["cn"]]
    return {"services": rows, "cn_best": cn_rows[0] if cn_rows else None,
            "cn_in_top20": len(cn_rows),
            "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d")}


# ---------------------------------------------------------------------------
# Daily metrics history (china-metrics.csv)
#
# Everything below exists so the page can show *trajectories*, not snapshots:
# the composite adoption index, the frontier price gap and the per-family
# shares are all recomputed each run and appended (one row per UTC day, the
# day's last run wins). The index math mirrors the page's renderGauge() and
# the documented methodology in china-ai-monitor.html - if one changes, change
# both, and test_update_china_data.py pins the shared reference values.
# ---------------------------------------------------------------------------

# Python port of the page's PRICE_FAMILIES_CN/US (see china-ai-monitor.html for
# why lines are pinned and versions resolved: exact slugs rot, price-ranking is
# circular). Kept in (label, regex) pairs so tests can compare against the JS.
PRICE_LINES_CN = [
    ("DeepSeek (pro)",   re.compile(r"^deepseek/deepseek-v[\d.]+-pro$")),
    ("DeepSeek (flash)", re.compile(r"^deepseek/deepseek-v[\d.]+-flash(-\d+)?$")),
    ("GLM (Z.ai)",       re.compile(r"^z-ai/glm-[\d.]+$")),
    ("Kimi (Moonshot)",  re.compile(r"^moonshotai/kimi-k[\d.]+$")),
    ("Kimi Code",        re.compile(r"^moonshotai/kimi-k[\d.]+-code$")),
    ("MiniMax",          re.compile(r"^minimax/minimax-m[\d.]+$")),
    ("Qwen Max",         re.compile(r"^qwen/qwen[\d.]+-max(-preview)?$")),
]
PRICE_LINES_US = [
    ("GPT (top)",        re.compile(r"^openai/gpt-[\d.]+-sol$")),
    ("GPT (mid)",        re.compile(r"^openai/gpt-[\d.]+-terra$")),
    ("Claude Opus",      re.compile(r"^anthropic/claude-opus-[\d.]+$")),
    ("Claude Sonnet",    re.compile(r"^anthropic/claude-sonnet-[\d.]+$")),
    ("Gemini Pro",       re.compile(r"^google/gemini-[\d.]+-pro(-preview)?$")),
    ("Gemini Flash",     re.compile(r"^google/gemini-[\d.]+-flash$")),
]


def resolve_price_lines(models, lines):
    """Newest live model per line -> [output $/M]; mirrors the page's resolveFamilies()."""
    live = [m for m in (models or [])
            if m.get("id") and not m["id"].endswith(":free")
            and float((m.get("pricing") or {}).get("completion") or 0) > 0]
    out = []
    for _label, rx in lines:
        hits = [m for m in live if rx.match(m["id"])]
        if not hits:
            continue
        newest = max(hits, key=lambda m: m.get("created") or 0)
        out.append(float(newest["pricing"]["completion"]) * 1e6)
    return out


def _median(vals):
    v = sorted(vals)
    return v[len(v) // 2] if v else None


def openrouter_price_gap():
    """Median US flagship output $/M divided by median Chinese - the '5x gap'."""
    models = jget("https://openrouter.ai/api/v1/models", timeout=60)["data"]
    us = _median(resolve_price_lines(models, PRICE_LINES_US))
    cn = _median(resolve_price_lines(models, PRICE_LINES_CN))
    if not us or not cn:
        raise ValueError("price lines unresolved")
    return {"us_med": round(us, 2), "cn_med": round(cn, 2), "gap": round(us / cn, 2)}


def _clamp01(x):
    return max(0.0, min(1.0, x))


def compute_index(out):
    """The page's Chinese AI Adoption Index, computed from this run's data.

    Same normalization ranges and weights as renderGauge()/the methodology
    footer; families with no value are excluded and the weights renormalize.
    Returns (index or None, {family: normalized 0-100 score}).
    """
    fams = {}
    wk, vg = out.get("openrouter_week"), out.get("vercel_gateway")
    if wk and wk.get("cn_share") is not None:
        orn = _clamp01(wk["cn_share"] / 0.70) * 100
        if vg and vg.get("cn_share") is not None:
            fams["router"] = (30, (orn + _clamp01(vg["cn_share"] / 100 / 0.70) * 100) / 2)
        else:
            fams["router"] = (30, orn)
    hf = out.get("hf")
    if hf and hf.get("cn") and hf.get("us"):
        fams["hf"] = (20, _clamp01(hf["cn"] / (hf["cn"] + hf["us"]) / 0.90) * 100)
    if out.get("github_stars_per_day") is not None:
        fams["github"] = (15, _clamp01(out["github_stars_per_day"] / 300) * 100)
    ol = out.get("ollama")
    if ol and ol.get("cn") and ol.get("us"):
        fams["ollama"] = (10, _clamp01(ol["cn"] / (ol["cn"] + ol["us"]) / 0.70) * 100)
    sc = out.get("search_consumer")
    if sc and sc.get("western_share_pct") is not None:
        fams["search"] = (10, _clamp01(sc["western_share_pct"] / 100 / 0.50) * 100)
    ap = out.get("apps")
    if ap and ap.get("score") is not None:
        fams["apps"] = (10, float(ap["score"]))
    lb = out.get("lmarena")
    if lb and lb.get("us_leader_score") and lb.get("best_score"):
        gap = lb["us_leader_score"] - lb["best_score"]
        fams["arena"] = (5, _clamp01(1 - gap / 100) * 100)
    wsum = sum(w for w, _ in fams.values())
    if not wsum:
        return None, {}
    idx = sum(w * v for w, v in fams.values()) / wsum
    return round(idx, 1), {k: round(v, 1) for k, (_, v) in fams.items()}


METRICS_COLS = ["date", "adoption_index", "spi", "router_cn_share", "vercel_cn_share",
                "hf_cn_share", "ollama_cn_share", "gh_stars_per_day", "price_gap",
                "search_share", "apps_score", "arena_elo_gap"]


def append_metrics(path, row):
    """Append one row per UTC day; a rerun on the same day replaces that day's row.

    Rows are re-keyed by column name against the file's own header, so adding a
    column to METRICS_COLS migrates the history in place (new cells blank) instead
    of discarding it."""
    rows = []
    if path.exists():
        lines = path.read_text().rstrip("\n").split("\n")
        old_cols = lines[0].split(",")
        rows = [dict(zip(old_cols, l.split(","))) for l in lines[1:] if l]
    rows = [r for r in rows if r.get("date") and r["date"] != row["date"]]
    rows.append({c: "" if row.get(c) is None else str(row[c]) for c in METRICS_COLS})
    body = [",".join(r.get(c, "") for c in METRICS_COLS) for r in rows]
    path.write_text("\n".join([",".join(METRICS_COLS)] + body) + "\n")


def metrics_row(out, price_gap):
    idx, _fams = compute_index(out)
    wk, vg = out.get("openrouter_week") or {}, out.get("vercel_gateway") or {}
    hf, ol = out.get("hf") or {}, out.get("ollama") or {}
    sc, ap, lb = out.get("search_consumer") or {}, out.get("apps") or {}, out.get("lmarena") or {}
    share = lambda d: (round(d["cn"] / (d["cn"] + d["us"]), 4)
                       if d.get("cn") and d.get("us") else None)
    return {"date": out["snapshot_date"], "adoption_index": idx, "spi": wk.get("spi"),
            "router_cn_share": wk.get("cn_share"),
            "vercel_cn_share": round(vg["cn_share"] / 100, 4) if vg.get("cn_share") is not None else None,
            "hf_cn_share": share(hf), "ollama_cn_share": share(ol),
            "gh_stars_per_day": out.get("github_stars_per_day"),
            "price_gap": price_gap["gap"] if price_gap else None,
            # fractions like the other share columns; the raw 0-100 apps score as-is
            "search_share": (round(sc["western_share_pct"] / 100, 4)
                             if sc.get("western_share_pct") is not None else None),
            "apps_score": ap.get("score"),
            "arena_elo_gap": (lb["us_leader_score"] - lb["best_score"]
                              if lb.get("us_leader_score") and lb.get("best_score") else None)}


# ---- Epoch AI supply-side datasets (CC BY 4.0) ------------------------------------
# The demand panels say who is WINNING adoption; these say who CAN scale it. Three
# keyless CSV downloads: GPU-cluster capacity (compute stock), quarterly accelerator
# output by designer (compute flow), notable-model releases by country (output flow).
# They update monthly-to-quarterly upstream and the biggest file is ~2 MB, so they are
# refetched at most every EPOCH_REFRESH_DAYS rather than on every 30-minute run - the
# last parsed value is carried in china-data.json between refetches, same as every
# other family.
EPOCH_GPU_CLUSTERS_CSV = "https://epoch.ai/data/gpu_clusters.csv"
EPOCH_CHIP_SALES_CSV = "https://epoch.ai/data/ai_chip_sales_timelines_by_chip.csv"
EPOCH_NOTABLE_MODELS_CSV = "https://epoch.ai/data/notable_ai_models.csv"
EPOCH_REFRESH_DAYS = 6
EPOCH_ATTRIBUTION = "Epoch AI (epoch.ai/data), CC BY 4.0"
# Epoch writes full country names, comma-joined when a model has several orgs
# ("United States of America,China"). Substring membership is safe here: Taiwan and
# Hong Kong appear as their own exact names, not as "..., Province of China" variants
# (verified against both CSVs 2026-08); Hong Kong-only entries deliberately count for
# neither side.
EPOCH_US = "United States"
EPOCH_CN = "China"
EPOCH_MODELS_SINCE = "2023-01"   # release-cadence window: the post-ChatGPT race
CHIP_DESIGNERS_CN = {"huawei", "cambricon", "biren", "moore threads", "hygon", "enflame"}
CHIP_DESIGNERS_US = {"nvidia", "amd", "google", "amazon", "intel", "microsoft", "meta", "cerebras"}


def epoch_csv(url):
    return list(csv.DictReader(io.StringIO(get(url, timeout=120).decode("utf-8", "replace"))))


def country_side(field):
    """Epoch country field -> 'cn' | 'us' | None. Joint US-CN work fits neither side -
    for a race chart, splitting one model between both lines is worse than dropping
    the handful of genuinely joint releases."""
    has_us, has_cn = EPOCH_US in (field or ""), EPOCH_CN in (field or "")
    if has_cn and not has_us:
        return "cn"
    if has_us and not has_cn:
        return "us"
    return None


def quarter_of(date):
    """'2026-01-15' -> '2026Q1'."""
    return f"{date[:4]}Q{(int(date[5:7]) - 1) // 3 + 1}"


def parse_gpu_clusters(rows):
    """Cluster rows -> country split of tracked H100-equivalent capacity."""
    us = cn = tot = 0.0
    us_n = cn_n = n = 0
    for r in rows:
        try:
            h = float(r.get("H100 equivalents") or 0)
        except ValueError:
            continue
        if h <= 0:
            continue
        n += 1
        tot += h
        side = country_side(r.get("Country"))
        if side == "us":
            us += h
            us_n += 1
        elif side == "cn":
            cn += h
            cn_n += 1
    if not us or not cn:
        raise ValueError("no tracked capacity on one side - column drift?")
    return {"us_share": round(us / tot * 100, 1), "cn_share": round(cn / tot * 100, 1),
            "us_h100e": round(us), "cn_h100e": round(cn), "total_h100e": round(tot),
            "us_n": us_n, "cn_n": cn_n, "n": n,
            "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "attribution": EPOCH_ATTRIBUTION}


def epoch_gpu_clusters():
    return parse_gpu_clusters(epoch_csv(EPOCH_GPU_CLUSTERS_CSV))


def chip_side(mfg):
    """Chip designer -> 'cn' | 'us' | None (unknown designers are skipped, not guessed)."""
    m = (mfg or "").lower()
    return "cn" if m in CHIP_DESIGNERS_CN else "us" if m in CHIP_DESIGNERS_US else None


def parse_chip_sales(rows):
    """Quarterly accelerator output in H100e (median estimates), US- vs CN-designed.

    The chart the page draws from this is the CN *share* line, not two absolute lines:
    US-designed output runs ~20x Chinese on a linear axis, which would just flatten the
    Chinese line onto zero and hide the only movement that matters here."""
    qs, cn_chips = {}, {}
    for r in rows:
        side = chip_side(r.get("Chip manufacturer"))
        d = r.get("Start date") or ""
        try:
            h = float(r.get("Compute estimate in H100e (median)") or 0)
        except ValueError:
            continue
        if not side or len(d) < 7 or h <= 0:
            continue
        q = quarter_of(d)
        qs.setdefault(q, {"us": 0.0, "cn": 0.0})[side] += h
        if side == "cn":
            cn_chips.setdefault(q, []).append(
                {"chip": r.get("Chip type") or r.get("Name"), "h100e": round(h)})
    if len(qs) < 4:
        raise ValueError("too few quarters parsed - column drift?")
    full = [{"q": q, "us": round(v["us"]), "cn": round(v["cn"])}
            for q, v in sorted(qs.items())]
    # Chinese estimates start later and lag ~2 quarters behind Nvidia's (estimates for
    # Huawei/Cambricon are generated in batches upstream). A quarter with cn=0 outside
    # the covered window means "no estimate yet", not "no chips" - showing it would
    # plot a fake collapse to zero. Keep only the both-sides-covered window.
    covered = [i for i, r in enumerate(full) if r["cn"] > 0]
    if not covered:
        raise ValueError("no Chinese-designer quarters parsed - column drift?")
    series = full[covered[0]:covered[-1] + 1][-16:]
    last = series[-1]
    return {"series": series, "latest_q": last["q"],
            "cn_share_latest": round(last["cn"] / (last["cn"] + last["us"]) * 100, 1),
            "cn_top": sorted(cn_chips.get(last["q"], []), key=lambda c: -c["h100e"])[:4],
            "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "attribution": EPOCH_ATTRIBUTION}


def epoch_chip_sales():
    return parse_chip_sales(epoch_csv(EPOCH_CHIP_SALES_CSV))


def parse_notable_models(rows, today=None):
    """Notable-model releases per quarter by side + trailing-12-month totals.

    The current quarter is excluded from the SERIES (a 5-week quarter plots as a fake
    collapse next to 13-week ones) but its releases still count in the trailing-12-month
    totals, which are calendar-day-bounded and don't have that artefact."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cutoff = f"{int(today[:4]) - 1}{today[4:]}"
    cur_q = quarter_of(today)
    qs, tot12 = {}, {"us": 0, "cn": 0}
    for r in rows:
        d = r.get("Publication date") or ""
        side = country_side(r.get("Country (of organization)"))
        if len(d) < 7 or d[:7] < EPOCH_MODELS_SINCE or not side:
            continue
        q = quarter_of(d)
        if q < cur_q:
            qs.setdefault(q, {"us": 0, "cn": 0})[side] += 1
        if d >= cutoff:
            tot12[side] += 1
    if len(qs) < 4:
        raise ValueError("too few quarters parsed - column drift?")
    series = [{"q": q, **v} for q, v in sorted(qs.items())]
    return {"series": series, "us_12mo": tot12["us"], "cn_12mo": tot12["cn"],
            "latest_q": series[-1]["q"], "asof": today,
            "attribution": EPOCH_ATTRIBUTION}


def epoch_notable_models():
    return parse_notable_models(epoch_csv(EPOCH_NOTABLE_MODELS_CSV))


def epoch_fresh(prev_fam, stamp, days=EPOCH_REFRESH_DAYS):
    """True when the previous run's parsed value is recent enough to skip a refetch.
    Both halves must exist: a stamp without a carried value (or vice versa) refetches."""
    return bool(prev_fam) and bool(stamp) and (time.time() - stamp["t"]) < days * 86400


def run():
    hist_path = HERE / "china-history.json"
    hist = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    data_path = HERE / "china-data.json"
    prev = json.loads(data_path.read_text()) if data_path.exists() else {}
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), **MANUAL}

    print("lmarena leaderboard (official HF dataset, arena.ai scrape as fallback) ...")
    for src in (lmarena_dataset, arena):
        try:
            out["lmarena"] = src()
            print(f"  best CN: {out['lmarena']['best_model']} #{out['lmarena']['best_rank']}"
                  f" via {out['lmarena']['source']}")
            break
        except Exception as e:
            print(f"  {src.__name__} FAILED ({e})", file=sys.stderr)
    else:
        print("  both sources failed - page keeps its embedded snapshot", file=sys.stderr)

    print("github basket discovery ...")
    gh_repos, gh_src = github_basket()
    print(f"  {len(gh_repos)} active repos via {gh_src}: {', '.join(gh_repos)}")
    out["github"] = {"repos": gh_repos, "source": gh_src,
                     "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d")}

    print("github velocity ...")
    per_day, stars, repo_vel = github_velocity(hist, gh_repos)
    vel = pick_github_velocity(per_day, prev, stars)
    if vel is not None:
        out["github_stars_per_day"] = vel
    # per-repo rates: fresh measurement wins, else carry the previous run's so the
    # page's Δ/day column never regresses to "…" between measurable runs
    if repo_vel:
        out["github"]["vel"] = repo_vel
    elif (prev.get("github") or {}).get("vel"):
        out["github"]["vel"] = prev["github"]["vel"]
    if per_day is not None:
        print(f"  +{per_day:.0f} stars/day across basket")
    elif vel is not None:
        print(f"  baseline too fresh to remeasure - carrying previous +{vel:.0f}/day")
    elif not stars:
        print("  every repo failed - baseline left untouched, no velocity published",
              file=sys.stderr)
    else:
        print("  baseline stored; velocity available from next run (>20h apart)")

    print("hugging face downloads ...")
    try:
        out["hf"] = huggingface()
        print(f"  CN {out['hf']['cn']/1e6:.0f}M vs US {out['hf']['us']/1e6:.0f}M / 30d")
    except Exception as e:
        print(f"  FAILED ({e}) - page falls back to its client fetch", file=sys.stderr)

    print("openrouter weekly share ...")
    try:
        wk = openrouter_week()
        out["openrouter_week"] = wk
        csv_path = HERE / "china-snapshots.csv"
        new = not csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "or_week", "cn_share", "us_share", "spi", "total_tokens"])
            w.writerow([out["snapshot_date"], wk["week"], wk["cn_share"], wk["us_share"], wk["spi"], wk["total_tokens"]])
        print(f"  CN {wk['cn_share']:.1%} / US {wk['us_share']:.1%} / SPI {wk['spi']}x (wk {wk['week']})")
    except Exception as e:
        print(f"  FAILED ({e})", file=sys.stderr)

    print("google trends search interest ...")
    fresh = None
    try:
        fresh = google_trends()
        print(f"  CN {fresh['western_share_pct']}% of US AI-assistant search interest")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous trends value or manual snapshot", file=sys.stderr)
    out["search_consumer"] = pick_search_consumer(fresh, prev, MANUAL["search_consumer"])

    print("consumer app Western chart presence ...")
    fresh_apps = None
    try:
        fresh_apps = compute_apps()
        if fresh_apps:
            print(f"  score {fresh_apps['score']}/100 - {fresh_apps['detail']}")
        else:
            print("  no store reachable - carrying previous apps value or manual snapshot")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous apps value or manual snapshot", file=sys.stderr)
    out["apps"] = pick_apps(fresh_apps, prev, MANUAL["apps"])

    print("vercel ai gateway lab share ...")
    try:
        out["vercel_gateway"] = vercel_gateway()
        vg = out["vercel_gateway"]
        print(f"  CN {vg['cn_share']}% / US {vg['us_share']}% / SPI {vg['spi']}x ({vg['asof']})")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous value", file=sys.stderr)
        if prev.get("vercel_gateway"):
            out["vercel_gateway"] = prev["vercel_gateway"]

    print("ollama pull counts ...")
    try:
        out["ollama"] = ollama_pulls(hist)
        o = out["ollama"]
        print(f"  CN {o['cn']/1e6:.0f}M vs US {o['us']/1e6:.0f}M lifetime pulls ({o['n_models']} models scanned)")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous value", file=sys.stderr)
        if prev.get("ollama"):
            out["ollama"] = prev["ollama"]

    print("kalshi prediction markets ...")
    try:
        out["kalshi"] = kalshi_markets()
        print(f"  {len(out['kalshi']['markets'])} markets")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous value", file=sys.stderr)
        if prev.get("kalshi"):
            out["kalshi"] = prev["kalshi"]

    print("hugging face fine-tune trees ...")
    try:
        out["hf_finetunes"] = hf_finetunes()
        ft = out["hf_finetunes"]
        print(f"  CN {ft['cn_total']} vs US {ft['us_total']} fine-tunes across baskets")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous value", file=sys.stderr)
        if prev.get("hf_finetunes"):
            out["hf_finetunes"] = prev["hf_finetunes"]

    print("pypi sdk downloads ...")
    try:
        out["sdk"] = sdk_downloads()
        print(f"  {len(out['sdk']['cn'])} CN + {len(out['sdk']['us'])} US packages")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous value", file=sys.stderr)
        if prev.get("sdk"):
            out["sdk"] = prev["sdk"]

    print("artificial analysis (Data API if key set) ...")
    fresh_aa = fresh_frontier = None
    try:
        got = artificial_analysis()
        if got:
            fresh_aa, fresh_frontier = got
            print(f"  CN {fresh_aa['cn_best']} {fresh_aa['cn_score']} vs US {fresh_aa['us_best']} {fresh_aa['us_score']}")
            if fresh_frontier:
                print(f"  frontier gap {fresh_frontier['gap_points']} pts, CN lag {fresh_frontier['lag_months']} mo")
        else:
            print("  ARTIFICIAL_ANALYSIS_API_KEY not set - carrying previous API value or manual snapshot")
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous API value or manual snapshot", file=sys.stderr)
    out["artificial_analysis"] = pick_aa(fresh_aa, prev, MANUAL["artificial_analysis"])
    if fresh_frontier:
        out["aa_frontier"] = fresh_frontier
    elif prev.get("aa_frontier"):
        out["aa_frontier"] = prev["aa_frontier"]

    print("cloudflare radar gen-AI service ranks (if token set) ...")
    try:
        radar = radar_ai()
        if radar:
            out["radar_ai"] = radar
            print(f"  {radar['cn_in_top20']} Chinese services in gen-AI top 20")
        else:
            print("  CF_RADAR_TOKEN not set - carrying previous value if any")
            if prev.get("radar_ai"):
                out["radar_ai"] = prev["radar_ai"]
    except Exception as e:
        print(f"  FAILED ({e}) - carrying previous value", file=sys.stderr)
        if prev.get("radar_ai"):
            out["radar_ai"] = prev["radar_ai"]

    print(f"epoch supply-side datasets (refetched every {EPOCH_REFRESH_DAYS}d) ...")
    for key, label, fn in (("epoch_compute", "gpu clusters", epoch_gpu_clusters),
                           ("epoch_chips", "chip sales", epoch_chip_sales),
                           ("epoch_models", "notable models", epoch_notable_models)):
        if epoch_fresh(prev.get(key), hist.get(key)):
            out[key] = prev[key]
            print(f"  {label}: carried (fetched <{EPOCH_REFRESH_DAYS}d ago)")
            continue
        try:
            out[key] = fn()
            hist[key] = {"t": time.time()}
            print(f"  {label}: ok ({out[key]['asof']})")
        except Exception as e:
            print(f"  {label} FAILED ({e}) - carrying previous value", file=sys.stderr)
            if prev.get(key):
                out[key] = prev[key]

    print("frontier price gap (OpenRouter catalogue) ...")
    price_gap = None
    try:
        price_gap = openrouter_price_gap()
        print(f"  US ${price_gap['us_med']}/M vs CN ${price_gap['cn_med']}/M = {price_gap['gap']}x")
    except Exception as e:
        print(f"  FAILED ({e}) - metrics row logs no gap today", file=sys.stderr)

    print("daily metrics history ...")
    try:
        row = metrics_row(out, price_gap)
        append_metrics(HERE / "china-metrics.csv", row)
        print(f"  index {row['adoption_index']} / SPI {row['spi']} appended for {row['date']}")
    except Exception as e:
        print(f"  FAILED ({e}) - history row skipped this run", file=sys.stderr)

    hist_path.write_text(json.dumps(hist))
    data_path.write_text(json.dumps(out, indent=1))
    print(f"wrote china-data.json ({out['updated']})")


if __name__ == "__main__":
    if "--watch" in sys.argv:
        every = int(sys.argv[sys.argv.index("--watch") + 1])
        while True:
            try:
                run()
            except Exception as e:
                print(f"run failed: {e}", file=sys.stderr)
            time.sleep(every)
    else:
        run()
