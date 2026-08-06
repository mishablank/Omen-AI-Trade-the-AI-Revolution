import datetime
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ucd", Path(__file__).parent / "update-capex-data.py")
ucd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ucd)


def test_roc_ym_converts_republic_calendar():
    assert ucd.roc_ym("11506") == "2026-06"
    assert ucd.roc_ym("9912") == "2010-12"
    assert ucd.roc_ym("bogus") is None
    assert ucd.roc_ym("") is None


TSMC_ROWS = [
    {"公司代號": "2317", "資料年月": "11506", "營業收入-當月營收": "1"},
    {"公司代號": "2330", "資料年月": "11506",
     "營業收入-當月營收": "442679969",
     "營業收入-上月比較增減(%)": "6.164589232380731",
     "營業收入-去年同月增減(%)": "67.86685548491262",
     "累計營業收入-前期比較增減(%)": "35.613194655616326",
     "備註": "因先進製程產品需求增加所致。"},
]


def test_parse_tsmc_rows_picks_2330_and_scales_to_billions():
    out = ucd.parse_tsmc_rows(TSMC_ROWS)
    assert out["asof"] == "2026-06"
    # 442,679,969 thousand NTD -> 442.7B NTD
    assert out["rev_ntd_b"] == 442.7
    assert out["mom_pct"] == 6.2
    assert out["yoy_pct"] == 67.9
    assert out["ytd_yoy_pct"] == 35.6
    assert "先進製程" in out["note"]


def test_parse_tsmc_rows_missing_symbol_is_none():
    assert ucd.parse_tsmc_rows([{"公司代號": "2317", "資料年月": "11506"}]) is None
    assert ucd.parse_tsmc_rows([]) is None


def test_efts_windows_are_contiguous_and_iso():
    cur, prev = ucd.efts_windows(datetime.date(2026, 7, 19), days=90)
    assert cur == ("2026-04-21", "2026-07-19")
    assert prev == ("2026-01-21", "2026-04-20")
    # contiguous: prev ends the day before cur starts
    assert (datetime.date.fromisoformat(cur[0])
            - datetime.date.fromisoformat(prev[1])).days == 1


def test_parse_efts_total_reads_hit_count():
    assert ucd.parse_efts_total({"hits": {"total": {"value": 17}}}) == 17
    assert ucd.parse_efts_total({"hits": {}}) is None
    assert ucd.parse_efts_total({}) is None


RAMP_CSV = """date_month,series,adoption_rate_pct,mom_change_pp,yoy_change_pp
2026-04-01,Ramp AI Index,53.10,0.60,13.00
2026-04-01,U.S. Census BTOS estimate,19.80,0.30,
2026-05-01,Ramp AI Index,54.17,1.07,12.80
2026-05-01,U.S. Census BTOS estimate,20.05,0.25,
2026-06-01,Ramp AI Index,54.95,0.78,12.23
2026-06-01,U.S. Census BTOS estimate,20.6,0.55,
"""


def test_parse_ramp_csv_headline_and_contrast_series():
    out = ucd.parse_ramp_csv(RAMP_CSV)
    assert out["asof"] == "2026-06"
    assert out["adoption_pct"] == 55.0
    assert out["mom_pp"] == 0.8
    assert out["yoy_pp"] == 12.2
    assert out["btos_pct"] == 20.6
    assert out["btos_asof"] == "2026-06"
    assert out["series"][-1] == ["2026-06", 55.0]
    assert [ym for ym, _ in out["series"]] == ["2026-04", "2026-05", "2026-06"]


def test_parse_ramp_csv_series_tail_capped():
    rows = ["date_month,series,adoption_rate_pct,mom_change_pp,yoy_change_pp"]
    for m in range(1, 13):
        rows.append(f"2025-{m:02d}-01,Ramp AI Index,{40 + m}.0,0.5,10.0")
    out = ucd.parse_ramp_csv("\n".join(rows), keep=6)
    assert len(out["series"]) == 6
    assert out["series"][-1] == ["2025-12", 52.0]
    assert out["btos_pct"] is None


def test_parse_ramp_csv_garbage_is_none():
    assert ucd.parse_ramp_csv("not,a,ramp\n1,2,3\n") is None
    assert ucd.parse_ramp_csv("") is None


AEI_META = {
    "lastModified": "2026-06-26T23:21:00.000Z",
    "siblings": [
        {"rfilename": "README.md"},
        {"rfilename": "release_2025_02_10/automation_vs_augmentation.csv"},
        {"rfilename": "release_2025_09_15/data.csv"},
        {"rfilename": "release_2025_03_27/README.md"},
    ],
}


def test_parse_aei_latest_release_and_modified():
    out = ucd.parse_aei(AEI_META)
    assert out["latest_release"] == "2025-09-15"
    assert out["last_modified"] == "2026-06-26"


def test_parse_aei_no_releases():
    out = ucd.parse_aei({"lastModified": "2026-06-26T23:21:00.000Z", "siblings": []})
    assert out["latest_release"] is None


def test_snapshot_row_flattens_payload():
    payload = {
        "updated": "2026-07-19T12:00:00Z",
        "tsmc": {"asof": "2026-06", "rev_ntd_b": 442.7, "yoy_pct": 67.9},
        "ramp": {"asof": "2026-06", "adoption_pct": 55.0},
        "issuance": {"cur": {"debt": 9, "s1_ai": 4, "formd_ai": 8}},
    }
    row = ucd.snapshot_row(payload)
    assert row == ["2026-07-19T12:00:00Z", 442.7, 67.9, 55.0, 9, 4, 8]


def test_snapshot_row_tolerates_missing_blocks():
    row = ucd.snapshot_row({"updated": "2026-07-19T12:00:00Z"})
    assert row[0] == "2026-07-19T12:00:00Z"
    assert row[1:] == ["", "", "", "", "", ""]


def test_append_snapshot_creates_header_then_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(ucd, "SNAP", tmp_path / "capex-snapshots.csv")
    payload = {"updated": "2026-07-19T12:00:00Z",
               "tsmc": {"rev_ntd_b": 442.7, "yoy_pct": 67.9},
               "ramp": {"adoption_pct": 55.0},
               "issuance": {"cur": {"debt": 29, "s1_ai": 391, "formd_ai": 8}}}
    ucd.append_snapshot(payload)
    ucd.append_snapshot(payload)
    lines = (tmp_path / "capex-snapshots.csv").read_text().splitlines()
    assert lines[0] == ("updated,tsmc_rev_ntd_b,tsmc_yoy_pct,"
                       "ramp_adoption_pct,debt_90d,s1_ai_90d,formd_ai_90d")
    assert len(lines) == 3 and lines[1] == lines[2]
    assert lines[1] == "2026-07-19T12:00:00Z,442.7,67.9,55.0,29,391,8"


def test_refresh_survives_failing_fetchers_and_writes_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ucd, "OUT", tmp_path / "capex-data.json")
    monkeypatch.setattr(ucd, "SNAP", tmp_path / "capex-snapshots.csv")
    monkeypatch.setattr(ucd, "fetch_tsmc", lambda: {"asof": "2026-06", "rev_ntd_b": 442.7})
    monkeypatch.setattr(ucd, "fetch_issuance", lambda: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(ucd, "fetch_ramp", lambda: None)
    monkeypatch.setattr(ucd, "fetch_aei", lambda: {"latest_release": "2026-06-26"})
    monkeypatch.setattr(ucd, "fetch_860m", lambda: None)
    monkeypatch.setattr(ucd, "fetch_capex_gdp", lambda: None)
    monkeypatch.setattr(ucd, "fetch_agents", lambda prev=None: None)
    ucd.refresh()
    import json
    d = json.loads((tmp_path / "capex-data.json").read_text())
    assert d["tsmc"]["rev_ntd_b"] == 442.7
    assert d["issuance"] is None          # failed fetcher -> null, not a crash
    assert d["eia"] is None
    assert d["manual"] == ucd.MANUAL  # structural — MANUAL values are hand-refreshed
    assert "issuance: FAILED down" in capsys.readouterr().err
    assert (tmp_path / "capex-snapshots.csv").exists()


def test_parse_ramp_csv_unordered_rows_pick_latest_month():
    text = ("date_month,series,adoption_rate_pct,mom_change_pp,yoy_change_pp\n"
            "2026-06-01,Ramp AI Index,55.0,0.8,12.2\n"
            "2026-06-01,U.S. Census BTOS estimate,20.6,0.55,\n"
            "2026-05-01,Ramp AI Index,54.2,1.1,12.8\n"
            "2026-05-01,U.S. Census BTOS estimate,20.0,0.25,\n")
    out = ucd.parse_ramp_csv(text)
    assert out["asof"] == "2026-06"
    assert out["btos_asof"] == "2026-06"
    assert out["btos_pct"] == 20.6


def test_parse_tsmc_rows_malformed_revenue_is_none():
    rows = [{"公司代號": "2330", "資料年月": "11506", "營業收入-當月營收": ""}]
    assert ucd.parse_tsmc_rows(rows) is None
    rows[0]["營業收入-當月營收"] = "N/A"
    assert ucd.parse_tsmc_rows(rows) is None


def test_fetch_issuance_carries_none_counts_without_crashing(monkeypatch):
    monkeypatch.setattr(ucd, "efts_count", lambda *a, **k: None)
    out = ucd.fetch_issuance(datetime.date(2026, 7, 19))
    assert out["cur"]["debt"] is None and out["prev"]["s1_ai"] is None


def test_refresh_eia_failure_is_null_not_a_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ucd, "OUT", tmp_path / "capex-data.json")
    monkeypatch.setattr(ucd, "SNAP", tmp_path / "capex-snapshots.csv")
    for n in ("fetch_tsmc", "fetch_issuance", "fetch_ramp", "fetch_aei",
              "fetch_capex_gdp"):
        monkeypatch.setattr(ucd, n, lambda: None)
    monkeypatch.setattr(ucd, "fetch_agents", lambda prev=None: None)
    monkeypatch.setattr(ucd, "fetch_860m", lambda: (_ for _ in ()).throw(OSError("down")))
    ucd.refresh()
    import json
    assert json.loads((tmp_path / "capex-data.json").read_text())["eia"] is None
    assert "eia: FAILED down" in capsys.readouterr().err


def test_refresh_carries_forward_prev_on_failure(tmp_path, monkeypatch):
    out = tmp_path / "capex-data.json"
    import json
    out.write_text(json.dumps({
        "tsmc": {"asof": "2026-05", "rev_ntd_b": 400.0},
        "ramp": {"asof": "2026-05", "adoption_pct": 54.0},
        "issuance": {"cur": {"debt": 20}}, "aei": {"latest_release": "old"},
    }))
    monkeypatch.setattr(ucd, "OUT", out)
    monkeypatch.setattr(ucd, "SNAP", tmp_path / "capex-snapshots.csv")
    monkeypatch.setattr(ucd, "fetch_tsmc", lambda: {"asof": "2026-06", "rev_ntd_b": 442.7})
    monkeypatch.setattr(ucd, "fetch_issuance", lambda: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(ucd, "fetch_ramp", lambda: None)
    monkeypatch.setattr(ucd, "fetch_aei", lambda: None)
    monkeypatch.setattr(ucd, "fetch_860m", lambda: None)
    monkeypatch.setattr(ucd, "fetch_capex_gdp", lambda: None)
    monkeypatch.setattr(ucd, "fetch_agents", lambda prev=None: None)
    ucd.refresh()
    d = json.loads(out.read_text())
    assert d["tsmc"]["rev_ntd_b"] == 442.7          # live value wins
    assert d["issuance"]["cur"]["debt"] == 20        # failed -> last good carried
    assert d["ramp"]["adoption_pct"] == 54.0         # None -> last good carried
    assert d["aei"]["latest_release"] == "old"


def test_refresh_skips_snapshot_when_all_feeds_down(tmp_path, monkeypatch):
    monkeypatch.setattr(ucd, "OUT", tmp_path / "capex-data.json")
    monkeypatch.setattr(ucd, "SNAP", tmp_path / "capex-snapshots.csv")
    for n in ("fetch_tsmc", "fetch_issuance", "fetch_ramp", "fetch_aei",
              "fetch_860m", "fetch_capex_gdp"):
        monkeypatch.setattr(ucd, n, lambda: None)
    monkeypatch.setattr(ucd, "fetch_agents", lambda prev=None: None)
    ucd.refresh()
    assert not (tmp_path / "capex-snapshots.csv").exists()  # no blank history row


def test_every_worker_data_path_is_run_worker_first():
    """Guard the class of bug the red team caught: a DATA_FILES path missing from
    wrangler run_worker_first serves the stale bundled asset, not the live R2 copy."""
    import json
    import re
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.js").read_text()
    block = re.search(r"const DATA_FILES\s*=\s*\{(.*?)\};", worker, re.S).group(1)
    data_paths = set(re.findall(r'"(/[^"]+)":', block))
    wrangler_raw = (root / "wrangler.jsonc").read_text()
    wrangler = json.loads(re.sub(r"//[^\n]*", "", wrangler_raw))
    rwf = set(wrangler["assets"]["run_worker_first"])
    missing = data_paths - rwf
    assert not missing, f"DATA_FILES paths absent from run_worker_first: {missing}"


def test_every_worker_data_path_is_uploaded_to_r2():
    """The third list. run_worker_first only routes the request; if refresh.yml never
    puts the file in the bucket, every request misses R2 and falls back to the bundled
    asset, which is the same freeze in a different disguise."""
    import re
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.js").read_text()
    block = re.search(r"const DATA_FILES\s*=\s*\{(.*?)\};", worker, re.S).group(1)
    keys = set(re.findall(r'key:\s*"([^"]+)"', block))
    workflow = (root / ".github/workflows/refresh.yml").read_text()
    uploaded = set(re.findall(r'^\s*put\s+(\S+)\s', workflow, re.M))
    missing = keys - uploaded
    assert not missing, f"DATA_FILES keys never uploaded to R2 by refresh.yml: {missing}"


def test_every_page_fetched_data_file_is_live_served():
    """Any same-origin data file a page fetches at runtime has to come off the R2 path,
    or the panel silently freezes at whatever was bundled on the last deploy. This is
    how china-data.json served 6-day-old Vercel/Ollama numbers while the batch job was
    refreshing it on time every 30 minutes."""
    import re
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.js").read_text()
    block = re.search(r"const DATA_FILES\s*=\s*\{(.*?)\};", worker, re.S).group(1)
    keys = set(re.findall(r'key:\s*"([^"]+)"', block))
    fetched = set()
    for page in (root / "omen").glob("*.html"):
        fetched |= set(re.findall(
            r'(?:fetch|jget)\(\s*"([a-z0-9-]+\.(?:json|csv))"', page.read_text()))
    missing = fetched - keys
    assert not missing, f"pages fetch data files that are not live-served: {missing}"


def _cron_covered_hours(crons):
    """(day-of-week, hour) pairs that at least one cron expression fires in."""
    def expand(field, lo, hi):
        out = set()
        for part in field.split(","):
            step = 1
            if "/" in part:
                part, raw = part.split("/")
                step = int(raw)
            if part == "*":
                start, end = lo, hi
            elif "-" in part:
                start, end = (int(x) for x in part.split("-"))
            else:
                start = end = int(part)
            out |= set(range(start, end + 1, step))
        return out

    covered = set()
    for cron in crons:
        _minute, hour, _dom, _month, dow = cron.split()
        for d in expand(dow, 0, 6):
            for h in expand(hour, 0, 23):
                covered.add((d % 7, h))
    return covered


def test_refresh_schedule_has_no_uncovered_hours():
    """Every hour of every day needs a trigger. The original pair of expressions left
    Sat/Sun 13:00–21:59 UTC with none, so the China panels froze for ~9h each weekend
    afternoon while the freshness strip still claimed 'live'."""
    import re
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/refresh.yml").read_text()
    crons = re.findall(r'^\s*- cron:\s*"([^"]+)"', workflow, re.M)
    assert crons, "no cron schedule found in refresh.yml"
    gaps = {(d, h) for d in range(7) for h in range(24)} - _cron_covered_hours(crons)
    assert not gaps, f"hours with no refresh trigger (dow, hour UTC): {sorted(gaps)}"


# ---------- EIA-860M monthly workbook (keyless) ----------

def _xlsx(sheets):
    """Minimal .xlsx blob: {sheet name: [[cell, ...], ...]}. Strings go through a real
    sharedStrings table so the fixture exercises the same path as EIA's workbook."""
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

    parts = {}
    names = list(sheets)
    for i, name in enumerate(names, start=1):
        xml = ['<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for r, row in enumerate(sheets[name], start=1):
            xml.append(f'<row r="{r}">')
            for c, val in enumerate(row):
                if val is None:
                    continue                      # a genuinely absent cell, as Excel writes it
                ref = f"{col(c)}{r}"
                if isinstance(val, (int, float)):
                    xml.append(f'<c r="{ref}"><v>{val}</v></c>')
                else:
                    xml.append(f'<c r="{ref}" t="s"><v>{sid(val)}</v></c>')
            xml.append("</row>")
        xml.append("</sheetData></worksheet>")
        parts[f"xl/worksheets/sheet{i}.xml"] = "".join(xml)

    wb = ['<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    rels = ['<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
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


_860M_HDR = ["Entity ID", "Plant Name", "Nameplate Capacity (MW)", "Status"]


def _860m_blob():
    return _xlsx({
        "Operating": [
            ["Inventory of Operating Generators as of April 2026"], [],
            _860M_HDR,
            ["1", "Alpha", "1000", "(OP) Operating"],
            ["2", "Beta", "500", "(OP) Operating"],
            ["3", "Gamma", "250", "(SB) Standby"],
        ],
        "Planned": [
            ["Inventory of Planned Generators as of April 2026"], [],
            _860M_HDR,
            ["4", "Delta", "300", "(P) Planned for installation, but regulatory approvals not initiated"],
            ["5", "Epsilon", "200", "(L) Regulatory approvals pending"],
            ["6", "Zeta", "120", "(U) Under construction, less than or equal to 50 percent complete"],
            ["7", "Eta", "80", "(V) Under construction, more than 50 percent complete"],
        ],
        "Canceled or Postponed": [
            ["Inventory of Canceled or Indefinitely Postponed Projects as of April 2026"], [],
            _860M_HDR,
            ["8", "Theta", "400", ""],
        ],
    })


def test_parse_860m_groups_nameplate_by_status_across_sheets():
    out = ucd.parse_860m(_860m_blob())
    assert out["asof"] == "2026-04"
    assert out["operating_gw"] == 1.5      # standby is not operating capacity
    assert out["planned_gw"] == 0.5
    assert out["under_construction_gw"] == 0.2
    assert out["canceled_gw"] == 0.4


def test_parse_860m_canceled_sheet_is_the_stranded_pipeline():
    """The 'Canceled or Postponed' sheet is thesis v's own metric in federal data and
    has no equivalent in the API route this replaced — announced capacity that stopped."""
    out = ucd.parse_860m(_860m_blob())
    assert out["canceled_gw"] == 0.4


def test_parse_860m_absent_status_group_is_none_not_zero():
    blob = _xlsx({"Operating": [
        ["Inventory of Operating Generators as of April 2026"], [],
        _860M_HDR, ["1", "Alpha", "1000", "(OP) Operating"]]})
    out = ucd.parse_860m(blob)
    assert out["operating_gw"] == 1.0
    assert out["planned_gw"] is None
    assert out["under_construction_gw"] is None
    assert out["canceled_gw"] is None


def test_parse_860m_tolerates_absent_cells_in_a_row():
    """Excel omits empty cells entirely, so column position has to come from the cell
    reference, not from counting siblings — otherwise Status shifts left and every
    row lands in the wrong bucket."""
    blob = _xlsx({"Planned": [
        ["Inventory of Planned Generators as of April 2026"], [],
        _860M_HDR,
        ["9", None, "1500", "(V) Under construction, more than 50 percent complete"]]})
    assert ucd.parse_860m(blob)["under_construction_gw"] == 1.5


def test_parse_860m_no_recognisable_sheet_is_none():
    assert ucd.parse_860m(_xlsx({"Notes": [["nothing here"]]})) is None


def test_status_code_extracts_parenthesised_code():
    assert ucd.status_code("(V) Under construction, more than 50 percent complete") == "V"
    assert ucd.status_code("(OP) Operating") == "OP"
    assert ucd.status_code("") is None
    assert ucd.status_code(None) is None


def test_sheet_asof_reads_the_title_row():
    assert ucd.sheet_asof("Inventory of Planned Generators as of April 2026") == "2026-04"
    assert ucd.sheet_asof("Inventory of Operating Generators as of December 2025") == "2025-12"
    assert ucd.sheet_asof("something else") is None


def test_eia_860m_urls_walk_back_from_current_month():
    urls = ucd.eia_860m_urls(datetime.date(2026, 8, 2))
    assert urls[0].endswith("/xls/august_generator2026.xlsx")
    assert "/xls/july_generator2026.xlsx" in urls[1]
    assert any("/archive/xls/" in u for u in urls)
    # the release rolls over a year boundary without asking for month 0
    jan = ucd.eia_860m_urls(datetime.date(2026, 1, 5))
    assert "/xls/december_generator2025.xlsx" in jan[1]


def test_fetch_860m_skips_html_redirect_pages(monkeypatch):
    """A missing month redirects to an HTML page that answers 200. Taking the first
    200 would parse a web page as a workbook and blank the panel."""
    blob = _860m_blob()
    seen = []
    def fake(url, **kw):
        seen.append(url)
        return b"<!DOCTYPE html><html>404</html>" if len(seen) < 3 else blob
    monkeypatch.setattr(ucd, "get_bytes", fake)
    out = ucd.fetch_860m(ref=datetime.date(2026, 8, 2))
    assert out["operating_gw"] == 1.5
    assert len(seen) == 3


def test_fetch_860m_all_candidates_missing_is_none(monkeypatch):
    monkeypatch.setattr(ucd, "get_bytes", lambda url, **kw: b"<html>nope</html>")
    assert ucd.fetch_860m(ref=datetime.date(2026, 8, 2)) is None


# ---------- Census C30 data-center construction + capex/GDP ----------

def _c30_blob():
    return _xlsx({"Sheet1": [
        ["Value of Private Construction Put in Place - Seasonally Adjusted Annual Rate"],
        [], [], [], [],
        ["Type of Construction:", "May\n2026p", "Apr\n2026r", "Mar\n2026r",
         "Feb\n2026r", "Jan\n2026r", "May\n2025r"],
        ["        Office", "107558", "107334", "107164", "106772", "105913", "102760"],
        ["            Data center", "59307", "58977", "58121", "57361", "56211", "48210"],
        ["            Financial", "9000", "8900", "8800", "8700", "8600", "8500"],
    ]})


def test_parse_c30_reads_the_data_center_line():
    out = ucd.parse_c30(_c30_blob())
    assert out["asof"] == "2026-05"
    assert out["dc_saar_musd"] == 59307.0
    assert out["yoy_pct"] == 23.0          # computed from the year-ago column, not the rounded one


def test_parse_c30_ignores_the_office_parent_row():
    """'Data center' is nested under 'Office'; matching loosely would pick the parent
    and overstate the series by ~1.8x."""
    assert ucd.parse_c30(_c30_blob())["dc_saar_musd"] == 59307.0


def test_parse_c30_without_year_ago_column_has_no_yoy():
    blob = _xlsx({"Sheet1": [
        ["Value of Private Construction Put in Place"], [], [], [], [],
        ["Type of Construction:", "May\n2026p"],
        ["            Data center", "59307"]]})
    out = ucd.parse_c30(blob)
    assert out["dc_saar_musd"] == 59307.0
    assert out["yoy_pct"] is None


def test_parse_c30_missing_row_is_none():
    blob = _xlsx({"Sheet1": [["x"], [], [], [], [],
                             ["Type of Construction:", "May\n2026p"],
                             ["            Financial", "9000"]]})
    assert ucd.parse_c30(blob) is None


def test_c30_month_parses_the_stacked_header():
    assert ucd.c30_month("May\n2026p") == "2026-05"
    assert ucd.c30_month("Apr\n2026r") == "2026-04"
    assert ucd.c30_month("Dec\n2025") == "2025-12"
    assert ucd.c30_month("Type of Construction:") is None


def test_capex_gdp_pct_uses_the_definition_the_page_states():
    """Data-center construction (SAAR, $M) plus computer & peripheral equipment
    investment (SAAR, $B), over nominal GDP (SAAR, $B)."""
    assert ucd.capex_gdp_pct(59307.0, 406.4, 32475.2) == 1.43


def test_capex_gdp_pct_missing_input_is_none():
    assert ucd.capex_gdp_pct(None, 406.4, 32475.2) is None
    assert ucd.capex_gdp_pct(59307.0, None, 32475.2) is None
    assert ucd.capex_gdp_pct(59307.0, 406.4, 0) is None


def test_parse_fred_last_takes_the_final_observation():
    csv = "observation_date,GDP\n2026-01-01,31865.721\n2026-04-01,32475.210\n"
    assert ucd.parse_fred_last(csv) == {"d": "2026-04-01", "v": 32475.21}


def test_parse_fred_last_skips_missing_observations():
    csv = "observation_date,X\n2026-01-01,1.0\n2026-04-01,.\n"
    assert ucd.parse_fred_last(csv) == {"d": "2026-01-01", "v": 1.0}


def test_parse_fred_last_empty_is_none():
    assert ucd.parse_fred_last("observation_date,X\n") is None


# ---------- agent-stack installs ----------

def test_parse_npm_point_reads_downloads():
    assert ucd.parse_npm_point({"downloads": 412345, "package": "x"}) == 412345
    assert ucd.parse_npm_point({"downloads": "9"}) == 9
    assert ucd.parse_npm_point({"downloads": -1}) is None
    assert ucd.parse_npm_point({"error": "not found"}) is None
    assert ucd.parse_npm_point(None) is None


def test_parse_pypi_recent_reads_last_week():
    assert ucd.parse_pypi_recent({"data": {"last_week": 71234}}) == 71234
    assert ucd.parse_pypi_recent({"data": {}}) is None
    assert ucd.parse_pypi_recent({}) is None
    assert ucd.parse_pypi_recent(None) is None


def test_merge_agent_series_dedupes_same_day_and_caps():
    prev = [["2026-08-01", 100], ["2026-08-02", 110]]
    out = ucd.merge_agent_series(prev, "2026-08-02", 115)
    assert out == [["2026-08-01", 100], ["2026-08-02", 115]]  # same-day point replaced
    out = ucd.merge_agent_series(prev, "2026-08-03", 120, cap=2)
    assert out == [["2026-08-02", 110], ["2026-08-03", 120]]  # capped, oldest dropped
    assert ucd.merge_agent_series(None, "2026-08-03", 120) == [["2026-08-03", 120]]
    # malformed rows in a hand-edited file are dropped, not crashed on
    assert ucd.merge_agent_series([["2026-08-01"], "junk", ["2026-08-02", 5]],
                                  "2026-08-03", 6) == [["2026-08-02", 5], ["2026-08-03", 6]]


def test_fetch_agents_none_when_npm_is_down(monkeypatch):
    monkeypatch.setattr(ucd, "jget", lambda url, *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert ucd.fetch_agents({"series": [["2026-08-01", 100]]}) is None


def test_fetch_agents_totals_npm_and_extends_series(monkeypatch):
    def fake_jget(url, *a, **k):
        if url.startswith(ucd.NPM_POINT):
            return {"downloads": 100}
        return {"data": {"last_week": 7}}
    monkeypatch.setattr(ucd, "jget", fake_jget)
    out = ucd.fetch_agents({"series": [["2000-01-01", 1]]})
    assert out["npm_total_wk"] == 100 * len(ucd.NPM_AGENT_PKGS)
    assert all(v == 7 for v in out["pypi"].values())
    assert out["series"][0] == ["2000-01-01", 1]           # prior history kept
    assert out["series"][-1][1] == out["npm_total_wk"]     # today appended
