import os, sys, glob, logging, unittest, tempfile, difflib, rtslib
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

    def cleanup(self):
        # Clear configfs
        list(rtslib.Config().apply())
        # Remove test scsi_debug symlinks
        for test_blockdev in glob.glob("/tmp/test_blockdev_*"):
            os.unlink(test_blockdev)
        os.system("rmmod scsi_debug 2> /dev/null")

    def setUp(self):
        # Backup system config
        self.config_backup = rtslib.Config()
        self.config_backup.load_live()

        self.cleanup()

        # Create scsi_debug devices
        os.system("modprobe scsi_debug dev_size_mb=500 add_host=4")
        scsi_debug_blockdevs = "/sys/devices/pseudo_*/adapter*" \
                               "/host*/target*/*/block"
        test_blockdevs = ["/dev/%s" % name
                          for path in glob.glob(scsi_debug_blockdevs)
                          for name in os.listdir(path)]
        for i, test_blockdev in enumerate(test_blockdevs):
            os.symlink(test_blockdev, "/tmp/test_blockdev_%d" % i)
        print
        log.info(self._testMethodName)

    def tearDown(self):
        print("Restoring initial config...")
        self.cleanup()
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
