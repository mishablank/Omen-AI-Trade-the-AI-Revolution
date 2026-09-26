# 2026-09-26 - Remove the KOL board

The influencer (KOL) board is out of scope: which voices are on it and whether each one
is bull or bear no longer feeds anything the site is for. It is removed completely, page
and producer both, the same way the China events pipeline was on 2026-07-23.

It had also never worked as designed. The auto-scorer needed `XAI_API_KEY`, which was
never configured, so the refresh step was skipped on every run and the page only ever
showed its hand-set snapshot. The scorer could not have worked with a key either: it
called xAI's Live Search (`search_parameters`), which xAI retired on 2026-01-12 and which
now answers 410.

## Removed

- **`omen/influencers.html`** - the page, with its inline fallback roster.
- **`omen/update-influencers.py`** and **`omen/test_update_influencers.py`** - the Grok
  scorer and its tests.
- **`.github/workflows/refresh.yml`** - the "Refresh influencer sentiment" step, the
  `HAS_XAI` presence flag, the `put influencers.json` R2 upload, and `omen/influencers.json`
  from the data-commit loop.
- **`worker.js`** / **`wrangler.jsonc`** / **`omen/test-worker.mjs`** - the
  `/influencers.json` data route, its `run_worker_first` entry and its contract row.
- The "KOLs" link from the nav on `index.html`, `indexes.html`, `gauge.html`,
  `methodology.html` and `ai-capex.html`, and "KOL Board" from the landing-page footer.
- README (page table, layout tree, secrets table) and `omen/README.md` (feature list,
  the auto-scoring section, the secrets paragraph).

While editing the same two README lines, the worker-first path lists now name every
route the Worker actually serves (`/capex-data.json`, `/china-data.json`,
`/china-metrics.csv` were missing from one or both).

## Left alone

- The historical write-ups that mention the board (`UPDATES-2026-07-18.md`,
  `UPDATES-2026-07-23.md`) and the done BACKLOG item on CSS token vocabularies, which list it as a page at the time.
- Nothing to clean up outside the repo: the `XAI_API_KEY` secret and an `influencers.json`
  R2 object were never created.

## Restoring it

`git revert` of this change brings everything back, but the scorer would first need
moving off Live Search to xAI's server-side search tools (`/v1/responses` with
`web_search` / `x_search`) and off `grok-4`, which is no longer in xAI's lineup.

## Deploy

Merging deploys through `deploy.yml` as usual, but every production deploy currently
fails at wrangler with `R2 binding error for bucket 'omen-data': Please enable R2 through
the Cloudflare Dashboard [code: 10136]`. Until R2 is re-enabled on the account,
production keeps serving the last successful deploy - which still has the KOL page.
