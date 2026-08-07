"""Claims in the documentation that a test can check, checked.

The repo carried two hand-written manuals of the same material - README.md and
readme.txt - and they had drifted from the code and from each other: README claimed
141 tests, readme.txt claimed 135, and the suite collected 289. Nobody got anything
wrong; there is just no way to edit one of two prose copies every time and have the
other stay true. readme.txt is now a pointer, README.md is the manual, and the claims
that rot fastest are pinned here.

This is deliberately a small suite. It does not try to verify prose - only the two
kinds of statement that have actually gone stale in this repo: a path that no longer
exists, and a count that nothing recomputes.
"""

import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
README = (ROOT / "README.md").read_text()
READMETXT = (ROOT / "readme.txt").read_text()


def test_the_layout_tree_names_only_files_that_exist():
    """README's repository-layout tree is the map a newcomer reads first.

    readme.txt's version of it had rotted quietly: four of thirteen test files, none
    of the three guard scripts. A tree is exactly the kind of prose that goes stale
    without looking stale, so every path in it is resolved here.
    """
    tree = re.search(r"<!-- layout-tree:.*?-->\s*```(.*?)```", README, re.S)
    assert tree, "the layout-tree block is gone from README.md - update this test with it"
    body = tree.group(1)

    # Filenames only: the tree also carries directories, box-drawing and prose.
    # Longest extensions first: an alternation led by "js" would clip "wrangler.jsonc"
    # to "wrangler.js" and then report the file it invented as missing.
    names = re.findall(r"[\w./-]+\.(?:jsonc|json|html|mjs|toml|csv|css|png|svg|yml|md|py|js)\b",
                       body)
    assert len(names) > 30, f"only {len(names)} paths matched - the regex has stopped working"

    # Paths are written relative to whichever directory the tree has them under.
    searchable = [ROOT, ROOT / "omen", ROOT / ".github" / "workflows"]
    missing = [n for n in set(names)
               if "*" not in n and not any((d / n).exists() for d in searchable)]
    assert not missing, f"README's layout tree names files that do not exist: {sorted(missing)}"


def test_every_test_file_on_disk_is_in_the_layout_tree():
    """The other direction: a suite added and never mentioned is how the tree rotted
    the first time."""
    tree = re.search(r"<!-- layout-tree:.*?-->\s*```(.*?)```", README, re.S).group(1)
    on_disk = {p.name for p in HERE.glob("test_*.py")} | {p.name for p in HERE.glob("test-*.mjs")}
    listed = set(re.findall(r"[\w.-]+\.(?:py|mjs)", tree))
    unlisted = sorted(on_disk - listed)
    assert not unlisted, f"test files README's layout tree does not list: {unlisted}"


def test_neither_document_claims_a_test_count():
    """The exact drift that produced 141 / 135 / 289.

    A count in prose is only true on the day it is typed. State the command instead -
    `python3 -m pytest omen/` prints the real number every time it runs.
    """
    for name, text in (("README.md", README), ("readme.txt", READMETXT)):
        # "141 tests", "over 200 tests". Deliberately narrow: "13-scenario test suite"
        # is a claim about one suite's contents, which does not rot the same way and is
        # asserted inside that suite.
        for m in re.finditer(r"\b\d{2,4}\s+tests\b", text):
            claim = m.group(0)
            # the 141/135/289 sentence in each file is *about* this drift, not a claim
            if "141" in claim or "135" in claim or "289" in claim:
                continue
            raise AssertionError(
                f"{name} states a test count ({claim!r}); nothing recomputes it, so it "
                "will be wrong by the next PR. Quote the command, not the number.")


def test_readme_txt_is_a_pointer_not_a_second_manual():
    """Guards the outcome, not the file: the drift came from having two copies, so
    the check is that a second copy has not grown back."""
    assert len(READMETXT.splitlines()) < 120, (
        "readme.txt is growing back into a full manual - README.md is the one manual")
    assert "README.md" in READMETXT
    for heading in ("CONTENTS", "THE VERDICT RULE", "WHERE THE NUMBERS COME FROM"):
        assert heading not in READMETXT.replace("THE MANUAL MOVED TO README.md", ""), (
            f"readme.txt has regrown the {heading!r} section that README.md owns")


def test_the_readme_describes_the_tail_math_the_code_actually_runs():
    """The LEAPS tail moved from N(-d2)-at-one-strike to a put-spread digital in
    2026-08; the README's page table still described the old, biased-high reading
    two lines above a table row that described the new one."""
    assert "N(−d2)" not in README and "N(-d2)" not in README
    assert "Breeden" in README
