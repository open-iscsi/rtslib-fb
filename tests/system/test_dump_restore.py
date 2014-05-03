import sys, pprint, logging, unittest, tempfile, rtslib
from pyparsing import ParseException

logging.basicConfig()
log = logging.getLogger('TestDumpRestore')
log.setLevel(logging.INFO)

class TestDumpRestore(unittest.TestCase):

    samples_dir = '../data'

    def setUp(self):
        self.config_backup = rtslib.Config()
        self.config_backup.load_live()
        print
        log.info(self._testMethodName)

    def tearDown(self):
        print("Restoring initial config...")
        for step in self.config_backup.apply():
            print(step)

    def test_load_apply_config(self):
        filepath = "%s/config_ramdisk_fileio_iscsi.lio" % self.samples_dir
        lio = rtslib.Config()
        lio.load(filepath)
        for step in lio.apply():
            print(step)

    def test_clear_apply_config(self):
        lio = rtslib.Config()
        lio.verify()
        for step in lio.apply():
            print(step)

if __name__ == '__main__':
    unittest.main()
