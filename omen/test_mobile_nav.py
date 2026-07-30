"""Guards the mobile nav drawer against the copy-paste drift this site is prone to.

Every page carries its own hand-written copy of the <nav> block. The drawer is the third
thing to be duplicated that way (after $/esc and the regime thresholds), and the failure it
replaces was silent: `@media(max-width:760px){nav .links{display:none}}` deleted six of the
seven destinations on a phone and nothing looked broken, because the links were simply gone.
These tests fail loudly if a page grows a nav without the drawer, or if that hide-with-no-
replacement rule comes back.
"""

import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent

# The pages that share the marketing-site nav (logo · link row · monitor CTA). The three
# dashboards (monitor, china, influencers) have their own chrome and no .links row.
NAV_PAGES = ["index.html", "indexes.html", "gauge.html", "methodology.html", "ai-capex.html"]


def read(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("page", NAV_PAGES)
def test_nav_page_ships_the_drawer_toggle(page: str):
    html = read(page)
    assert 'class="navtoggle"' in html, f"{page} has a nav with no mobile toggle button"
    assert 'aria-controls="navlinks"' in html, f"{page} toggle is not wired to the link row"
    assert 'id="navlinks"' in html, f"{page} link row is missing the id the toggle controls"
    assert "omen-nav.js" in html, f"{page} never loads the drawer script"


@pytest.mark.parametrize("page", NAV_PAGES)
def test_no_page_hides_the_links_without_a_replacement(page: str):
    """The original bug, spelled out: a bare display:none on the link row inside a
    max-width media query, with no drawer to open it again."""
    html = read(page)
    stripped = re.sub(r"\s+", "", html)
    assert "@media(max-width:760px){nav.links{display:none}}" not in stripped, (
        f"{page} still hides the nav links outright on mobile"
    )


@pytest.mark.parametrize("page", NAV_PAGES)
def test_pages_do_not_redeclare_the_drawer_css(page: str):
    """The drawer lives in omen.css exactly once; a page-local copy is how the eight
    :root blocks happened."""
    html = read(page)
    assert ".navtoggle{" not in re.sub(r"\s+", "", html).replace("<style>", ""), (
        f"{page} declares .navtoggle styles locally instead of using omen.css"
    )


def test_drawer_css_and_script_exist():
    css = read("omen.css")
    for rule in [".navtoggle", "nav .links", "[data-open]"]:
        assert rule in css, f"omen.css is missing the drawer rule {rule!r}"
    js = read("omen-nav.js")
    assert "aria-expanded" in js, "the toggle never reports its state to assistive tech"
    assert "data-open" in js, "the script does not drive the attribute the CSS keys off"


def test_landing_page_has_no_layout_wider_than_a_phone():
    """The hero grid column used to be floored at 446px by the nowrap theme text in the
    dial panel's .mini rows, so at 390px the document laid out at 536px and
    body{overflow-x:hidden} silently clipped a quarter of every line off the right."""
    css = read("index.html")
    stripped = re.sub(r"\s+", "", css)
    assert ".hgrid>*{min-width:0}" in stripped, (
        "hero grid items can still be floored open by their content's min-content width"
    )
    assert re.search(r"\.mini\.th\{[^}]*white-space:normal", stripped), (
        "the dial panel's theme text still refuses to wrap on mobile"
    )


# Every page that ships to a phone. The three dashboards have their own chrome and are
# absent from NAV_PAGES, but they overflowed just as badly, so width is checked site-wide.
ALL_PAGES = NAV_PAGES + [
    "polymarket-ai-index.html", "china-ai-monitor.html", "influencers.html",
]


@pytest.mark.parametrize("page", ALL_PAGES)
def test_every_page_scales_to_the_device(page: str):
    """Without width=device-width a phone renders at ~980px and scales the result down,
    which makes every other mobile rule on the page unreachable."""
    html = read(page)
    assert re.search(
        r'<meta\s+name="viewport"\s+content="[^"]*width=device-width', html
    ), f"{page} has no width=device-width viewport meta"


def test_capex_tables_carry_their_column_labels():
    """The eleven .dt tables restack to one block per row on mobile, which hides the
    header row — so each data cell has to carry its own label or the figures lose their
    meaning ("Latest" vs "Δ", "90d" vs "Prior 90d")."""
    html = read("ai-capex.html")
    tables = re.findall(r'<table class="dt"[^>]*>(.*?)</table>', html, re.S)
    assert tables, "no .dt tables found — did the markup change?"
    for i, body in enumerate(tables):
        rows = [r for r in re.split(r"(?=<tr>)", body) if "<tr>" in r]
        labels = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.S)
        for row in rows[1:]:
            cells = re.findall(r"<td([^>]*)>", row)
            # cell 0 becomes the row title; every later cell needs its header as data-l
            for j, attrs in enumerate(cells[1:len(labels)], start=1):
                assert "data-l=" in attrs, (
                    f"ai-capex.html table {i}, cell {j} has no data-l — its column "
                    f"header is lost once the table restacks"
                )


@pytest.mark.parametrize("page", ALL_PAGES)
def test_wide_min_widths_are_released_on_mobile(page: str):
    """A fixed min-width wider than the narrowest phone is exactly how content ends up
    clipped by body{overflow-x:hidden} instead of scrolled: index.html's verdict table
    was pinned to 560px inside a 334px column. Keeping the desktop pin is fine, but it
    has to be released again inside a max-width block."""
    text = re.sub(r"\s+", "", read(page))
    # a media query's own condition is not a declaration — @media(min-width:700px) is a
    # breakpoint, not something pinning an element open
    decls = re.sub(r"@media\([^)]*\)", "@media", text)
    wide = {int(m.group(1)) for m in re.finditer(r"min-width:(\d+)px", decls)
            if int(m.group(1)) > 320}
    if not wide:
        return
    mobile_css = "".join(
        re.findall(r"@media\(max-width:\d+px\)\{(.*?)\}\}", text, re.S)
    ) + "".join(re.findall(r"@media\(max-width:\d+px\)\{([^@]*?)\}", text, re.S))
    assert "min-width:0" in mobile_css, (
        f"{page} pins {sorted(wide)}px but never releases a min-width on mobile"
    )
