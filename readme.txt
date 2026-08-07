                ▄▄▄▄▄▄  ▄▄   ▄▄  ▄▄▄▄▄▄  ▄▄   ▄▄
                ██  ██  ███▄███  ██▄▄▄   ███▄ ██
                ██  ██  ██ ▀ ██  ██▀▀▀   ██ ▀███
                ▀▀▀▀▀▀  ▀▀   ▀▀  ▀▀▀▀▀▀  ▀▀   ▀▀

        ┌───────────────────────────────────────────────────┐
        │   A I   C Y C L E   B O O M  ·  A N D  ·  B U S T │
        │                  T R A C K E R                    │
        └───────────────────────────────────────────────────┘

     Prediction markets, options skew, credit spreads, GPU rents and
     hyperscaler filings — folded into one 0–100 crash-pressure gauge
             and one published, deterministic verdict.

                        Not investment advice.


================================================================================
  THE MANUAL MOVED TO README.md
================================================================================

This file used to be a second, complete manual: 15 numbered sections covering the
same material as README.md, written out again in ASCII.

Two hand-maintained copies of one manual drift, and these had. README.md claimed
141 tests, this file claimed 135, and the suite actually collected 289 — three
numbers, none of them right. The repository-layout tree here listed four test
files out of thirteen and none of the three guard scripts. Nobody had done
anything wrong; there is just no way to edit one of two prose copies every time
and have the other stay true.

So there is one manual now, and it is README.md. Everything this file had that
README.md did not — the repository layout tree above all — moved across, and the
stale numeric claims were replaced with things a test can check: test_docs_truth.py
asserts the layout tree names only files that exist, and fails the build if a
hardcoded test count reappears in either document.

  README.md ....... the manual
  BACKLOG.md ...... open work, with acceptance criteria
  docs/updates/ ... dated change notes

The banner stays. It was the best part of this file anyway.

                    ─────────────────────────────────

                        Not investment advice.

           This is a measurement instrument, not a recommendation.
        Every threshold is published so you can disagree with a number
                    rather than with a black box.

                    ─────────────────────────────────
