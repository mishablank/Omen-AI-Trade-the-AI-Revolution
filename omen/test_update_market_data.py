import importlib.util
import math
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "umd", Path(__file__).parent / "update-market-data.py")
umd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(umd)


def test_parse_fred_csv_skips_missing_and_parses_floats():
    csv = "DATE,BAMLH0A0HYM2\n2026-07-07,2.67\n2026-07-08,.\n2026-07-09,2.70\n"
    out = umd.parse_fred_csv(csv)
    assert out == [{"d": "2026-07-07", "c": 2.67}, {"d": "2026-07-09", "c": 2.70}]


def test_parse_fred_csv_keeps_tail():
    csv = "DATE,X\n" + "\n".join(f"2026-01-{i:02d},{i}" for i in range(1, 31))
    out = umd.parse_fred_csv(csv, keep=5)
    assert len(out) == 5 and out[-1]["c"] == 30.0


FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>210.50</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10</value></transactionShares>
        <transactionPricePerShare><value>200</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>9999</value></transactionShares>
        <transactionPricePerShare><value>1</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4_counts_only_open_market_s_and_p():
    sells, buys = umd.parse_form4_xml(FORM4)
    assert sells == 100 * 210.50
    assert buys == 10 * 200


def test_parse_form4_bad_xml_is_zero():
    assert umd.parse_form4_xml("<not xml") == (0.0, 0.0)


def _synthetic_puts(spot, iv, dte, lo, hi, step):
    """A Black-Scholes put curve on a flat smile, so the digital has a known answer."""
    return {float(k): umd.bs_price(spot, float(k), iv, dte / 365.0, "P")
            for k in range(lo, hi + 1, step)}


def test_implied_vol_round_trips():
    px = umd.bs_price(200.0, 150.0, 0.45, 0.9, "P")
    assert abs(umd.implied_vol(px, 200.0, 150.0, 0.9, "P") - 0.45) < 1e-3
    pxc = umd.bs_price(200.0, 250.0, 0.38, 0.5, "C")
    assert abs(umd.implied_vol(pxc, 200.0, 250.0, 0.5, "C") - 0.38) < 1e-3


def test_implied_vol_rejects_junk_quotes():
    assert umd.implied_vol(None, 200.0, 100.0, 0.9, "P") is None
    assert umd.implied_vol(0, 200.0, 100.0, 0.9, "P") is None
    assert umd.implied_vol(1.0, 200.0, 100.0, 0, "P") is None
    # below intrinsic: a $100 put on a $50 spot cannot trade at $1
    assert umd.implied_vol(1.0, 50.0, 100.0, 0.9, "P") is None


def test_digital_put_matches_n_minus_d2_on_a_flat_smile():
    # With no skew the correction term vanishes, so BL must agree with N(-d2). That is
    # the check that the new estimator is unbiased; the divergence on real chains is the
    # smile, not an artefact.
    spot, iv, dte = 200.0, 0.50, 319
    puts = _synthetic_puts(spot, iv, dte, 60, 340, 5)
    t = dte / 365.0
    d2 = (math.log(spot / 100.0) + (umd.TAIL_RATE - iv * iv / 2) * t) / (iv * math.sqrt(t))
    assert abs(umd.digital_put(puts, 100.0, dte, spot) - umd.norm_cdf(-d2)) < 0.01


def test_digital_put_is_monotone_in_strike():
    puts = _synthetic_puts(200.0, 0.50, 319, 60, 340, 5)
    ps = [umd.digital_put(puts, k, 319, 200.0) for k in (100.0, 140.0, 180.0)]
    assert all(p is not None for p in ps)
    assert ps[0] < ps[1] < ps[2]          # a CDF must increase with strike


def test_digital_put_half_width_scales_with_spot():
    # The SOXX bug: a flat $5 floor on a ~$505 name reads pure quote noise. The floor
    # must be the larger of $5 and 4% of spot.
    puts = _synthetic_puts(505.0, 0.55, 319, 200, 700, 5)
    assert umd.digital_put(puts, 380.0, 319, 505.0) is not None
    wide = umd.digital_put(puts, 380.0, 319, 505.0)
    narrow = umd.digital_put(puts, 380.0, 319, spot=None, min_h=5.0)
    assert abs(wide - narrow) < 0.05      # on clean data both work; the floor is for noise
    assert umd.digital_put(puts, 380.0, 319, 505.0) > 0


def test_digital_put_needs_strikes_on_both_sides():
    puts = _synthetic_puts(200.0, 0.5, 319, 100, 140, 5)
    assert umd.digital_put(puts, 100.0, 319, 200.0) is None   # nothing below 100 - 8
    assert umd.digital_put(puts, 140.0, 319, 200.0) is None   # nothing above 140 + 8


def test_digital_put_clamps_to_a_probability():
    # Non-convex junk quotes can imply a negative or >1 density; never emit one.
    assert umd.digital_put({90.0: 5.0, 100.0: 4.0, 110.0: 3.0}, 100.0, 319, 200.0) == 0.0


def test_num_parses_nasdaq_placeholders():
    assert umd._num("--") is None and umd._num("") is None and umd._num(None) is None
    assert umd._num("1,234.50") == 1234.5
    assert umd._num("0.03") == 0.03


def test_quarterlize_differences_cumulative_flows():
    # calendar-FY filer: Q1 direct, 6mo/9mo/FY cumulative -> quarters by subtraction
    entries = [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 10.0},
        {"start": "2025-01-01", "end": "2025-06-30", "val": 25.0},
        {"start": "2025-01-01", "end": "2025-09-30", "val": 45.0},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 70.0},
    ]
    q = umd.quarterlize(entries)
    assert q["2025Q1"] == 10.0
    assert q["2025Q2"] == 15.0
    assert q["2025Q3"] == 20.0
    assert q["2025Q4"] == 25.0


def test_quarterlize_maps_offset_fiscal_years_to_calendar_quarters():
    # June-FY filer (MSFT-style): fiscal Q2 ends Dec 31 -> calendar Q4
    entries = [
        {"start": "2025-07-01", "end": "2025-09-30", "val": 30.0},
        {"start": "2025-07-01", "end": "2025-12-31", "val": 64.0},
    ]
    q = umd.quarterlize(entries)
    assert q["2025Q3"] == 30.0
    assert q["2025Q4"] == 34.0


def test_gauge_groups_split():
    fam = {"pred": 30.0, "opt": 40.0, "credit": 20.0, "vol": 50.0, "equity": 70.0}
    lead, conf = umd.gauge_groups(fam)
    assert lead == 30.0
    assert conf == 60.0
    lead2, conf2 = umd.gauge_groups({"pred": 10.0, "opt": None, "credit": None,
                                     "vol": None, "equity": None})
    assert lead2 == 10.0 and conf2 is None


def test_quarter_of_maps_fred_quarter_start_dates():
    assert umd.quarter_of("2025-01-01") == "2025Q1"
    assert umd.quarter_of("2025-04-01") == "2025Q2"
    assert umd.quarter_of("2025-07-01") == "2025Q3"
    assert umd.quarter_of("2025-10-15") == "2025Q4"


def test_macro_capex_gdp_shares_and_growth_contribution():
    # fundamentals capex is a single-quarter figure ($B); GDP is SAAR ($B).
    # capex must be annualized (x4) before comparing to SAAR GDP.
    fund = {"quarters": ["2025Q1", "2025Q2"], "capex_b": [50.0, 60.0]}
    gdp = [{"d": "2025-01-01", "c": 29000.0}, {"d": "2025-04-01", "c": 29400.0}]
    m = umd.macro_capex_gdp(fund, gdp)
    assert m["quarters"] == ["2025Q1", "2025Q2"]
    assert m["capex_ann_b"] == [200.0, 240.0]
    # 200/29000 = 0.690%, 240/29400 = 0.816%
    assert round(m["pct_gdp"][0], 3) == 0.690
    assert round(m["pct_gdp"][1], 3) == 0.816
    # growth contribution: d(annualized capex)=40 over d(GDP)=400 -> 10%
    assert m["growth_share"][0] is None          # no prior quarter
    assert round(m["growth_share"][1], 1) == 10.0


def test_macro_capex_gdp_handles_missing_gdp_quarter():
    fund = {"quarters": ["2025Q1", "2025Q2"], "capex_b": [50.0, 60.0]}
    gdp = [{"d": "2025-01-01", "c": 29000.0}]     # Q2 GDP not published yet
    m = umd.macro_capex_gdp(fund, gdp)
    assert m["quarters"] == ["2025Q1"]            # unmatched quarter dropped
    assert m["capex_ann_b"] == [200.0]


def test_macro_capex_gdp_empty_inputs_return_none():
    assert umd.macro_capex_gdp(None, [{"d": "2025-01-01", "c": 1.0}]) is None
    assert umd.macro_capex_gdp({"quarters": [], "capex_b": []}, []) is None


def test_kalshi_mid_reads_dollar_denominated_fields():
    # regression: Kalshi renamed quote fields to *_dollars and they are already
    # dollars (0.23), not cents. The old yes_bid/yes_ask read returned None and
    # silently emptied the whole cross-venue panel.
    m = {"yes_bid_dollars": "0.2300", "yes_ask_dollars": "0.2600"}
    price, spread = umd.kalshi_mid(m)
    assert round(price, 4) == 0.245
    assert round(spread, 4) == 0.03


def test_kalshi_mid_rejects_one_sided_book():
    # bid 0 / ask 1 is an empty book quoted at the bounds, not a 50c market
    assert umd.kalshi_mid({"yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.9900"}) == (None, None)
    assert umd.kalshi_mid({"yes_bid_dollars": "0.2200", "yes_ask_dollars": "1.0000"}) == (None, None)
    assert umd.kalshi_mid({}) == (None, None)


def test_kalshi_last_price_falls_back_for_display():
    # cross-venue table may show a last print when the book is one-sided
    assert umd.kalshi_price({"yes_bid_dollars": "0.2300", "yes_ask_dollars": "0.2600"}) == 0.245
    assert umd.kalshi_price({"yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.9900",
                             "last_price_dollars": "0.2100"}) == 0.21
    assert umd.kalshi_price({"last_price_dollars": "0.0000"}) is None


def test_kalshi_ladder_filters_wide_spreads_and_enforces_monotonic_survival():
    markets = [
        {"floor_strike": 2.0, "yes_bid_dollars": "0.94", "yes_ask_dollars": "0.98"},
        # non-monotonic print: survival cannot rise with strike -> clamped down
        {"floor_strike": 2.5, "yes_bid_dollars": "0.97", "yes_ask_dollars": "0.99"},
        # too wide to trust
        {"floor_strike": 2.7, "yes_bid_dollars": "0.10", "yes_ask_dollars": "0.90"},
        # one-sided -> dropped
        {"floor_strike": 2.8, "yes_bid_dollars": "0.00", "yes_ask_dollars": "0.99"},
        {"floor_strike": 3.0, "yes_bid_dollars": "0.03", "yes_ask_dollars": "0.07"},
    ]
    rows = umd.kalshi_ladder(markets)
    assert [r["k"] for r in rows] == [2.0, 2.5, 3.0]
    assert rows[0]["p"] == 0.96
    assert rows[1]["p"] == 0.96          # clamped from 0.98 to preserve monotonicity
    assert rows[2]["p"] == 0.05


def test_implied_median_interpolates_the_fifty_percent_crossing():
    rows = [{"k": 2.0, "p": 0.8}, {"k": 3.0, "p": 0.4}]
    # survival falls 0.8 -> 0.4 across $1.00; 50% sits 3/4 of the way: $2.75
    assert round(umd.implied_median(rows), 4) == 2.75
    # exact hit at a strike returns that strike
    assert umd.implied_median([{"k": 2.0, "p": 0.5}, {"k": 3.0, "p": 0.2}]) == 2.0


def test_implied_median_none_when_crossing_outside_ladder():
    # entire ladder above 50% -> median is beyond the highest strike, unknowable
    assert umd.implied_median([{"k": 2.0, "p": 0.9}, {"k": 3.0, "p": 0.7}]) is None
    assert umd.implied_median([{"k": 2.0, "p": 0.2}]) is None
    assert umd.implied_median([]) is None


def test_gauge_families_and_regime():
    data = {
        "skew": {"NVDA": {"rr": 0.055}, "SOXX": {"rr": 0.095}},
        "vol": {"VIX": {"last": 20.0}, "VIX3M": {"last": 20.0},
                "VXN": {"last": 29.0}, "SKEW": {"last": 137.5}, "VVIX": {"last": 110.0}},
        # dated exactly as yahoo_series() emits them - the HY/IG ratio is joined on "d"
        "credit": {"HYG": [{"d": "2026-08-05", "c": 100}, {"d": "2026-08-06", "c": 96}],
                   "LQD": [{"d": "2026-08-05", "c": 100}, {"d": "2026-08-06", "c": 100}]},
        "fred": {"HY_OAS": {"last": 3.75}, "CCC_OAS": {"last": 11.25}},
        "equity": {"NVDA": [{"c": 100}, {"c": 75}], "SOXX": [{"c": 100}, {"c": 80}]},
    }
    price = {umd.BUBBLE_ID: 0.20}
    score, fam = umd.compute_gauge(data, price)
    assert fam["pred"] == 50.0                     # 20% of 0-40 range
    assert round(fam["equity"]) == 50              # -25%/50 and -20%/40 both 50
    assert 0 < score < 100
    assert umd.compute_regime(score, price) in ("calm", "elevated", "stressed")
    # A lone market can raise Elevated but never trips Stressed on its own. Hold the rest
    # of the crash sleeve cold so these exercise the single-market path, not the sleeve
    # average (which stays well under 25 here).
    cold = {i: 0.02 for i in umd.BEAR_SLEEVES["mkt"][1:]}
    # bubble >= 15% forces at least elevated...
    assert umd.compute_regime(10, dict(cold, **{umd.BUBBLE_ID: 0.16})) == "elevated"
    # ...but even a very hot single market is capped at elevated, not stressed
    assert umd.compute_regime(10, dict(cold, **{umd.BUBBLE_ID: 0.30})) == "elevated"
    assert umd.compute_regime(10, dict(cold, **{umd.BUBBLE_ID: 0.50})) == "elevated"
    # a cold single market with a calm gauge and cold sleeve stays calm
    assert umd.compute_regime(10, dict(cold, **{umd.BUBBLE_ID: 0.10})) == "calm"


def _credit_only(hyg, lqd):
    """compute_gauge with credit as the only live family, so fam['credit'] is readable."""
    _, fam = umd.compute_gauge({"credit": {"HYG": hyg, "LQD": lqd}}, {})
    return fam["credit"]


def test_hy_ig_ratio_joins_on_date_not_array_position():
    """The HY/IG ratio pairs HYG with LQD by trading date.

    It used to zip() the two series, pairing them by array position. The carry-forward
    policy makes a length mismatch a real state - either leg can be a session behind when
    its fetch fails - and a one-row offset silently divides one day's HYG by another day's
    LQD. Here LQD is missing the first session: by position the ratio reads perfectly flat
    and the credit family sees no stress at all, while the dated join sees the 20% ratio
    drawdown that is actually on the tape.
    """
    hyg = [{"d": "2026-08-04", "c": 100}, {"d": "2026-08-05", "c": 100},
           {"d": "2026-08-06", "c": 80}]
    lqd = [{"d": "2026-08-05", "c": 100}, {"d": "2026-08-06", "c": 100}]
    # HYG drawdown alone is -20% (past its 0->-8% range, so 100); the ratio drawdown is
    # -20% too (past 0->-6%, so 100). Position-pairing would have scored the ratio leg 0
    # and halved the family to 50.
    assert _credit_only(hyg, lqd) == 100.0


def test_hy_ig_ratio_ignores_dates_the_other_leg_does_not_have():
    """Unmatched dates are dropped, never guessed at or interpolated."""
    hyg = [{"d": "2026-08-04", "c": 100}, {"d": "2026-08-05", "c": 50}]
    lqd = [{"d": "2026-08-04", "c": 100}, {"d": "2026-08-05", "c": 0}]   # 0 is unusable
    # 08-05 drops (a zero LQD print would divide by zero), leaving a single flat ratio day
    # and so no ratio drawdown: that leg scores 0 against the HYG leg's -50% (100), for 50.
    assert _credit_only(hyg, lqd) == 50.0
    # No overlap at all, so the ratio is not computable rather than wrong. A dark component
    # leaves the mean instead of scoring 0 - the family is then the HYG leg alone, the same
    # degradation rule every other family follows.
    assert _credit_only(hyg, [{"d": "2025-01-02", "c": 100}]) == 100.0


def test_bear_basket_is_the_union_of_its_sleeves():
    assert umd.POLY_IDS["bear"] == umd.BEAR_SLEEVES["mkt"] + umd.BEAR_SLEEVES["gov"]
    assert len(umd.POLY_IDS["bear"]) == 9
    assert len(set(umd.POLY_IDS["bear"])) == 9
    assert umd.BUBBLE_ID in umd.BEAR_SLEEVES["mkt"]
    # the two short-side sleeves are disjoint, so the union is a clean 3 + 6
    assert not set(umd.BEAR_SLEEVES["mkt"]) & set(umd.BEAR_SLEEVES["gov"])
    assert (len(umd.BEAR_SLEEVES["mkt"]), len(umd.BEAR_SLEEVES["gov"])) == (3, 6)


def test_bear_level_is_the_flat_mean_of_all_nine_not_the_mean_of_sleeve_means():
    # sleeves are unequal (3 vs 6), so a mean-of-means would differ from the flat mean –
    # this pins the composite to the equal-weight union the methodology promises
    price = {i: 0.10 for i in umd.BEAR_SLEEVES["mkt"]}
    price.update({i: 0.40 for i in umd.BEAR_SLEEVES["gov"]})
    assert umd.index_level(price, "bear") == pytest.approx(30.0)   # (3*10 + 6*40)/9
    assert umd.sleeve_level(price, "mkt") == pytest.approx(10.0)
    assert umd.sleeve_level(price, "gov") == pytest.approx(40.0)


def test_index_level_skips_markets_missing_from_the_price_map():
    price = {umd.BEAR_SLEEVES["mkt"][0]: 0.20, umd.BEAR_SLEEVES["gov"][0]: 0.60}
    assert umd.index_level(price, "bear") == pytest.approx(40.0)   # mean of the 2 present
    assert umd.index_level({}, "bear") is None


def test_regime_reads_the_mkt_sleeve_not_the_bear_composite():
    # the gauge is about priced *crash* risk: its thresholds must keep firing off the
    # old crash basket (= the MKT sleeve). A hot GOV sleeve lifts Bear but must not
    # move the regime, or the merge would silently retune the gauge.
    price = {i: 0.02 for i in umd.BEAR_SLEEVES["mkt"]}
    price.update({i: 0.95 for i in umd.BEAR_SLEEVES["gov"]})
    assert umd.index_level(price, "bear") > 60      # composite is way past the 40 trip
    assert umd.compute_regime(10, price) == "calm"  # ...but crash risk is not priced
    # and the MKT sleeve still trips the bands on its own. Hold the bubble market cold
    # so these exercise the sleeve-level rule, not the separate bubble-market rule.
    cold_bubble = {umd.BUBBLE_ID: 0.10}
    stressed = dict(cold_bubble, **{i: 0.60 for i in umd.BEAR_SLEEVES["mkt"][1:]})
    assert umd.sleeve_level(stressed, "mkt") == pytest.approx(43.33, abs=0.01)
    assert umd.compute_regime(10, stressed) == "stressed"      # level >= 40
    elevated = dict(cold_bubble, **{i: 0.35 for i in umd.BEAR_SLEEVES["mkt"][1:]})
    assert umd.sleeve_level(elevated, "mkt") == pytest.approx(26.67, abs=0.01)
    assert umd.compute_regime(10, elevated) == "elevated"      # 25 <= level < 40


def test_snapshot_row_keeps_crash_and_reg_as_sleeve_provenance():
    price = {i: 0.10 for i in umd.BEAR_SLEEVES["mkt"]}
    price.update({i: 0.40 for i in umd.BEAR_SLEEVES["gov"]})
    price.update({i: 0.50 for i in umd.POLY_IDS["bull"]})
    row = umd.snapshot_row(price)
    assert row["bear"] == pytest.approx(30.0)
    assert row["bear_n"] == 9
    # crash/reg columns live on as the sleeve reads, so the stored series stays comparable
    assert row["crash"] == pytest.approx(10.0)
    assert row["crash_n"] == 3
    assert row["reg"] == pytest.approx(40.0)
    assert row["reg_n"] == 6
    # the fallback backfill formula in the spec must reproduce the flat union
    assert (row["crash_n"] * row["crash"] + row["reg_n"] * row["reg"]) / (
        row["crash_n"] + row["reg_n"]) == pytest.approx(row["bear"])


def test_snapshot_header_is_bear_plus_legacy_columns():
    assert umd.SNAP_HEADER == ["date", "bull", "bull_n", "bear", "bear_n",
                               "crash", "crash_n", "reg", "reg_n",
                               "gauge", "lead", "conf", "comp"]


# ---- RPO (remaining performance obligation) — instant XBRL facts ----

RPO_ENTRIES = [
    {"end": "2025-03-31", "val": 315.0e9, "form": "10-Q", "filed": "2025-04-25"},
    {"end": "2025-06-30", "val": 368.0e9, "form": "10-Q", "filed": "2025-07-29"},
    {"end": "2026-03-31", "val": 633.0e9, "form": "10-Q", "filed": "2026-04-24"},
    # restatement of the same instant, filed later -> must win
    {"end": "2026-03-31", "val": 999.0e9, "form": "10-K", "filed": "2026-06-01"},
]


def test_instantize_maps_instants_to_calendar_quarters():
    out = umd.instantize(RPO_ENTRIES)
    assert out["2025Q1"] == 315.0e9
    assert out["2025Q2"] == 368.0e9
    assert out["2026Q1"] == 999.0e9          # latest-filed restatement wins


def test_instantize_ignores_duration_facts_and_junk():
    # a flow fact (has start) is not an instant balance — must be skipped, since
    # summing/differencing it as a balance would be silently wrong
    entries = [
        {"start": "2026-01-01", "end": "2026-03-31", "val": 1.0, "filed": "2026-04-01"},
        {"end": "2026-03-31", "filed": "2026-04-01"},           # no val
        {"val": 5.0, "filed": "2026-04-01"},                     # no end
        {"end": "not-a-date", "val": 5.0, "filed": "2026-04-01"},
    ]
    assert umd.instantize(entries) == {}


def test_instantize_handles_missing_filed_date():
    entries = [{"end": "2026-03-31", "val": 100.0}, {"end": "2026-03-31", "val": 200.0}]
    assert umd.instantize(entries)["2026Q1"] == 200.0   # last wins when filed absent


def test_backlog_shapes_per_firm_series_with_yoy(monkeypatch):
    fake = {
        "ORCL": {"2025Q2": 138.0e9, "2025Q3": 455.0e9, "2026Q1": 552.6e9, "2026Q2": 638.0e9},
        "MSFT": {"2025Q2": 368.0e9, "2026Q1": 633.0e9},
    }
    monkeypatch.setattr(umd, "RPO_CIKS", {"ORCL": "1", "MSFT": "2"})
    monkeypatch.setattr(umd, "sec_instant", lambda cik, tags:
                        fake["ORCL"] if cik == "1" else fake["MSFT"])
    out = umd.backlog()
    assert out["names"] == ["ORCL", "MSFT"]
    o = out["per"]["ORCL"]
    assert o["latest_q"] == "2026Q2" and o["latest_b"] == 638.0
    # YoY against the same quarter one year back: 638.0 / 138.0 - 1 = +362%
    assert round(o["yoy_pct"]) == 362
    assert o["series"][-1] == ["2026Q2", 638.0]
    assert out["per"]["MSFT"]["yoy_pct"] is None      # no 2025Q1 comparator
    # headline is the sum of each firm's most recent report, not a fake aligned total
    assert out["total_latest_b"] == round(638.0 + 633.0, 2)


def test_backlog_returns_none_when_no_filer_reports(monkeypatch):
    monkeypatch.setattr(umd, "RPO_CIKS", {"ORCL": "1"})
    monkeypatch.setattr(umd, "sec_instant", lambda cik, tags: {})
    assert umd.backlog() is None


# ---------- CFTC Commitments of Traders (positioning) ----------
def test_inty_coerces_strings_and_guards_junk():
    assert umd._inty("300") == 300
    assert umd._inty("300.0") == 300      # Socrata sometimes returns decimals
    assert umd._inty(5) == 5
    assert umd._inty(None) is None
    assert umd._inty("") is None
    assert umd._inty("n/a") is None


def test_pctile_rank_counts_values_at_or_below():
    assert umd.pctile_rank([10, 20, 30], 20) == 66.7
    assert umd.pctile_rank([10, 20, 30], 30) == 100.0
    assert umd.pctile_rank([10, 20, 30], 5) == 0.0
    assert umd.pctile_rank([], 5) is None


def test_zscore_basic_and_degenerate():
    assert umd.zscore([2, 4, 6], 4) == 0.0        # x at the mean
    assert umd.zscore([2, 4, 6], 6) == 1.22       # (6-4)/1.633
    assert umd.zscore([5, 5, 5], 5) == 0.0        # zero variance -> 0, not a divide error
    assert umd.zscore([5], 5) is None             # need >=2 points


# Socrata returns newest-first strings; reduce must be order-independent and coerce.
COT_ROWS = [
    {"report_date_as_yyyy_mm_dd": "2026-07-14T00:00:00.000",
     "open_interest_all": "1000", "noncomm_positions_long_all": "300",
     "noncomm_positions_short_all": "100"},                        # net +200, +20%
    {"report_date_as_yyyy_mm_dd": "2026-07-07T00:00:00.000",
     "open_interest_all": "1000", "noncomm_positions_long_all": "100",
     "noncomm_positions_short_all": "300"},                        # net -200, -20%
    {"report_date_as_yyyy_mm_dd": "2026-06-30T00:00:00.000",
     "open_interest_all": "1000", "noncomm_positions_long_all": "200",
     "noncomm_positions_short_all": "200"},                        # net 0, 0%
    {"report_date_as_yyyy_mm_dd": "2026-06-23T00:00:00.000",
     "open_interest_all": "0", "noncomm_positions_long_all": "5",
     "noncomm_positions_short_all": "5"},                          # OI 0 -> dropped
    {"report_date_as_yyyy_mm_dd": "2026-06-16T00:00:00.000",
     "open_interest_all": "1000", "noncomm_positions_long_all": None,
     "noncomm_positions_short_all": "5"},                          # missing leg -> dropped
]


def test_cot_reduce_computes_net_percentile_and_latest():
    out = umd.cot_reduce("E-mini Nasdaq-100", "CME", COT_ROWS)
    assert out["label"] == "E-mini Nasdaq-100" and out["venue"] == "CME"
    assert out["date"] == "2026-07-14"       # latest by date, not by input order
    assert out["net"] == 200
    assert out["net_pct_oi"] == 20.0
    assert out["n_weeks"] == 3               # the two malformed rows are dropped
    # window net%OI = [0, -20, 20]; latest 20 is the max -> 100th pctile
    assert out["pctile"] == 100.0
    assert out["z"] == 1.22                  # (20 - 0) / 16.33
    # sparkline history is oldest -> newest, compact {d, v}
    assert out["history"][0] == {"d": "2026-06-30", "v": 0.0}
    assert out["history"][-1] == {"d": "2026-07-14", "v": 20.0}


def test_cot_reduce_returns_none_when_all_rows_unusable():
    bad = [{"report_date_as_yyyy_mm_dd": "2026-07-14", "open_interest_all": "0",
            "noncomm_positions_long_all": "1", "noncomm_positions_short_all": "1"}]
    assert umd.cot_reduce("x", "y", bad) is None
    assert umd.cot_reduce("x", "y", []) is None


# ---------- FINRA short interest (single-name short crowding, via api.nasdaq.com) ----------
def test_si_num_strips_commas_and_dollar():
    assert umd.si_num("80,963,200") == 80963200.0
    assert umd.si_num("$12.30") == 12.30
    assert umd.si_num(2.5) == 2.5
    assert umd.si_num(None) is None
    assert umd.si_num("") is None
    assert umd.si_num("n/a") is None


# api.nasdaq.com returns settlements newest-first; interest is a comma string.
SI_ROWS = [
    {"settlementDate": "06/30/2026", "interest": "80,963,200",
     "avgDailyShareVolume": "31,763,241", "daysToCover": 2.548959},
    {"settlementDate": "06/15/2026", "interest": "69,012,019",
     "avgDailyShareVolume": "29,288,664", "daysToCover": 2.356271},
    {"settlementDate": "05/29/2026", "interest": "54,604,588",
     "avgDailyShareVolume": "26,064,506", "daysToCover": 2.094979},
    {"settlementDate": "", "interest": "1,000", "daysToCover": 1.0},        # no date -> dropped
    {"settlementDate": "05/15/2026", "interest": None, "daysToCover": 1.0},  # no SI  -> dropped
]


def test_short_interest_reduce_latest_change_and_trend():
    out = umd.short_interest_reduce("CRWV", SI_ROWS)
    assert out["sym"] == "CRWV"
    assert out["date"] == "06/30/2026"          # newest settlement, input order preserved
    assert out["si"] == 80963200.0
    assert out["dtc"] == 2.548959
    # change vs the prior settlement: 80,963,200 / 69,012,019 - 1 = +17.3%
    assert out["chg_pct"] == 17.3
    # the two malformed rows are dropped; history is oldest -> newest, compact
    assert [h["d"] for h in out["history"]] == ["05/29/2026", "06/15/2026", "06/30/2026"]
    assert out["history"][-1] == {"d": "06/30/2026", "si": 80963200.0, "dtc": 2.548959}


def test_short_interest_reduce_single_row_has_no_change():
    out = umd.short_interest_reduce("NBIS", [SI_ROWS[0]])
    assert out["chg_pct"] is None               # nothing to compare against
    assert out["si"] == 80963200.0


def test_short_interest_reduce_returns_none_when_empty():
    assert umd.short_interest_reduce("X", []) is None
    assert umd.short_interest_reduce("X", [{"settlementDate": "", "interest": None}]) is None


# ---------- transient-failure policy ----------
def _http_error(code, retry_after=None):
    import email.message
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("http://x", code, "boom", hdrs, None)


@pytest.fixture(autouse=True)
def _fresh_retry_budget():
    """The budget is process-wide state; no test may inherit another's spend."""
    umd.reset_retry_budget()
    yield
    umd.reset_retry_budget()


@pytest.mark.parametrize("code", sorted(umd.RETRY_STATUS))
def test_retryable_true_for_transient_status(code):
    assert umd.retryable(_http_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 422])
def test_retryable_false_for_client_errors(code):
    """A 4xx is a real answer — asking again just burns the rate limit."""
    assert umd.retryable(_http_error(code)) is False


def test_retryable_true_for_network_errors():
    # HTTPError subclasses URLError, so ordering inside retryable() matters
    assert umd.retryable(urllib.error.URLError("dns")) is True
    assert umd.retryable(TimeoutError()) is True
    assert umd.retryable(ConnectionResetError()) is True
    assert umd.retryable(ValueError("bad json")) is False


def test_retry_wait_is_exponential():
    plain = urllib.error.URLError("dns")
    assert umd.retry_wait(plain, 0) == umd.RETRY_BACKOFF
    assert umd.retry_wait(plain, 1) == umd.RETRY_BACKOFF * 2
    assert umd.retry_wait(plain, 2) == umd.RETRY_BACKOFF * 4


def test_retry_wait_honours_retry_after_but_caps_it():
    assert umd.retry_wait(_http_error(429, retry_after=10), 0) == 10.0
    # a server asking for an hour must not stall the whole refresh
    assert umd.retry_wait(_http_error(429, retry_after=3600), 0) == umd.RETRY_AFTER_CAP
    # a Retry-After shorter than the backoff never shortens it
    assert umd.retry_wait(_http_error(429, retry_after=0.1), 1) == umd.RETRY_BACKOFF * 2
    # junk header falls back to plain backoff
    assert umd.retry_wait(_http_error(429, retry_after="soon"), 0) == umd.RETRY_BACKOFF


def test_get_bytes_retries_transient_then_succeeds(monkeypatch):
    calls = []

    class FakeResp:
        headers = {}

        def read(self):
            return b"payload"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise _http_error(503)
        return FakeResp()

    monkeypatch.setattr(umd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(umd.time, "sleep", lambda s: None)
    assert umd.get("http://x/y") == "payload"
    assert len(calls) == 3


def test_get_bytes_does_not_retry_a_4xx(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise _http_error(404)

    monkeypatch.setattr(umd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(umd.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        umd.get("http://x/y")
    assert len(calls) == 1


def test_get_bytes_gives_up_after_the_retry_budget(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise _http_error(503)

    monkeypatch.setattr(umd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(umd.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        umd.get("http://x/y")
    assert len(calls) == umd.RETRIES + 1


def test_get_bytes_decompresses_gzip(monkeypatch):
    import gzip as _gzip

    class FakeResp:
        headers = {"Content-Encoding": "gzip"}

        def read(self):
            return _gzip.compress(b'{"ok":1}')

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(umd.urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    assert umd.get("http://x/y") == '{"ok":1}'


# ---------- uniform carry-forward ----------
def test_carry_restores_previous_panel():
    data, prev = {}, {"gpu": {"median_dph": 2.1}}
    assert umd.carry(data, prev, "gpu", RuntimeError("timeout")) is True
    assert data["gpu"] == {"median_dph": 2.1}


def test_carry_reports_false_when_there_is_nothing_to_carry():
    data = {}
    assert umd.carry(data, {}, "gpu", RuntimeError("timeout")) is False
    assert "gpu" not in data


def test_carry_sub_restores_one_symbol_only():
    data = {"equity": {"NVDA": [{"d": "2026-07-25", "c": 1.0}]}}
    prev = {"equity": {"NVDA": ["stale"], "SOXX": [{"d": "2026-07-24", "c": 2.0}]}}
    assert umd.carry_sub(data, prev, "equity", "SOXX", RuntimeError("boom")) is True
    assert data["equity"]["SOXX"] == [{"d": "2026-07-24", "c": 2.0}]
    assert data["equity"]["NVDA"] == [{"d": "2026-07-25", "c": 1.0}]   # live value untouched


def test_carry_sub_handles_a_missing_section():
    data = {"tail": {}}
    assert umd.carry_sub(data, {}, "tail", "NVDA", RuntimeError("boom")) is False
    assert data["tail"] == {}


def test_carried_equity_keeps_the_gauge_family_alive():
    """The reason the policy exists: a dropped equity key silently rescales the gauge."""
    series = [{"d": "2026-07-01", "c": 100.0}, {"d": "2026-07-25", "c": 60.0}]
    prev = {"equity": {"NVDA": series, "SOXX": series}}
    healthy, _ = umd.compute_gauge({"equity": prev["equity"]}, {})
    dropped, fam_dropped = umd.compute_gauge({"equity": {}}, {})
    assert fam_dropped["equity"] is None and dropped != healthy

    data = {"equity": {}}
    for sym in ("NVDA", "SOXX"):
        umd.carry_sub(data, prev, "equity", sym, RuntimeError("yahoo blip"))
    carried, fam_carried = umd.compute_gauge(data, {})
    assert fam_carried["equity"] is not None
    assert carried == healthy


def test_retry_budget_caps_total_backoff(monkeypatch):
    """A broad outage must not turn ~40 endpoints into minutes of pure sleep."""
    slept = []
    monkeypatch.setattr(umd.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(umd.urllib.request, "urlopen",
                        lambda req, timeout=None: (_ for _ in ()).throw(_http_error(503)))
    umd.reset_retry_budget()
    for _ in range(50):                       # every endpoint down
        with pytest.raises(urllib.error.HTTPError):
            umd.get("http://x/y")
    assert sum(slept) <= umd.RETRY_BUDGET
    assert umd.retry_budget_left() == 0


def test_retry_budget_lets_the_first_failures_retry(monkeypatch):
    """The common case — one flaky endpoint — still gets its retries."""
    slept, calls = [], []
    monkeypatch.setattr(umd.time, "sleep", lambda s: slept.append(s))

    class FakeResp:
        headers = {}
        def read(self): return b"ok"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise _http_error(503)
        return FakeResp()

    monkeypatch.setattr(umd.urllib.request, "urlopen", flaky)
    umd.reset_retry_budget()
    assert umd.get("http://x/y") == "ok"
    assert len(calls) == 3 and slept == [umd.RETRY_BACKOFF, umd.RETRY_BACKOFF * 2]


def test_reset_retry_budget_restores_it():
    umd.reset_retry_budget()
    assert umd.retry_budget_left() == umd.RETRY_BUDGET


# ---------- per-filer TTM (ai-capex theses iv + vii) ----------

def _per(capex, ocf):
    return {"capex": capex, "ocf": ocf, "dep": {}}


def test_filer_ttm_sums_each_filers_own_last_four_quarters():
    per = {
        "MSFT": _per({"2025Q3": 25e9, "2025Q4": 28e9, "2026Q1": 30e9, "2026Q2": 32.9e9},
                     {"2025Q3": 44e9, "2025Q4": 45e9, "2026Q1": 46e9, "2026Q2": 47.9e9}),
        "ORCL": _per({"2025Q3": 12e9, "2025Q4": 13e9, "2026Q1": 14e9, "2026Q2": 16.7e9},
                     {"2025Q3": 8e9, "2025Q4": 8e9, "2026Q1": 8e9, "2026Q2": 8e9}),
    }
    out = umd.filer_ttm(per)
    assert out["per"]["MSFT"]["capex_ttm_b"] == 115.9
    assert out["per"]["MSFT"]["ocf_ttm_b"] == 182.9
    assert out["per"]["MSFT"]["fcf_ttm_b"] == 67.0
    assert out["per"]["MSFT"]["capex_over_ocf"] == 0.63
    assert out["per"]["ORCL"]["fcf_ttm_b"] == -23.7
    assert out["per"]["ORCL"]["capex_over_ocf"] == 1.74


def test_filer_ttm_windows_are_per_filer_not_shared():
    """ORCL's quarters end Feb/May/Aug/Nov and META reports a quarter behind the rest.
    A shared window would compare different 12-month periods and call it a comparison."""
    per = {
        "MSFT": _per({"2025Q3": 1e9, "2025Q4": 1e9, "2026Q1": 1e9, "2026Q2": 1e9},
                     {"2025Q3": 2e9, "2025Q4": 2e9, "2026Q1": 2e9, "2026Q2": 2e9}),
        "META": _per({"2025Q2": 1e9, "2025Q3": 1e9, "2025Q4": 1e9, "2026Q1": 1e9},
                     {"2025Q2": 2e9, "2025Q3": 2e9, "2025Q4": 2e9, "2026Q1": 2e9}),
    }
    out = umd.filer_ttm(per)
    assert out["per"]["MSFT"]["quarters"] == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert out["per"]["META"]["quarters"] == ["2025Q2", "2025Q3", "2025Q4", "2026Q1"]


def test_filer_ttm_skips_filers_without_four_aligned_quarters():
    per = {"MSFT": _per({"2026Q1": 1e9, "2026Q2": 1e9}, {"2026Q1": 2e9, "2026Q2": 2e9})}
    assert umd.filer_ttm(per) is None


def test_filer_ttm_needs_capex_and_ocf_in_the_same_quarter():
    """A quarter with capex but no OCF cannot produce an FCF figure — dropping it
    silently would understate the window rather than shorten it."""
    per = {"MSFT": _per({"2025Q3": 1e9, "2025Q4": 1e9, "2026Q1": 1e9, "2026Q2": 1e9},
                        {"2025Q3": 2e9, "2025Q4": 2e9, "2026Q1": 2e9})}
    assert umd.filer_ttm(per) is None


def test_filer_ttm_totals_count_negative_fcf_filers():
    per = {
        "MSFT": _per({q: 1e9 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")},
                     {q: 2e9 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")}),
        "ORCL": _per({q: 3e9 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")},
                     {q: 1e9 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")}),
    }
    t = umd.filer_ttm(per)["totals"]
    assert t["capex_ttm_b"] == 16.0
    assert t["ocf_ttm_b"] == 12.0
    assert t["fcf_ttm_b"] == -4.0
    assert t["n_fcf_negative"] == 1
    assert t["n_filers"] == 2


def test_filer_ttm_zero_ocf_does_not_divide_by_zero():
    per = {"X": _per({q: 1e9 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")},
                     {q: 0.0 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")})}
    out = umd.filer_ttm(per)
    assert out["per"]["X"]["capex_over_ocf"] is None
    assert out["per"]["X"]["fcf_ttm_b"] == -4.0


# ---------- XBRL issuance (ai-capex theses i + iii) ----------

def _chan(quarters=None, fact=None):
    return {"quarters": quarters or {}, "fact": fact}


def test_quarter_window_counts_back_calendar_quarters():
    assert umd.quarter_window("2026Q2", 4) == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert umd.quarter_window("2026Q1", 2) == ["2025Q4", "2026Q1"]


def test_issuance_ttm_sums_only_inside_the_calendar_window():
    per = {"ORCL": {"debt": _chan({"2025Q3": 10e9, "2025Q4": 12e9,
                                   "2026Q1": 12e9, "2026Q2": 12.1e9}),
                    "equity": _chan()}}
    out = umd.issuance_ttm(per, asof_q="2026Q2")
    assert out["per"]["ORCL"]["debt_ttm_b"] == 46.1
    assert out["per"]["ORCL"]["debt_window"] == "2025Q3–2026Q2"
    assert out["per"]["ORCL"]["debt_full_year"] is True


def test_issuance_ttm_ignores_quarters_outside_the_window():
    """META tags debt proceeds only in the years it issued. Summing 'the last four
    tagged quarters' produced a 2023Q4–2025Q4 window presented as a TTM — four real
    numbers spanning two years, added together and labelled twelve months."""
    per = {"META": {"debt": _chan({"2023Q4": 9e9, "2024Q2": 10e9,
                                   "2025Q4": 29.9e9, "2026Q1": 1e9}),
                    "equity": _chan()}}
    out = umd.issuance_ttm(per, asof_q="2026Q2")
    assert out["per"]["META"]["debt_ttm_b"] == 30.9      # 2025Q4 + 2026Q1 only
    assert out["per"]["META"]["debt_window"] == "2025Q3–2026Q2"


def test_issuance_ttm_nothing_in_window_is_none_not_zero():
    per = {"META": {"debt": _chan({"2012Q3": 1.5e9}), "equity": _chan()}}
    assert umd.issuance_ttm(per, asof_q="2026Q2") is None


def test_issuance_ttm_falls_back_to_a_recent_cumulative_fact():
    """Alphabet tags common-stock proceeds only as a fiscal-year-to-date cumulative —
    two facts, no clean quarters — so quarterising alone drops the single number
    thesis iii exists to show. The fallback keeps it, labelled with its real window."""
    per = {"GOOGL": {"debt": _chan(),
                     "equity": _chan(fact={"val": 30.499e9, "start": "2026-01-01",
                                           "end": "2026-06-30", "days": 180})}}
    out = umd.issuance_ttm(per, asof_q="2026Q2")
    assert out["per"]["GOOGL"]["equity_ttm_b"] == 30.5
    assert out["per"]["GOOGL"]["equity_full_year"] is False
    assert out["per"]["GOOGL"]["equity_window"] == "2026-01-01→2026-06-30"


def test_issuance_ttm_stale_fallback_fact_is_dropped():
    """A 2013 cumulative is not this year's raise, however cleanly it parses."""
    per = {"META": {"debt": _chan(),
                    "equity": _chan(fact={"val": 1.5e9, "start": "2013-01-01",
                                          "end": "2013-12-31", "days": 364})}}
    assert umd.issuance_ttm(per, asof_q="2026Q2") is None


def test_issuance_ttm_totals_only_sum_full_year_windows():
    """A six-month figure added to twelve-month figures is not a TTM total. Partial
    windows show per filer and are counted out of the headline."""
    per = {
        "META": {"debt": _chan({q: 5e9 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")}),
                 "equity": _chan()},
        "GOOGL": {"debt": _chan(),
                  "equity": _chan(fact={"val": 30.499e9, "start": "2026-01-01",
                                        "end": "2026-06-30", "days": 180})},
    }
    out = umd.issuance_ttm(per, asof_q="2026Q2")
    assert out["totals"]["debt_ttm_b"] == 20.0
    assert out["totals"]["equity_ttm_b"] is None
    assert out["totals"]["equity_partial"] == ["GOOGL"]


def test_issuance_ttm_a_full_year_cumulative_fact_counts_as_ttm():
    per = {"META": {"debt": _chan(fact={"val": 29.9e9, "start": "2025-01-01",
                                        "end": "2025-12-31", "days": 364}),
                    "equity": _chan()}}
    out = umd.issuance_ttm(per, asof_q="2026Q2")
    assert out["per"]["META"]["debt_full_year"] is True
    assert out["totals"]["debt_ttm_b"] == 29.9


def test_issuance_ttm_missing_channel_is_none_not_zero():
    """A filer that has never tagged equity proceeds is unknown, not '$0 raised' —
    and thesis iii turns on exactly that distinction."""
    per = {"AMZN": {"debt": _chan({q: 1e9 for q in ("2025Q3", "2025Q4", "2026Q1", "2026Q2")}),
                    "equity": _chan()}}
    out = umd.issuance_ttm(per, asof_q="2026Q2")
    assert out["per"]["AMZN"]["debt_ttm_b"] == 4.0
    assert out["per"]["AMZN"]["equity_ttm_b"] is None
    assert out["totals"]["equity_ttm_b"] is None


def test_issuance_ttm_infers_the_window_end_from_the_data():
    per = {"ORCL": {"debt": _chan({"2025Q3": 1e9, "2025Q4": 1e9,
                                   "2026Q1": 1e9, "2026Q2": 1e9}), "equity": _chan()}}
    assert umd.issuance_ttm(per)["per"]["ORCL"]["debt_window"] == "2025Q3–2026Q2"


def test_issuance_ttm_empty_is_none():
    assert umd.issuance_ttm({}) is None
    assert umd.issuance_ttm({"X": {"debt": _chan(), "equity": _chan()}}) is None


def test_latest_period_fact_picks_the_most_recent_longest_window():
    entries = [
        {"start": "2026-01-01", "end": "2026-03-31", "val": 10.0, "filed": "2026-04-20"},
        {"start": "2026-01-01", "end": "2026-06-30", "val": 30.5, "filed": "2026-07-23"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 99.0, "filed": "2026-02-01"},
    ]
    out = umd.latest_period_fact(entries)
    assert out["val"] == 30.5 and out["days"] == 180


def test_latest_period_fact_ignores_multi_year_spans():
    """Some filers tag a cumulative 'since inception' duration; counting it as a
    period figure would inflate the raise by years of history."""
    entries = [
        {"start": "2020-01-01", "end": "2026-06-30", "val": 500.0, "filed": "2026-07-23"},
        {"start": "2026-01-01", "end": "2026-06-30", "val": 30.5, "filed": "2026-07-23"},
    ]
    assert umd.latest_period_fact(entries)["val"] == 30.5


def test_latest_period_fact_takes_the_latest_restatement():
    entries = [
        {"start": "2026-01-01", "end": "2026-06-30", "val": 28.0, "filed": "2026-07-01"},
        {"start": "2026-01-01", "end": "2026-06-30", "val": 30.5, "filed": "2026-07-23"},
    ]
    assert umd.latest_period_fact(entries)["val"] == 30.5


def test_latest_period_fact_empty_is_none():
    assert umd.latest_period_fact([]) is None
    assert umd.latest_period_fact([{"end": "2026-06-30", "val": 1.0}]) is None


# ---------- NVDA trailing-P/E percentile ----------

def test_ni_ttm_series_requires_four_consecutive_quarters():
    q = {"2024Q4": 8.0, "2025Q1": 9.0, "2025Q2": 10.0, "2025Q3": 11.0, "2025Q4": 12.0}
    out = umd.ni_ttm_series(q)
    assert out == [("2025-09", 38.0), ("2025-12", 42.0)]
    # a hole in the quarter history breaks the window instead of summing across it
    gappy = {"2024Q4": 8.0, "2025Q1": 9.0, "2025Q3": 11.0, "2025Q4": 12.0}
    assert umd.ni_ttm_series(gappy) == []
    assert umd.ni_ttm_series({}) == []
    assert umd.ni_ttm_series(None) == []


def test_latest_share_count_picks_newest_end():
    entries = [{"end": "2025-10-26", "val": 24_600_000_000},
               {"end": "2026-04-26", "val": 24_400_000_000},
               {"end": "2026-01-25", "val": 24_500_000_000},
               {"end": "2026-07-26", "val": None}]          # null val never wins
    assert umd.latest_share_count(entries) == 24_400_000_000
    assert umd.latest_share_count([]) is None
    assert umd.latest_share_count(None) is None


def test_pe_series_uses_newest_ttm_known_by_each_month():
    ttm = [("2025-10", 2.0), ("2026-01", 4.0)]
    months = [("2025-09", 100.0),   # before any TTM window: skipped
              ("2025-10", 100.0),
              ("2025-12", 110.0),   # still the 2.0 EPS
              ("2026-02", 120.0)]   # the 4.0 EPS
    out = umd.pe_series(months, ttm)
    assert out == [["2025-10", 50.0], ["2025-12", 55.0], ["2026-02", 30.0]]
    # non-positive TTM EPS never becomes a P/E print
    assert umd.pe_series([("2025-12", 110.0)], [("2025-10", -0.5)]) == []
    assert umd.pe_series(None, ttm) == []


def test_percentile_of_last_needs_a_year_of_points():
    vals = list(range(1, 25))          # 24 ascending months, latest is the max
    assert umd.percentile_of_last(vals) == 100.0
    assert umd.percentile_of_last(vals[::-1]) == round(100.0 / 24, 1)  # latest is the min
    assert umd.percentile_of_last(vals[:6]) is None
    assert umd.percentile_of_last([]) is None


# ================= Rosenberg/Bernstein parameter set =================

def _xlsx(sheets, inline=False):
    """Minimal .xlsx blob: {sheet name: [[cell, ...], ...]}.

    `inline` writes strings as t="inlineStr" instead of through a sharedStrings table,
    which is how FINRA writes its date column and the exact shape update-capex-data.py's
    reader returns None for. Both paths are exercised because both are real files.
    """
    import io
    import zipfile
    from xml.sax.saxutils import escape

    shared, index = [], {}

    def sid(s):
        if s not in index:
            index[s] = len(shared)
            shared.append(s)
        return index[s]

    def col(n):
        name = ""
        while n >= 0:
            name = chr(ord("A") + n % 26) + name
            n = n // 26 - 1
        return name

    parts, names = {}, list(sheets)
    for i, name in enumerate(names, start=1):
        xml = ['<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               "<sheetData>"]
        for r, row in enumerate(sheets[name], start=1):
            xml.append(f'<row r="{r}">')
            for c, val in enumerate(row):
                if val is None:
                    continue                  # a genuinely absent cell, as Excel writes it
                ref = f"{col(c)}{r}"
                if isinstance(val, (int, float)):
                    xml.append(f'<c r="{ref}"><v>{val}</v></c>')
                elif inline:
                    xml.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(val)}</t></is></c>')
                else:
                    xml.append(f'<c r="{ref}" t="s"><v>{sid(val)}</v></c>')
            xml.append("</row>")
        xml.append("</sheetData></worksheet>")
        parts[f"xl/worksheets/sheet{i}.xml"] = "".join(xml)

    wb = ['<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          "<sheets>"]
    rels = ['<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships">']
    for i, name in enumerate(names, start=1):
        wb.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
        rels.append(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/worksheet"/>')
    wb.append("</sheets></workbook>")
    rels.append("</Relationships>")

    ss = ['<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    ss += [f"<si><t>{escape(s)}</t></si>" for s in shared]
    ss.append("</sst>")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "".join(wb))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        z.writestr("xl/sharedStrings.xml", "".join(ss))
        for path, xml in parts.items():
            z.writestr(path, xml)
    return buf.getvalue()


# ---------- Census C30: the percent-change columns are not months ----------
# Column layout copied from the live workbook (2026-06 release): six dollar columns, then
# a "Percent change Jun 2026 from -" block whose two sub-columns are headed with a month.
C30_BANNER = [None, None, None, None, None, None, None, "Percent change\nJun 2026 from -"]
C30_HEADER = ["Type of Construction:", "Jun\n2026p", "May\n2026r", "Apr\n2026r",
              "Mar\n2026", "Feb\n2026", "Jun\n2025", "May\n2026", "Jun\n2025"]
C30_OFFICE = ["    Office", "123000", "122000", "121000", "120000", "119000", "110000",
              "0.8", "11.8"]
C30_DC = ["Data center", "68297", "63843", "61859", "58121", "57361", "46850", "7.0", "45.8"]


def _c30_blob(rows=None):
    return _xlsx({"PrivateSA": rows if rows is not None else
                  [["Value of Private Construction Put in Place"], [], C30_BANNER,
                   C30_HEADER, C30_OFFICE, C30_DC]})


def test_parse_c30_series_reads_every_dollar_column():
    out = umd.parse_c30_series(_c30_blob())
    assert out == [{"d": "2025-06-01", "c": 46850.0}, {"d": "2026-02-01", "c": 57361.0},
                   {"d": "2026-03-01", "c": 58121.0}, {"d": "2026-04-01", "c": 61859.0},
                   {"d": "2026-05-01", "c": 63843.0}, {"d": "2026-06-01", "c": 68297.0}]


def test_parse_c30_series_never_reads_a_percent_change_column_as_a_level():
    """The bug this exists for: "May 2026" and "Jun 2025" head both a dollar column and a
    percent-change column. Reading the percent cell as the year-ago level turned a +53%
    year into a +156,386% one, and nothing about the output looked malformed."""
    out = umd.parse_c30_series(_c30_blob())
    assert [p["c"] for p in out] == sorted({46850.0, 57361.0, 58121.0, 61859.0,
                                            63843.0, 68297.0})
    assert 7.0 not in [p["c"] for p in out]      # the % change cells
    assert 45.8 not in [p["c"] for p in out]
    # one observation per month, so a later join cannot pick the wrong one
    assert len({p["d"] for p in out}) == len(out)


def test_parse_c30_series_stops_at_a_repeated_month_without_the_banner():
    """Second guard, independent of the banner text: the percent block's sub-columns are
    by construction the prior month and the year-ago month, both already dollar columns."""
    no_banner = [["Value of Private Construction Put in Place"], [],
                 C30_HEADER, C30_DC]
    out = umd.parse_c30_series(_c30_blob(no_banner))
    assert len(out) == 6 and max(p["c"] for p in out) == 68297.0


def test_parse_c30_series_ignores_the_office_parent_row():
    out = umd.parse_c30_series(_c30_blob())
    assert out[-1]["c"] == 68297.0          # not 123000, the Office line it nests under


def test_parse_c30_series_missing_row_or_bad_blob_is_none():
    assert umd.parse_c30_series(_c30_blob([C30_HEADER, C30_OFFICE])) is None
    assert umd.parse_c30_series(b"<html>503</html>") is None


def test_c30_month_parses_the_revision_suffix():
    assert umd.c30_month("Jun\n2026p") == "2026-06"
    assert umd.c30_month("May\n2026r") == "2026-05"
    assert umd.c30_month("September\n2025") == "2025-09"
    assert umd.c30_month("Percent change") is None
    assert umd.c30_month(None) is None


# ---------- FINRA margin debt ----------
FINRA_HEADER = ["Year-Month", "Debit Balances in Customers' Securities Margin Accounts",
                "Free Credit Balances in Customers' Cash Accounts"]


def test_parse_finra_margin_reads_inline_string_dates_newest_last():
    blob = _xlsx({"Customer Margin Balances": [
        FINRA_HEADER,
        ["2026-06", 1502072, 217441],
        ["2026-05", 1415557, 206600],
        ["2025-06", 1008000, 200000]]}, inline=True)
    out = umd.parse_finra_margin(blob)
    assert out == [{"d": "2025-06-01", "c": 1008000.0},
                   {"d": "2026-05-01", "c": 1415557.0},
                   {"d": "2026-06-01", "c": 1502072.0}]


def test_parse_finra_margin_picks_the_debit_column_not_the_first_number():
    """The sheet carries three balance columns; only the debit one is margin debt."""
    blob = _xlsx({"S": [["Year-Month", "Free Credit Balances in Customers' Cash Accounts",
                         FINRA_MARGIN_DEBIT], ["2026-06", 217441, 1502072]]}, inline=True)
    assert umd.parse_finra_margin(blob)[-1]["c"] == 1502072.0


FINRA_MARGIN_DEBIT = "Debit Balances in Customers' Securities Margin Accounts"


def test_parse_finra_margin_bad_blob_is_none():
    assert umd.parse_finra_margin(b"not a workbook") is None


# ---------- Shiller CAPE ----------
def test_parse_cape_table_decodes_entities_before_matching():
    """The value cell is prefixed with an en-space written as &#x2002;. A regex run over
    the raw markup reads that entity's own digits and returns a CAPE of 2002 for every
    month in the table — a series with zero variance, which then divides by zero."""
    page = ("<table id='datatable'><tr><th>Date</th><th>Value</th></tr>"
            "<tr><td>Aug 12, 2026</td><td> &#x2002; 42.34 </td></tr>"
            "<tr><td>Jul 1, 2026</td><td> &#x2002; 40.73 </td></tr></table>")
    out = umd.parse_cape_table(page)
    assert out == [{"d": "2026-07-01", "c": 40.73}, {"d": "2026-08-12", "c": 42.34}]


def test_cape_sigma_uses_the_post_epoch_window():
    series = ([{"d": f"1880-{m:02d}-01", "c": 100.0} for m in range(1, 13)]
              + [{"d": f"19{y:02d}-01-01", "c": 10.0 + (y % 5)} for y in range(0, 60)]
              + [{"d": "2026-08-01", "c": 40.0}])
    out = umd.cape_sigma(series, epoch=1900)
    assert out["cape"] == 40.0 and out["epoch"] == 1900
    assert out["n"] == 61                    # the 1880 block is excluded
    assert out["sigma"] > 3 and out["pctile"] == 100.0


def test_cape_sigma_needs_enough_history():
    assert umd.cape_sigma([{"d": "2026-01-01", "c": 40.0}]) is None
    assert umd.cape_sigma(None) is None


# ---------- A: credit-price divergence and the clock ----------
def _flat(dates, val):
    return [{"d": d, "c": val} for d in dates]


DAYS = [f"2026-0{m}-{d:02d}" for m in (4, 5, 6) for d in (1, 15)] + ["2026-07-01"]


def test_credit_price_divergence_needs_both_legs():
    rising = [{"d": d, "c": 100.0 + i} for i, d in enumerate(DAYS)]      # basket at highs
    widening = [{"d": d, "c": 2.0 + i * 0.2} for i, d in enumerate(DAYS)]
    flat_ig = _flat(DAYS, 1.0)
    out = umd.credit_price_divergence(rising, widening, flat_ig)
    assert out["at_highs"] is True and out["widening"] is True and out["diverging"] is True

    # same spreads, but the basket has already rolled over: that is a selloff, not the
    # divergence the transcript is about
    falling = [{"d": d, "c": 130.0 - i * 5} for i, d in enumerate(DAYS)]
    out2 = umd.credit_price_divergence(falling, widening, flat_ig)
    assert out2["at_highs"] is False and out2["diverging"] is False

    # basket at highs, spreads calm: no signal either
    out3 = umd.credit_price_divergence(rising, _flat(DAYS, 2.0), flat_ig)
    assert out3["widening"] is False and out3["diverging"] is False


def test_credit_price_divergence_joins_on_date_not_position():
    """HY and IG are carried forward independently when a fetch fails, so one can be a
    session behind the other; zipping them would price today's HY against last week's IG."""
    hy = [{"d": d, "c": 4.0} for d in DAYS]
    ig = [{"d": d, "c": 1.0} for d in DAYS if d != "2026-05-15"]
    out = umd.credit_price_divergence(_flat(DAYS, 100.0), hy, ig)
    assert out["hy_ig_gap"] == 3.0


def test_spread_change_bp_measures_over_the_calendar_window():
    series = [{"d": "2026-04-01", "c": 2.00}, {"d": "2026-05-01", "c": 2.10},
              {"d": "2026-07-01", "c": 2.50}]
    assert umd.spread_change_bp(series, 8) == pytest.approx(40.0)   # vs 2026-05-06 cutoff
    assert umd.spread_change_bp([], 8) is None


def test_credit_clock_starts_only_on_a_stressed_credit_family():
    assert umd.credit_clock(20, None, "2026-08-13") is None          # calm
    assert umd.credit_clock(40, None, "2026-08-13") is None          # elevated, never crossed
    started = umd.credit_clock(60, None, "2026-08-13")
    assert started["started"] == "2026-08-13" and started["months_left"] == 12.0


def test_credit_clock_keeps_the_first_crossing_and_counts_down():
    prior = {"started": "2026-02-13"}
    out = umd.credit_clock(60, prior, "2026-08-13")
    assert out["started"] == "2026-02-13"
    assert out["months_elapsed"] == pytest.approx(5.9, abs=0.1)
    assert out["months_left"] == pytest.approx(6.1, abs=0.1)
    # it keeps running while credit stays merely elevated - the clock is about the crossing
    assert umd.credit_clock(40, prior, "2026-08-13")["started"] == "2026-02-13"


def test_credit_clock_resets_when_credit_falls_back_to_calm():
    assert umd.credit_clock(10, {"started": "2026-02-13"}, "2026-08-13") is None


def test_credit_clock_never_goes_negative():
    out = umd.credit_clock(60, {"started": "2024-01-01"}, "2026-08-13")
    assert out["months_left"] == 0.0 and out["months_elapsed"] > 12


# ---------- B: capital misallocation ----------
def test_dc_housing_ratio_joins_on_month_and_takes_a_real_year_ago_base():
    dc = [{"d": "2025-06-01", "c": 46850.0}, {"d": "2026-06-01", "c": 68297.0}]
    res = [{"d": "2025-06-01", "c": 920447.0}, {"d": "2026-06-01", "c": 877118.0}]
    out = umd.dc_housing_ratio(dc, res)
    assert out["ratio"] == pytest.approx(0.0779, abs=1e-4)
    assert out["yoy_pct"] == pytest.approx(53.0, abs=0.5)
    assert out["dc_saar_b"] == 68.3 and out["res_saar_b"] == 877.1


def test_dc_housing_ratio_drops_months_the_other_side_is_missing():
    dc = [{"d": "2026-05-01", "c": 63843.0}, {"d": "2026-06-01", "c": 68297.0}]
    out = umd.dc_housing_ratio(dc, [{"d": "2026-06-01", "c": 877118.0}])
    assert len(out["history"]) == 1 and out["asof"] == "2026-06"
    assert umd.dc_housing_ratio(dc, []) is None
    assert umd.dc_housing_ratio(None, None) is None


def _fund(quarters, capex):
    return {"quarters": quarters, "capex_b": capex}


QS = ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]


def test_ex_ai_capex_annualizes_the_filer_quarter_before_subtracting():
    """BEA publishes a seasonally adjusted annual rate; the filers report one quarter of
    cash. Subtracting them raw would leave ~75% of AI capex inside the "ex-AI" line."""
    equip = [{"d": f"{q[:4]}-{(int(q[5]) - 1) * 3 + 1:02d}-01", "c": 1000.0} for q in QS]
    ip = [{"d": p["d"], "c": 500.0} for p in equip]
    out = umd.ex_ai_capex(equip, ip, _fund(QS, [50.0] * 5 + [100.0]))
    assert out["quarter"] == "2026Q2"
    assert out["total_b"] == 1500.0
    assert out["ai_b"] == 400.0                      # 100 x 4, not 100
    assert out["ex_ai_b"] == 1100.0
    assert out["ai_share_pct"] == pytest.approx(26.7, abs=0.1)
    # year-ago quarter is 2025Q2, whose ex-AI line was 1500 - 200 = 1300
    assert out["yoy_pct"] == pytest.approx(-15.4, abs=0.1)


def test_ex_ai_capex_needs_a_year_of_overlap():
    assert umd.ex_ai_capex([], [], _fund(QS, [1.0] * 6)) is None
    assert umd.ex_ai_capex(None, None, None) is None


def test_quarter_start_month_maps_to_the_bea_stamp():
    assert umd.quarter_start_month("2026Q1") == "2026-01"
    assert umd.quarter_start_month("2026Q4") == "2026-10"
    assert umd.quarter_start_month("2026H1") is None


def test_gdp_ex_ai_subtracts_the_change_in_ai_capex_not_its_level():
    """The arithmetic contribution to growth is the *change* in spending over the level of
    GDP. Subtracting the level would remove several points of GDP a year and read as a
    permanent depression."""
    growth = [{"d": "2025-07-01", "c": 2.0}, {"d": "2025-10-01", "c": 2.0},
              {"d": "2026-01-01", "c": 2.0}, {"d": "2026-04-01", "c": 2.0}]
    real = [{"d": "2026-04-01", "c": 24000.0}]
    out = umd.gdp_ex_ai(growth, real, _fund(QS, [50.0] * 5 + [110.0]))
    assert out["gdp_4q_avg_pct"] == 2.0
    # (110 - 50) x 4 / 24000 = 1.0pp
    assert out["ai_contrib_pp"] == pytest.approx(1.0, abs=0.01)
    assert out["ex_ai_pct"] == pytest.approx(1.0, abs=0.01)


def test_gdp_ex_ai_needs_four_quarters_of_growth():
    assert umd.gdp_ex_ai([{"d": "2026-04-01", "c": 2.0}], [{"d": "2026-04-01", "c": 1.0}],
                         _fund(QS, [1.0] * 6)) is None


# ---------- E: correlation breadth, rotation ----------
def test_pearson_is_none_without_variance():
    assert umd.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert umd.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert umd.pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None       # flat is not "uncorrelated"
    assert umd.pearson([1, 2], [1, 2]) is None                   # too short


def test_basket_series_joins_on_trading_date():
    equity = {"A": [{"d": "2026-01-01", "c": 10.0}, {"d": "2026-01-02", "c": 11.0},
                    {"d": "2026-01-03", "c": 12.0}],
              # B is a session behind - the extra date must be dropped, not paired by index
              "B": [{"d": "2026-01-01", "c": 100.0}, {"d": "2026-01-02", "c": 100.0}]}
    out = umd.basket_series(equity, ["A", "B"])
    assert [p["d"] for p in out] == ["2026-01-01", "2026-01-02"]
    assert out[0]["c"] == 100.0                                   # based at 100
    assert out[1]["c"] == pytest.approx(105.0)                    # (1.1 + 1.0) / 2 x 100


def test_basket_series_needs_two_live_symbols():
    assert umd.basket_series({"A": [{"d": "2026-01-01", "c": 1.0}]}, ["A"]) is None
    assert umd.basket_series({}, ["A", "B"]) is None


def _walk(days, steps, start=100.0):
    """Price path from a repeating list of gross returns.

    Deliberately not a straight line: a linear path has monotonically *shrinking* returns,
    so two lines with opposite slopes still produce return series that both fall over the
    window and correlate at +1. The correlation here is of returns, so the fixture has to
    vary them."""
    out, px = [], start
    for i, d in enumerate(days):
        out.append({"d": d, "c": px})
        px *= steps[i % len(steps)]
    return out


def test_correlation_breadth_counts_only_sectors_over_the_threshold():
    days = [f"2026-01-{d:02d}" for d in range(1, 21)]
    steps = [1.02, 0.99, 1.03, 0.98, 1.01, 0.97, 1.04, 0.99, 1.02, 0.98]
    basket = _walk(days, steps)
    equity = {"XLK": _walk(days, steps, 50.0),                          # lockstep
              "XLP": _walk(days, [2 - s for s in steps], 50.0)}         # mirrored
    out = umd.correlation_breadth(equity, basket,
                                  {"XLK": "technology", "XLP": "staples"}, window=10)
    assert out["n_total"] == 2 and out["n_hot"] == 1
    assert out["cool"] == ["staples"]
    assert out["sectors"][0]["sym"] == "XLK"          # sorted by correlation, descending


def test_rotation_rs_reports_the_change_not_the_level():
    days = [f"2026-01-{d:02d}" for d in range(1, 11)]
    basket = [{"d": d, "c": 100.0 + i * 5} for i, d in enumerate(days)]   # AI leads
    equity = {"ACWX": [{"d": d, "c": 80.0} for d in days]}
    out = umd.rotation_rs(equity, basket, window=9)
    assert out["change_pct"] < 0 and out["leading"] is False
    # ex-US pulling ahead flips it
    equity2 = {"ACWX": [{"d": d, "c": 80.0 + i * 20} for i, d in enumerate(days)]}
    assert umd.rotation_rs(equity2, basket, window=9)["leading"] is True


# ---------- F: macro strip ----------
def test_taylor_gap_reads_nrou_at_the_unemployment_date_not_at_the_series_end():
    """NROU is a CBO projection that runs a decade past the last real observation. Taking
    its final point would measure today's policy rate against the 2036 natural rate."""
    ffr = [{"d": "2026-07-01", "c": 3.63}]
    pce = [{"d": "2026-06-01", "c": 2.23}]
    unrate = [{"d": "2026-07-01", "c": 4.10}]
    nrou = [{"d": "2026-04-01", "c": 4.39}, {"d": "2036-10-01", "c": 9.99}]
    out = umd.taylor_gap(ffr, pce, unrate, nrou)
    assert out["nrou_pct"] == 4.39
    # 2.0 + 2.23 + 0.5(2.23 - 2.0) + (4.39 - 4.10) = 4.635
    assert out["rule_pct"] == pytest.approx(4.64, abs=0.01)
    assert out["gap_pp"] == pytest.approx(1.01, abs=0.01)
    assert out["stance"] == "loose"


def test_taylor_gap_is_none_without_every_leg():
    assert umd.taylor_gap(None, [{"d": "x", "c": 1}], [{"d": "x", "c": 1}],
                          [{"d": "x", "c": 1}]) is None


def test_series_percentile_locates_the_latest_reading():
    series = [{"d": f"2026-01-{i:02d}", "c": float(i)} for i in range(1, 21)]
    out = umd.series_percentile(series)
    assert out["value"] == 20.0 and out["pctile"] == 100.0 and out["n"] == 20
    assert umd.series_percentile(series[:3]) is None


# ---------- the fragility composite ----------
def _frag_data(**over):
    data = {
        "misalloc": {"dc_housing": {"ratio": 0.12},
                     "ex_ai_capex": {"yoy_pct": -8.0},
                     "gdp_ex_ai": {"ex_ai_pct": 0.0}},
        "positioning": {"hh_equity_fin": {"pctile": 100.0},
                        "margin_debt": {"yoy_pct": 30.0},
                        "survey": {"ici_cash_pct": {"value": 1.5},
                                   "fms_recession_pct": {"value": 2.0},
                                   "fms_base_rate_pct": {"value": 15.0}}},
        "cape": {"sigma": 3.0},
        "corr_breadth": {"n_hot": 10, "n_total": 11},
        "spec_blur": {"ratio": 30.0},
        "credit_div": {"gap_z": 2.0},
        "cot": {"contracts": [{"key": "ndx", "pctile": 100.0}]},
    }
    data.update(over)
    return data


def test_compute_fragility_pegs_at_100_when_every_component_is_at_its_stressed_end():
    out = umd.compute_fragility(_frag_data())
    assert out["score"] == 100.0
    assert out["n_families"] == 4
    assert set(out["fam"]) == {"mis", "pos", "val", "cred"}


def test_compute_fragility_weights_families_equally_not_components():
    """`pos` has five components and `cred` has one; the handover's rule is that no family
    dominates, so a five-component family must not carry five times the weight."""
    calm_pos = _frag_data()
    calm_pos["positioning"] = {"hh_equity_fin": {"pctile": 50.0},
                               "margin_debt": {"yoy_pct": 0.0},
                               "survey": {"ici_cash_pct": {"value": 5.0},
                                          "fms_recession_pct": {"value": 15.0},
                                          "fms_base_rate_pct": {"value": 15.0}}}
    calm_pos["cot"] = {"contracts": [{"key": "ndx", "pctile": 50.0}]}   # the fifth component
    out = umd.compute_fragility(calm_pos)
    assert out["fam"]["pos"] == 0.0
    assert out["score"] == 75.0            # three families at 100, one at 0


def test_compute_fragility_needs_more_than_one_live_family():
    only_cred = {"credit_div": {"gap_z": 2.0}}
    assert umd.compute_fragility(only_cred) is None
    assert umd.compute_fragility({}) is None


def test_compute_fragility_survives_a_dark_feed():
    data = _frag_data()
    del data["cape"]
    data["corr_breadth"] = None
    data["spec_blur"] = None
    out = umd.compute_fragility(data)
    assert out["fam"]["val"] is None       # the whole family goes dark
    assert out["n_families"] == 3          # ...and drops out of the mean, not counted as 0
    assert out["score"] == 100.0


def test_dig_walks_past_missing_levels():
    assert umd.dig({"a": {"b": 1}}, "a", "b") == 1
    assert umd.dig({"a": None}, "a", "b") is None
    assert umd.dig(None, "a") is None


def test_neg_keeps_none():
    assert umd.neg(3) == -3 and umd.neg(-2.5) == 2.5 and umd.neg(None) is None


# ---------- payload pruning ----------
def test_prune_payload_drops_only_the_compute_only_series():
    data = {"equity": {"NVDA": [{"d": "2026-01-01", "c": 1.0}],
                       "XLU": [{"d": "2026-01-01", "c": 2.0}],     # also the power proxy
                       "XLK": [{"d": "2026-01-01", "c": 3.0}],
                       "GLD": [{"d": "2026-01-01", "c": 4.0}],
                       "ACWX": [{"d": "2026-01-01", "c": 5.0}]},
            "fred": {"HY_OAS": {"last": 2.7, "series": [{"d": "2026-01-01", "c": 2.7}]},
                     "HH_EQ_FIN": {"last": 45.8, "series": [{"d": "2026-01-01", "c": 45.8}]},
                     "NROU": {"last": 4.39, "series": [{"d": "2026-01-01", "c": 4.39}]}}}
    umd.prune_payload(data)
    assert set(data["equity"]) == {"NVDA", "XLU"}
    assert "series" in data["fred"]["HY_OAS"]        # charted
    assert "series" in data["fred"]["HH_EQ_FIN"]     # charted
    assert "series" not in data["fred"]["NROU"]      # a Taylor-rule input, nothing more
    assert data["fred"]["NROU"]["last"] == 4.39      # the summary survives


def test_prune_payload_survives_a_dark_section():
    assert umd.prune_payload({}) == {}
    assert umd.prune_payload({"fred": {"NROU": None}})["fred"] == {"NROU": None}


def test_the_power_proxy_is_never_pruned():
    """XLU is both a sector SPDR and the power panel's series; the power panel charts it."""
    assert not (umd.TRANSIENT_EQUITY & set(umd.POWER_PROXY))


def test_every_pruned_fred_name_is_a_real_series():
    live = set(umd.FRED.values())
    assert umd.FRED_SUMMARY_ONLY <= live, umd.FRED_SUMMARY_ONLY - live
    assert umd.TRANSIENT_EQUITY <= set(umd.SECTORS) | set(umd.FROTH) | set(umd.ROTATION)
