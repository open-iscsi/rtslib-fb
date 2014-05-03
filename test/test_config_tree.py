import re, sys, pprint, logging, unittest
from rtslib import config_tree

logging.basicConfig()
log = logging.getLogger('TestConfigTree')
log.setLevel(logging.INFO)

class TestConfigTree(unittest.TestCase):

    def test_create(self):
        print
        log.info(self._testMethodName)
        tree = config_tree.ConfigTree()
        self.failUnless(tree.get(None) is None)
        self.failUnless(tree.get_path(None) is None)
        self.failUnless(tree.get_path([]) is None)
        self.failUnless(tree.get(()) is None)
        self.failUnless(tree.delete(None) is None)
        self.failUnless(tree.get_path(('a',)) is None)
        self.failUnless(tree.get_path([('a',), ('b',), ('c',)]) is None)

    def test_add_get_delete(self):
        print
        log.info(self._testMethodName)
        tree = config_tree.ConfigTree()
        n1 = tree.set(('1', '2'), {'info': 'n1'})
        nA = tree.set(('a', 'b'), {'info': 'nA'})
        n2 = n1.set(('3', '4'), {'info': 'n2'})
        nB = nA.set(('c', 'd'), {'info': 'nB'})

        node = tree.get([('1', '2'), ('3', '4')])
        self.failUnless(node.data['info'] == 'n2')
        node = tree.get([('1', '2')])
        self.failUnless(node.data['info'] == 'n1')
        node = tree.get([('a', 'b'), ('c', 'd')])
        self.failUnless(node.data['info'] == 'nB')
        self.failUnless(node.is_root == False)
        self.failUnless(tree.is_root == True)

    def test_add_get_delete(self):
        print
        log.info(self._testMethodName)
        tree = config_tree.ConfigTree()
        n1 = tree.set(('1', '2'), {'info': 'n1'})
        nA = tree.set(('a', 'b'), {'info': 'nA'})
        n2 = n1.set(('3', '4'), {'info': 'n2'})
        nB = nA.set(('c', 'd'), {'info': 'nB'})
        log.debug("root path: %s" % tree.path)
        log.debug("Node [1 2] path: %s" % n1.path)
        log.debug("Node [1 2 3 4] path: %s" % n2.path)
        log.debug("Node [a b] path: %s" % nA.path)
        log.debug("Node [a b c d] path: %s" % nB.path)

    def test_search(self):
        print
        log.info(self._testMethodName)
        tree = config_tree.ConfigTree()
        fileio = tree.set(('storage', 'fileio'))
        fileio.set(('disk', 'vm1'))
        fileio.set(('disk', 'vm2'))
        fileio.set(('disk', 'test1'))
        fileio.set(('disk', 'test2'))
        iblock = tree.set(('storage', 'iblock'))
        iblock.set(('disk', 'vm3'))
        iblock.set(('disk', 'vm4'))
        iblock.set(('disk', 'test1'))
        iblock.set(('disk', 'test2'))

        tests = [([("storage", ".*"), ("disk", "vm1")], 1),
                 ([("storage", ".*"), ("disk", "vm2")], 1),
                 ([("storage", ".*"), ("disk", "vm1")], 1),
                 ([("storage", "fileio"), ("disk", "vm[0-9]")], 2),
                 ([("storage", "file.*"), ("disk", "vm[0-9]")], 2),
                 ([("storage", ".*"), ("disk", "vm[0-9]")], 4),
                 ([("storage", ".*"), ("disk", ".*[12]")], 6),
                 ([("storage", ".*"), ("disk", ".*")], 8)]

        for search_path, arity in tests: 
            nodes = tree.search(search_path)
            self.failUnless(len(nodes) == arity)

        log.debug("Deleting iblock subtree")
        for node in tree.search([(".*", "iblock")]):
            tree.delete(node.path)

        tests = [([(".*", ".*"), ("disk", "vm1")], 1),
                 ([(".*", ".*"), ("disk", "vm2")], 1),
                 ([("storage", ".*"), ("disk", "vm1")], 1),
                 ([(".*", "fileio"), ("disk", "vm[0-9]")], 2),
                 ([(".*", "file.*"), ("disk", "vm[0-9]")], 2),
                 ([(".*", ".*"), ("disk", "vm[0-9]")], 2),
                 ([(".*", ".*"), (".*", ".*[12]")], 4),
                 ([(".*", ".*"), (".*", ".*")], 4)]

        for search_path, arity in tests: 
            nodes = tree.search(search_path)
            log.debug("search(%s) ->  %s" % (search_path, nodes))
            self.failUnless(len(nodes) == arity)

if __name__ == '__main__':
    unittest.main()
