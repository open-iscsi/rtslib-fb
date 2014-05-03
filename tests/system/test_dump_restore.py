import sys, pprint, logging, unittest, tempfile
from pyparsing import ParseException
from rtslib import config

logging.basicConfig()
log = logging.getLogger('TestDumpRestore')
log.setLevel(logging.INFO)

class TestDumpRestore(unittest.TestCase):

    samples_dir = 'data'

    def test_clear_apply_config(self):
        print
        log.info(self._testMethodName)
        lio = config.Config()
        lio.verify()
        lio.apply()

if __name__ == '__main__':
    unittest.main()
