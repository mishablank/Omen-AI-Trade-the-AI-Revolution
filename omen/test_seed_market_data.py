import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "smd", Path(__file__).parent / "seed-market-data.py")
smd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smd)

SEED = json.dumps({"updated": "2026-07-27T03:49:38Z", "skew": {"NVDA": {"history": [1, 2]}}})
FRESH = json.dumps({"updated": "2026-08-02T14:23:59Z", "skew": {"NVDA": {"history": [1, 2, 3]}}})


def test_fresh_r2_copy_is_adopted():
    adopt, reason = smd.verdict(FRESH, SEED)
    assert adopt
    assert "2026-08-02T14:23:59Z" in reason


def test_missing_r2_copy_keeps_the_seed():
    # wrangler failed or the object does not exist yet: previous behaviour, not a crash.
    adopt, reason = smd.verdict("", SEED)
    assert adopt is False
    assert "keeping the committed seed" in reason


def test_truncated_r2_copy_keeps_the_seed():
    # The poisoning vector this guard exists for: a half-written 171 KB body parses as
    # nothing, and adopting it would hand the fetcher an empty baseline to append to.
    adopt, reason = smd.verdict(FRESH[: len(FRESH) // 2], SEED)
    assert adopt is False
    assert "truncated" in reason


def test_json_that_is_not_an_object_keeps_the_seed():
    assert smd.verdict("[1, 2, 3]", SEED)[0] is False


def test_r2_copy_without_updated_stamp_keeps_the_seed():
    adopt, reason = smd.verdict(json.dumps({"skew": {}}), SEED)
    assert adopt is False
    assert "updated" in reason


def test_r2_copy_older_than_the_seed_is_refused():
    # An R2 rollback must not rewind the rolling histories.
    adopt, reason = smd.verdict(SEED, FRESH)
    assert adopt is False
    assert "older" in reason


def test_equal_stamps_adopt():
    # Same run's body re-downloaded; adopting is a no-op, refusing would be too.
    assert smd.verdict(FRESH, FRESH)[0] is True


def test_unreadable_seed_is_replaced_by_a_valid_r2_copy():
    # A fresh fork, or a seed that never parsed: any valid baseline beats none.
    assert smd.verdict(FRESH, "")[0] is True
    assert smd.verdict(FRESH, "{ not json")[0] is True


def test_unparseable_stamp_is_treated_as_absent():
    assert smd.verdict(json.dumps({"updated": "last Tuesday"}), SEED)[0] is False


def test_naive_and_zulu_stamps_compare():
    # The fetcher writes "...Z"; be tolerant of a body that omits it rather than
    # refusing every candidate on a TypeError.
    naive = json.dumps({"updated": "2026-08-02T14:23:59"})
    assert smd.verdict(naive, SEED)[0] is True


def test_main_installs_the_fresh_copy(tmp_path):
    cand, seed = tmp_path / "r2.json", tmp_path / "market-data.json"
    cand.write_text(FRESH)
    seed.write_text(SEED)
    assert smd.main(["seed-market-data.py", str(cand), str(seed)]) == 0
    assert json.loads(seed.read_text())["updated"] == "2026-08-02T14:23:59Z"


def test_main_leaves_the_seed_alone_when_the_download_is_absent(tmp_path):
    seed = tmp_path / "market-data.json"
    seed.write_text(SEED)
    assert smd.main(["seed-market-data.py", str(tmp_path / "nope.json"), str(seed)]) == 0
    assert seed.read_text() == SEED


def test_main_rejects_bad_arg_counts():
    assert smd.main(["seed-market-data.py"]) == 2


# ---------- refresh.yml: the commit step survives an R2 outage ----------

def _refresh_steps():
    """refresh.yml's steps as {name: body}. A regex split rather than a YAML parser: the
    repo is stdlib-only, and the step list is flat enough that '- name:' at step indent
    is an unambiguous boundary."""
    import re
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/refresh.yml").read_text()
    parts = re.split(r"^      - (?=name:|uses:)", wf, flags=re.M)[1:]
    steps = {}
    for p in parts:
        m = re.match(r"name:\s*(.+)", p)
        if m:
            steps[m.group(1).strip()] = p
    return steps


def test_commit_step_still_runs_when_only_the_r2_upload_failed():
    """From 2026-09-11 R2 refused every upload and, because the commit step carried the
    implicit success() condition, no refresh landed in git either for over two weeks -
    the append-only history CSVs just stopped. Pin the fix: the commit runs when the
    upload is the thing that failed, and nothing looser than that."""
    steps = _refresh_steps()
    upload, commit = steps["Upload data to R2"], steps["Commit refreshed data"]
    assert "id: r2put" in upload
    cond = next(ln for ln in commit.splitlines() if ln.strip().startswith("if:"))
    assert "steps.r2put.outcome == 'failure'" in cond
    assert "!cancelled()" in cond
    # a bare always() would also commit after a *fetcher* failure - half-written data
    assert "always()" not in cond


def test_commit_step_reseeds_market_data_daily_while_r2_is_down():
    """With R2 down the next run seeds from git, so the weekly re-seed would rebuild the
    rolling histories on a week-old baseline. The step must shorten the window when the
    upload failed."""
    commit = _refresh_steps()["Commit refreshed data"]
    assert "R2_PUT: ${{ steps.r2put.outcome }}" in commit
    assert '[ "$R2_PUT" = "failure" ]' in commit
    assert "SEED_MAX_AGE=$((20 * 60 * 60))" in commit


def test_commit_step_runs_after_the_upload():
    names = list(_refresh_steps())
    assert names.index("Commit refreshed data") > names.index("Upload data to R2")
