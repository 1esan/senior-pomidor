import sys,json,tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from statistics_store import publish,read_statistics,render_report

class StatisticsTests(unittest.TestCase):
    def test_concurrent_sections_are_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(lambda i:publish(d,'activity' if i%2 else 'analysis',{'value':i}),range(20)))
            data=read_statistics(d)
            self.assertEqual(data['revision'],20)
            self.assertIn('analysis',data);self.assertIn('activity',data)
            self.assertEqual((Path(d)/'statistics.json').stat().st_mode&0o777,0o600)

    def test_html_uses_latest_json_without_rebuilding_template(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'hh-dashboard.html'
            file.write_text('<script id="data" type="application/json">{}</script>')
            def value(n):return {'gen':'2026-10-14T14:00:00Z','funnel':{'sent':n,'invited':0,'rejected':0,'pending':n,'other':0}}
            publish(d,'dashboard',value(1));self.assertIn('"sent": 1',render_report(d,'dashboard'))
            publish(d,'dashboard',value(2));self.assertIn('"sent": 2',render_report(d,'dashboard'))
            self.assertEqual(file.read_text(),'<script id="data" type="application/json">{}</script>')

    def test_invalid_statistics_preserve_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            publish(d,'dashboard',{'gen':'now','funnel':{'sent':1,'invited':0,'rejected':0,'pending':1,'other':0}})
            before=(Path(d)/'statistics.json').read_bytes()
            with self.assertRaises(ValueError):publish(d,'dashboard',{'gen':'now','funnel':{'sent':1,'invited':2,'rejected':0,'pending':1,'other':0}})
            self.assertEqual((Path(d)/'statistics.json').read_bytes(),before)

    def test_injected_text_cannot_escape_json_script(self):
        with tempfile.TemporaryDirectory() as d:
            publish(d,'activity',{'gen':'now','text':'</script><img onerror=evil()>'})
            html=render_report(d,'activity','<script id="d" type="application/json">{}</script>')
            self.assertNotIn('<img',html);self.assertEqual(html.count('</script>'),1)

if __name__=='__main__':unittest.main()
