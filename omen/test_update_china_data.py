import importlib.util
import re
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "ucd", Path(__file__).parent / "update-china-data.py")
ucd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ucd)


def tl(*rows):
    return [{"value": list(r)} for r in rows]


def test_parse_gjson_strips_antiscrape_prefix():
    assert ucd.parse_gjson(b")]}',\n{\"a\": 1}") == {"a": 1}


def test_us_terms_include_llama_and_meta():
    assert "Llama AI" in ucd.TRENDS_TERMS_US
    assert "Meta AI" in ucd.TRENDS_TERMS_US


def test_trends_batches_share_anchor_and_respect_5_term_cap():
    batches = ucd.trends_batches()
    assert batches[0][:len(ucd.TRENDS_TERMS_US)] == ucd.TRENDS_TERMS_US
    flat = batches[0] + [t for b in batches[1:] for t in b[1:]]
    assert flat == ucd.TRENDS_TERMS_US + ucd.TRENDS_TERMS_CN
    for b in batches:
        assert len(b) <= 5
        assert b[0] == "ChatGPT"


def test_trends_avgs_averages_per_term():
    assert ucd.trends_avgs(tl([80, 30, 4], [70, 35, 6]), 3) == [75, 32.5, 5]


def test_trends_avgs_rejects_empty_timeline():
    with pytest.raises(ValueError):
        ucd.trends_avgs([], 3)


def test_merge_anchored_rescales_by_shared_anchor():
    batches = [["ChatGPT", "Gemini", "DeepSeek"], ["ChatGPT", "Kimi"]]
    merged = ucd.merge_anchored(batches, [[80, 30, 4], [40, 3]])
    # batch 2 anchor 40 vs 80 -> scale x2
    assert merged == {"ChatGPT": 80, "Gemini": 30, "DeepSeek": 4, "Kimi": 6}


def test_merge_anchored_rejects_zero_anchor():
    with pytest.raises(ValueError):
        ucd.merge_anchored([["ChatGPT", "Gemini"], ["ChatGPT", "Kimi"]],
                           [[80, 30], [0, 3]])


def test_trends_search_consumer_computes_cn_share():
    merged = {t: 0.0 for t in ucd.TRENDS_TERMS_US + ucd.TRENDS_TERMS_CN}
    merged.update({"ChatGPT": 75, "Gemini": 32.5, "Claude": 27.5,
                   "DeepSeek": 4, "Qwen": 1})
    sc = ucd.trends_search_consumer(merged)
    # cn 5 / total 140 = 3.57%
    assert sc["western_share_pct"] == 3.6
    assert sc["source"] == "google-trends"
    assert re.fullmatch(r"\d{4}-\d{2}", sc["asof"])
    assert "Google Trends" in sc["note"]


def test_trends_search_consumer_rejects_all_zero():
    merged = {t: 0 for t in ucd.TRENDS_TERMS_US + ucd.TRENDS_TERMS_CN}
    with pytest.raises(ValueError):
        ucd.trends_search_consumer(merged)


def test_pick_search_consumer_prefers_fresh():
    fresh = {"western_share_pct": 2.7, "source": "google-trends"}
    assert ucd.pick_search_consumer(fresh, {}, ucd.MANUAL["search_consumer"]) is fresh


def test_pick_search_consumer_carries_forward_previous_trends_value():
    prev = {"search_consumer": {"western_share_pct": 3.1, "source": "google-trends", "asof": "2026-06"}}
    got = ucd.pick_search_consumer(None, prev, ucd.MANUAL["search_consumer"])
    assert got == prev["search_consumer"]


def test_pick_search_consumer_falls_back_to_manual():
    # previous value without a trends source (old Goodie snapshot) is not carried
    prev = {"search_consumer": {"western_share_pct": 1, "asof": "2026-04"}}
    got = ucd.pick_search_consumer(None, prev, ucd.MANUAL["search_consumer"])
    assert got == ucd.MANUAL["search_consumer"]


# ---- consumer-app Western chart presence (iOS Apple RSS + Android Play) ----

def test_app_points_maps_rank_to_top100_scale():
    # top-100 only: #1 -> 100, #100 -> 1, anything past the top-100 -> 0
    assert ucd.app_points(1) == 100
    assert ucd.app_points(82) == 19    # Kimi CA Play snapshot (only real top-100 hit)
    assert ucd.app_points(100) == 1
    assert ucd.app_points(101) == 0
    assert ucd.app_points(194) == 0    # Talkie US Play: charts, but far outside top-100


def test_match_app_identifies_basket_by_title_or_appid():
    assert ucd.match_app("DeepSeek - AI Assistant", "com.deepseek.chat") == "DeepSeek"
    assert ucd.match_app("Kimi", "com.moonshot.kimichat") == "Kimi"
    # Talkie carries no "minimax" in its title/appId; matched via the talkie/weaver pattern
    assert ucd.match_app("Talkie: Creative AI Community", "com.weaver.app.prod") == "MiniMax"
    assert ucd.match_app("ChatGPT", "com.openai.chatgpt") is None
    assert ucd.match_app("TikTok Pro - Events", "com.ss.android.ugc.tiktok.pro") is None


def test_apps_score_is_basket_mean_of_best_per_app_points():
    # Kimi cracks a top-100 (CA #82); the rest only chart in the 101-200 tail
    hits = [
        {"label": "Kimi", "store": "android", "country": "ca", "rank": 82},
        {"label": "Kimi", "store": "android", "country": "gb", "rank": 186},   # worse dup ignored
        {"label": "MiniMax", "store": "android", "country": "br", "rank": 112},
        {"label": "MiniMax", "store": "android", "country": "us", "rank": 194},
    ]
    out = ucd.apps_score(hits)
    # basket of 5: (Kimi 19 + MiniMax 0 + DeepSeek 0 + Qwen 0 + Doubao 0) / 5 = 3.8 -> 4
    assert out["score"] == 4
    assert out["source"] == "app-charts"
    assert out["best"][0]["label"] == "Kimi" and out["best"][0]["rank"] == 82
    assert "Kimi" in out["detail"]  # detail surfaces the top-100 hit


def test_apps_score_zero_when_no_hits():
    out = ucd.apps_score([])
    assert out["score"] == 0
    assert out["source"] == "app-charts"
    assert "no chinese ai app" in out["detail"].lower()


def test_apps_score_rewards_a_top_ranked_app():
    hits = [{"label": "DeepSeek", "store": "ios", "country": "us", "rank": 1}]
    out = ucd.apps_score(hits)
    assert out["score"] == 20  # (100 + 0 + 0 + 0 + 0) / 5


def test_pick_apps_prefers_fresh():
    fresh = {"score": 2, "source": "app-charts"}
    assert ucd.pick_apps(fresh, {}, ucd.MANUAL["apps"]) is fresh


def test_pick_apps_carries_forward_previous_computed_value():
    prev = {"apps": {"score": 3, "source": "app-charts", "asof": "2026-07-18"}}
    got = ucd.pick_apps(None, prev, ucd.MANUAL["apps"])
    assert got == prev["apps"]


def test_pick_apps_falls_back_to_manual():
    # previous judgmental snapshot (no app-charts source) is not carried
    prev = {"apps": {"score": 20, "asof": "2026-01"}}
    got = ucd.pick_apps(None, prev, ucd.MANUAL["apps"])
    assert got == ucd.MANUAL["apps"]


BASKET = {r: 35000 for r in ucd.GH_SEED}


def stub_github(stars, monkeypatch):
    """Make github_velocity see exactly `stars`; any other repo fails like a 403."""
    def jget(url, *a, **kw):
        repo = url.split("/repos/", 1)[1]
        if repo not in stars:
            raise RuntimeError("403 rate limit exceeded")
        return {"stargazers_count": stars[repo]}
    monkeypatch.setattr(ucd, "jget", jget)


def test_pick_github_velocity_prefers_fresh_measurement():
    assert ucd.pick_github_velocity(41.66, {"github_stars_per_day": 99.0}, BASKET) == 41.7


def test_pick_github_velocity_carries_forward_previous_value():
    prev = {"github_stars_per_day": 32.3}
    assert ucd.pick_github_velocity(None, prev, BASKET) == 32.3


def test_pick_github_velocity_none_when_never_measured():
    assert ucd.pick_github_velocity(None, {}, BASKET) is None
    assert ucd.pick_github_velocity(None, None, BASKET) is None


def test_pick_github_velocity_drops_a_carried_value_larger_than_the_basket():
    # the basket cannot gain or lose more stars in a day than it holds; a value that
    # big came from a run measured against a broken baseline, so it must not be carried
    assert ucd.pick_github_velocity(None, {"github_stars_per_day": -282776.7}, BASKET) is None
    assert ucd.pick_github_velocity(None, {"github_stars_per_day": 120.0}, BASKET) == 120.0


def test_pick_github_velocity_carries_forward_when_the_basket_is_unknown():
    # every repo failed this run, so there is nothing to sanity-check against - a
    # GitHub outage must not erase the last good measurement
    assert ucd.pick_github_velocity(None, {"github_stars_per_day": 32.3}, {}) == 32.3


def test_gh_headers_authorize_only_when_a_token_is_set(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert ucd.gh_headers() == {}
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")
    assert ucd.gh_headers()["Authorization"] == "Bearer ghs_test"


def test_github_velocity_seeds_the_baseline_on_a_first_run(monkeypatch):
    stub_github(BASKET, monkeypatch)
    hist = {}
    per_day, stars, _vel = ucd.github_velocity(hist, ucd.GH_SEED)
    assert per_day is None and stars == BASKET
    assert hist["github"]["stars"] == BASKET


def test_github_velocity_never_seeds_a_baseline_when_every_repo_fails(monkeypatch):
    # the bug of record: an all-failed run stored total=0 / stars={}, and the old
    # reseed only fired when the key was absent, so the baseline was poisoned for good
    stub_github({}, monkeypatch)
    hist = {}
    per_day, stars, _vel = ucd.github_velocity(hist, ucd.GH_SEED)
    assert per_day is None and stars == {}
    assert "github" not in hist


def test_github_velocity_reseeds_a_baseline_left_empty_by_a_failed_run(monkeypatch):
    stub_github(BASKET, monkeypatch)
    hist = {"github": {"t": time.time() - 5 * 86400, "total": 0, "stars": {}}}
    per_day, _, _vel = ucd.github_velocity(hist, ucd.GH_SEED)
    assert per_day is None
    assert hist["github"]["stars"] == BASKET


def test_github_velocity_measures_only_repos_present_in_both_snapshots(monkeypatch):
    # two repos fail this run; the rate is over the five we can see on both sides,
    # not the whole basket "losing" everything the missing two had
    seen = {r: 35100 for r in ucd.GH_SEED[:-2]}
    stub_github(seen, monkeypatch)
    hist = {"github": {"t": time.time() - 2 * 86400, "stars": dict(BASKET)}}
    per_day, _, _vel = ucd.github_velocity(hist, ucd.GH_SEED)
    assert per_day == pytest.approx(len(seen) * 100 / 2, rel=1e-3)
    assert hist["github"]["stars"] == seen


def test_github_velocity_keeps_a_fresh_baseline_until_it_ages_past_20h(monkeypatch):
    stub_github({r: 99000 for r in ucd.GH_SEED}, monkeypatch)
    t0 = time.time() - 3600
    hist = {"github": {"t": t0, "stars": dict(BASKET)}}
    per_day, _, _vel = ucd.github_velocity(hist, ucd.GH_SEED)
    assert per_day is None
    assert hist["github"] == {"t": t0, "stars": BASKET}


# ---- dynamic GitHub basket (2026-08-02) ------------------------------------------

NOW = 1_785_000_000.0        # fixed clock so "pushed N days ago" is deterministic


def repo(name, stars, days_ago):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days_ago * 86400))
    return {"full_name": name, "stargazers_count": stars, "pushed_at": ts}


def stub_search(items_by_org, monkeypatch):
    def jget(url, *a, **kw):
        org = url.split("q=org:", 1)[1].split("+", 1)[0]
        if org not in items_by_org:
            raise RuntimeError("422 search unavailable")
        return {"items": items_by_org[org]}
    monkeypatch.setattr(ucd, "jget", jget)


def test_gh_active_repos_drops_repos_pushed_outside_the_active_window(monkeypatch):
    # the whole bug: DeepSeek-V3 still has 104k stars but has not been pushed to since
    # 2025-08, so its star drift is not an adoption signal for anything
    stub_search({"x": [repo("x/Dead-Flagship", 104000, 340),
                       repo("x/Live-Model", 7800, 5)]}, monkeypatch)
    assert ucd.gh_active_repos("x", now=NOW) == ["x/Live-Model"]


def test_gh_active_repos_excludes_awesome_lists_and_docs(monkeypatch):
    stub_search({"x": [repo("x/awesome-x-integration", 38000, 10),
                       repo("x/x-cookbook", 9000, 3),
                       repo("x/Real-Model", 5000, 3)]}, monkeypatch)
    assert ucd.gh_active_repos("x", now=NOW) == ["x/Real-Model"]


def test_gh_active_repos_caps_at_per_org_limit(monkeypatch):
    stub_search({"x": [repo(f"x/r{i}", 9000 - i, 2) for i in range(6)]}, monkeypatch)
    assert len(ucd.gh_active_repos("x", now=NOW)) == ucd.GH_PER_ORG


def test_gh_active_repos_tolerates_a_malformed_pushed_at(monkeypatch):
    stub_search({"x": [{"full_name": "x/no-date", "stargazers_count": 1},
                       repo("x/ok", 10, 1)]}, monkeypatch)
    assert ucd.gh_active_repos("x", now=NOW) == ["x/ok"]


def test_github_basket_falls_back_to_the_seed_when_every_org_fails(monkeypatch):
    stub_search({}, monkeypatch)
    repos, src = ucd.github_basket(now=NOW)
    assert (repos, src) == (ucd.GH_SEED, "seed")


def test_github_basket_keeps_a_partial_result_when_one_org_fails(monkeypatch):
    # one lab's search failing must not throw the run back to the stale seed basket
    stub_search({"MoonshotAI": [repo("MoonshotAI/Kimi-K3", 7800, 5)]}, monkeypatch)
    repos, src = ucd.github_basket(now=NOW)
    assert (repos, src) == (["MoonshotAI/Kimi-K3"], "search")


def test_github_basket_returns_sorted_repos_across_orgs(monkeypatch):
    stub_search({o: [repo(f"{o}/model", 100, 1)] for o in ucd.GH_ORGS}, monkeypatch)
    repos, src = ucd.github_basket(now=NOW)
    assert src == "search"
    assert repos == sorted(repos) and len(repos) == len(ucd.GH_ORGS)


def test_github_velocity_rebaselines_when_the_basket_has_no_overlap(monkeypatch):
    # swapping the basket leaves nothing measurable this run, but the new membership
    # must still be written down or the velocity can never recover
    stub_github({"new/A": 500, "new/B": 700}, monkeypatch)
    hist = {"github": {"t": time.time() - 2 * 86400, "stars": {"old/X": 1000}}}
    per_day, stars, _vel = ucd.github_velocity(hist, ["new/A", "new/B"])
    assert per_day is None
    assert hist["github"]["stars"] == {"new/A": 500, "new/B": 700}


# ---- new source families (2026-07-20) --------------------------------------------

def test_parse_count_handles_suffixes_and_commas():
    assert ucd.parse_count("117.3M") == 117300000
    assert ucd.parse_count("2.1K") == 2100
    assert ucd.parse_count("5,000") == 5000
    assert ucd.parse_count("1B") == 1000000000


def test_ollama_side_classifies_named_families_only():
    assert ucd.ollama_side("deepseek-r1") == "cn"
    assert ucd.ollama_side("qwen2.5-coder") == "cn"
    assert ucd.ollama_side("llama3.1") == "us"
    assert ucd.ollama_side("gpt-oss") == "us"
    assert ucd.ollama_side("mistral") is None       # FR - outside both baskets
    assert ucd.ollama_side("llava") is None          # academic community model


def test_ollama_models_parses_library_chunks():
    page = ('<a href="/library/deepseek-r1" class="group">'
            '<span >90M</span>\n<span class="hidden sm:flex">&nbsp;Pulls</span></a>'
            '<a href="/library/llama3.1"><span>117.3M</span> <span>&nbsp;Pulls</span></a>')
    got = ucd.ollama_models(page)
    assert got == [{"name": "deepseek-r1", "pulls": 90000000},
                   {"name": "llama3.1", "pulls": 117300000}]


def test_ollama_models_rejects_pageful_of_nothing():
    with pytest.raises(ValueError):
        ucd.ollama_models("<html>redesigned page</html>")


def test_vercel_days_aggregates_token_share_by_date():
    rows = [
        {"date": "2026-07-18", "name": "deepseek", "metric": "tokens", "share_percent": 20.0},
        {"date": "2026-07-18", "name": "anthropic", "metric": "tokens", "share_percent": 30.0},
        {"date": "2026-07-18", "name": "deepseek", "metric": "requests", "share_percent": 99.0},
        {"date": "2026-07-19", "name": "zai", "metric": "tokens", "share_percent": 5.0},
        {"date": "2026-07-19", "name": "somelab", "metric": "tokens", "share_percent": 4.0},
    ]
    got = ucd.vercel_days(rows)
    assert got == [{"d": "2026-07-18", "cn": 20.0, "us": 30.0},
                   {"d": "2026-07-19", "cn": 5.0, "us": 0.0}]


def test_vercel_days_rejects_export_without_token_rows():
    with pytest.raises(ValueError):
        ucd.vercel_days([{"date": "2026-07-18", "name": "x", "metric": "spend", "share_percent": 1}])


def test_arena_summary_counts_cn_orgs_case_insensitively():
    rows = [
        {"model": "claude-fable-5", "org": "anthropic", "rank": 1, "elo": 1507},
        {"model": "kimi-k3", "org": "moonshot", "rank": 10, "elo": 1486},
        {"model": "qwen-max", "org": "Alibaba", "rank": 15, "elo": 1470},
    ]
    got = ucd.arena_summary(rows)
    assert got["best_model"] == "kimi-k3"
    assert got["us_leader"] == "claude-fable-5"
    assert (got["top10"], got["top20"]) == (1, 2)


def test_arena_summary_strips_ai_suffix_from_org():
    rows = [
        {"model": "us", "org": "OpenAI", "rank": 1, "elo": 1500},
        {"model": "k2", "org": "Moonshot AI", "rank": 5, "elo": 1480},
    ]
    assert ucd.arena_summary(rows)["best_org"] == "Moonshot AI"


def test_arena_summary_rejects_all_us_board():
    with pytest.raises(ValueError):
        ucd.arena_summary([{"model": "m", "org": "openai", "rank": 1, "elo": 1500}])


def test_kalshi_price_prefers_dollars_string():
    assert ucd.kalshi_price({"last_price_dollars": "0.1900"}) == 0.19
    assert ucd.kalshi_price({"last_price_dollars": None}) is None
    assert ucd.kalshi_price({}) is None


def test_kalshi_pick_yearend_cn_brands_plus_top_us_reference():
    mkts = [
        {"event_ticker": "KXLLM1-26DEC31", "yes_sub_title": "Kimi", "last_price_dollars": "0.02"},
        {"event_ticker": "KXLLM1-26DEC31", "yes_sub_title": "Qwen", "last_price_dollars": "0.009"},
        {"event_ticker": "KXLLM1-26DEC31", "yes_sub_title": "Claude", "last_price_dollars": "0.61"},
        {"event_ticker": "KXLLM1-26DEC31", "yes_sub_title": "ChatGPT", "last_price_dollars": "0.15"},
        {"event_ticker": "KXLLM1-26JUL20", "yes_sub_title": "Kimi", "last_price_dollars": "0.01"},
    ]
    cn, us_ref = ucd.kalshi_pick(mkts)
    assert [m["yes_sub_title"] for m in cn] == ["Kimi", "Qwen"]
    assert [m["yes_sub_title"] for m in us_ref] == ["Claude"]


def test_parse_finetune_count_reads_model_tree_link():
    page = ('... <a class="x" href="/models?other=base_model:finetune:Qwen/Qwen3-8B">'
            "1,951 models</a> ...")
    assert ucd.parse_finetune_count(page, "Qwen/Qwen3-8B") == 1951
    with pytest.raises(ValueError):
        ucd.parse_finetune_count(page, "meta-llama/Llama-3.1-8B")


def test_aa_best_picks_top_intelligence_index_per_side():
    models = [
        {"name": "GLM-5.2", "model_creator": {"name": "Zhipu AI"},
         "evaluations": {"artificial_analysis_intelligence_index": 51.2}},
        {"name": "DeepSeek V4", "model_creator": {"name": "DeepSeek"},
         "evaluations": {"artificial_analysis_intelligence_index": 49.0}},
        {"name": "Claude Fable 5", "model_creator": {"name": "Anthropic"},
         "evaluations": {"artificial_analysis_intelligence_index": 60.1}},
        {"name": "noscore", "model_creator": {"name": "OpenAI"}, "evaluations": {}},
    ]
    got = ucd.aa_best(models)
    assert (got["cn_best"], got["cn_score"]) == ("GLM-5.2", 51)
    assert (got["us_best"], got["us_score"]) == ("Claude Fable 5", 60)
    assert got["source"] == "aa-api"


def test_aa_best_rejects_one_sided_data():
    with pytest.raises(ValueError):
        ucd.aa_best([{"name": "m", "model_creator": {"name": "Anthropic"},
                      "evaluations": {"artificial_analysis_intelligence_index": 60}}])


def test_pick_aa_carries_forward_api_value_only():
    api_prev = {"artificial_analysis": {"cn_score": 52, "source": "aa-api"}}
    manual_prev = {"artificial_analysis": {"cn_score": 51}}
    fresh = {"cn_score": 55, "source": "aa-api"}
    assert ucd.pick_aa(fresh, api_prev, ucd.MANUAL["artificial_analysis"]) == fresh
    assert ucd.pick_aa(None, api_prev, ucd.MANUAL["artificial_analysis"]) == api_prev["artificial_analysis"]
    assert ucd.pick_aa(None, manual_prev, ucd.MANUAL["artificial_analysis"]) == ucd.MANUAL["artificial_analysis"]


def test_radar_rows_marks_cn_services_and_tolerates_shapes():
    got = ucd.radar_rows({"top_0": [{"rank": 1, "service": "ChatGPT"},
                                    {"rank": 9, "service": "DeepSeek"}]})
    assert got == [{"rank": 1, "name": "ChatGPT", "cn": False},
                   {"rank": 9, "name": "DeepSeek", "cn": True}]
    got2 = ucd.radar_rows({"serviceTop": [{"name": "Kimi"}]})
    assert got2[0]["cn"] is True and got2[0]["rank"] == 1
    with pytest.raises(ValueError):
        ucd.radar_rows({})


# ---------------------------------------------------------------------------
# Daily metrics history: compute_index / resolve_price_lines / append_metrics
# ---------------------------------------------------------------------------

def full_out():
    """One synthetic run with every family live, at easy round numbers."""
    return {
        "snapshot_date": "2026-08-05",
        "openrouter_week": {"cn_share": 0.35, "us_share": 0.35, "spi": 1.0},
        "vercel_gateway": {"cn_share": 35.0},          # percent, like the fetcher emits
        "hf": {"cn": 45, "us": 55},
        "github_stars_per_day": 150,
        "ollama": {"cn": 35, "us": 65},
        "search_consumer": {"western_share_pct": 25},
        "apps": {"score": 40},
        "lmarena": {"us_leader_score": 1509, "best_score": 1459},
    }


def test_compute_index_matches_documented_normalizations():
    idx, fams = ucd.compute_index(full_out())
    # each family sits exactly halfway up its documented reference range
    assert fams == {"router": 50.0, "hf": 50.0, "github": 50.0, "ollama": 50.0,
                    "search": 50.0, "apps": 40.0, "arena": 50.0}
    # full weight sum = 100; hand-computed weighted mean
    want = (30 * 50 + 20 * 50 + 15 * 50 + 10 * 50 + 10 * 50 + 10 * 40 + 5 * 50) / 100
    assert abs(idx - want) < 0.1


def test_compute_index_renormalizes_when_families_are_missing():
    out = full_out()
    del out["hf"], out["ollama"], out["apps"]
    out["github_stars_per_day"] = None
    idx, fams = ucd.compute_index(out)
    assert set(fams) == {"router", "search", "arena"}
    assert abs(idx - (30 * 50 + 10 * 50 + 5 * 50) / 45) < 0.1


def test_compute_index_router_blends_vercel_when_present():
    out = full_out()
    out["vercel_gateway"] = {"cn_share": 70.0}   # normalizes to 100
    _, fams = ucd.compute_index(out)
    assert fams["router"] == 75.0                # mean of 50 and 100
    del out["vercel_gateway"]
    _, fams = ucd.compute_index(out)
    assert fams["router"] == 50.0


def test_compute_index_zero_score_is_a_value_not_an_exclusion():
    out = full_out()
    out["apps"]["score"] = 0
    idx_with_zero, fams = ucd.compute_index(out)
    assert fams["apps"] == 0.0                   # present, scored zero
    out["apps"] = None
    idx_excluded, fams2 = ucd.compute_index(out)
    assert "apps" not in fams2
    assert idx_excluded > idx_with_zero          # excluding renormalizes upward


def test_resolve_price_lines_newest_wins_and_free_excluded():
    models = [
        {"id": "anthropic/claude-opus-4.8", "created": 100, "pricing": {"completion": "0.000025"}},
        {"id": "anthropic/claude-opus-5", "created": 200, "pricing": {"completion": "0.000025"}},
        {"id": "moonshotai/kimi-k3:free", "created": 900, "pricing": {"completion": "0.000015"}},
        {"id": "moonshotai/kimi-k3", "created": 100, "pricing": {"completion": "0.000015"}},
        {"id": "z-ai/glm-5.2", "created": 100, "pricing": {"completion": "0"}},
    ]
    got = ucd.resolve_price_lines(models, ucd.PRICE_LINES_US)
    assert got == [25.0]                          # opus 5, once, at $25/M output
    got_cn = ucd.resolve_price_lines(models, ucd.PRICE_LINES_CN)
    assert got_cn == [15.0]                       # paid kimi only; zero-priced glm dropped


def test_price_lines_mirror_the_pages_families():
    """The JS PRICE_FAMILIES_* and this port must not drift apart."""
    src = (Path(__file__).parent / "china-ai-monitor.html").read_text()
    for label, rx in ucd.PRICE_LINES_CN + ucd.PRICE_LINES_US:
        js = rx.pattern.replace("/", r"\/")
        assert f"re:/{js}/" in src, f"{label}: /{rx.pattern}/ not found in page JS"


def test_append_metrics_one_row_per_day_last_run_wins(tmp_path):
    p = tmp_path / "china-metrics.csv"
    r1 = {c: None for c in ucd.METRICS_COLS} | {"date": "2026-08-04", "adoption_index": 58.0}
    r2 = {c: None for c in ucd.METRICS_COLS} | {"date": "2026-08-05", "adoption_index": 59.5}
    r3 = {c: None for c in ucd.METRICS_COLS} | {"date": "2026-08-05", "adoption_index": 60.1}
    for r in (r1, r2, r3):
        ucd.append_metrics(p, r)
    lines = p.read_text().strip().split("\n")
    assert lines[0].split(",") == ucd.METRICS_COLS
    assert len(lines) == 3                        # header + one row per day
    assert lines[2].startswith("2026-08-05,60.1,")


def test_metrics_row_carries_shares_and_gap():
    row = ucd.metrics_row(full_out(), {"gap": 5.2, "us_med": 12.0, "cn_med": 2.3})
    assert row["router_cn_share"] == 0.35
    assert row["vercel_cn_share"] == 0.35
    assert row["hf_cn_share"] == 0.45
    assert row["price_gap"] == 5.2
    assert row["adoption_index"] is not None
    row2 = ucd.metrics_row(full_out(), None)
    assert row2["price_gap"] is None


def test_arena_summary_emits_per_model_elo_list():
    rows = [{"model": "claude-fable-5", "org": "Anthropic", "rank": 1, "elo": 1509},
            {"model": "qwen3.8-max", "org": "Alibaba", "rank": 5, "elo": 1496}]
    out = ucd.arena_summary(rows)
    assert out["models"] == [
        {"model": "claude-fable-5", "org": "Anthropic", "elo": 1509, "cn": False},
        {"model": "qwen3.8-max", "org": "Alibaba", "elo": 1496, "cn": True}]


# ---- AA frontier gap --------------------------------------------------------------

def aa_model(name, creator, idx, d, blended=None, inp=None, outp=None):
    p = {}
    if blended is not None:
        p["price_1m_blended_3_to_1"] = blended
    if inp is not None:
        p.update(price_1m_input_tokens=inp, price_1m_output_tokens=outp)
    return {"name": name, "model_creator": {"name": creator},
            "evaluations": {"artificial_analysis_intelligence_index": idx},
            "release_date": d, "pricing": p}


AA_FIXTURE = [
    aa_model("gpt-a", "OpenAI", 45, "2024-06-15", blended=5.0),
    aa_model("gpt-b", "OpenAI", 50, "2025-06-01", blended=6.0),
    aa_model("claude-c", "Anthropic", 60, "2026-03-10", blended=9.0),
    aa_model("claude-cheap", "Anthropic", 58, "2026-05-10", blended=4.0),
    aa_model("qwen-x", "Alibaba", 40, "2024-09-01", blended=1.0),
    aa_model("deepseek-y", "DeepSeek", 50, "2026-01-05", inp=0.4, outp=1.2),
    aa_model("kimi-z", "Moonshot", 57, "2026-07-20", blended=1.5),
    aa_model("undated", "OpenAI", 70, ""),
    aa_model("unsided", "Mistral", 55, "2026-01-01", blended=2.0),
]


def test_month_math_rolls_years():
    assert ucd.month_add("2025-12") == "2026-01"
    assert ucd.month_add("2026-01", 14) == "2027-03"
    assert ucd.months_between("2025-06", "2026-01") == 7
    assert ucd.months_between("2026-03", "2026-03") == 0


def test_aa_points_blends_pricing_and_drops_undated_or_unsided():
    pts = {p["name"]: p for p in ucd.aa_points(AA_FIXTURE)}
    assert "undated" not in pts and "unsided" not in pts
    # blended fallback: (3*0.4 + 1.2) / 4
    assert pts["deepseek-y"]["usd"] == 0.6
    assert pts["gpt-a"]["usd"] == 5.0 and pts["gpt-a"]["d"] == "2024-06"


def test_aa_frontier_series_gap_lag_and_value():
    af = ucd.aa_frontier(AA_FIXTURE, today="2026-08")
    assert af["gap_points"] == 3.0                     # 60 US vs 57 CN
    # US first matched today's CN level (57) in 2026-03; CN got there 2026-07
    assert af["lag_months"] == 4
    assert af["cn_now"] == {"name": "kimi-z", "idx": 57.0}
    assert af["series"][0]["m"] == "2024-06" and af["series"][-1]["m"] == "2026-08"
    assert af["series"][-1] == {"m": "2026-08", "cn": 57.0, "us": 60.0}
    # near-frontier value: cheapest within 3 pts of each side's frontier
    assert af["value"]["us"]["name"] == "claude-cheap"
    assert af["value"]["cn"]["name"] == "kimi-z"
    assert af["value"]["ratio"] == round(4.0 / 1.5, 1)


def test_aa_frontier_rejects_one_sided_dated_data():
    with pytest.raises(ValueError):
        ucd.aa_frontier([aa_model(f"gpt-{i}", "OpenAI", 50 + i, f"2025-0{i}-01")
                         for i in range(1, 5)], today="2026-08")


def test_aa_value_excludes_free_tiers():
    pts = [{"side": "us", "d": "2026-01", "idx": 60.0, "name": "paid", "usd": 8.0},
           {"side": "us", "d": "2026-02", "idx": 60.0, "name": "free", "usd": 0},
           {"side": "cn", "d": "2026-03", "idx": 58.0, "name": "cn", "usd": 2.0}]
    val = ucd.aa_value(pts, {"us": 60.0, "cn": 58.0})
    assert val["us"]["name"] == "paid" and val["ratio"] == 4.0


# ---- Epoch supply-side ------------------------------------------------------------

def test_country_side_is_exclusive_membership():
    assert ucd.country_side("United States of America") == "us"
    assert ucd.country_side("China,China") == "cn"
    assert ucd.country_side("China,Hong Kong") == "cn"
    assert ucd.country_side("United States of America,China") is None   # joint work
    assert ucd.country_side("Hong Kong") is None
    assert ucd.country_side("") is None and ucd.country_side(None) is None


def test_quarter_of_maps_months_to_quarters():
    assert ucd.quarter_of("2026-01-15") == "2026Q1"
    assert ucd.quarter_of("2026-12-31") == "2026Q4"


def gpu_row(country, h100e):
    return {"Country": country, "H100 equivalents": h100e}


def test_parse_gpu_clusters_splits_h100e_by_country():
    got = ucd.parse_gpu_clusters([
        gpu_row("United States of America", "700"), gpu_row("United States of America", "100"),
        gpu_row("China", "150"), gpu_row("Japan", "50"),
        gpu_row("China", ""),            # unspecced cluster: ignored entirely
        gpu_row("China", "not-a-number"),
    ])
    assert (got["us_share"], got["cn_share"]) == (80.0, 15.0)
    assert got["total_h100e"] == 1000 and got["n"] == 4
    assert (got["us_n"], got["cn_n"]) == (2, 1)


def test_parse_gpu_clusters_rejects_one_sided_data():
    with pytest.raises(ValueError):
        ucd.parse_gpu_clusters([gpu_row("United States of America", "700")])


def test_chip_side_known_designers_only():
    assert ucd.chip_side("Huawei") == "cn"
    assert ucd.chip_side("Nvidia") == "us"
    assert ucd.chip_side("TSMC") is None and ucd.chip_side(None) is None


def chip_row(mfg, start, h100e, chip="X1"):
    return {"Chip manufacturer": mfg, "Start date": start,
            "Compute estimate in H100e (median)": h100e, "Chip type": chip}


def test_parse_chip_sales_trims_to_the_cn_covered_window():
    got = ucd.parse_chip_sales([
        chip_row("Nvidia", "2023-01-01", "1000"),           # before CN coverage: dropped
        chip_row("Nvidia", "2023-04-01", "1000"),
        chip_row("Nvidia", "2024-01-01", "900"), chip_row("Huawei", "2024-01-01", "100", "Ascend"),
        chip_row("Nvidia", "2024-04-01", "800"), chip_row("Huawei", "2024-04-01", "200", "Ascend"),
        chip_row("Nvidia", "2024-07-01", "1000"),           # after CN coverage: dropped
        chip_row("TSMC", "2024-04-01", "9999"),             # unknown designer: skipped
    ])
    assert [r["q"] for r in got["series"]] == ["2024Q1", "2024Q2"]
    assert got["latest_q"] == "2024Q2" and got["cn_share_latest"] == 20.0
    assert got["cn_top"] == [{"chip": "Ascend", "h100e": 200}]


def test_parse_chip_sales_rejects_data_without_cn_quarters():
    with pytest.raises(ValueError):
        ucd.parse_chip_sales([chip_row("Nvidia", f"2023-{m:02d}-01", "1000")
                              for m in (1, 4, 7, 10)])


def model_row(country, pub):
    return {"Country (of organization)": country, "Publication date": pub}


def test_parse_notable_models_counts_quarters_and_trailing_year():
    got = ucd.parse_notable_models([
        model_row("United States of America", "2025-02-10"),
        model_row("United States of America", "2025-11-01"),
        model_row("China", "2025-02-20"),
        model_row("China,China", "2026-03-05"),
        model_row("United States of America,China", "2026-03-06"),  # joint: dropped
        model_row("China", "2026-04-01"),
        model_row("United States of America", "2026-05-01"),
        model_row("China", "2026-08-01"),        # current quarter: 12mo yes, series no
        model_row("China", "2022-06-01"),        # pre-window: dropped everywhere
    ], today="2026-08-06")
    assert {r["q"]: (r["us"], r["cn"]) for r in got["series"]} == {
        "2025Q1": (1, 1), "2025Q4": (1, 0), "2026Q1": (0, 1), "2026Q2": (1, 1)}
    assert got["latest_q"] == "2026Q2"
    assert (got["us_12mo"], got["cn_12mo"]) == (2, 3)


def test_epoch_fresh_requires_a_value_and_a_recent_stamp():
    now = time.time()
    fam = {"asof": "2026-08-01"}
    assert ucd.epoch_fresh(fam, {"t": now - 3600})
    assert not ucd.epoch_fresh(fam, {"t": now - 10 * 86400})   # stale stamp
    assert not ucd.epoch_fresh(fam, None)                      # never stamped
    assert not ucd.epoch_fresh(None, {"t": now - 3600})        # stamp but no value


def test_metrics_row_carries_search_apps_and_arena_gap():
    row = ucd.metrics_row(full_out(), None)
    assert row["search_share"] == 0.25       # 25% -> fraction, like the other shares
    assert row["apps_score"] == 40
    assert row["arena_elo_gap"] == 50


def test_append_metrics_migrates_old_schema_rows_instead_of_discarding(tmp_path):
    """Adding a column to METRICS_COLS must widen the history in place - the first
    version of this writer reset the whole file whenever the header changed."""
    p = tmp_path / "china-metrics.csv"
    old_cols = ucd.METRICS_COLS[:9]          # the schema before search/apps/arena
    p.write_text(",".join(old_cols) + "\n" +
                 "2026-08-04,59.8,1.488,0.5162,0.4724,0.6949,0.381,253.7,\n")
    row = {c: None for c in ucd.METRICS_COLS} | {"date": "2026-08-05",
                                                 "adoption_index": 57.7, "apps_score": 0}
    ucd.append_metrics(p, row)
    lines = p.read_text().strip().split("\n")
    assert lines[0].split(",") == ucd.METRICS_COLS
    assert len(lines) == 3                   # header + migrated old row + new row
    assert lines[1].startswith("2026-08-04,59.8,")
    assert lines[1].count(",") == len(ucd.METRICS_COLS) - 1   # padded to new width
    assert lines[2].split(",")[ucd.METRICS_COLS.index("apps_score")] == "0"
