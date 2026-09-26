"""The one Artificial Analysis request both updaters share.

update-china-data.py (the best-model snapshot and the US-vs-CN frontier series) and
update-capex-data.py (token-price deflation, thesis #1) read the same model catalogue,
cut two different ways. The free tier allows 100 requests per 24 hours - not the
"1,000 req/day" this code's comments used to claim - and refresh.yml runs roughly 33
times a day, so two calls per run would spend 66 of them before anyone reran a job by
hand. So it is one request per run: the China step, the only step the key is injected
into, fetches and leaves the response in a cache file; the capex step runs after it in
the same job, reads that file, and never needs the key at all.

The cache lives in the system temp directory, never under omen/. omen/ is the Worker's
assets directory, and a hand-run deploy from a machine holding the cache would publish
AA's whole catalogue as a static file - redistribution the free tier does not grant.

Stdlib only, like everything it is imported by. The parser lives here too, so neither
updater carries its own copy.
"""
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
CACHE = Path(tempfile.gettempdir()) / "omen-aa-models.json"
CACHE_MAX_AGE = 6 * 3600   # comfortably spans one refresh job; a local rerun reuses it too
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) omen-aa-client/1.0"}

# The integration shipped against /api/v2/data/llms/models; the current API reference
# documents /api/v2/language/models. AA checks auth before routing - every path, real or
# invented, answers 401 without a key - so which one works cannot be settled keyless.
# Try the documented path first and fall back on a 404 only; whichever answered is
# recorded as "endpoint" in the cache and printed, so the first keyed run pins it.
AA_URLS = ("https://artificialanalysis.ai/api/v2/language/models",
           "https://artificialanalysis.ai/api/v2/data/llms/models")

# The fields the two updaters actually read. A 200 with these missing is a schema drift,
# not a success, and field_coverage() is how a run says so.
AA_FIELDS = ("model_creator.name", "evaluations.artificial_analysis_intelligence_index",
             "release_date", "pricing.price_1m_blended_3_to_1")

AA_CN_CREATORS = re.compile(r"deepseek|alibaba|qwen|z\.?ai|zhipu|moonshot|minimax|xiaomi|tencent|stepfun|baidu|bytedance|01\.?ai", re.I)
AA_US_CREATORS = re.compile(r"openai|anthropic|google|xai|meta|amazon|nvidia|microsoft", re.I)

# Series start pinned to the modern index era - AA re-bases its index every major
# version, so pre-2024 scores are not comparable and a longer window would fabricate a
# trend. Both the frontier series and the token-price bands start here.
AA_FRONTIER_SINCE = "2024-01"


def aa_side(creator):
    """AA creator name -> 'cn' | 'us' | None."""
    return "cn" if AA_CN_CREATORS.search(creator) else "us" if AA_US_CREATORS.search(creator) else None


def month_add(m, n=1):
    """'2026-01' + n months -> 'YYYY-MM'."""
    y, mo = int(m[:4]), int(m[5:7]) - 1 + n
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


def months_between(a, b):
    """Whole months from month a to month b (positive when b is later)."""
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))


def aa_points(models, sided=True):
    """AA model list -> [{side, d:'YYYY-MM', idx, name, usd}] for dated, scored models.

    usd is the blended $/1M tokens: the API's 3:1 blend when present, else recomputed
    from input/output prices, else None (the model still counts for the frontier, just
    not for the price pick). sided=False keeps models from labs that are neither US nor
    Chinese (side None) - the country cut needs them gone, the price-deflation cut does
    not care who sells the token."""
    pts = []
    for m in models:
        creator = ((m.get("model_creator") or {}).get("name")) or ""
        side = aa_side(creator)
        idx = (m.get("evaluations") or {}).get("artificial_analysis_intelligence_index")
        d = (m.get("release_date") or m.get("first_release_date") or "")[:7]
        if (sided and not side) or idx is None or len(d) != 7:
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


def field_coverage(models):
    """{dotted field: share of models carrying a non-null value}, for AA_FIELDS."""
    def has(m, dotted):
        v = m
        for part in dotted.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        return v is not None
    n = len(models) or 1
    return {f: round(sum(1 for m in models if has(m, f)) / n, 2) for f in AA_FIELDS}


def read_cache(path=CACHE, max_age=CACHE_MAX_AGE, now=None):
    """(models, endpoint) from a cache younger than max_age, else None."""
    try:
        c = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(c, dict) or not isinstance(c.get("data"), list):
        return None
    if (now or time.time()) - float(c.get("t") or 0) > max_age:
        return None
    return c["data"], c.get("endpoint")


def fetch_models(key=None, path=CACHE, max_age=CACHE_MAX_AGE, now=None, opener=None):
    """-> (models, endpoint) or None.

    A fresh cache wins (no request spent); otherwise, with a key, one request - the
    documented endpoint first, the legacy one only on a 404 - and the response is
    cached for the next caller. Without a key and without a fresh cache: None, which
    every caller treats as "carry the previous value"."""
    got = read_cache(path, max_age, now)
    if got:
        return got
    key = key if key is not None else os.environ.get(KEY_ENV)
    if not key:
        return None
    opener = opener or urllib.request.urlopen
    last = None
    for url in AA_URLS:
        req = urllib.request.Request(url, headers={**UA, "x-api-key": key})
        try:
            body = json.loads(opener(req, timeout=60).read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                last = e
                continue
            raise
        models = body.get("data") or []
        cov = field_coverage(models)
        print(f"  aa endpoint {url}: {len(models)} models; field coverage {cov}", file=sys.stderr)
        try:
            Path(path).write_text(json.dumps({"t": now or time.time(), "endpoint": url,
                                              "data": models}))
        except OSError as e:   # a read-only temp dir costs the capex step, not this one
            print(f"  aa cache not written ({e})", file=sys.stderr)
        return models, url
    raise last or ValueError("no AA endpoint answered")
