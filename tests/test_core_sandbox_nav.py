"""Regression test for the sandbox left navigation layout.

The old markup put the heading, the list and the delete action into one flat
column: long session titles wrapped into a narrow card and the delete cross
floated away from its row. The navigation is now a stack of sections, every
section has a header row, and every list item is a two column grid.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dagi_core" / "static" / "index.html"
APP = Path(__file__).resolve().parents[1] / "dagi_core" / "static" / "app.js"


def _html() -> str:
    return STATIC.read_text(encoding="utf-8")


def _app() -> str:
    return APP.read_text(encoding="utf-8")


def test_navigation_uses_sections_with_header_rows():
    html = _html()
    assert html.count('class="nav-section"') == 3
    assert html.count('class="nav-head"') == 3
    # The old inline heading with a floating action link is gone.
    assert "Delete all</button></h2>" not in html
    assert 'id="purge-sessions" class="nav-action"' in html


def test_list_items_are_a_two_column_grid():
    html = _html()
    assert "#sessions li, #templates li, #runs li" in html
    assert "grid-template-columns: minmax(0, 1fr) auto" in html
    assert "text-overflow: ellipsis" in html
    # The old flex row with a floating delete button is gone.
    assert "#sessions li { display: flex;" not in html


def test_navigation_column_is_wider_than_the_old_230px():
    html = _html()
    assert "grid-template-columns: 268px minmax(300px, 1fr)" in html


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
