from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dagi_core/static/index.html").read_text()
CSS = (ROOT / "dagi_core/static/dagi-app.css").read_text() if (ROOT / "dagi_core/static/dagi-app.css").exists() else ""
LANDING = (ROOT / "site/index.html").read_text()


class DagiBootstrap6UiTests(unittest.TestCase):
    def test_chat_loads_pinned_bootstrap6_css_locally(self):
        self.assertIn("/bootstrap-6.0.0-alpha.1.min.css", HTML)

    def test_chat_preserves_operational_controls_and_accessible_live_regions(self):
        for required in ['id="chat"', 'id="message"', 'id="send"', 'id="stop-run"', 'id="composer-status"', 'aria-live="polite"']:
            with self.subTest(required=required):
                self.assertIn(required, HTML)

    def test_chat_uses_bootstrap_layout_and_mobile_breakpoints(self):
        for required in ['class="container-fluid', 'class="btn', 'card', 'class="form-control']:
            with self.subTest(required=required):
                self.assertIn(required, HTML)
        self.assertIn("@media (max-width: 767.98px)", CSS)

    def test_templates_are_not_embedded_in_the_chat_sidebar(self):
        nav = HTML.split("<nav", 1)[1].split("</nav>", 1)[0]
        self.assertNotIn('id="templates"', nav)
        self.assertIn('href="/templates/"', HTML)

    def test_markup_uses_bootstrap6_utilities_not_bootstrap5_breakpoint_names(self):
        self.assertIn("lg:col-5", LANDING)
        self.assertIn("lg:col-7", LANDING)
        self.assertIn("btn-solid theme-primary", HTML)
        self.assertNotIn("col-lg-", LANDING)
        self.assertNotIn("btn-primary", HTML)
        self.assertTrue((ROOT / "dagi_core/static/bootstrap-LICENSE.txt").is_file())

    def test_mobile_composer_can_shrink_to_keep_send_button_visible(self):
        self.assertIn(".composer-input.form-control{min-width:0;width:100%;flex:1 1 auto;", CSS)
        self.assertIn(".composer-send{display:flex;flex:0 0 auto", CSS)
        self.assertIn(".composer-send:disabled{--bs-btn-disabled-bg:", CSS)
        self.assertIn(".chat-toolbar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap", CSS)

    def test_homepage_is_english_and_centers_servers_memory_and_presets(self):
        self.assertIn('<html lang="en"', LANDING)
        self.assertNotIn('<html lang="ru"', LANDING)
        for text in ["multi-server", "memory", "presets", "Hermes-style", "/chat/"]:
            with self.subTest(text=text):
                self.assertIn(text.casefold(), LANDING.casefold())

    def test_header_has_a_direct_github_repository_link(self):
        header = LANDING.split("</header>", 1)[0]
        self.assertIn('href="https://github.com/martinroot/dagi"', header)
        self.assertIn("GitHub", header)
        self.assertNotRegex(LANDING, r"[А-Яа-яЁё]")


if __name__ == "__main__":
    unittest.main()
