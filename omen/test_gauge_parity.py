"""Parity contract for the server-side gauge, against the shared fixture.

The crash-pressure gauge is computed twice: compute_gauge() here in Python (feeding
alerts, snapshots.csv and the landing page's embedded server_gauge) and computeGauge()
in polymarket-ai-index.html (the monitor's headline). The two share four families'
math exactly and differ - today deliberately - in two places: the monitor's pred
family averages three components where the server reads the bubble market alone, and
the monitor carries a macro family the server gauge does not have.

This suite and test-gauge-parity.mjs evaluate their respective implementations
against ONE fixture (fixtures/gauge-parity.json) whose expected values pin current
behaviour. A change to either side's math fails its suite until the fixture is
updated on purpose - so the shared families can no longer drift apart silently, and
the intended divergences are written down as numbers rather than folklore.
"""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).parent

spec = importlib.util.spec_from_file_location("umd", HERE / "update-market-data.py")
umd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(umd)

FIX = json.loads((HERE / "fixtures" / "gauge-parity.json").read_text())

TOL = 1e-9


def approx(a, b):
    assert a is not None and b is not None
    assert abs(a - b) <= TOL, f"{a} != {b}"


def test_shared_families_match_the_contract():
    """opt/vol/credit/equity - the math both implementations share, byte for byte."""
    _, fam = umd.compute_gauge(FIX["mkt"], FIX["prices"])
    for k, want in ((k, v) for k, v in FIX["expected"]["shared_fam"].items()
                    if not k.startswith("_")):
        approx(fam[k], want)


def test_pred_family_is_bubble_only():
    """The server pred family reads one market. The monitor's reads three - that
    divergence is pinned here and in the fixture's js block, not implied."""
    _, fam = umd.compute_gauge(FIX["mkt"], FIX["prices"])
    approx(fam["pred"], FIX["expected"]["python"]["pred"])
    assert fam["pred"] != FIX["expected"]["js"]["pred"], (
        "server and monitor pred agree on a fixture built to tell them apart - "
        "if the implementations were converged on purpose, update the fixture")


def test_server_gauge_has_no_macro_family():
    """The monitor's sixth family. The day compute_gauge grows one, this fails and
    the fixture's expected blocks both need a deliberate rewrite."""
    _, fam = umd.compute_gauge(FIX["mkt"], FIX["prices"])
    assert set(fam) == {"pred", "opt", "vol", "credit", "equity"}


def test_blended_score_lead_conf():
    score, fam = umd.compute_gauge(FIX["mkt"], FIX["prices"])
    lead, conf = umd.gauge_groups(fam)
    exp = FIX["expected"]["python"]
    approx(score, exp["score"])
    approx(lead, exp["lead"])
    approx(conf, exp["conf"])


def test_regime_and_crash_level():
    score, _ = umd.compute_gauge(FIX["mkt"], FIX["prices"])
    exp = FIX["expected"]["python"]
    assert umd.compute_regime(score, FIX["prices"]) == exp["regime"]
    approx(umd.sleeve_level(FIX["prices"], "mkt"), exp["crash_level"])
