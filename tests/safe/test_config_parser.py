import sys, pprint, logging, unittest, cPickle
from rtslib import config_parser

# TODO Add PolicyParser tests

logging.basicConfig()
log = logging.getLogger('TestConfigParser')
log.setLevel(logging.INFO)

class TestConfigParser(unittest.TestCase):

    parser = config_parser.ConfigParser()
    samples_dir = '../data'

    def test_one_line(self):
        print
        log.info(self._testMethodName)
        config = "%s/config_one_line.lio" % self.samples_dir
        parse_tree = self.parser.parse_file(config)
        for statement in parse_tree:
            log.debug(pprint.pformat(statement))
        # with open("%s.ast" % config[:-4], 'w') as f:
        #     cPickle.dump(parse_tree, f)
        with open("%s.ast" % config[:-4], 'r') as f:
            expected_tree = cPickle.load(f)
        self.failUnless(parse_tree == expected_tree)

    def test_basic(self):
        print
        log.info(self._testMethodName)
        config = "%s/config_basic.lio" % self.samples_dir
        parse_tree = self.parser.parse_file(config)
        for statement in parse_tree:
            log.debug(pprint.pformat(statement))
        # with open("%s.ast" % config[:-4], 'w') as f:
        #     cPickle.dump(parse_tree, f)
        with open("%s.ast" % config[:-4], 'r') as f:
            expected_tree = cPickle.load(f)
        self.failUnless(parse_tree == expected_tree)
    
    def test_attribute_group(self):
        print
        log.info(self._testMethodName)
        config = "%s/config_attribute_group.lio" % self.samples_dir
        parse_tree = self.parser.parse_file(config)
        for statement in parse_tree:
            log.debug(pprint.pformat(statement))
        # with open("%s.ast" % config[:-4], 'w') as f:
        #     cPickle.dump(parse_tree, f)
        with open("%s.ast" % config[:-4], 'r') as f:
            expected_tree = cPickle.load(f)
        self.failUnless(parse_tree == expected_tree)

    def test_nested_blocks(self):
        print
        log.info(self._testMethodName)
        config = "%s/config_nested_blocks.lio" % self.samples_dir
        parse_tree = self.parser.parse_file(config)
        for statement in parse_tree:
            log.debug(pprint.pformat(statement))
        # with open("%s.ast" % config[:-4], 'w') as f:
        #     cPickle.dump(parse_tree, f)
        with open("%s.ast" % config[:-4], 'r') as f:
            expected_tree = cPickle.load(f)
        self.failUnless(parse_tree == expected_tree)

    def test_comments(self):
        print
        log.info(self._testMethodName)
        config = "%s/config_comments.lio" % self.samples_dir
        parse_tree = self.parser.parse_file(config)
        for statement in parse_tree:
            log.debug(pprint.pformat(statement))
        # with open("%s.ast" % config[:-4], 'w') as f:
        #     cPickle.dump(parse_tree, f)
        with open("%s.ast" % config[:-4], 'r') as f:
            expected_tree = cPickle.load(f)
        self.failUnless(parse_tree == expected_tree)

    def test_strings(self):
        print
        log.info(self._testMethodName)
        config = "%s/config_strings.lio" % self.samples_dir
        parse_tree = self.parser.parse_file(config)
        for statement in parse_tree:
            log.debug(pprint.pformat(statement))
        # with open("%s.ast" % config[:-4], 'w') as f:
        #     cPickle.dump(parse_tree, f)
        with open("%s.ast" % config[:-4], 'r') as f:
            expected_tree = cPickle.load(f)
        self.failUnless(parse_tree == expected_tree)

    def test_complete(self):
        print
        log.info(self._testMethodName)
        config = "%s/config_complete.lio" % self.samples_dir
        parse_tree = self.parser.parse_file(config)
        for statement in parse_tree:
            log.debug(pprint.pformat(statement))
        # with open("%s.ast" % config[:-4], 'w') as f:
        #     cPickle.dump(parse_tree, f)
        with open("%s.ast" % config[:-4], 'r') as f:
            expected_tree = cPickle.load(f)

        self.failUnless(parse_tree == expected_tree)

if __name__ == '__main__':
    unittest.main()
