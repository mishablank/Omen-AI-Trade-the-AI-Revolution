# 2026-10-28 - The Trades page: ten positions against the verdict

Every page measured; none said what a position would look like. `omen/trades.html` does:
ten positions buildable with tokenized stocks (xStocks, Ondo Global Markets), on-chain perps
(Hyperliquid HIP-3 via trade.xyz), prediction markets (Polymarket, Kalshi) and tokenized
T-bills - three bull, two bear, three neutral, two hedges - each with its legs and venue,
the live OMEN readings it leans on, the logic in plain words, a published ON / WATCH / OFF
rule, and what kills it.

## What changed

- **`omen/trades.html`.** The cards are static HTML; the rule line, the stance chip and the
  readings list are rendered from one threshold object (`T`) so the published number and the
  applied number cannot disagree. Readings come from `market-data.json` and `capex-data.json`,
  the same files every other page reads; the pair share is computed from `constituents.js`
  through `OMEN.constituentsAt`, the verdict through the shared matrix. A filter row shows
  one kind at a time. A "Today" strip counts ON / WATCH / OFF. The honesty section is part of
  the page, and the advice disclaimer sits in the hero, not only the footer.
- **The verdict rule moved to `omen-common.js`.** `dirOf` and `verdictOf` (with the direction
  bands as `OMEN.DIRECTION`) used to live in `index.html`; the Trades page is the second
  consumer, so the rule is written once and the landing page aliases it. `test-verdict.mjs`
  and `test-constituents.mjs` still slice the landing page's block and now exercise the shared
  functions through it.
- **Nav.** "Trades" joins the link row on the five marketing pages and the landing footer;
  `test_mobile_nav.py` covers the new page.
- **`omen/test-trades.mjs`.** Ten positions, four kinds, every card present in the markup;
  each rule's prose quotes the thresholds it applies; today's board; every verdict cell for
  the two verdict-driven cards, rolling included; both sides of every threshold; a missing
  reading is WATCH with a reason; `readSignals` against a synthetic payload (live-only
  constituents, legs from coverage, the moratorium market found by label, drawdowns,
  degraded payloads). Registered in `test_regime_explainer.py` and `package.json`.
- **README** page table and layout tree; **BACKLOG** entry for the three reads the page
  states it cannot make (funding, the T-bill rate, listing checks) and the un-fitted
  thresholds.

## Not done here

Position 4's stance is always CHECK: funding is a venue number the fetcher does not carry.
The T-bill rate is a dated constant. Venue listings are asserted from public lists as of
2026-10-28, not read. All three are in BACKLOG.md with the keyless endpoints that would fix
them. The thresholds are a reading of the data on the day, not a fit - the page says so twice.

## Verification

`python3 -m pytest omen/` green on the Python side locally (3.9; the Node suites are skipped
where node is absent and run in CI). Every page opened in a browser against a local server:
the Trades page renders the ten cards, the Today strip and the ticker from the committed
data file with no console errors; the mobile drawer opens and closes; the filter row hides
and restores cards.
