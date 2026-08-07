"""The calm->stress reference ranges are written down once, and this proves the copy.

Until 2026-08 the ranges the gauge normalizes against were re-typed in five places:
compute_gauge() here in Python, computeGauge() and computeGaugeHistory() in the monitor,
and the published reference-range prose on gauge.html and in the monitor's methodology
footer. The regime *thresholds* were centralized into OMEN.REGIME after they drifted; the
ranges were the same accident waiting to happen with a worse failure mode, because a range
that drifts changes the number without changing a single word of the wording.

They now live in OMEN.GAUGE_REFS (omen/omen-common.js): the two browser implementations
score through OMEN.gaugeScore, and both prose sites render from OMEN.gaugeRefsProse.
Python cannot import a JS file, so update-market-data.py keeps a mirror - and this suite
parses the real table out of omen-common.js and fails if the mirror disagrees on any
number, or if either side quietly gains or loses a component.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent

spec = importlib.util.spec_from_file_location("umd", HERE / "update-market-data.py")
umd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(umd)

COMMON = (HERE / "omen-common.js").read_text()


def js_gauge_refs():
    """The GAUGE_REFS object literal from omen-common.js, as a dict.

    Read as JSON rather than by a per-field regex so reformatting the table (or adding a
    field to a row) does not silently stop the comparison from happening.
    """
    m = re.search(r"const GAUGE_REFS = \{(.*?)\n  \};", COMMON, re.S)
    assert m, "GAUGE_REFS object literal not found in omen-common.js"
    body = m.group(1)
    body = re.sub(r"(\w+):", r'"\1":', body)          # bare keys -> JSON keys
    body = re.sub(r",(\s*[}\]])", r"\1", body)        # trailing commas inside rows
    body = re.sub(r",\s*$", "", body.strip())         # ...and after the last row
    return json.loads("{" + body + "}")


JS = js_gauge_refs()


def test_the_table_parsed_at_all():
    """A silently-empty parse would make every other assertion here vacuous."""
    assert len(JS) >= 15
    for key, row in JS.items():
        assert {"fam", "name", "lo", "hi", "fmt"} <= set(row), key
        assert row["lo"] < row["hi"], key


def test_python_mirrors_the_shared_table_number_for_number():
    for key, (lo, hi) in umd.GAUGE_REFS.items():
        assert key in JS, f"{key} is scored in Python but is not a row in omen-common.js"
        assert (lo, hi) == (JS[key]["lo"], JS[key]["hi"]), (
            f"{key}: Python has {(lo, hi)}, omen-common.js has "
            f"{(JS[key]['lo'], JS[key]['hi'])} - edit the JS table and mirror it here")


def test_the_server_split_is_the_documented_one():
    """`server: true` marks the rows the five-family server gauge also reads. The rest are
    the monitor's exploratory-only components, and that split is what the parity fixture
    calls the intended divergence - so it is pinned, not inferred."""
    server_side = {k for k, v in JS.items() if v.get("server")}
    assert server_side == set(umd.GAUGE_REFS), (
        "the `server: true` rows and update-market-data.py's GAUGE_REFS have diverged")
    assert {k for k in JS if not JS[k].get("server")} == {
        "pred_nvda_tail", "pred_h100_sub2",
        "macro_recession", "macro_fed_cuts", "macro_china_top3"}


def test_every_python_range_is_actually_used_by_the_server_gauge():
    """A row nobody scores against is a range that can rot unnoticed."""
    src = (HERE / "update-market-data.py").read_text()
    used = set(re.findall(r'\bsc\([^\n]*?,\s*"(\w+)"\)', src))
    assert used == set(umd.GAUGE_REFS), f"unused or unknown: {used ^ set(umd.GAUGE_REFS)}"


def test_an_unknown_range_name_fails_loudly():
    with pytest.raises(KeyError):
        umd.sc(1.0, "no_such_range")


PROSE_PAGES = ["gauge.html", "methodology.html", "polymarket-ai-index.html"]


def test_the_published_ranges_are_rendered_not_typed():
    """Every page that publishes the ranges reads the table.

    gauge.html and methodology.html each carried a hand-typed copy of the same block, and
    both had drifted the same two ways: they advertised the monitor-only NVDA-tail and
    H100 components and omitted the two spread rows the server gauge does read. The
    monitor's footer called the set five families while the code computed six.
    """
    for page in PROSE_PAGES:
        assert "gaugeRefsProse" in (HERE / page).read_text(), (
            f"{page} publishes reference ranges without rendering them from the table")


def test_no_page_still_hand_types_a_range():
    """The copies are gone, not just outnumbered - a stale sixth copy on a page nobody
    edits is exactly how this started. Checks the literals that were actually typed."""
    stale = ["NVDA deep tail 0–25%", "VXN 18–40 · SKEW 115–160", "HYG drawdown 0 to −8%"]
    for page in PROSE_PAGES + ["index.html", "indexes.html"]:
        text = (HERE / page).read_text()
        found = [s for s in stale if s in text]
        assert not found, f"{page} still hand-types reference ranges: {found}"
