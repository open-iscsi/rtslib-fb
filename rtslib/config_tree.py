'''
This file is part of the LIO SCSI Target.

Copyright (c) 2012-2014 by Datera, Inc.
More information on www.datera.io.

Original author: Jerome Martin <jxm@netiant.com>

Datera and LIO are trademarks of Datera, Inc., which may be registered in some
jurisdictions.

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.
'''
import re, copy, logging

DEBUG = False
if DEBUG:
    logging.basicConfig()
    log = logging.getLogger('ConfigTree')
    log.setLevel(logging.DEBUG)
else:
    log = logging.getLogger('ConfigTree')
    log.setLevel(logging.INFO)

NO_VALUE = '~~~'

def match_key(search_key, key):
    '''
    Matches search_key and key tuple items-for-item, with search_key containing
    regular expressions patterns or None values, and key containing string ir
    None values.
    '''
    log.debug("match_key(%s, %s)" % (search_key, key))
    if len(search_key) == len(key):
        for idx, pattern in enumerate(search_key):
            item = key[idx]
            if not pattern.endswith('$'):
                pattern = "%s$" % pattern
            if item is None and pattern is None:
                continue
            elif item is None:
                break
            else:
                match = re.match(pattern, item)
                if match is None:
                    break
        else:
            return True

class ConfigTreeError(Exception):
    pass

class ConfigTree(object):
    '''
    An ordered tree structure to hold configuration data.

    A node can be referred to by its path, relative to the current node.
    A path is a list of keys, each key a tuple of either string or None items.
    '''
    def __init__(self, data=None,
                 sort_key=lambda x:x,
                 key_to_string=lambda x:str(x)):
        '''
        Initializes a new ConfigTree.

        The optional sort_key is a function used when ordering children of a
        configuration node.

        The optional key_to_string is a function used when converting a node
        key to string.

        Direct instanciation should only happen for the root node of the tree.
        Adding a new node to the tree is achieved by using the set()
        method of the desired parent for that new node.
        '''
        self.data = data

        self._key = ()
        self._nodes = {}
        self._parent = None
        self._sort_key = sort_key
        self._key_to_string = key_to_string

    def __repr__(self):
        return "(%s)" % self.path_str

    def __str__(self):
        return self.path_str

    def get_clone(self, parent=None):
        '''
        Returns a clone of the ConfigTree, not sharing any mutable data.
        '''
        clone = ConfigTree(copy.deepcopy(self.data),
                           self._sort_key,
                           self._key_to_string)
        clone._parent = parent
        clone._key = self._key
        clone.data = copy.deepcopy(self.data)
        for node in self.nodes:
            clone._nodes[node.key] = node.get_clone(parent=clone)
        return clone

    @property
    def root(self):
        '''
        Returns the root node of the tree.
        '''
        cur = self
        while cur.parent:
            cur = cur.parent
        return cur

    @property
    def key(self):
        '''
        Returns the current node's key tuple.
        '''
        return self._key

    @property
    def key_str(self):
        '''
        Returns the current node's key as a string.
        '''
        return self._key_to_string(self.key)

    @property
    def path(self):
        '''
        Returns the node's full path from the tree root as a list of keys.
        '''
        if self.is_root:
            path = []
        else:
            path = self.parent.path + [self._key]
        return path

    @property
    def path_str(self):
        '''
        Returns the node's full path from the tree root as a string.
        '''
        strings = []
        for key in self.path:
            strings.append(self._key_to_string(key))
        return " ".join(strings)

    @property
    def nodes(self):
        '''
        Returns the list of all children nodes, sorted with potential
        dependencies first.
        '''
        nodes = sorted(self._nodes.values(), key=self._sort_key)
        return nodes

    @property
    def keys(self):
        '''
        Generates all children nodes keys, sorted with potential
        dependencies first.
        '''
        keys = (node.key for node in self.nodes)
        return keys

    @property
    def parent(self):
        '''
        Returns the parent node of the current node, or None.
        '''
        return self._parent

    @property
    def is_root(self):
        '''
        Returns True if this is a root node, else False.
        '''
        return self._parent == None

    def get(self, node_key):
        '''
        Returns the current node's child having node_key, or None.
        '''
        return self._nodes.get(node_key)

    def set(self, node_key, node_data=None):
        '''
        Creates and adds a child node to the current node, and returns that new
        node. If the node already exists, then a ConfigTreeError exception will
        be raised. Else, the new node will be returned.

        node_key is any tuple of strings
        node_data is an optional arbitrary value
        '''
        if node_key not in self.keys:
            new_node = ConfigTree(self.data,
                                  self._sort_key,
                                  self._key_to_string)
            new_node._parent = self
            new_node.data = node_data
            new_node._key = node_key
            self._nodes[node_key] = new_node
            return new_node
        else:
            raise ConfigTreeError("Node already exists, cannot set: %s"
                                  % self.get(node_key))

    def cine(self, node_key, node_data=None):
        '''
        cine stands for create if not exist: it makes sure a node exists.
        If it does not, it will create it using node_data.
        Else node_data will not be updated.

        Returns the matching node in all cases.

        node_key is any tuple of strings
        node_data is an optional arbitrary value
        '''
        if node_key in self.keys:
            log.debug("cine(%s %s) -> Already exists"
                      % (self.path_str, node_key))
            return self.get(node_key)
        else:
            log.debug("cine(%s %s) -> Creating"
                      % (self.path_str, node_key))
            return self.set(node_key, node_data)

    def update(self, node_key, node_data=None):
        '''
        If a node already has node_key as key, its data will be replaced with
        node_data. Else, it will be created using node_data.

        The matching node will be returned in both cases.

        node_key is any tuple of strings.
        node_data is an optional arbitrary value.
        '''
        try:
            node = self.set(node_key, node_data)
        except ConfigTreeError:
            node = self.get(node_key)
            node.data = node_data
        return node

    def delete(self, path):
        '''
        Given a path, deletes an entire subtree from the configuration,
        relative to the current node.

        The deleted subtree will be returned, or None is the path does not
        exist or is empty. The path must be a list of node keys.
        '''
        log.debug("delete(%s) getting subtree" % str(path))
        subtree = self.get_path(path)
        log.debug("delete(%s) got subtree: %s"
                  % (str(path), subtree))
        if subtree is not None:
            del subtree.parent._nodes[subtree.key]
        return subtree
    
    def get_path(self, path):
        '''
        Returns either the node matching path, relative to the current node, or
        None if the path does not exists.
        '''
        log.debug("get_path(%s)" % str(path))
        cur = self
        log.debug("get_path(%s) - cur: %s" % (str(path), cur))
        if path:
            for key in path:
                cur = cur.get(key)
                if cur is None:
                    break
            else:
                return cur

    def search(self, search_path, node_filter=lambda x:x):
        '''
        Returns a list of nodes matching the search_path, relative to the
        current node, or an empty list if no match was found.

        The search_path is a list of node search_key. Each will be matched
        against node key tuples items-for-item, with search_key containing
        regular expressions patterns or None values, and key containing string
        or None values.

        node_filter is a function applied to each node before returning it:
            node_filter(node_in) -> node_out | None (aka filtered out)
        '''
        results = []
        if search_path:
            search_key = search_path[0]
            for node in self.nodes:
                if match_key(search_key, node.key):
                    if search_path[1:]:
                        results.extend(node.search(search_path[1:]))
                    else:
                        node_out = node_filter(node)
                        if node_out is not None:
                            results.append(node_out)
        return results

    def walk(self, node_filter=lambda x:x):
        '''
        Returns a generator yielding our children's tree in depth-first order.

        node_filter is a function applied to each node before dumping it:
            node_filter(node_in) -> node_out | None (aka filtered out)

        When a node is filtered out, its children will still be walked and
        filtered/yielded as usual.
        '''
        for node_in in self.nodes:
            node_out = node_filter(node_in)
            if node_out is not None:
                yield node_out
            for next in node_in.walk(node_filter):
                yield next
