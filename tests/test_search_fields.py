import argparse,unittest
from search_options import resolve_search_fields
import hh,operations

class SearchFieldTests(unittest.TestCase):
 def test_default_is_name_only(self):self.assertEqual(resolve_search_fields(),['name'])
 def test_invalid_and_empty_are_rejected(self):
  for value in ([],['unknown'],'name',True,[None]):
   with self.subTest(value=value),self.assertRaises(ValueError):resolve_search_fields(value)
 def test_panel_to_hh_command_preserves_field_combinations(self):
  for fields in (['name'],['description'],['company_name'],['name','description'],['name','description','company_name']):
   with self.subTest(fields=fields):
    command,channel=operations.command_for('apply',{'search_fields':fields,'queries':'тестовая должность'})
    args=hh.parser().parse_args(command[1:]);self.assertEqual(args.search_fields,fields)
    result=hh.build_command(args,{'profile_confirmed':True})
    start=result.index('--search-field')+1;end=result.index('--force-letter')
    self.assertEqual(result[start:end],fields);self.assertEqual(channel,'hh')
 def test_explicit_selection_overrides_legacy_body_setting(self):
  self.assertEqual(resolve_search_fields(['name'],body_too=True),['name'])
 def test_old_cli_flag_remains_compatible(self):
  self.assertEqual(resolve_search_fields(body_too=True),['name','description'])
 def test_no_hidden_professional_role_filter_and_guards_preserved(self):
  profile={'profile_confirmed':True,'excluded_employers':[{'hh_ids':['990000098']} ]}
  args=hh.parser().parse_args(['apply','--query','тестовая должность','--no-sber','--search-fields','name','--preset','all','--pages','10','--per-page','100'])
  cmd=hh.build_command(args,profile)
  self.assertNotIn('--professional-role',cmd)
  self.assertIn('--excluded-employer-id',cmd);self.assertIn('990000098',cmd);self.assertIn('3529',cmd)
  self.assertEqual(cmd[cmd.index('--search-field')+1],'name')
  self.assertEqual(cmd[cmd.index('--total-pages')+1],'10');self.assertEqual(cmd[cmd.index('--per-page')+1],'100')
  self.assertIn('--dry-run',cmd)
 def test_panel_rejects_empty_selection(self):
  with self.assertRaises(ValueError):operations.command_for('apply',{'search_fields':[],'queries':'тестовая должность'})
 def test_panel_requires_an_explicit_search_query(self):
  with self.assertRaises(ValueError):operations.command_for('apply',{'search_fields':['name']})

if __name__=='__main__':unittest.main()
