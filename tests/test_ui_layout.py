import re,unittest
from pathlib import Path
from ui_skin import skin_report,sidebar
BASE=Path(__file__).resolve().parents[1]

class UiLayoutTests(unittest.TestCase):
    def test_shared_skin_is_idempotent(self):
        html='<style>:root{color-scheme:light}</style><div class="wrap">report</div><script id="d" type="application/json">{"safe":"<value>"}</script>'
        first=skin_report(html,'activity');second=skin_report(first,'activity')
        self.assertEqual(first,second)
        self.assertEqual(second.count('class="eg-sidebar"'),1)
        self.assertIn('<script id="d" type="application/json">{"safe":"<value>"}</script>',second)
    def test_all_operation_types_and_unique_controls(self):
        source=(BASE/'setup.html').read_text()
        action=re.search(r'<select id="action".*?</select>',source,re.S)[0]
        self.assertEqual(len(re.findall(r'<option ',action)),10)
        ids=re.findall(r'\bid="([^"]+)"',source)
        self.assertEqual(len(ids),len(set(ids)))
        for name in ['operation-form','profile-form','binding-form','telethon-form','work-log','captcha-resume','confirm-live']:
            self.assertIn(name,ids)
    def test_report_navigation_has_one_active_page(self):
        for page in ['activity','dashboard']:
            nav=sidebar(page)
            self.assertEqual(nav.count('aria-current="page"'),1)
            self.assertIn('data-eg-nav="'+page+'"',nav)
    def test_theme_respects_reduced_motion(self):
        self.assertIn('prefers-reduced-motion:reduce',(BASE/'ui_theme.css').read_text())

if __name__=='__main__':unittest.main()
