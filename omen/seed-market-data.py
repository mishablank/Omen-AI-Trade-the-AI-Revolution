#!/usr/bin/env python3
"""Adopt the live R2 copy of market-data.json as the fetcher's `prev` baseline.

update-market-data.py reads its previous state from omen/market-data.json in the
checkout. That file is a git *seed*, re-committed only when the tracked copy is over
7 days old (see "Commit refreshed data" in refresh.yml) because at 171 KB rewritten
every 30 minutes it was ~86% of the repo's data churn. The site never reads it out of
git – worker.js streams the live copy from R2.

The gap nobody noticed: the seed is also what the fetcher appends its rolling
histories to. With the seed up to a week stale, every run rebuilds skew/term/tail/gpu
history on a week-old baseline and writes back only `baseline + today`, so yesterday's
point is destroyed by today's run. Observed on 2026-08-02: the live skew history ran
07-18..07-27 and then jumped straight to 08-02, five days lost, with every cron run
green. Left alone the series decay to roughly one point per week, because the 7-day
re-seed eventually commits the gapped file and the next week starts from that.

So: pull the live copy down first and hand the fetcher a baseline that is 30 minutes
old rather than up to 7 days old.

Adopting blindly would be worse than not adopting at all – a truncated download or an
R2 rollback would replace a good baseline with a bad one, and the fetcher would happily
write the damage back. A candidate is therefore installed only when it parses as a JSON
object, carries a readable `updated` stamp, and that stamp is not older than the seed's.
Anything else leaves the committed seed untouched, i.e. previous behaviour.
"""

import datetime
import json
import sys


def _load(text):
    """Parse a market-data body, or None if it is missing/truncated/not an object."""
    if not text or not text.strip():
        return None
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _stamp(doc):
    """The doc's `updated` time, or None if absent/unparseable.

    Python 3.9's fromisoformat rejects the trailing "Z" the fetcher writes, and CI runs
    3.12 – normalise rather than depend on the interpreter.
    """
    raw = (doc or {}).get("updated")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        at = datetime.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # The fetcher stamps UTC with a trailing "Z", but a body that omits the offset would
    # otherwise make the comparison below raise TypeError (naive vs aware) and take down
    # the step. Everything here is UTC by construction, so say so.
    return at.replace(tzinfo=datetime.timezone.utc) if at.tzinfo is None else at


def verdict(candidate_text, seed_text):
    """Whether to install the R2 body over the committed seed. Returns (adopt, reason)."""
    candidate = _load(candidate_text)
    if candidate is None:
        return False, "no usable R2 copy (missing, empty or truncated); keeping the committed seed"

    cand_at = _stamp(candidate)
    if cand_at is None:
        return False, "R2 copy has no readable 'updated' stamp; keeping the committed seed"

    seed = _load(seed_text)
    seed_at = _stamp(seed)
    if seed_at is None:
        return True, f"committed seed is missing or unreadable; adopting R2 copy ({candidate['updated']})"

    if cand_at < seed_at:
        # An R2 rollback, or a stale object served during a bucket issue. The seed is
        # the better baseline; taking the older body would silently rewind the histories.
        return False, (f"R2 copy ({candidate['updated']}) is older than the committed seed "
                       f"({seed['updated']}); keeping the seed")

    return True, f"adopting R2 copy ({candidate['updated']}) as the fetcher baseline"


def main(argv):
    if len(argv) != 3:
        print(f"usage: {argv[0]} <downloaded-r2-copy> <seed-path>", file=sys.stderr)
        return 2
    cand_path, seed_path = argv[1], argv[2]

    def read(path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    candidate_text = read(cand_path)
    adopt, reason = verdict(candidate_text, read(seed_path))
    print(reason)
    if adopt:
        # Write the text we already validated, not a copy of the file on disk, so a
        # concurrent rewrite of the download cannot slip past the checks above.
        with open(seed_path, "w") as f:
            f.write(candidate_text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
