import importlib.util,json,logging,unittest
from pathlib import Path
from unittest.mock import patch
B=Path(__file__).resolve().parents[1]
with patch('logging.FileHandler',return_value=logging.NullHandler()):
    spec=importlib.util.spec_from_file_location('pinned_menu_engine',B/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PinnedMenuTests(unittest.TestCase):
    def test_only_exact_bound_vacancy_can_be_selected(self):
        scope={'id':'138337933','employer_id':'3529','name':'Системный аналитик (Мои сервисы)'}
        mapping={'системный аналитик (мои сервисы)':{'vacancy_id':'138337933','employer_id':'3529'}}
        with patch.object(Path,'read_text',side_effect=lambda:json.dumps(mapping)),patch.object(Path,'exists',return_value=True):
            self.assertEqual(m.pinned_menu_target(['1. Системный аналитик (Мои сервисы)','2. Системный аналитик'],scope),'1. Системный аналитик (Мои сервисы)')
            for buttons in [['2. Системный аналитик'],['1. Системный аналитик (Мои сервисы)','2. Системный аналитик (Мои сервисы)']]:
                with self.assertRaises(m.NeedsDecision):m.pinned_menu_target(buttons,scope)
            mapping['системный аналитик (мои сервисы)']['employer_id']='1833'
            with self.assertRaises(m.NeedsDecision):m.pinned_menu_target(['1. Системный аналитик (Мои сервисы)'],scope)
