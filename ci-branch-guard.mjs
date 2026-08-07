/* Refuse a Cloudflare Workers Builds deploy that is not building main.
 *
 * Two mechanisms can deploy this Worker. The intended one is
 * .github/workflows/deploy.yml, which runs on push to main behind the test gate.
 * The other was Cloudflare's Workers Builds git integration, which builds *every
 * branch push* and puts it straight into production — on 2026-07-30 two
 * feature-branch pushes each reached production ~30s later, and on 2026-08-05 the
 * branch `dataviz-upgrades` served an unreviewed landing page to production for ~2
 * minutes, until the data cron's next push to main rebuilt over it. Nothing
 * guarantees that drag-back — the window is "until main is pushed again".
 *
 * The integration was disconnected in the dashboard on 2026-08-07, so this guard is
 * now insurance against a future reconnect rather than the active defence. It stays
 * wired in because reconnecting takes one dashboard click and forgets nothing.
 *
 * wrangler runs wrangler.jsonc's build.command before it uploads, and Workers
 * Builds deploys by running wrangler. So this is the one repo-side hook that can
 * veto that path without dashboard access. It is the CI-side sibling of
 * omen/deploy-guard.py, which guards the hand-run laptop deploy.
 *
 * FAIL-OPEN BY DESIGN. This runs in front of every legitimate deploy too, so a
 * false positive means production cannot ship at all — strictly worse than the
 * race it prevents. It therefore blocks only the one case it can positively
 * identify: WORKERS_CI_BRANCH is set (so this *is* a Workers Build) and names a
 * branch other than main. Anything else — no such variable (deploy.yml, a laptop,
 * wrangler dev), an unreadable value, a future rename of the variable — is allowed
 * through untouched.
 *
 * Escape hatch, for deliberately shipping a branch from Workers Builds:
 *   ALLOW_NON_MAIN_WORKERS_BUILD=1
 */

import { pathToFileURL } from "node:url";

const PRODUCTION_BRANCH = "main";

/** Why this build must not deploy, or null when it may proceed. Pure: all input
 *  comes from the env object, so the policy is testable without a build. */
export function verdict(env = {}) {
  if (env.ALLOW_NON_MAIN_WORKERS_BUILD) return null;

  // The only positive signal that this is a Workers Build of a known branch.
  const branch = typeof env.WORKERS_CI_BRANCH === "string" ? env.WORKERS_CI_BRANCH.trim() : "";
  if (!branch) return null;              // not a Workers Build, or it stopped telling us
  if (branch === PRODUCTION_BRANCH) return null;

  return `Workers Builds is building '${branch}', not ${PRODUCTION_BRANCH}.`;
}

const REMEDY = `
Production is deployed from ${PRODUCTION_BRANCH} by .github/workflows/deploy.yml,
behind the test gate. A branch build reaching production would replace the live
site with unreviewed work until the next push to ${PRODUCTION_BRANCH}.

Fix the cause: disconnect the Workers Builds git integration in the Cloudflare
dashboard (Compute (Workers) > omen-ai > Settings > Build), leaving deploy.yml as
the only deployer.

To ship a branch from Workers Builds on purpose, set
ALLOW_NON_MAIN_WORKERS_BUILD=1 on the build.`;

function main() {
  const reason = verdict(process.env);
  if (!reason) return 0;
  console.error(`refusing to deploy: ${reason}${REMEDY}`);
  return 1;
}

// Only act when run as a script; importing this module (the test suite) must not exit.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
