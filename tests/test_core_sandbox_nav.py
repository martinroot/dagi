"""Regression tests for the Bootstrap 6 responsive workspace navigation.

The sidebar keeps chats and saved runs in separate collapsible cards; templates
live on their own page. Session and run labels stay within the sidebar at every
breakpoint.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dagi_core" / "static" / "index.html"
APP = Path(__file__).resolve().parents[1] / "dagi_core" / "static" / "app.js"
CSS = Path(__file__).resolve().parents[1] / "dagi_core" / "static" / "dagi-app.css"


def _html() -> str:
    return STATIC.read_text(encoding="utf-8")


def _app() -> str:
    return APP.read_text(encoding="utf-8")


def test_navigation_uses_separate_collapsible_chat_and_run_cards():
    html = _html()
    assert html.count('class="sidebar-card card') == 2
    assert html.count('class="sidebar-disclosure" open') == 2
    assert 'id="sessions"' in html
    assert 'id="runs"' in html
    assert 'id="purge-sessions"' in html
    nav = html.split("<nav", 1)[1].split("</nav>", 1)[0]
    assert 'id="templates"' not in nav


def test_session_rows_shrink_and_preserve_the_delete_action():
    css = CSS.read_text(encoding="utf-8")
    assert "#sessions li,#runs li{display:grid;grid-template-columns:minmax(0,1fr) auto" in css
    assert "text-overflow:ellipsis" in css
    assert "#sessions li .row-delete" in css


def test_navigation_and_workspace_have_responsive_three_column_layout():
    css = CSS.read_text(encoding="utf-8")
    assert ".app-container{min-height:0;display:grid;grid-template-columns:minmax(220px,250px) minmax(0,1fr) minmax(270px,320px)" in css
    assert "@media (max-width: 1199.98px)" in css
    assert "@media (max-width: 767.98px)" in css



def test_session_button_carries_a_title_for_the_truncated_label():
    app = _app()
    assert 'button.title = `${session.title || "Untitled"} · #${session.id}`;' in app


def test_template_button_shows_the_name_without_the_clone_prefix():
    app = _app()
    assert "button.textContent = template.name;" in app
    assert "Clone · ${template.name}" not in app


def test_empty_states_use_the_nav_empty_style():
    app = _app()
    assert 'empty.className = "nav-empty";' in app
