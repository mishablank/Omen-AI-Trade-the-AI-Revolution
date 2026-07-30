#!/usr/bin/env python3
"""Refuse a hand-run `wrangler deploy` that would not reproduce origin/main.

`wrangler deploy` bundles ./omen straight off disk, so it ships the *working tree* —
not a commit. On 2026-07-27 that put a china-data.json stamped 05:39:38Z into
production that existed in no commit on any ref: a stale worktree had run
update-china-data.py locally and deployed without committing. The site's HTML went
back with it, a week behind main.

Production is deployed by .github/workflows/deploy.yml on push to main. This guard is
for the escape hatch — the manual deploy someone still runs from a laptop. It fails
closed: HEAD must equal origin/main and the tree must be clean, or nothing ships.

    python3 omen/deploy-guard.py && npx wrangler@4 deploy
"""

import subprocess
import sys

# Enough dirty paths to recognise what is wrong, not so many that the real message
# scrolls off. The count in the same line covers the rest.
MAX_LISTED = 10


def blockers(head: str, origin_main: str, porcelain: str) -> list[str]:
    """Reasons this tree must not be deployed. Empty list means it is safe.

    Pure so the policy is testable without a repo: callers supply `git rev-parse`
    and `git status --porcelain` output.
    """
    reasons = []

    dirty = [line for line in porcelain.splitlines() if line.strip()]
    if dirty:
        listed = " ".join(line[3:] for line in dirty[:MAX_LISTED])
        reasons.append(
            f"working tree is not clean — {len(dirty)} path(s) would ship as-is: {listed}")

    if not origin_main:
        reasons.append(
            "no origin/main remote-tracking ref — run `git fetch origin main` first")
    elif head != origin_main:
        reasons.append(
            f"HEAD is {head[:12]}, origin/main is {origin_main[:12]} — "
            "deploy only what is on main")

    return reasons


def _rev_parse(ref: str) -> str:
    """The ref's sha, or "" if it does not resolve."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return out.stdout.strip()


def main() -> int:
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=True).stdout

    reasons = blockers(
        head=_rev_parse("HEAD"),
        origin_main=_rev_parse("refs/remotes/origin/main"),
        porcelain=porcelain,
    )

    if not reasons:
        return 0

    print("refusing to deploy:", file=sys.stderr)
    for reason in reasons:
        print(f"  - {reason}", file=sys.stderr)
    print(
        "\nProduction is deployed from main by .github/workflows/deploy.yml.\n"
        "To deploy by hand anyway: git fetch origin main && git checkout origin/main,\n"
        "with a clean tree.",
        file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
