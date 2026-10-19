"""The shared frame of the one-screen pages (REQ-044, DEC-080): the .os rules and the router that leaves the footer out of them."""
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src" / "titanium_platform" / "ui"
CSS = (UI / "styles.css").read_text(encoding="utf-8")
ROUTER = (UI / "router.js").read_text(encoding="utf-8")


def test_a_one_screen_page_is_as_high_as_the_window_and_only_a_long_list_scrolls_inside_its_panel():
    assert re.search(r":root \{--os-h:calc\(100vh - 76px - 26px\)\}", CSS) and re.search(r"body\.is-workspace \{--os-h:calc\(100vh - 76px - 20px\)\}", CSS)
    assert re.search(r"\.os \{[^}]*height:var\(--os-h\)", CSS) and re.search(r"\.os-body \{[^}]*flex:1;min-height:0;display:grid", CSS)
    assert re.search(r"\.os-col \{[^}]*min-height:0[^}]*overflow:hidden", CSS) and re.search(r"\.os-scroll \{[^}]*flex:1;min-height:0;overflow:auto", CSS)
    narrow = re.search(r"@media \(max-width:1100px\) \{\s*\.os \{(.*?)\n\}", CSS[CSS.index("15) один экран"):], re.S)
    assert narrow and "height:auto" in narrow.group(1) and ".os-scroll {overflow:visible}" in CSS      # a phone scrolls the page as before


def test_the_router_leaves_the_footer_out_of_a_one_screen_page():
    assert "node.classList.contains('os')" in ROUTER and "main.replaceChildren(...(bare ? [node] :" in ROUTER
    assert "document.body.classList.toggle('is-workspace', workspace)" in ROUTER and "main.querySelector('.workspace')" in ROUTER


def test_the_sections_are_a_rail_of_icons_on_every_page_and_a_button_opens_them_as_a_popup_over_the_page():
    """DEC-081: the menu is never folded away; the rail is fixed at the left edge and the page makes room for it."""
    assert re.search(r"\.app-layout \{display:block;padding-left:56px", CSS) and re.search(r"\.sidebar \{position:fixed;top:76px;left:0;bottom:0;[^}]*width:56px", CSS)
    assert re.search(r"\.sidebar\.is-open \{width:min\(290px,86vw\)", CSS) and ".sidebar:not(.is-open) .nav-text {position:absolute" in CSS
    assert "body.is-workspace .sidebar" not in CSS and "body.is-workspace .app-layout" not in CSS      # no page folds the menu away any more
    assert "railButton = h('button', {type: 'button', class: 'rail-toggle'" in ROUTER and "'aria-controls': 'app-navigation'" in ROUTER
    assert "h('a', {class: 'nav-link', href: '#' + r, title: l" in ROUTER and "h('span', {class: 'nav-text'}, l)" in ROUTER     # an icon with a name for the popup
    assert "onClick: () => setMenu(false)" in ROUTER                                                  # choosing a section closes the popup
    assert "ev.key === 'Escape' && menuOpen()" in ROUTER and "!sidebar.contains(ev.target)" in ROUTER   # Esc and a click outside close it
    narrow = re.search(r"@media \(max-width:1000px\) \{(.*?)\n\}", CSS[CSS.index("5) адаптация"):], re.S)
    assert narrow and ".app-layout {padding-left:0" in narrow.group(1) and ".sidebar {display:none;top:66px}" in narrow.group(1) and ".rail-toggle {display:none}" in narrow.group(1)

