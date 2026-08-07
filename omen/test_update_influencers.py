"""Tests for the KOL auto-scorer's policy rules.

The scores and takes are model-generated, so the fetcher's job is containment: clamp
whatever comes back into the -100..100 scale, truncate the take, refuse to overwrite
a good board with a thin one, and stay a strict no-op without the key. Those rules
are what these tests pin — the model call itself is stubbed.
"""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).parent

spec = importlib.util.spec_from_file_location("ui", HERE / "update-influencers.py")
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

PERSON = {"name": "Test Voice", "org": "Test Org", "cat": "tech",
          "handle": "testvoice", "url": "https://x.com/testvoice"}


def fake_post(score, take="steady as she goes"):
    """A post() stand-in returning what the xAI endpoint would."""
    def _post(url, payload, headers, timeout=90):
        return {"choices": [{"message": {"content": json.dumps({"score": score, "take": take})}}]}
    return _post


# ---------- score_one: containment of model output ----------

def test_score_is_clamped_high(monkeypatch):
    monkeypatch.setattr(ui, "post", fake_post(1500))
    score, _ = ui.score_one(PERSON, "k")
    assert score == 100


def test_score_is_clamped_low(monkeypatch):
    monkeypatch.setattr(ui, "post", fake_post(-1500))
    score, _ = ui.score_one(PERSON, "k")
    assert score == -100


def test_fractional_score_becomes_an_int(monkeypatch):
    monkeypatch.setattr(ui, "post", fake_post(42.6))
    score, _ = ui.score_one(PERSON, "k")
    assert score == 43 and isinstance(score, int)


def test_take_is_truncated(monkeypatch):
    monkeypatch.setattr(ui, "post", fake_post(0, take="x" * 500))
    _, take = ui.score_one(PERSON, "k")
    assert len(take) == 200


def test_handleless_voice_still_scores(monkeypatch):
    """Sløk and Covello have no X handle; the prompt falls back to public commentary."""
    monkeypatch.setattr(ui, "post", fake_post(-50))
    score, _ = ui.score_one({**PERSON, "handle": None}, "k")
    assert score == -50


# ---------- main: the overwrite policy ----------

def run_main(monkeypatch, tmp_path, scorer, key="test-key"):
    out = tmp_path / "influencers.json"
    monkeypatch.setattr(ui, "OUT", str(out))
    monkeypatch.setattr(ui, "score_one", scorer)
    if key is None:
        monkeypatch.delenv("XAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("XAI_API_KEY", key)
    return ui.main(), out


def test_no_key_is_a_no_op(monkeypatch, tmp_path):
    def explode(p, k):
        raise AssertionError("must not score without a key")
    rc, out = run_main(monkeypatch, tmp_path, explode, key=None)
    assert rc == 0 and not out.exists()


def test_thin_roster_refuses_to_overwrite(monkeypatch, tmp_path):
    """Fewer than 60% scored means the dashboard keeps its previous board — a mostly
    failed run must not replace fifteen curated rows with five."""
    calls = {"n": 0}
    def flaky(p, k):
        calls["n"] += 1
        if calls["n"] % 2:                 # every other voice fails -> ~50% < 60%
            raise RuntimeError("api down")
        return 10, "ok"
    rc, out = run_main(monkeypatch, tmp_path, flaky)
    assert rc == 1 and not out.exists()


def test_full_run_writes_sorted_board(monkeypatch, tmp_path):
    scores = iter(range(-70, 80, 10))      # 15 distinct scores, unsorted vs roster order
    rc, out = run_main(monkeypatch, tmp_path, lambda p, k: (next(scores), f"take for {p['name']}"))
    assert rc == 0 and out.exists()
    doc = json.loads(out.read_text())
    got = [v["score"] for v in doc["influencers"]]
    assert got == sorted(got, reverse=True)          # bullish first
    assert len(doc["influencers"]) == len(ui.ROSTER)
    assert doc["asof"]                               # dated, so staleness is visible
    row = doc["influencers"][0]
    assert set(row) == {"name", "org", "cat", "url", "score", "take"}
