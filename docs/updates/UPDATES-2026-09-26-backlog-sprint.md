# 2026-09-26 - Backlog sprint: ten PRs, and what still needs a human

One unattended pass over `BACKLOG.md`. Every open item that could be finished without a
key, a dashboard login or a judgment call now has a PR; the rest are written down with
exactly what is missing. Each PR merges on its own, in any order - they were
test-merged forward, reverse and pairwise with zero conflicts, and the fully merged tree
passes CI.

## The PRs

| PR | What | Live without anything else? |
| --- | --- | --- |
| #59 | Refresh commits its data even when the R2 upload fails; daily seed re-commit while R2 is down | Yes, once merged |
| #60 | China: WebDev + Agent boards on the leaderboard card, media-arenas table; fixes GLM never counting as Chinese (`zai`) | Yes |
| #61 | China: capital-input stat (US $285.9B vs CN $12.4B private AI investment, 2025) | Yes |
| #62 | Shared `aa_data.py` (one AA request per run), `token_prices` for thesis #1, doc fixes | Needs the AA key |
| #63 | Capex: curated AI-spend-per-employee watchlist | Yes |
| #64 | China: live US-vs-CN platform capex asymmetry (13x today) | Yes - Alibaba/Tencent hand-keyed |
| #65 | China: FLI + Concordia safety profile under the ban market | Yes - Concordia per-model values pending |
| #66 | SerpApi fallback for the Android charts | Needs `SERPAPI_KEY` |
| #67 | Monitor: lab-economics EV/ARR table; fixes the valuation ladder parser (card read "unreliable" since Polymarket moved to HIGH/LOW trillion ladders) | Yes |
| #68 | Capex: memory pulse (DRAM contract forecast scan, HBM/spot direction, Korea 20-day with enforced asof); fixes memory counting as a live feed | Yes |

## Nothing ships until R2 is back

Cloudflare R2 is disabled on the account. Refresh uploads fail (`10042`) and so does every
production deploy (`10136`, the Worker's R2 binding for `omen-data`). Merging any PR above
goes red at deploy until R2 is re-enabled in the dashboard - see the top BACKLOG item
(added in #59).

## Blocked on a human

- **Artificial Analysis key + a redistribution answer** - unlocks the frontier card, the
  AA coding/agentic cut, media-arena pricing and thesis #1's token-price panel (#62).
- **`SERPAPI_KEY`** - arms the Android fallback (#66).
- **Reddit / X credentials** - and a decision: the "Community mentions" family the backlog
  describes was removed from the index on 2026-07-18 (dc77942), so building it now means
  adding an eighth family and choosing its weight and reference range.
- **Concordia per-model risk indices** - airiskmonitor.net refuses automated fetches; the
  ~8 numbers need keying by hand into `MANUAL["safety"]["concordia"]["per_model"]`.

## Upkeep this sprint added (hand-updated values, all dated on the page)

- `update-capex-data.py` `MANUAL["korea"]` - each Korea Customs 20-day release (~1st/11th/21st);
  the page flags it STALE after 15 days.
- `MANUAL["cn_capex"]` - Alibaba and Tencent quarterly capex as each reports (next: mid-Nov).
- `update-china-data.py` `MANUAL["investment"]` - each April, when the AI Index ships.
- `MANUAL["safety"]` - FLI each Summer/Winter edition; Concordia each quarter.
- `LAB_ECON` in `polymarket-ai-index.html` - append a row per ARR disclosure or priced round.
