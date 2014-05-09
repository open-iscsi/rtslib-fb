import os, sys, logging, unittest, tempfile, difflib, rtslib
from pyparsing import ParseException

logging.basicConfig()
log = logging.getLogger('TestDumpRestore')
log.setLevel(logging.INFO)

def diffs(a, b):
    differ = difflib.Differ()
    context = []
    result = []

    for line in differ.compare(a.splitlines(), b.splitlines()):
        if line[0] in "+-":
            result.extend(context[-5:])
            result.append(line)
        elif line[0] == "?":
            result.append(line[:-1])
            context = []
        else:
            context.append(line)
    return '\n'.join(result)

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
        config = rtslib.Config()
        config.load(filepath)
        for step in config.apply():
            print(step)

    def test_clear_apply_config(self):
        config = rtslib.Config()
        config.verify()
        for step in config.apply():
            print(step)

    def test_config_samples(self):
        samples = ["%s/%s" % (self.samples_dir, name)
                   for name in sorted(os.listdir(self.samples_dir))
                   if name.startswith("config_sample_")
                   if name.endswith(".lio")]
        for sample in samples:
            with open(sample) as fd:
                orig = fd.read()

            config = rtslib.Config()
            print("Loading %s" % sample)
            config.load(sample)
            diff =  diffs(orig, config.dump())
            print(diff)
            self.failIf(diff)

            print("Verifying %s" % sample)
            config.verify()
            print("Applying %s" % sample)
            for step in config.apply():
                print(step)

            config = rtslib.Config()
            print("Reloading %s from live" % sample)
            config.load_live()
            diff =  diffs(orig, config.dump())
            print(diff)
            self.failIf(diff)

if __name__ == '__main__':
    unittest.main()
