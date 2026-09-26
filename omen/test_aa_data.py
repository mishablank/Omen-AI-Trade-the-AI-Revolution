"""The shared Artificial Analysis client: one request per run, cache-first, endpoint
fallback on 404 only. No network - the opener is injected."""
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import aa_data


class FakeResp(io.BytesIO):
    pass


def opener_for(answers, calls):
    """answers: {url: payload dict | HTTP status int}."""
    def opener(req, timeout=0):
        calls.append((req.full_url, req.get_header("X-api-key")))
        a = answers[req.full_url]
        if isinstance(a, int):
            raise urllib.error.HTTPError(req.full_url, a, "err", {}, None)
        return FakeResp(json.dumps(a).encode())
    return opener


MODELS = [{"name": "m", "model_creator": {"name": "OpenAI"},
           "evaluations": {"artificial_analysis_intelligence_index": 60},
           "release_date": "2026-01-01", "pricing": {"price_1m_blended_3_to_1": 2.0}}]


def test_no_key_and_no_cache_spends_nothing(tmp_path):
    calls = []
    got = aa_data.fetch_models(key="", path=tmp_path / "c.json", opener=opener_for({}, calls))
    assert got is None and calls == []


def test_documented_endpoint_first_and_response_cached(tmp_path):
    calls, cache = [], tmp_path / "c.json"
    op = opener_for({aa_data.AA_URLS[0]: {"data": MODELS}}, calls)
    models, url = aa_data.fetch_models(key="k", path=cache, now=1000.0, opener=op)
    assert (models, url) == (MODELS, aa_data.AA_URLS[0])
    assert calls == [(aa_data.AA_URLS[0], "k")]
    assert json.loads(cache.read_text())["endpoint"] == aa_data.AA_URLS[0]


def test_legacy_endpoint_only_on_a_404(tmp_path):
    calls = []
    op = opener_for({aa_data.AA_URLS[0]: 404, aa_data.AA_URLS[1]: {"data": MODELS}}, calls)
    _, url = aa_data.fetch_models(key="k", path=tmp_path / "c.json", opener=op)
    assert url == aa_data.AA_URLS[1] and len(calls) == 2


def test_auth_failure_is_not_retried_on_the_other_path(tmp_path):
    # a 401 means a bad key everywhere; walking the list would only spend a second request
    calls = []
    op = opener_for({aa_data.AA_URLS[0]: 401, aa_data.AA_URLS[1]: {"data": MODELS}}, calls)
    with pytest.raises(urllib.error.HTTPError):
        aa_data.fetch_models(key="k", path=tmp_path / "c.json", opener=op)
    assert len(calls) == 1


def test_fresh_cache_serves_the_second_caller_without_a_key(tmp_path):
    cache, calls = tmp_path / "c.json", []
    cache.write_text(json.dumps({"t": 1000.0, "endpoint": "u", "data": MODELS}))
    got = aa_data.fetch_models(key="", path=cache, now=1000.0 + 60, opener=opener_for({}, calls))
    assert got == (MODELS, "u") and calls == []


def test_stale_or_corrupt_cache_is_ignored(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({"t": 0, "endpoint": "u", "data": MODELS}))
    assert aa_data.read_cache(cache, max_age=60, now=10_000) is None
    cache.write_text("{not json")
    assert aa_data.read_cache(cache) is None


def test_cache_lives_outside_the_assets_directory():
    # omen/ is what the Worker serves; AA's catalogue must never land there
    assert Path(__file__).parent.resolve() not in aa_data.CACHE.resolve().parents


def test_field_coverage_reports_what_the_updaters_read():
    cov = aa_data.field_coverage(MODELS + [{"name": "bare"}])
    assert cov["model_creator.name"] == 0.5
    assert set(cov) == set(aa_data.AA_FIELDS)


def test_aa_points_unsided_keeps_other_labs_for_price_cuts():
    m = MODELS + [{"name": "mistral-x", "model_creator": {"name": "Mistral"},
                   "evaluations": {"artificial_analysis_intelligence_index": 55},
                   "release_date": "2026-02-01", "pricing": {"price_1m_blended_3_to_1": 0.5}}]
    assert [p["name"] for p in aa_data.aa_points(m)] == ["m"]
    assert [p["name"] for p in aa_data.aa_points(m, sided=False)] == ["m", "mistral-x"]
