# 2026-08-06 - China monitor: supply-side panels

Four new panels on `china-ai-monitor.html`, fed by `update-china-data.py`. Motivation: an
Aug-2026 survey of the public US-vs-China dashboards (Artificial Analysis, Epoch AI,
Stanford HAI, CSET ETO, ASPI) found the monitor demand-side complete but blind upstream
of demand. These are the five cleanest-source gaps from that survey, wired in.

## What the page gains

- **Frontier capability gap** (`aa_frontier`): monthly best-AA-Intelligence-Index by lab
  country since 2024, the lag in months between a US model first reaching today's best
  Chinese score and the Chinese frontier getting there (Epoch's us-vs-china-eci statistic
  computed on AA's index), and a near-frontier price ratio - cheapest blended $/M within
  3 index points of each side's frontier. Rides the existing AA Data API call, so it
  costs no extra request; the card stays hidden without `ARTIFICIAL_ANALYSIS_API_KEY`.
- **Compute stock** (`epoch_compute`): country split of H100-equivalent capacity across
  Epoch's GPU-clusters dataset. Note in-panel: coverage is 10-20% of world capacity and
  Chinese systems are anonymized upstream, so the split understates China.
- **Chip supply** (`epoch_chips`): quarterly accelerator output in H100e, US designers
  (NVIDIA/AMD/Google/Amazon) vs Chinese (Huawei/Cambricon), charted as the Chinese
  share line (absolute lines differ ~20x and flatten to zero on a linear axis), plus the
  top Chinese chips and Epoch's ~660k-H100e smuggling estimate as context. Series is
  trimmed to the both-sides-covered window - Chinese estimates lag ~2 quarters, and a
  cn=0 quarter outside that window means "no estimate yet", not "no chips".
- **Notable model releases** (`epoch_models`): releases per quarter by lab country since
  2023 + trailing-12-month totals. Joint US-CN models fit neither line and are dropped;
  the current quarter is excluded from the series (a 5-week quarter plots as a fake
  collapse) but still counts in the trailing-12-month totals.

## Mechanics

- No new data files: all four live as keys inside `china-data.json`, so nothing needed
  the refresh.yml / R2-upload / worker registration treatment, and this PR deliberately
  does not commit a regenerated `china-data.json` - the keys appear on the first
  post-merge refresh run, and every panel renders the standard "appears after the next
  server-side refresh" note until then.
- Epoch CSVs (CC BY 4.0, keyless, up to ~2 MB) are refetched at most every 6 days via
  timestamps in `china-history.json`; between refetches the parsed value is carried
  forward from the previous `china-data.json`, same as every other family.
- Supply-side panels are context, not signals: none of them write into the adoption
  index (`IDX`), and the methodology/caveats footers say so.
- New freshness chip ("Supply-side") dates the Epoch parse and the AA gap series.

## Tests

- 14 new pure-function tests in `test_update_china_data.py` (country/designer
  classification, quarter math, all three Epoch parsers incl. the cn-window trim and
  current-quarter exclusion, AA frontier series/lag/value incl. the blended-price
  fallback and free-tier exclusion, the weekly refetch gate). Full suite: 256 passed.
- Parsers were also validated against the live CSVs (482 clusters, 16 sales quarters,
  1,043 notable models) and the page visually QA'd with a populated preview
  `china-data.json`.

## Coordination note

Written alongside PR #38 (`feat/china-monitor-dataviz`), which touches the same three
files for different reasons (daily metrics history + hero charts). The overlaps are
append-points (end of the test file, docstring, boot()/loadSnap one-liners, footer
lists); whichever lands second rebases with keep-both resolutions.
