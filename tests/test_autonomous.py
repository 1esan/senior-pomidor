import asyncio,importlib.util,json,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,AsyncMock,patch
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import autonomous_runtime as a,operations
from employer_guard import ContactBlocked

class AutonomousTests(unittest.TestCase):
    def test_intro_is_not_completion(self):
        intro='Здравствуйте! Передам информацию команде подбора. Получил отклик на позицию Системный аналитик (Мои сервисы). Будет удобно ответить на вопросы?'
        self.assertFalse(a.interview_finished(intro))
        self.assertTrue(a.interview_finished('Спасибо за ответы! Передам ваши ответы команде. Оцените интервью?'))
        self.assertFalse(a.interview_finished('Расскажите, как работала команда подбора?'))

    def test_requires_decision_does_not_block_technical_questions(self):
        self.assertTrue(a.requires_decision('Когда удобно созвониться?'))
        self.assertTrue(a.requires_decision('Подтвердите согласие на обработку персональных данных'))
        self.assertTrue(a.requires_decision('Подтвердите принятие оффера'))
        self.assertFalse(a.requires_decision('Как вы проектировали REST API?'))

    def test_scope_does_not_allow_switching_employer(self):
        scope={'id':'1','employer_id':'3529','company':'СБЕР','name':'Системный аналитик (Мои сервисы)'}
        with self.assertRaises(ContactBlocked):a.fresh_guard(scope,{'name':scope['name'],'company':'Другой работодатель'})
        with self.assertRaises(a.NeedsDecision):a.check_intro([{'dir':'in','text':'Получил ваш отклик на позицию Другой аналитик'}],scope)
        a.check_intro([{'dir':'in','text':'Получил ваш отклик на позицию '+scope['name']}],scope)

    def test_scope_checks_actual_hh_invitation(self):
        with tempfile.TemporaryDirectory() as d,patch.object(a,'BASE',Path(d)),patch.object(a,'ensure_contact'):
            v={'id':'137109340','name':'СА','employer':{'id':'3529','name':'СБЕР'}}
            negotiations={'pages':1,'items':[{'id':'2','vacancy':v}]}
            with patch.object(a,'hh_read_json',side_effect=[v,negotiations,{'pages':1,'items':[]}]):
                with self.assertRaises(a.NeedsDecision):a.verified_scope('137109340')
            messages={'pages':1,'items':[{'author':{'participant_type':'employer'},'text':'https://telegram.me/Giga_recruiter_bot?start=private'}]}
            with patch.object(a,'hh_read_json',side_effect=[v,negotiations,messages]):
                scope=a.verified_scope('137109340')
                self.assertEqual(scope['id'],'137109340')
                self.assertEqual(scope['employer_id'],'3529')
                self.assertTrue((Path(d)/'.state/giga-invitations/137109340.json').exists())

    def test_invitation_search_paginates_and_checks_author(self):
        with tempfile.TemporaryDirectory() as d,patch.object(a,'BASE',Path(d)),patch.object(a,'ensure_contact'):
            v={'id':'3','name':'СА','employer':{'id':'3529','name':'СБЕР'}}
            pages=[v,{'pages':2,'items':[]},{'pages':2,'items':[{'id':'4','vacancy':v}]},
                   {'pages':2,'items':[{'author':{'participant_type':'applicant'},'text':'https://t.me/Giga_recruiter_bot?start=untrusted'}]},
                   {'pages':2,'items':[{'author':{'participant_type':'employer'},'text':'https://t.me/Giga_recruiter_bot?start=trusted'}]}]
            with patch.object(a,'hh_read_json',side_effect=pages):self.assertEqual(a.verified_scope('3')['negotiation_id'],'4')
            stored=json.loads((Path(d)/'.state/giga-invitations/3.json').read_text())
            self.assertEqual(stored['links'],['https://t.me/Giga_recruiter_bot?start=trusted'])

    def test_wrong_employer_or_no_application_is_rejected(self):
        v={'id':'3','name':'СА','employer':{'id':'3529','name':'СБЕР'}}
        with patch.object(a,'ensure_contact'),patch.object(a,'hh_read_json',side_effect=[v,{'pages':1,'items':[]},{'pages':1,'items':[]}]):
            with self.assertRaises(a.NeedsDecision):a.verified_scope('3')
        wrong={**v,'employer':{'id':'999','name':'Другой'}}
        with patch.object(a,'ensure_contact'),patch.object(a,'hh_read_json',side_effect=[v,{'pages':1,'items':[{'id':'4','vacancy':wrong}]}]):
            with self.assertRaises(a.NeedsDecision):a.verified_scope('3')

    def test_foreign_bot_and_forged_domains_are_not_invitations(self):
        messages=[{'author':{'participant_type':'employer'},'text':u} for u in ['https://t.me/other_bot?start=x','https://t.me.evil.example/Giga_recruiter_bot?start=x','https://t.me/Giga_recruiter_bot','https://example.com/Giga_recruiter_bot?start=x']]
        self.assertEqual(a.invitation_links(messages),[])

    def test_autonomous_requires_live_and_scope(self):
        with self.assertRaises(ValueError):operations.command_for('giga-web',{'autonomous':True,'vacancy_id':'138337933'})
        command,_=operations.command_for('giga-web',{'autonomous':True,'vacancy_id':'138337933','mode':'live','confirm_live':True,'auto_next':False})
        self.assertIn('--autonomous',command);self.assertIn('--vacancy-id',command);self.assertIn('--no-auto-next',command)

    def test_visible_delivery_required(self):
        spec=importlib.util.spec_from_file_location('giga_delivery',BASE/'giga-bot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with patch.object(m,'scrape',new=AsyncMock(return_value=[{'dir':'out','text':'Да, готов.'}])):
            asyncio.run(m.confirm_outgoing(Mock(),'Да, готов.'))
        with patch.object(m,'scrape',new=AsyncMock(return_value=[])),patch.object(m.asyncio,'sleep',new=AsyncMock()):
            with self.assertRaises(a.NeedsDecision):asyncio.run(m.confirm_outgoing(Mock(),'Да, готов.'))

if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Сеть запрещена')):unittest.main(verbosity=2)
