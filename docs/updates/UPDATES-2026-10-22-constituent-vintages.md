# 2026-10-22 - One constituent list, dated vintages, and the expiry watchdog

Found while deciding what to spend two hours on: 16 of the 17 live Polymarket markets
behind the Bull/Bear pair resolve on 2027-01-01, and nothing in the repo would have said
so until the landing page woke up on 1 January with a one-market Bull index and an empty
Bear one. On the way there, two smaller things: three of the original twenty had already
left the basket (31 Jul, 4 Sep, 30 Sep) while every page still said "twenty", and the
landing page was still averaging the delisted one at its 2026-07-11 baked price - the
bull share read 77% on the landing page against 71% on the monitor.

## What changed

- **`omen/constituents.js`** is the one constituent list: a JSON literal every page loads
  as a script and `update-market-data.py` parses with `json.loads`. Every market has a
  `from` date and, once gone, a `to` date; successors can be written down as `proposed`
  without being members. The five copies (POLY_IDS and four page arrays) are gone, and
  `test_constituents.py` fails if a page grows one back or a `to` date disagrees with the
  membership `snapshots.csv` recorded.
- **Coverage watchdog.** The fetcher writes a `coverage` block (per side: configured, live,
  expiring inside 30 days, rolling; the cliff; the next vintage; prose warnings), prints
  each warning as a GitHub Actions annotation, and alerts on the existing Telegram/ntfy
  channel when the warning set changes. The landing chip and the monitor's Constituents
  card show "N of M live · K expire <date>" once the cliff is inside 120 days.
- **Chain-linked pair levels.** `bull_chain` / `bear_chain` in `snapshots.csv`, carried run
  to run in `market-data.json.poly`, move only by the markets both runs priced. The
  landing page's verdict tape and cycle map read them when present, so the 89-day trail
  stays continuous across a roll (and across the next resolution).
- **Roll rule.** A side with fewer than `roll_floor` (3) live markets has no direction
  read: `verdictOf` returns "No edge", the page says "basket rolling", the fetcher's
  coverage says the same.
- **Copy.** "Twenty markets - 11 Bull, 9 Bear" on four pages is now rendered from the
  file (17 today: 9 Bull, 8 Bear).
- **Fix.** A market Gamma no longer returns is now closed on every page; it used to stay
  in the pair at its baked price.

## Not done here - the curation

Polymarket had listed 2027 versions of only some themes on 2026-10-22. Five successors are
written down as `proposed`; seven themes have no 2027 market yet. The join date, the
bubble range and the deadline-decay question are the user's calls. All in
`BACKLOG.md` under "Constituent roll - the 2027 vintage".

## Verification

`python3 -m pytest omen/` and `ruff check .` green locally (Python side). The Node suites
could not run on the authoring machine (no Node); CI runs them. Every page was opened in
a browser against a local server and the live Gamma feed with no console errors.
