"""Guards the docs against naming a secret that nothing actually reads.

`EIA_API_KEY` outlived its code by weeks. `update-capex-data.py` moved off the
api.eia.gov v2 route to the published EIA-860M workbook, which needs no key at all, but
three documents went on telling you to set one: the source-inventory row *and* the
secrets table in README.md, the same two lines in the readme.txt mirror, and the CapEx
row in omen/README.md. Nothing failed and no test went red. The setup instructions were
simply false, and the only way to find out was to grep the script.

The check is whole-document rather than secrets-table-only on purpose: the second-stalest
claim was the source-inventory row, which no table parser would have looked at.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Anything shaped like a credential name. Covers every secret this site has carried
# (…_API_KEY, …_TOKEN, …_CHAT_ID, NTFY_TOPIC) without parsing a markdown table.
SECRET_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:KEY|TOKEN|ID|TOPIC)\b")

# Docs that tell a reader how to *run* the site, i.e. instructions someone would act on.
# UPDATES-*.md and BACKLOG.md are excluded deliberately: the first are dated changelogs
# that must keep naming retired secrets, and the second proposes secrets for features that
# do not exist yet (SERPAPI_KEY as of writing).
DOCS = ["README.md", "readme.txt", "omen/README.md"]

# The production surface: what CI runs and what those runs execute. Test files are
# excluded for two reasons — a secret named only in a test is not actually wired to
# anything, and this very file would otherwise vouch for EIA_API_KEY via its own
# docstring, which is not a `#` comment and survives the stripping below.
CODE = [
    p
    for p in (
        sorted(ROOT.glob(".github/workflows/*.yml"))
        + sorted((ROOT / "omen").glob("*.py"))
        + sorted(ROOT.glob("*.mjs"))
        + sorted((ROOT / "omen").glob("*.mjs"))
        + [ROOT / "worker.js"]
    )
    if not p.name.startswith(("test_", "test-"))
]


def strip_comments(text: str) -> str:
    """Drop whole-line `#` and `//` comments.

    Not cosmetic. refresh.yml carries the line "block used to need EIA_API_KEY and is now
    read from the published monthly workbook". That comment is accurate and should stay,
    but counting it as a reference would make this guard pass on precisely the drift it
    exists to catch.
    """
    kept = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "//"))]
    return "\n".join(kept)


def referenced_secrets() -> set[str]:
    names: set[str] = set()
    for path in CODE:
        names |= set(SECRET_RE.findall(strip_comments(path.read_text(encoding="utf-8"))))
    return names


@pytest.mark.parametrize("doc", DOCS)
def test_documented_secrets_are_actually_read(doc: str):
    documented = set(SECRET_RE.findall((ROOT / doc).read_text(encoding="utf-8")))
    orphaned = documented - referenced_secrets()
    assert not orphaned, (
        f"{doc} documents {sorted(orphaned)}, which no workflow or script reads. "
        "Either the code stopped using it and the docs did not follow, or it is a typo."
    )


def test_a_secret_named_only_in_a_comment_does_not_count_as_read():
    """This guard is only as good as strip_comments. If that quietly stops working, the
    test above passes forever on docs that are wrong."""
    assert not SECRET_RE.findall(strip_comments("  # we used to need OLD_API_KEY here"))
    assert SECRET_RE.findall(strip_comments("  OLD_API_KEY: ${{ secrets.OLD_API_KEY }}"))
