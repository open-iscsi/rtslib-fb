import sys, pprint, logging, unittest, tempfile
from pyparsing import ParseException
from rtslib import config

logging.basicConfig()
log = logging.getLogger('TestConfig')
log.setLevel(logging.INFO)

class TestConfig(unittest.TestCase):

    samples_dir = '../data'

    def test_load_basic(self):
        print
        log.info(self._testMethodName)
        filepath = "%s/config_basic.lio" % self.samples_dir
        lio = config.Config()

        lio.load(filepath)

        tests = [("storage fileio", 'obj', 1),
                 ("storage fileio disk vm1 path /tmp/vm1.img", 'attr', 1),
                 ("storage fileio disk vm1 size 1.0MB", 'attr', 1),
                 ("storage .* disk .* .* .*", 'attr', 3)]

        for pattern, node_type, arity in tests:
            results = lio.search(pattern)
            log.debug("config.current.search(%s) -> (%d) %s"
                      % (pattern, len(results), results))
            self.failUnless(len(results) == arity)
            for result in results:
                self.failUnless(result.data['type'] == node_type)

        self.failUnless(lio.search("storage fileio disk vm1 path") == [])

    def test_load_complete(self):
        print
        log.info(self._testMethodName)
        filepath = "%s/config_complete.lio" % self.samples_dir
        lio = config.Config()
        lio.load(filepath)

        tests = [("storage fileio", 'obj', 1),
                 ("storage fileio disk disk1 path", None, 0),
                 ("storage fileio disk disk1 path /tmp/disk1.img", 'attr', 1),
                 ("storage fileio disk disk1 path /tmp/disk2.img", 'attr', 0),
                 ("storage fileio disk disk1 size 1.0MB", 'attr', 1),
                 ("storage fileio disk disk2 path /tmp/disk2.img", 'attr', 1),
                 ("storage .* disk .* .* .* .*", 'attr', 46),
                 ("storage .* disk .* attribute .* .*", 'attr', 46),
                 ("storage .* disk .* .* .*", 'attr', 6)]

        for pattern, node_type, arity in tests:
            results = lio.search(pattern)
            log.debug("config.current.search(%s) -> (%d) %s"
                      % (pattern, len(results), results))
            self.failUnless(len(results) == arity)
            for result in results:
                self.failUnless(result.data['type'] == node_type)

    def test_clear_undo(self):
        print
        log.info(self._testMethodName)
        filepath = "%s/config_complete.lio" % self.samples_dir
        lio = config.Config()
        log.info("Load config")
        lio.load(filepath)
        self.failUnless(len(lio.search("storage fileio disk disk2")) == 1)
        lio.clear()
        self.failUnless(len(lio.search("storage fileio disk disk2")) == 0)
        lio.undo()
        self.failUnless(len(lio.search("storage fileio disk disk2")) == 1)

    def test_load_save(self):
        print
        log.info(self._testMethodName)
        filepath = "%s/config_complete.lio" % self.samples_dir
        lio = config.Config()
        lio.load(filepath)

        with tempfile.NamedTemporaryFile(delete=False) as temp:
            log.debug("Saving initial config to %s" % temp.name)
            dump1 = lio.save(temp.name)
            lio.load(temp.name)

        with tempfile.NamedTemporaryFile(delete=False) as temp:
            log.debug("Saving reloaded config to %s" % temp.name)
            dump2 = lio.save(temp.name)

        self.failUnless(dump1 == dump2)

    def test_set_delete(self):
        print
        log.info(self._testMethodName)
        filepath = "%s/config_complete.lio" % self.samples_dir

        lio = config.Config()
        set1 = lio.search("storage fileio disk mydisk")
        set2 = lio.search("fabric iscsi discovery_auth enable yes")
        self.failUnless(len(set1) == len(set2) == 0)

        iqn = '"iqn.2003-01.org.linux-iscsi.targetcli.x8664:sn.foo"'
        lio.set("fabric iscsi target " + iqn)
        self.assertRaises(ParseException, lio.set,
                          "fabric iscsi discovery_auth")
        lio.set("fabric iscsi discovery_auth enable yes")
        lio.set("storage fileio disk vm1 {path /foo.img; size 1MB;}")
        self.assertRaises(ParseException, lio.set,
                          "storage fileio disk vm1 {path /foo.img; size 1MB}")
        lio.set("storage fileio disk mydisk")
        set1 = lio.search("storage fileio disk mydisk")
        set2 = lio.search("fabric iscsi discovery_auth enable yes")
        self.failUnless(len(set1) == len(set2) == 1)

        lio.delete("storage fileio disk mydisk")
        lio.delete("fabric iscsi discovery_auth enable yes")
        set1 = lio.search("storage fileio disk mydisk")
        set2 = lio.search("fabric iscsi discovery_auth enable yes")
        self.failUnless(len(set1) == 0)
        self.failUnless(len(set2) == 0)

    def test_invalid_reference(self):
        print
        log.info(self._testMethodName)
        filepath = "%s/config_invalid_reference.lio" % self.samples_dir
        lio = config.Config()
        self.assertRaisesRegexp(config.ConfigError,
                                ".*Invalid.*disk3.*",
                                lio.load, filepath)
        lio = config.Config()

if __name__ == '__main__':
    unittest.main()
