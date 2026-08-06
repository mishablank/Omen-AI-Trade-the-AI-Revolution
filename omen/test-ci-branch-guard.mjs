// Unit tests for ci-branch-guard.mjs — the veto in front of a Cloudflare Workers Builds
// deploy of a branch other than main. The guard runs ahead of *every* deploy, including
// the legitimate one, so the fail-open cases below matter more than the blocking case:
// a false positive means production cannot ship at all.
//
//   node omen/test-ci-branch-guard.mjs
//
// The module is imported rather than sliced (unlike the page suites) because it is a
// real module with an exported pure function.

import { verdict } from "../ci-branch-guard.mjs";

let failures = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failures++;
  console.error(`  FAIL ${name}${detail ? " — " + detail : ""}`);
};
const allows = (name, env) => ok(name, verdict(env) === null, JSON.stringify(verdict(env)));
const blocks = (name, env) => {
  const r = verdict(env);
  ok(name, typeof r === "string" && r.length > 0, JSON.stringify(r));
  return r;
};

console.log("ci-branch-guard — Workers Builds branch veto\n");

/* ---------- blocks the one case it can positively identify ---------- */
{
  const r = blocks("blocks a named feature branch", { WORKERS_CI: "1", WORKERS_CI_BRANCH: "dataviz-upgrades" });
  ok("reason names the branch", r.includes("dataviz-upgrades"), r);
  ok("reason names the production branch", r.includes("main"), r);
  // the exact shape of the 2026-07-30 incident
  blocks("blocks fix/china-data-r2", { WORKERS_CI: "1", WORKERS_CI_BRANCH: "fix/china-data-r2" });
  blocks("blocks without WORKERS_CI when branch is known", { WORKERS_CI_BRANCH: "some-branch" });
  blocks("blocks a branch whose name merely contains main", { WORKERS_CI_BRANCH: "mainline" });
  blocks("blocks surrounding whitespace on a feature branch", { WORKERS_CI_BRANCH: "  wip  " });
  console.log("  blocks non-main Workers Builds");
}

/* ---------- fail-open: everything it cannot identify must deploy ---------- */
{
  allows("allows main", { WORKERS_CI: "1", WORKERS_CI_BRANCH: "main" });
  allows("allows main with stray whitespace", { WORKERS_CI: "1", WORKERS_CI_BRANCH: " main\n" });
  // deploy.yml: no Workers Builds variables at all
  allows("allows the GitHub Action deploy", { CI: "true", GITHUB_ACTIONS: "true" });
  allows("allows a bare local deploy", {});
  allows("allows a missing env object", undefined);
  // the variable exists but says nothing usable — never guess
  allows("allows an empty branch value", { WORKERS_CI: "1", WORKERS_CI_BRANCH: "" });
  allows("allows a whitespace-only branch value", { WORKERS_CI: "1", WORKERS_CI_BRANCH: "   " });
  allows("allows a non-string branch value", { WORKERS_CI: "1", WORKERS_CI_BRANCH: 42 });
  // WORKERS_CI alone is not enough to block: the branch is what the policy is about
  allows("allows Workers CI with no branch reported", { WORKERS_CI: "1" });
  console.log("  fail-open on everything unidentified");
}

/* ---------- the documented escape hatch ---------- */
{
  allows("escape hatch releases the block", { WORKERS_CI: "1", WORKERS_CI_BRANCH: "wip", ALLOW_NON_MAIN_WORKERS_BUILD: "1" });
  console.log("  escape hatch");
}

console.log(failures ? `\n${failures} failure(s)` : "\nall ci-branch-guard tests passed");
process.exit(failures ? 1 : 0);
