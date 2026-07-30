import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "dg", Path(__file__).parent / "deploy-guard.py")
dg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dg)

SHA = "b2401fc7735126063b232d4ca90d6dffafce9918"
OTHER = "7336748aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_clean_tree_at_origin_main_is_allowed():
    assert dg.blockers(head=SHA, origin_main=SHA, porcelain="") == []


def test_dirty_tree_is_blocked():
    reasons = dg.blockers(head=SHA, origin_main=SHA, porcelain=" M omen/china-data.json\n")
    assert len(reasons) == 1
    assert "omen/china-data.json" in reasons[0]


def test_untracked_file_is_blocked():
    # `wrangler deploy` bundles ./omen off disk, so an untracked asset ships too.
    reasons = dg.blockers(head=SHA, origin_main=SHA, porcelain="?? omen/scratch.html\n")
    assert len(reasons) == 1
    assert "omen/scratch.html" in reasons[0]


def test_head_off_origin_main_is_blocked():
    reasons = dg.blockers(head=OTHER, origin_main=SHA, porcelain="")
    assert len(reasons) == 1
    assert OTHER[:12] in reasons[0]
    assert SHA[:12] in reasons[0]


def test_both_failures_are_reported_together():
    # The 2026-07-27 incident was exactly this: a stale worktree *and* a locally
    # regenerated china-data.json that existed in no commit on any ref.
    reasons = dg.blockers(head=OTHER, origin_main=SHA, porcelain=" M omen/china-data.json\n")
    assert len(reasons) == 2


def test_porcelain_whitespace_only_is_not_dirty():
    assert dg.blockers(head=SHA, origin_main=SHA, porcelain="\n  \n") == []


def test_dirty_listing_is_truncated_but_counts_all():
    porcelain = "".join(f" M omen/f{i}.json\n" for i in range(20))
    reasons = dg.blockers(head=SHA, origin_main=SHA, porcelain=porcelain)
    assert "20" in reasons[0]
    assert reasons[0].count("omen/f") <= 10


def test_missing_origin_main_is_blocked():
    # No remote-tracking ref means we cannot prove HEAD matches main — fail closed.
    reasons = dg.blockers(head=SHA, origin_main="", porcelain="")
    assert len(reasons) == 1
    assert "origin/main" in reasons[0]
