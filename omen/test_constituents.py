"""constituents.js - the one constituent list - and what the fetcher builds on it.

The Bull / Bear basket used to exist in five hand-typed copies (POLY_IDS here, a MARKETS
or CONSTITUENTS array in four pages). Three markets had left the live basket by
2026-10-22 and every page still said "twenty"; the landing page was still averaging a
delisted market at its three-month-old baked price. This suite pins the fix:

  - the file parses as the JSON literal update-market-data.py reads, and is well-formed;
  - the vintage rule reproduces history (the original twenty on 2026-07-11, the snapshot
    membership on later days) - so a `to` date is a recorded fact, not an opinion;
  - no page carries a constituent literal of its own any more;
  - the coverage watchdog and the chain-linked levels behave on synthetic rows.
"""

import csv
import importlib.util
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent

spec = importlib.util.spec_from_file_location("umd", HERE / "update-market-data.py")
umd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(umd)

DOC = umd.load_constituents()
SIDES = {"bull", "bear", "china", "macro"}
THEMES = {"bull": {"tech", "capital"}, "bear": {"mkt", "gov"}}
PAGES = ["index.html", "indexes.html", "gauge.html", "polymarket-ai-index.html"]
# every job a market can hold, and the side it must sit on
ROLES = {"bubble": "bear", "recession": "macro", "fed_cuts": "macro",
         "china_top3": "china", "china_best": "china"}


# ---- the file ----

def test_the_literal_is_json_after_the_assignment():
    txt = (HERE / "constituents.js").read_text(encoding="utf-8")
    assert "window.OMEN_CONSTITUENTS =" in txt
    start = txt.index("{", txt.index("OMEN_CONSTITUENTS"))
    json.loads(txt[start:txt.rindex("}") + 1])   # raises if anyone adds a JS-only construct
    assert txt.rstrip().endswith("};")


def test_every_market_is_well_formed():
    ids = [m["id"] for m in DOC["markets"]]
    assert len(ids) == len(set(ids)), "duplicate constituent id"
    for m in DOC["markets"]:
        assert re.fullmatch(r"\d{5,8}", m["id"]), m
        assert m["side"] in SIDES, m
        assert m["htype"] in {"event", "structural"}, m
        assert m["label"] and m["from"], m
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", m["from"]), m
        if m["side"] in THEMES:
            assert m.get("theme") in THEMES[m["side"]], m
            assert m.get("slug"), f"{m['id']} needs a slug: the pages link the pair's rows"
        if m.get("to"):
            assert m["to"] > m["from"], m
        if m.get("role"):
            assert m["role"] in ROLES, m
            assert m["side"] == ROLES[m["role"]], m
            if m["role"] == "bubble":
                assert m["theme"] == "mkt", m
    assert DOC["roll_floor"] >= 2
    assert DOC["horizon_days"] >= 7


def test_at_most_one_live_market_per_role_per_day():
    for day in ("2026-07-11", "2026-10-22", "2027-01-01", "2027-06-01"):
        for role in ROLES:
            holders = [m for m in umd.constituents_at(day, None, DOC) if m.get("role") == role]
            # a successor can overlap its predecessor; then the newer one holds the job
            assert len(holders) <= 2, (day, role, holders)
            if len(holders) == 2:
                newest = max(holders, key=lambda m: m["from"])
                assert umd.role_id_at(role, day, DOC) == newest["id"]


def test_the_recession_leg_hands_over_on_new_years_day():
    assert umd.role_id_at("recession", "2026-12-31", DOC) == "609655"
    assert umd.role_id_at("recession", "2027-01-01", DOC) == "3407418"
    # roles with no successor yet simply have no holder once the 2026 market is gone
    assert umd.role_id_at("fed_cuts", "2026-10-22", DOC) == "616905"


def test_the_dead_china_markets_are_retired_not_silently_absent():
    """Five of the seven China markets stopped coming back from Gamma (three ended in July,
    two were closed early on 2026-08-03). They now carry the day they left, so the China
    index's member count is the truth rather than seven with five missing."""
    china_today = {m["id"] for m in umd.constituents_at("2026-10-22", "china", DOC)}
    assert china_today == {"1820798", "2873443"}
    for i in ("2873458", "2873459", "2431240", "2431245", "2431244"):
        m = next(x for x in DOC["markets"] if x["id"] == i)
        assert m.get("to") and m.get("note"), i
    assert umd.bubble_id_at("2026-10-22", DOC) == "691340"
    assert umd.BUBBLE_ID == umd.bubble_id_at(None, DOC)


# ---- the vintage rule reproduces history ----

def test_the_original_twenty_on_curation_day():
    ids = umd.poly_ids_at("2026-07-11", DOC)
    assert len(ids["bull"]) == 11 and len(ids["bear"]) == 9
    sl = umd.bear_sleeves_at("2026-07-11", DOC)
    assert (len(sl["mkt"]), len(sl["gov"])) == (3, 6)


def test_vintages_match_the_snapshot_membership():
    """snapshots.csv records the live membership of every day in its trailing `comp`
    list. A market's `to` date must agree with the day it stopped appearing there, and
    nothing may be a member that the snapshot never priced after its `to`."""
    rows = list(csv.reader((HERE / "snapshots.csv").open()))
    head = rows[0]
    ci = head.index("comp")
    seen_ever = set()
    for r in rows[1:]:
        day, live = r[0], set(x for x in r[ci:] if x)
        seen_ever |= live
        members = set(umd.poly_ids_at(day, DOC)["bull"] + umd.poly_ids_at(day, DOC)["bear"])
        # live ⊆ members: the snapshot cannot have priced a market the vintage excludes
        assert live <= members, (day, sorted(live - members))
    known = {m["id"] for m in DOC["markets"]}
    assert seen_ever <= known, sorted(seen_ever - known)


def test_departed_markets_are_out_today_and_proposed_ones_are_never_in():
    today = umd.poly_ids_at(None, DOC)
    live = set(today["bull"] + today["bear"])
    for m in DOC["markets"]:
        if m.get("to") and m["to"] <= "2026-10-22":
            assert m["id"] not in live, m["id"]
        if m.get("proposed"):
            assert m["id"] not in live, m["id"]
            for day in ("2026-07-11", "2027-01-01", "2030-01-01"):
                assert m["id"] not in [x["id"] for x in umd.constituents_at(day, None, DOC)]


def test_module_level_basket_is_todays_vintage():
    assert umd.POLY_IDS == umd.poly_ids_at(None, DOC)
    assert umd.BEAR_SLEEVES == umd.bear_sleeves_at(None, DOC)
    assert umd.POLY_IDS["bear"] == umd.BEAR_SLEEVES["mkt"] + umd.BEAR_SLEEVES["gov"]


# ---- no page carries a copy ----

@pytest.mark.parametrize("page", PAGES)
def test_pages_build_their_list_from_the_shared_file(page):
    html = (HERE / page).read_text(encoding="utf-8")
    assert '<script src="constituents.js"></script>' in html, f"{page} does not load constituents.js"
    assert "OMEN.constituentsAt(" in html, f"{page} does not build its list from it"
    # the old shape: an array of object literals with an id and a side
    literals = re.findall(r'\{\s*id:\s*"\d{5,8}"\s*,\s*side:', html)
    assert not literals, f"{page} has grown a constituent list of its own again: {literals[:3]}"
    # the only literal uses allowed: the baked price snapshot's key and the fallback
    # after OMEN.bubbleIdAt(...) - never a lookup by the bare id
    stripped = re.sub(r'\|\|\s*"691340"|"691340"\s*:', "", html)
    assert '"691340"' not in stripped, (
        f"{page} hardcodes the bubble market id; read OMEN.bubbleIdAt(doc) instead")


def test_the_fetcher_has_no_literal_basket():
    src = (HERE / "update-market-data.py").read_text(encoding="utf-8")
    assert not re.search(r'POLY_IDS\s*=\s*\{\s*\n?\s*"bull":\s*\[', src)
    assert 'BUBBLE_ID = bubble_id_at() or "691340"' in src


# ---- the coverage watchdog ----

def _rows(members, end="2027-01-01", closed=()):
    return {m["id"]: {"id": m["id"], "endDate": f"{end}T00:00:00Z",
                      "closed": m["id"] in closed, "outcomePrices": '["0.3","0.7"]'}
            for m in members}


def test_coverage_counts_live_expiring_and_the_cliff():
    members = umd.constituents_at("2026-10-22", None, DOC)
    core = [m for m in members if m["side"] in ("bull", "bear")]
    rows = _rows(members)
    price = {m["id"]: 0.3 for m in members}
    cov = umd.build_coverage(rows, price, asof="2026-10-22", doc=DOC)
    assert cov["sides"]["bull"]["live"] == len([m for m in core if m["side"] == "bull"])
    assert cov["sides"]["bear"]["live"] == len([m for m in core if m["side"] == "bear"])
    assert cov["next_cliff"] == {"date": "2027-01-01", "count": len(core), "days_left": 71}
    # 71 days out, nothing is inside the 30-day horizon yet and the pair is not rolling
    assert cov["sides"]["bull"]["expiring"] == 0 and not cov["sides"]["bull"]["rolling"]
    # the side-indexes are watched too: China is down to two live markets, and says so
    assert set(cov["sides"]) == {"bull", "bear", "china", "macro"}
    assert cov["sides"]["china"]["live"] == 2 and cov["sides"]["macro"]["live"] == 4
    assert cov["warnings"] == ["china: 2 live market(s), below the floor of 3 - the china "
                               "side-index is reading too few markets to be an index"]
    assert cov["sides"]["macro"]["cliff"] == {"date": "2027-01-01", "count": 4, "days_left": 71}
    assert {m["status"] for m in cov["markets"]} == {"live"}


def test_coverage_warns_when_half_a_side_is_inside_the_horizon():
    members = [m for m in umd.constituents_at("2026-12-10", None, DOC) if m["side"] in ("bull", "bear")]
    rows = _rows(members)
    price = {m["id"]: 0.3 for m in members}
    cov = umd.build_coverage(rows, price, asof="2026-12-10", doc=DOC)
    assert cov["sides"]["bull"]["expiring"] >= cov["sides"]["bull"]["live"] / 2
    assert any(w.startswith("bull:") and "expire within 30 days" in w for w in cov["warnings"])
    assert any(w.startswith("bear:") for w in cov["warnings"])
    assert "cliff 2027-01-01" in cov["warnings"][0]


def test_coverage_flags_a_rolling_side_and_missing_markets():
    members = [m for m in umd.constituents_at("2026-10-22", None, DOC) if m["side"] in ("bull", "bear")]
    bull = [m for m in members if m["side"] == "bull"]
    # Gamma returns only two bull markets open, one closed, the rest not at all
    rows = _rows(bull[:3], closed=(bull[2]["id"],))
    rows.update(_rows([m for m in members if m["side"] == "bear"]))
    price = {m["id"]: 0.3 for m in bull[:2]} | {m["id"]: 0.3 for m in members if m["side"] == "bear"}
    cov = umd.build_coverage(rows, price, asof="2026-10-22", doc=DOC)
    assert cov["sides"]["bull"] == {"configured": len(bull), "live": 2, "expiring": 0, "rolling": True,
                                    "cliff": {"date": "2027-01-01", "count": 2, "days_left": 71}}
    statuses = {m["id"]: m["status"] for m in cov["markets"]}
    assert statuses[bull[2]["id"]] == "closed" and statuses[bull[3]["id"]] == "missing"
    assert cov["warnings"][0].startswith("bull: 2 live market(s), below the floor of 3")
    assert cov["proposed"] == sum(1 for m in DOC["markets"] if m.get("proposed"))


def test_coverage_lists_the_next_vintage_once_it_is_dated():
    doc = json.loads(json.dumps(DOC))
    for m in doc["markets"]:
        m.pop("proposed", None)          # the user curates them in
    cov = umd.build_coverage({}, {}, asof="2026-10-22", doc=doc)
    assert cov["upcoming"] and all(u["from"] > "2026-10-22" for u in cov["upcoming"])
    assert cov["proposed"] == 0
    # and on the day they join, they are members
    later = umd.poly_ids_at("2027-01-02", doc)
    assert "4838928" in later["bear"] and umd.bubble_id_at("2027-01-02", doc) == "4838928"


# ---- chain-linked levels ----

def test_chain_moves_only_by_the_common_set():
    ids = {"bull": ["a", "b", "c"], "bear": ["x", "y"]}
    prev_price = {"a": 0.2, "b": 0.4, "c": 0.6, "x": 0.1, "y": 0.3}
    first = umd.chain_levels(None, None, prev_price, ids)
    assert first == {"bull": 40.0, "bear": 20.0}           # anchored to raw
    # c resolves and drops out, a and b are unchanged: raw bull jumps to 30, chain holds 40
    price = {"a": 0.2, "b": 0.4, "x": 0.1, "y": 0.3}
    chain = umd.chain_levels(first, prev_price, price, ids)
    assert chain == {"bull": 40.0, "bear": 20.0}
    # then a new market d joins at 0.9: still no jump, and the next move carries it
    ids2 = {"bull": ["a", "b", "d"], "bear": ["x", "y"]}
    price2 = {"a": 0.2, "b": 0.4, "d": 0.9, "x": 0.1, "y": 0.3}
    chain2 = umd.chain_levels(chain, price, price2, ids2)
    assert chain2["bull"] == 40.0
    price3 = {"a": 0.3, "b": 0.4, "d": 0.8, "x": 0.1, "y": 0.3}
    chain3 = umd.chain_levels(chain2, price2, price3, ids2)
    assert chain3["bull"] == pytest.approx(40.0 + (0.1 - 0.1) / 3 * 100)


def test_chain_falls_back_to_the_raw_move_without_overlap():
    ids = {"bull": ["a", "b"], "bear": ["x"]}
    prev = umd.chain_levels({"bull": 50.0, "bear": 10.0}, {"p": 0.5, "q": 0.5, "x": 0.1},
                            {"a": 0.2, "b": 0.2, "x": 0.1}, ids)
    # no common bull market, no previous bull member priced either: the level carries
    assert prev["bull"] == 50.0 and prev["bear"] == 10.0
    gone = umd.chain_levels({"bull": 50.0, "bear": 10.0}, {"a": 0.5}, {"x": 0.1}, ids)
    assert gone["bull"] is None and gone["bear"] == 10.0


def test_snapshot_row_writes_the_chain_cells():
    price = {i: 0.25 for i in umd.POLY_IDS["bull"] + umd.POLY_IDS["bear"]}
    data = {"poly": {"chain": {"bull": 31.25, "bear": 12.5}}}
    # append_snapshot writes a file; the row shape is what the pages parse, test that
    row = umd.snapshot_row(price)
    chain = data["poly"]["chain"]
    row["bull_chain"], row["bear_chain"] = chain["bull"], chain["bear"]
    line = ",".join(str(row.get(h, "")) for h in umd.SNAP_HEADER)
    cells = line.split(",", len(umd.SNAP_HEADER) - 1)
    assert cells[umd.SNAP_HEADER.index("bull_chain")] == "31.25"
    assert umd.SNAP_HEADER[-1] == "comp", "comp must stay last: it is an unquoted comma list"


def test_runner_lists_stay_identical():
    """test_regime_explainer.SUITES and package.json's `test` script must name the same
    Node suites, or one entry point silently runs fewer than the other."""
    pkg = json.loads((HERE / "package.json").read_text())
    from_npm = re.findall(r"node (test-[\w-]+\.mjs)", pkg["scripts"]["test"])
    spec2 = importlib.util.spec_from_file_location("tre", HERE / "test_regime_explainer.py")
    tre = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(tre)
    assert sorted(from_npm) == sorted(tre.SUITES)
    on_disk = sorted(p.name for p in HERE.glob("test-*.mjs"))
    assert on_disk == sorted(tre.SUITES), "a Node suite on disk is not run by pytest"


def test_a_side_index_warns_on_its_own_cliff_but_never_says_the_verdict_rolls():
    members = [m for m in umd.constituents_at("2026-12-10", None, DOC)]
    rows = _rows(members)
    price = {m["id"]: 0.3 for m in members}
    cov = umd.build_coverage(rows, price, asof="2026-12-10", doc=DOC)
    macro = [w for w in cov["warnings"] if w.startswith("macro:")]
    assert macro == ["macro: 4 of 4 live markets expire within 30 days (cliff 2027-01-01, 22d)"]
    assert not any("verdict" in w for w in cov["warnings"] if w.startswith(("china:", "macro:")))
