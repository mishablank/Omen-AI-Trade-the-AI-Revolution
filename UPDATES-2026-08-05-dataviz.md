# 2026-08-05 – Data-visualization upgrades

The landing page carried the verdict as prose plus one gradient dial – no history
anywhere, even though the data layer already had it (snapshots.csv has a daily row since
2026-07-11, and the CLOB serves per-market price history). This change puts time on the
page and fixes a set of chart-craft defects across the shared toolkit.

## Landing page (index.html)

**The cycle map.** The verdict matrix, drawn as a phase diagram: x the crash-pressure
gauge (band edges 35/55), y the Bull share of the pair (direction edges 45%/55%), the
five verdict states as shaded labeled regions, the last weeks of snapshots as a trail,
today as a pulsing point in its verdict color. The published table stays below as the
rule; the map is the same rule with time on it.

**The verdict tape.** One colored cell per snapshot day (verdict state), today
highlighted and anchored to the live numbers. Answers "how long have we been in
Risk-on?" at a glance. Historical regimes are recomputed by the published rule –
`regimeOf(gauge, crash basket, bubble odds)` – with the bubble market's daily closes
fetched from the CLOB so single-market Elevated trips are honored; days before the
bubble history default that term to 0, which can only miss a trip, never invent one.

**The dial, re-banded.** The green→red gradient implied linear risk; the model is
banded. The arc is now three wash-tinted band segments with threshold ticks and numbers
at 35/55 (0/100 at the ends), the fill colored by the band the score sits in, and a
ghost tick + caption for yesterday's close (from snapshots.csv) – the reference that
turns "21.1" into "21.1 and falling". The SVG carries a live aria-label.

**Five family micro-bars** under the dial (from `server_gauge.fam`), each colored by
its own band with 35/55 marks – the gauge's provenance without leaving the page.

**7-day sparklines** next to the BULL/BEAR prices, built by the same pair-share
resampler the indexes page uses (now shared, see below).

All history panels are best-effort: on file:// or fetch failure they stay hidden rather
than rendering empty frames, and the baked-snapshot path is unchanged.

## Shared toolkit (omen-common.js)

- `sparkSvg` – y-domain floored at 4% of the series mean (or an explicit `minSpan`), so
  a ±0.3% drift no longer renders as a full-height mountain range; a dotted line marks
  the period mean so flat weeks *look* flat. Both behaviors covered by new tests.
- `parseSnapshots` – snapshots.csv rows → {date, share, crash, gauge} with malformed
  cells dropped or nulled. Tested.
- `pairShareSeries` – the CLOB-history pair-share resampler, extracted from
  indexes.html so the landing page's hero sparks are the same construction. Tested.

## Indexes page (indexes.html)

- `fetchSparks` now delegates to `OMEN.pairShareSeries`.
- The LOADING/UNAVAILABLE placeholder moved out of the stretched SVG
  (`preserveAspectRatio="none"` warps text) into an HTML overlay.

## Monitor (polymarket-ai-index.html)

- `lineChart`/`multiPanelChart`: last-value labels in the right margin per series
  (nudged apart on collision) – the number a viewer otherwise hovers for.
- Hover handlers moved from mouse to pointer events with `touch-action: pan-y`, so
  tooltips work on touch without hijacking vertical scroll.

## Tests

`test-omen-common.mjs` grew assertions for the sparkline domain floor/mean line,
`parseSnapshots`, and `pairShareSeries`. All four Node suites pass; no fetcher or
worker changes.
