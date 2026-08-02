#!/usr/bin/env python3
"""Refresh capex-data.json for the AI CapEx live tape (ai-capex.html).

Stdlib only, same pattern as update-china-data.py. Feeds the "live tape"
section of the otherwise hand-curated fundamentals page:

  - TSMC monthly revenue (TWSE OpenAPI, keyless)  : realized AI-hardware demand
  - Issuance velocity (SEC EDGAR full-text search): FWP/424B debt events by the
    AI-capex issuers, S-1s and Form Ds mentioning "artificial intelligence"
  - Ramp AI Index (public CSV)                    : paid AI adoption by US firms
  - Anthropic Economic Index (HF dataset meta)    : release freshness only
  - EIA-860M generator pipeline (monthly XLSX)    : operating vs planned vs under
    construction vs canceled nameplate GW; keyless
  - Census C30 + FRED (keyless)                   : data-center construction and
    computer-equipment investment as a share of nominal GDP

Not automated, kept in MANUAL below (no free machine-readable source):
  - Korea 20-day semiconductor exports (customs.go.kr press releases)
  - Taiwan MOEA export orders
  - PJM capacity-auction clears, LBNL interconnection-queue totals
  - Anthropic Economic Index headline split (freshness is live, numbers manual)
FINRA TRACE single-name spreads stay manual: the free Query API tier only
carries market aggregates, not the per-CUSIP prints the credit panel needs.

Usage:
  python3 update-capex-data.py                # one shot
  python3 update-capex-data.py --watch 21600  # 6h loop
"""
import csv
import datetime
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent
OUT = HERE / "capex-data.json"
SNAP = HERE / "capex-snapshots.csv"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) omen-capex-tape/1.0"}
SEC_UA = {"User-Agent": "Mikhail Blank blank.mikhail@gmail.com"}

TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TSMC_CODE = "2330"

EFTS = "https://efts.sec.gov/LATEST/search-index"
# the AI-capex debt issuers the thesis-i panel tracks: big-5 + CoreWeave
DEBT_CIKS = ["0000789019", "0001652044", "0001018724",   # MSFT GOOGL AMZN
             "0001326801", "0001341439", "0001769628"]   # META ORCL CRWV
DEBT_FORMS = "FWP,424B2,424B5"
EFTS_WINDOW_DAYS = 90

RAMP_CSV_URL = "https://ramp.com/data/ai-index/adoptionHeadline.csv"
RAMP_SERIES = "Ramp AI Index"
RAMP_BTOS = "U.S. Census BTOS estimate"

AEI_META_URL = "https://huggingface.co/api/datasets/Anthropic/EconomicIndex"

# EIA-860M monthly workbook. This replaced the api.eia.gov v2 route, which needed a
# key AND served the operating inventory only — so the two rows the stranded-GW thesis
# actually needs (planned, under construction) rendered "–" no matter what. The
# published workbook carries Operating, Planned and "Canceled or Postponed" sheets,
# needs no key, and the canceled sheet is thesis v's metric in federal data.
EIA_860M_BASE = "https://www.eia.gov/electricity/data/eia860m"
EIA_860M_LOOKBACK = 6          # months to walk back looking for the newest release
EIA_STATUS_GROUPS = {
    "operating_gw": {"OP"},
    "planned_gw": {"P", "L", "T"},
    "under_construction_gw": {"U", "V", "TS"},
}
EIA_CANCELED_SHEET = "Canceled or Postponed"
EIA_MW_COL = "Nameplate Capacity (MW)"
EIA_STATUS_COL = "Status"

# Census "Value of Private Construction Put in Place", seasonally adjusted annual rate.
# The workbook carries an explicit "Data center" line nested under Office.
C30_URL = "https://www.census.gov/construction/c30/xlsx/privsa.xlsx"
C30_ROW = "Data center"
C30_HEADER_CELL = "Type of Construction:"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
# FRED tarpits browser-spoofing UAs on this endpoint; an honest UA responds instantly
FRED_UA = {"User-Agent": "ai-crash-monitor/1.0 (blank.mikhail@gmail.com)"}
FRED_COMPUTERS = "B935RC1Q027SBEA"   # computers & peripheral equipment investment, SAAR $B
FRED_GDP = "GDP"                     # nominal GDP, SAAR $B

# fields with no machine-readable source: update by hand when re-verified
MANUAL = {
    "korea": {"chip_exports_yoy_pct": None, "asof": None,
              "note": "Korea Customs 20-day export release (~1st/11th/21st); "
                      "no keyless API - update by hand from the release coverage.",
              "src": "https://www.customs.go.kr"},
    "moea_orders": {"asof": None,
                    "note": "Taiwan MOEA export orders - manual; stats site blocks bots.",
                    "src": "https://www.moea.gov.tw"},
    "queues": {"lbnl_active_gw": 2600, "asof": "2023-12",
               "note": "LBNL Queued Up: active US interconnection requests, all fuels.",
               "src": "https://emp.lbl.gov/queues"},
    "pjm_capacity_auction": {"clears_usd_mw_day": {"2025/26": 269.92, "2026/27": 329.17},
                             "asof": "2025-07",
                             "note": "PJM base residual auction clearing prices.",
                             "src": "https://www.pjm.com"},
    "aei_headline": {"aug_pct": 57, "auto_pct": 43, "asof": "2025-02",
                     "note": "Anthropic Economic Index first report: augmentation vs "
                             "automation share of Claude usage."},
}


def get(url, timeout=30, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def get_bytes(url, timeout=90, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def jget(url, timeout=30, headers=None):
    return json.loads(get(url, timeout, headers))


def rnd(x, nd=1):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


# ---------- TSMC (TWSE OpenAPI) ----------

def roc_ym(s):
    """ROC calendar 'YYYMM' -> ISO 'YYYY-MM' (ROC year + 1911)."""
    m = re.fullmatch(r"(\d{2,3})(\d{2})", s or "")
    if not m:
        return None
    return f"{int(m.group(1)) + 1911}-{m.group(2)}"


def parse_tsmc_rows(rows):
    row = next((r for r in rows if r.get("公司代號") == TSMC_CODE), None)
    if not row:
        return None
    raw = rnd(row.get("營業收入-當月營收"), 6)  # thousand NTD
    rev = rnd(raw / 1e6, 1) if raw else None    # -> B NTD
    if not rev:
        return None
    return {"asof": roc_ym(row.get("資料年月")),
            "rev_ntd_b": rev,
            "mom_pct": rnd(row.get("營業收入-上月比較增減(%)")),
            "yoy_pct": rnd(row.get("營業收入-去年同月增減(%)")),
            "ytd_yoy_pct": rnd(row.get("累計營業收入-前期比較增減(%)")),
            "note": row.get("備註", "")}


def fetch_tsmc():
    return parse_tsmc_rows(jget(TWSE_REVENUE_URL, headers={**UA, "Accept": "application/json"}))


# ---------- Issuance velocity (EDGAR full-text search) ----------

def efts_windows(today, days=EFTS_WINDOW_DAYS):
    cur_end = today
    cur_start = today - datetime.timedelta(days=days - 1)
    prev_end = cur_start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=days - 1)
    return ((cur_start.isoformat(), cur_end.isoformat()),
            (prev_start.isoformat(), prev_end.isoformat()))


def parse_efts_total(payload):
    try:
        return int(payload["hits"]["total"]["value"])
    except (KeyError, TypeError, ValueError):
        return None


def efts_count(window, q="", forms=None, ciks=None):
    params = {"q": q, "startdt": window[0], "enddt": window[1]}
    if forms:
        params["forms"] = forms
    if ciks:
        params["ciks"] = ",".join(ciks)
    url = f"{EFTS}?{urllib.parse.urlencode(params)}"
    n = parse_efts_total(jget(url, headers=SEC_UA))
    time.sleep(0.15)  # stay far under SEC's 10 req/s
    return n


def fetch_issuance(today=None):
    cur, prev = efts_windows(today or datetime.date.today())
    out = {"days": EFTS_WINDOW_DAYS}
    for label, window in (("cur", cur), ("prev", prev)):
        out[label] = {
            "from": window[0], "to": window[1],
            "debt": efts_count(window, forms=DEBT_FORMS, ciks=DEBT_CIKS),
            "s1_ai": efts_count(window, q='"artificial intelligence"', forms="S-1"),
            "formd_ai": efts_count(window, q='"artificial intelligence"', forms="D"),
        }
    return out


# ---------- Ramp AI Index ----------

def parse_ramp_csv(text, keep=24):
    rows = list(csv.DictReader(io.StringIO(text)))
    series, btos = [], []
    for r in rows:
        pct = rnd(r.get("adoption_rate_pct"))
        ym = (r.get("date_month") or "")[:7]
        if pct is None or not re.fullmatch(r"\d{4}-\d{2}", ym):
            continue
        if r.get("series") == RAMP_SERIES:
            series.append((ym, pct, rnd(r.get("mom_change_pp")), rnd(r.get("yoy_change_pp"))))
        elif r.get("series") == RAMP_BTOS:
            btos.append((ym, pct))
    if not series:
        return None
    series.sort()
    btos.sort()
    ym, pct, mom, yoy = series[-1]
    return {"asof": ym, "adoption_pct": pct, "mom_pp": mom, "yoy_pp": yoy,
            "btos_pct": btos[-1][1] if btos else None,
            "btos_asof": btos[-1][0] if btos else None,
            "series": [[m, p] for m, p, _, _ in series[-keep:]]}


def fetch_ramp():
    return parse_ramp_csv(get(RAMP_CSV_URL))


# ---------- Anthropic Economic Index ----------

def parse_aei(meta):
    releases = set()
    for s in meta.get("siblings", []):
        m = re.match(r"release_(\d{4})_(\d{2})_(\d{2})/", s.get("rfilename", ""))
        if m:
            releases.add("-".join(m.groups()))
    return {"last_modified": (meta.get("lastModified") or "")[:10] or None,
            "latest_release": max(releases) if releases else None}


def fetch_aei():
    return parse_aei(jget(AEI_META_URL))


# ---------- EIA-860M generator pipeline (keyless monthly workbook) ----------

XL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XL_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
XL_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]


def xlsx_sheets(zf):
    """{sheet name: archive path}. The name->path mapping runs through the workbook
    rels, not sheet order: sheetN.xml is not guaranteed to be the Nth tab."""
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels")).iter(XL_PKG + "Relationship")}
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    out = {}
    for s in wb.iter(XL + "sheet"):
        target = rels.get(s.get(XL_RID))
        if target:
            out[s.get("name")] = "xl/" + target.lstrip("/")
    return out


def xlsx_strings(zf):
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(XL + "t")) for si in root]


def col_index(ref):
    """'AB12' -> 27. Cell position has to come from the reference: Excel omits empty
    cells entirely, so counting siblings shifts every later column left."""
    n = 0
    for ch in ref or "":
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def xlsx_rows(zf, path, shared):
    """Stream one sheet as lists of cell values, positioned by cell reference."""
    with zf.open(path) as f:
        for _event, el in ET.iterparse(f, events=("end",)):
            if el.tag != XL + "row":
                continue
            row = []
            for c in el:
                v = c.find(XL + "v")
                if v is None or v.text is None:
                    continue
                val = shared[int(v.text)] if c.get("t") == "s" else v.text
                i = col_index(c.get("r"))
                if i < 0:
                    continue
                row += [None] * (i + 1 - len(row))
                row[i] = val
            yield row
            el.clear()


def status_code(text):
    """'(V) Under construction, more than 50 percent complete' -> 'V'."""
    m = re.match(r"\s*\(([A-Z]{1,2})\)", text or "")
    return m.group(1) if m else None


def sheet_asof(title):
    """'Inventory of Planned Generators as of April 2026' -> '2026-04'."""
    m = re.search(r"as of ([A-Za-z]+)\s+(\d{4})", title or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}"


def _header_map(row):
    return {c: i for i, c in enumerate(row) if c} if row and EIA_MW_COL in row else None


def parse_860m(blob):
    """Nameplate GW by construction status from the EIA-860M workbook.

    None, not 0.0, for a group that matched no rows: an absent status group is
    unknown, and a false 0 on the planned line would read as "no pipeline" —
    the opposite of what the stranded-GW thesis is watching for."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
        sheets = xlsx_sheets(zf)
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return None
    shared = xlsx_strings(zf)
    sums = {k: None for k in EIA_STATUS_GROUPS}
    canceled, asof, seen = None, None, False
    for name, path in sheets.items():
        if name not in set(EIA_STATUS_GROUPS) | {"Operating", "Planned", EIA_CANCELED_SHEET}:
            continue
        hdr = None
        for row in xlsx_rows(zf, path, shared):
            if not row:
                continue
            if asof is None:
                asof = sheet_asof(row[0] if isinstance(row[0], str) else "")
            if hdr is None:
                hdr = _header_map(row)
                continue
            seen = True
            try:
                mw = float(row[hdr[EIA_MW_COL]])
            except (IndexError, TypeError, ValueError):
                continue
            if name == EIA_CANCELED_SHEET:
                canceled = (canceled or 0.0) + mw
                continue
            si = hdr.get(EIA_STATUS_COL)
            code = status_code(row[si] if si is not None and si < len(row) else None)
            for key, codes in EIA_STATUS_GROUPS.items():
                if code in codes:
                    sums[key] = (sums[key] or 0.0) + mw
    if not seen:
        return None
    out = {k: (rnd(v / 1000, 1) if v is not None else None) for k, v in sums.items()}
    out["canceled_gw"] = rnd(canceled / 1000, 1) if canceled is not None else None
    out["asof"] = asof
    return out


def eia_860m_urls(ref=None):
    """Candidate workbook URLs, most likely first. The current release sits under
    /xls/ and older months move to /archive/xls/, and neither path announces which
    month is current — so /xls/ is swept newest-first (that is where a hit almost
    always is, 860M lagging ~2 months), then the archive as the fallback."""
    d = ref or datetime.date.today()
    stems = []
    for back in range(EIA_860M_LOOKBACK):
        m = d.month - 1 - back
        stems.append(f"{MONTHS[m % 12]}_generator{d.year + m // 12}.xlsx")
    return ([f"{EIA_860M_BASE}/xls/{s}" for s in stems]
            + [f"{EIA_860M_BASE}/archive/xls/{s}" for s in stems])


def fetch_860m(ref=None):
    """First candidate that is actually a workbook wins.

    A month that is not published redirects to an HTML page served with 200, so the
    status code proves nothing — parse_860m returning None on non-zip content is the
    real gate."""
    for url in eia_860m_urls(ref):
        try:
            out = parse_860m(get_bytes(url))
        except Exception:
            continue
        if out:
            out["src"] = url
            return out
    return None


# ---------- capex vs GDP (Census C30 + FRED, both keyless) ----------

def c30_month(text):
    """'May\n2026p' -> '2026-05'. The revision/preliminary suffix is not part of it."""
    m = re.match(r"\s*([A-Za-z]{3,})\s*\n?\s*(\d{4})[pr]?\s*$", text or "")
    if not m:
        return None
    name = m.group(1).lower()
    hit = next((i for i, mo in enumerate(MONTHS) if mo.startswith(name[:3])), None)
    return f"{m.group(2)}-{hit + 1:02d}" if hit is not None else None


def parse_c30(blob):
    """Data-center construction spending (SAAR, $M) from the Census C30 workbook.

    Matched on the exact stripped label: 'Data center' is nested under 'Office', and
    a loose match picks the parent row and overstates the series by ~1.8x."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
        sheets = xlsx_sheets(zf)
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return None
    shared = xlsx_strings(zf)
    for path in sheets.values():
        months, row = None, None
        for cells in xlsx_rows(zf, path, shared):
            if not cells or not isinstance(cells[0], str):
                continue
            if months is None and cells[0].strip() == C30_HEADER_CELL:
                months = {i: c30_month(c) for i, c in enumerate(cells) if i and c30_month(c)}
            elif months is not None and cells[0].strip() == C30_ROW:
                row = cells
                break
        if not months or not row:
            continue
        latest = max(months, key=lambda i: months[i])
        try:
            val = float(row[latest])
        except (IndexError, TypeError, ValueError):
            continue
        asof = months[latest]
        prior = f"{int(asof[:4]) - 1}{asof[4:]}"
        back = next((i for i, ym in months.items() if ym == prior), None)
        yoy = None
        try:
            if back is not None and float(row[back]):
                yoy = rnd((val / float(row[back]) - 1) * 100, 1)
        except (IndexError, TypeError, ValueError):
            yoy = None
        return {"dc_saar_musd": val, "asof": asof, "yoy_pct": yoy}
    return None


def parse_fred_last(text):
    """Final non-missing observation of a fredgraph.csv series."""
    out = None
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[0] or ""):
            continue
        try:
            out = {"d": row[0], "v": float(row[1])}
        except ValueError:
            continue
    return out


def fred_last(series_id):
    return parse_fred_last(get(FRED_CSV + series_id, headers=FRED_UA))


def capex_gdp_pct(dc_saar_musd, computers_saar_b, gdp_b):
    """Data-center construction plus computer-equipment investment, over nominal GDP.

    This is the definition the thesis-iv tile states. It is NOT the big-5-capex/GDP
    ratio the monitor's macro panel carries — that one runs ~0.4pp higher because its
    numerator is five companies' worldwide capex, not US data-center formation."""
    if dc_saar_musd is None or computers_saar_b is None or not gdp_b:
        return None
    return rnd((dc_saar_musd / 1000 + computers_saar_b) / gdp_b * 100, 2)


def fetch_capex_gdp():
    dc = parse_c30(get_bytes(C30_URL))
    comp = fred_last(FRED_COMPUTERS)
    gdp = fred_last(FRED_GDP)
    if not dc or not comp or not gdp:
        return None
    return {"dc_construction_saar_b": rnd(dc["dc_saar_musd"] / 1000, 1),
            "dc_yoy_pct": dc["yoy_pct"],
            "dc_asof": dc["asof"],
            "computers_saar_b": rnd(comp["v"], 1),
            "gdp_saar_b": rnd(gdp["v"], 1),
            "gdp_asof": gdp["d"],
            "pct_gdp": capex_gdp_pct(dc["dc_saar_musd"], comp["v"], gdp["v"])}


# ---------- assembly ----------

def snapshot_row(payload):
    tsmc = payload.get("tsmc") or {}
    ramp = payload.get("ramp") or {}
    cur = (payload.get("issuance") or {}).get("cur") or {}
    blank = lambda v: "" if v is None else v
    return [payload.get("updated"),
            blank(tsmc.get("rev_ntd_b")), blank(tsmc.get("yoy_pct")),
            blank(ramp.get("adoption_pct")),
            blank(cur.get("debt")), blank(cur.get("s1_ai")), blank(cur.get("formd_ai"))]


def append_snapshot(payload):
    new = not SNAP.exists()
    with SNAP.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["updated", "tsmc_rev_ntd_b", "tsmc_yoy_pct",
                        "ramp_adoption_pct", "debt_90d", "s1_ai_90d", "formd_ai_90d"])
        w.writerow(snapshot_row(payload))


def load_prev():
    """Last good capex-data.json, so a transient upstream failure keeps the
    previous value on the page instead of blanking the panel (matches the
    carry-forward convention in update-china-data.py)."""
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {}


def refresh():
    prev = load_prev()
    payload = {"updated": datetime.datetime.now(datetime.timezone.utc)
               .strftime("%Y-%m-%dT%H:%M:%SZ")}
    live_ok = False
    for name, fn in (("tsmc", fetch_tsmc), ("issuance", fetch_issuance),
                     ("ramp", fetch_ramp), ("aei", fetch_aei),
                     ("eia", fetch_860m), ("capex_gdp", fetch_capex_gdp)):
        try:
            payload[name] = fn()
        except Exception as e:
            print(f"  {name}: FAILED {e}", file=sys.stderr)
            payload[name] = None
        if payload[name] is None:
            payload[name] = prev.get(name)  # carry last good value forward
        else:
            live_ok = True
    payload["manual"] = MANUAL
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    # only append a snapshot when at least one live feed refreshed, so a total
    # outage doesn't write a blank-columned row into the durable history
    if live_ok:
        append_snapshot(payload)
    print(f"wrote {OUT.name}: tsmc={bool(payload['tsmc'])} "
          f"issuance={bool(payload['issuance'])} ramp={bool(payload['ramp'])} "
          f"aei={bool(payload['aei'])} eia={bool(payload['eia'])} "
          f"capex_gdp={bool(payload['capex_gdp'])} "
          f"snapshot={'appended' if live_ok else 'skipped (all feeds down)'}")


if __name__ == "__main__":
    if "--watch" in sys.argv:
        every = int(sys.argv[sys.argv.index("--watch") + 1])
        while True:
            refresh()
            time.sleep(every)
    else:
        refresh()
