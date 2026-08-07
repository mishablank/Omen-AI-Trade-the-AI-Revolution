# 2026-08-06 – Fail closed on a Workers Builds deploy of a non-main branch

## Deploy-race guard (ci-branch-guard.mjs)

Unrelated to the charts, found while shipping them. deploy.yml's header says the
Cloudflare Workers Builds git integration "must be disconnected, or the two race and
the older mechanism silently wins" – it was never disconnected. Re-verified today:
pushing the `dataviz-upgrades` branch served this unreviewed landing page from
production for ~2 minutes, until the data cron's next push to main rebuilt over it.
Nothing guarantees that drag-back; the exposure window is "until main is pushed again".

`ci-branch-guard.mjs` is wired in as `wrangler.jsonc`'s `build.command`, which wrangler
runs before every upload – including the one Workers Builds performs. It exits non-zero
when `WORKERS_CI_BRANCH` names a branch other than main, so that path fails closed.

**Fail-open by design.** The guard sits in front of the legitimate deploy too, so a
false positive would mean production cannot ship at all – strictly worse than the race.
It blocks only the one case it can positively identify (a Workers Build of a known
non-main branch) and allows everything else through: no such variable (deploy.yml, a
laptop, `wrangler dev`), an empty or non-string value, or a future rename of the
variable. Worst case it is a no-op, never a blocked release. Escape hatch for
deliberately shipping a branch: `ALLOW_NON_MAIN_WORKERS_BUILD=1`.

Expected side effect while the integration is still connected: the "Workers Builds:
omen-ai" check on a PR now fails by design, because that build is exactly what the
guard refuses. It disappears once the integration is disconnected in the Cloudflare
dashboard (Compute (Workers) → omen-ai → Settings → Build), which remains the actual
fix – the guard is insurance in case it is ever reconnected.

## Note on the 2026-08-05 evidence

For the record, since it is easy to misread: production serving the cycle map on
2026-08-06 is *correct* – PR #36 merged at 2026-08-05T19:48Z, so it is on main. The
branch-deploy evidence is the earlier window: at ~20:14Z, before that merge, the live
site served markup that existed only on the unmerged branch, then reverted to main. The
first Workers Build of this guard's own branch is the confirmation – it failed, by
design, instead of shipping.
