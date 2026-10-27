import sys,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
from menu_identity import exact_menu_button
from autonomous_runtime import NeedsDecision
class MenuIdentityTests(unittest.TestCase):
    def setUp(self):
        self.scope={'menu_identity':{'official_url':'https://rabota.sber.ru/search/4567342','official_id':'4567342','button_label':'2. Системный аналитик','menu_summary':'Работа с требованиями и переводами.'}}
        self.buttons=['1. Системный аналитик','2. Системный аналитик','3. Системный аналитик']
        self.bubble={'text':'Меню\n1. Системный аналитик\nДанные.\n\n2. Системный аналитик\nРабота с требованиями и переводами.\n\n3. Системный аналитик\nВеб.','links':['https://rabota.sber.ru/search/sistemnyy-analitik-4567342/']}
    def test_same_titles_are_resolved_by_verified_url_and_section(self):
        self.assertEqual(exact_menu_button(self.buttons,self.scope,self.bubble),'2. Системный аналитик')
    def test_missing_or_forged_link_stops_selection(self):
        for links in [[],['https://rabota.sber.ru.evil.example/search/4567342'],['https://rabota.sber.ru/search/4578088']]:
            with self.assertRaises(NeedsDecision):exact_menu_button(self.buttons,self.scope,{**self.bubble,'links':links})
    def test_reordered_menu_stops_selection(self):
        with self.assertRaises(NeedsDecision):exact_menu_button(self.buttons,self.scope,{**self.bubble,'text':self.bubble['text'].replace('Работа с требованиями и переводами.','Другая вакансия.')})
    def test_ambiguous_exact_button_stops_selection(self):
        with self.assertRaises(NeedsDecision):exact_menu_button(self.buttons+['2. Системный аналитик'],self.scope,self.bubble)
if __name__=='__main__':unittest.main()
