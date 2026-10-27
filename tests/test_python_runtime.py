import unittest
from unittest.mock import patch
import python_runtime as r
class PythonRuntimeTests(unittest.TestCase):
 def tearDown(self):r.apple_silicon.cache_clear()
 def test_native_arm(self):
  with patch.object(r.platform,'system',return_value='Darwin'),patch.object(r.platform,'machine',return_value='arm64'):
   self.assertEqual(r.python_command('-u','hh.py')[:2],['/usr/bin/arch','-arm64'])
 def test_rosetta_forces_arm(self):
  with patch.object(r.platform,'system',return_value='Darwin'),patch.object(r.platform,'machine',return_value='x86_64'),patch.object(r.subprocess,'check_output',return_value='1\n'):
   cmd=r.python_command('-u','hh.py','apply','--preview')
   self.assertEqual(cmd[:2],['/usr/bin/arch','-arm64']);self.assertEqual(cmd[3:],['-u','hh.py','apply','--preview'])
 def test_intel_mac(self):
  with patch.object(r.platform,'system',return_value='Darwin'),patch.object(r.platform,'machine',return_value='x86_64'),patch.object(r.subprocess,'check_output',return_value='0\n'):
   self.assertEqual(r.python_command('hh.py'),[str(r.BASE/'.venv/bin/python'),'hh.py'])
 def test_non_mac(self):
  with patch.object(r.platform,'system',return_value='Linux'):
   self.assertNotIn('/usr/bin/arch',r.python_command('hh.py'))
if __name__=='__main__':unittest.main()
