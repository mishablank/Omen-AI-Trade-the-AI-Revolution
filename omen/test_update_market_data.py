import importlib.util
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


def test_bs_prob_below_is_sane_and_monotonic():
    # deeper strikes must be less likely; a rough known value anchors the math
    p50 = umd.bs_prob_below(210.0, 105.0, 0.51, 340)
    p30 = umd.bs_prob_below(210.0, 147.0, 0.46, 340)
    assert p50 is not None and p30 is not None
    assert 0.05 < p50 < 0.20          # ~10% at current NVDA vols
    assert p30 > p50                  # -30% strictly more likely than -50%
    assert umd.bs_prob_below(210.0, 105.0, 0, 340) is None
    assert umd.bs_prob_below(None, 105.0, 0.5, 340) is None


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
        "credit": {"HYG": [{"c": 100}, {"c": 96}], "LQD": [{"c": 100}, {"c": 100}]},
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
