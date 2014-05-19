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
import os, re, time, copy, logging

from rtslib.utils import is_ipv4_address, is_ipv6_address, is_valid_wwn

from config_filters import *
from config_tree import ConfigTree, NO_VALUE
from config_parser import ConfigParser, PolicyParser, PatternParser

DEBUG = False
if DEBUG:
    logging.basicConfig()
    log = logging.getLogger('Config')
    log.setLevel(logging.DEBUG)
else:
    log = logging.getLogger('Config')
    log.setLevel(logging.INFO)

# FIXME validate_* and _load_parse_tree are a mess !!!
# TODO Implement resync() to reload both policy and configfs state
# TODO Add class_match_ids (objs) and name_match_value (attrs) to search etc.
#      Use it to simplify all "%s .*" tricks in cli
# TODO Implement commit_live()
# TODO Custom defaults load
# TODO Add copy() operation

def dump_value(string):
    if string == NO_VALUE:
        return NO_VALUE
    for char in " ~\t{}#',;":
        if char in string:
            return '"%s"' % string
    if '"' in string:
        return "'%s'" % string
    elif not string:
        return '""'
    else:
        return string

def key_to_string(key):
    strings = []
    for item in key:
        strings.append(dump_value(item))
    return " ".join(strings)

def is_valid_backend(value, parent):
    cur = parent
    while cur.parent is not None:
        cur = cur.parent
    (backend, _, disk) = value.partition(':')
    if cur.search([("storage", backend), ("disk", disk)]):
        return True
    else:
        return False

def sort_key(node):
    '''
    A sort key for configuration nodes, that ensures nodes potentially
    referenced in the config come first: storage before fabric and lun
    objects before acl objects. Also, attributes will be sorted before
    objects, so that configuration dumps are easier to read, with simple
    attributes coming before attribute groups.
    '''
    node_type = node.data['type']
    obj_classes = ConfigParser.obj_classes
    ordered_obj = {}
    for k, v in enumerate(obj_classes.split()):
        ordered_obj[v] = "%s%s" % (k, v) 

    if node_type == 'attr':
        key = ('0', node.key[0], node.key[1])
    elif node_type == 'group':
        key = ('1', node.key[0])
    elif node_type == 'obj':
        key = ('2', ordered_obj.get(node.key[0], node.key[0]), node.key[1])
    else:
        raise ConfigError("Unknown configuration node type %s for %s"
                          % (node_type, node))

    return key

class ConfigError(Exception):
    pass

class Config(object):
    '''
    The LIO configuration API.

    The Config object provide methods to edit, search, validate and update the
    current configuration, and commit that configuration to the live system on
    request.

    It features pattern-matching search for all configuration objects and
    attributes as well as multi-level undo capabilities. In addition, all
    configuration changes are staged before being applied, isolating the
    current configuration from load-time and validation errors.
    '''
    policy_dir = "/var/target/policy"

    def __init__(self):
        data = {'source': {'operation': 'init', 'timestamp': time.time()},
                'type': 'root',
                'policy_path': []}
        self.policy = ConfigTree(data, sort_key, key_to_string)
        self.reference = ConfigTree(data, sort_key, key_to_string)

        self._parser = ConfigParser()
        self._policy_parser = PolicyParser()
        self._pattern_parser = PatternParser()
        self._configs = [ConfigTree(data, sort_key, key_to_string)]
        self._load_policy()

    def _load_policy(self):
        '''
        Loads all LIO system policy files.
        '''
        filepaths = ["%s/%s" % (self.policy_dir, path)
                     for path in os.listdir(self.policy_dir)
                     if path.endswith(".lio")]
        for filepath in filepaths:
            log.debug('Loading policy file %s' % filepath)
            parse_tree = self._policy_parser.parse_file(filepath)
            source = {'operation': 'load',
                      'filepath': filepath,
                      'timestamp': time.time(),
                      'mtime': os.path.getmtime(filepath)}
            self._load_parse_tree(parse_tree, replace=False,
                                  source=source, target='policy')

    def _load_parse_tree(self, parse_tree, cur_stage=None,
                         replace=False, source=None,
                         target='config', allow_new_attrs=False):
        '''
        target can be 'config', 'policy' or 'reference'
        '''
        # TODO accept 'defaults' target too
        if source is None:
            source = {}
        if cur_stage is None:
            update_target = True
            if replace:
                data = {'source': source, 'policy_path': [], 'type': 'root'}
                stage = ConfigTree(data, sort_key, key_to_string)
            elif target == 'config':
                stage = self.current.get_clone()
                stage.data['source'] = source
            elif target == 'policy':
                stage = self.policy.get_clone()
                stage.data['source'] = source
            elif target == 'reference':
                stage = self.reference.get_clone()
                stage.data['source'] = source
        else:
            update_target = False
            stage = cur_stage

        loaded = []
        log.debug("Loading parse tree %s" % parse_tree)
        for statement in parse_tree:
            cur = stage
            log.debug("Visiting statement %s" % statement)
            for token in statement:
                token['source'] = source
                log.debug("Visiting token %s" % token)
                if token['type'] == 'obj':
                    log.debug("Loading obj token: %s" % token)
                    if target != 'policy':
                        token = self.validate_obj(token, cur)
                    old = cur.get(token['key'])
                    cur = cur.cine(token['key'], token)
                    if not old:
                        loaded.append(cur)
                    if target != 'policy':
                        self._add_missing_attributes(cur)
                    log.debug("Added object %s" % cur.path)
                elif token['type'] == 'attr':
                    log.debug("Loading attr token: %s" % token)
                    if target != 'policy':
                        token = self.validate_attr(token, cur, allow_new_attrs)
                    old_nodes = cur.search([(token['key'][0], ".*")])
                    for old_node in old_nodes:
                        log.debug("Deleting old value: %s\nnew is: %s"
                                  % (old_node.path, str(token['key'])))
                        deleted = cur.delete([old_node.key])
                        log.debug("Deleted: %s" % str(deleted))
                    cur = cur.cine(token['key'], token)
                    if old_nodes and old_nodes[0].key != cur.key:
                        loaded.append(cur)
                    log.debug("Added attribute %s" % cur.path)
                elif token['type'] == 'group':
                    log.debug("Loading group token: %s" % token)
                    if target != 'policy':
                        log.debug("cur '%s' token '%s'" % (cur, token))
                        token['policy_path'] = (cur.data['policy_path']
                                                + [(token['key'][0],)])
                    old = cur.get(token['key'])
                    cur = cur.cine(token['key'], token)
                    if not old:
                        loaded.append(cur)
                elif token['type'] == 'block':
                    log.debug("Loading block token: %s" % token)
                    for statement in token['statements']:
                        log.debug("_load_parse_tree recursion on block "
                                  "statement: %s" % [statement])
                        loaded.extend(self._load_parse_tree(
                            [statement], cur, source=source,
                            target=target, allow_new_attrs=allow_new_attrs))

        if update_target:
            if target == 'config':
                self.current = stage
            elif target == 'policy':
                self.policy = stage
            elif target == 'reference':
                self.reference = stage

        return loaded

    def _add_missing_attributes(self, obj):
        '''
        Given an obj node, add all missing attributes and attribute groups in
        the configuration.
        '''
        source = {'operation': 'auto', 'timestamp': time.time()}
        policy_root = self.policy.get_path(obj.data['policy_path'])
        for policy_node in [node for node in policy_root.nodes
                            if node.data['type'] == 'attr']:
            attr = obj.search([(policy_node.key[0], ".*")])
            if not attr:
                key = (policy_node.key[0], policy_node.data.get('val_dfl'))
                data = {'key': key, 'type': 'attr', 'source': source,
                        'val_dfl': policy_node.data.get('val_dfl'),
                        'val_type': policy_node.data['val_type'],
                        'required': key[1] is None,
                        'policy_path': policy_node.path}
                log.debug("obj.set(%s, %s)" % (str(key), data))
                obj.set(key, data)

        groups = []
        for policy_node in [node for node in policy_root.nodes
                            if node.data['type'] == 'group']:
            group = obj.get((policy_node.key[0],))
            if not group:
                key = (policy_node.key[0],)
                data = {'key': key, 'type': 'group', 'source': source,
                        'policy_path': policy_node.path}
                groups.append(obj.set(key, data))
            else:
                groups.append(group)

        for group in groups:
            policy_root = self.policy.get_path(group.data['policy_path'])
            for policy_node in [node for node in policy_root.nodes
                                if node.data['type'] == 'attr']:
                attr = group.search([(policy_node.key[0], ".*")])
                if not attr:
                    key = (policy_node.key[0], policy_node.data.get('val_dfl'))
                    data = {'key': key, 'type': 'attr', 'source': source,
                            'val_dfl': policy_node.data.get('val_dfl'),
                            'val_type': policy_node.data['val_type'],
                            'required': key[1] is None,
                            'policy_path': policy_node.path}
                    group.set(key, data)

    def validate_val(self, value, val_type, parent=None): 
        valid_value = None
        log.debug("validate_val(%s, %s)" % (value, val_type))
        if value == NO_VALUE:
            return None

        if val_type == 'bool':
            if value.lower() in ['yes', 'true', '1', 'enable']:
                valid_value = 'yes'
            elif value.lower() in ['no', 'false', '0', 'disable']:
                valid_value = 'no'
        elif val_type == 'bytes':
            match = re.match(r'(\d+(\.\d*)?)([kKMGT]?B?$)', value)
            if match:
                qty = str(float(match.group(1)))
                unit = match.group(3).upper()
                if not unit.endswith('B'):
                    unit += 'B'
                valid_value = "%s%s" % (qty, unit)
        elif val_type == 'int':
            try:
                valid_value = str(int(value))
            except:
                pass
        elif val_type == 'ipport':
            (addr, _, port) = value.rpartition(":")
            try:
                str(int(port))
            except:
                pass
            else:
                if is_ipv4_address(addr) or is_ipv6_address(addr):
                    valid_value = value
        elif val_type == 'posint':
            try:
                val = int(value)
            except:
                pass
            else:
                if val > 0:
                    valid_value = value
        elif val_type == 'str':
            valid_value = str(value)
            forbidden = "*?[]"
            for char in forbidden:
                if char in valid_value:
                    valid_value = None
                    break
        elif val_type == 'erl':
            if value in ["0", "1", "2"]:
                valid_value = value
        elif val_type == 'iqn':
            if is_valid_wwn('iqn', value):
                valid_value = value
        elif val_type == 'naa':
            if is_valid_wwn('naa', value):
                valid_value = value
        elif val_type == 'backend':
            if is_valid_backend(value, parent):
                valid_value = value
        else:
            raise ConfigError("Unknown value type '%s' when validating %s"
                              % (val_type, value))
        log.debug("validate_val(%s) is a valid %s: %s"
                  % (value, val_type, valid_value))
        return valid_value

    def validate_obj(self, token, parent):
        log.debug("validate_obj(%s, %s)" % (token, parent.data))
        policy_search = parent.data['policy_path'] + [(token['key'][0], ".*")]
        policy_nodes = self.policy.search(policy_search)
        valid_token = copy.deepcopy(token)
        expected_val_types = set()

        for policy_node in policy_nodes:
            id_fixed = policy_node.data['id_fixed']
            id_type = policy_node.data['id_type']
            if id_fixed is not None:
                expected_val_types.add("'%s'" % id_fixed)
                if id_fixed == token['key'][1]:
                    valid_token['policy_path'] = policy_node.path
                    return valid_token
            else:
                expected_val_types.add(id_type)
                valid_value = self.validate_val(valid_token['key'][1], id_type)
                if valid_value is not None:
                    valid_token['key'] = (valid_token['key'][0], valid_value)
                    valid_token['policy_path'] = policy_node.path
                    return valid_token

        if not policy_nodes:
            obj_type = ("%s %s" % (parent.path_str, token['key'][0])).strip()
            raise ConfigError("Unknown object type: %s" % obj_type)
        else:
            raise ConfigError("Invalid %s identifier '%s': expected type %s"
                              % (token['key'][0],
                                 token['key'][1],
                                 ", ".join(expected_val_types)))

    def validate_attr(self, token, parent, allow_new_attr=False):
        log.debug("validate_attr(%s, %s)" % (token, parent.data))
        if token['key'][1] is None:
            return token

        policy_search = parent.data['policy_path'] + [(token['key'][0], ".*")]
        policy_nodes = self.policy.search(policy_search)
        valid_token = copy.deepcopy(token)
        expected_val_types = set()
        for policy_node in policy_nodes:
            ref_path = policy_node.data['ref_path']
            valid_token['required'] = policy_node.data['required']
            valid_token['comment'] = policy_node.data['comment']
            valid_token['val_dfl'] = policy_node.data.get('val_dfl')
            valid_token['val_type'] = policy_node.data['val_type']
            if ref_path is not None:
                root = parent
                if ref_path.startswith('-'):
                    (upno, _, down) = ref_path[1:].partition(' ')
                    for i in range(int(upno) - 1):
                        root = root.parent
                else:
                    while not root.is_root:
                        root = root.parent

                search_path = [(down, token['key'][1])]
                nodes = root.search(search_path)

                if len(nodes) == 1:
                    valid_token['ref_path'] = nodes[0].path_str
                    return valid_token
                elif len(nodes) == 0:
                    raise ConfigError("Invalid reference for attribute %s: %s"
                                      % (token['key'][0], search_path))
                else:
                    raise ConfigError("Unexpected reference error, got: %s"
                                      % nodes)

                return valid_token
            else:
                expected_val_types.add(policy_node.data['val_type'])
                if valid_token['key'][1] == NO_VALUE:
                    valid_value = NO_VALUE
                else:
                    valid_value = \
                            self.validate_val(valid_token['key'][1],
                                              policy_node.data['val_type'],
                                              parent=parent)
                if valid_value is not None:
                    valid_token['key'] = (valid_token['key'][0], valid_value)
                    return valid_token

        if not policy_nodes:
            if allow_new_attr:
                valid_token['required'] = False
                valid_token['comment'] = "Unknown"
                valid_token['val_dfl'] = valid_token['key'][1]
                valid_token['val_type'] = "raw"
                valid_token['ref_path'] = None
                return valid_token
            else:
                attr_name = ("%s %s"
                             % (parent.path_str, token['key'][0])).strip()
                raise ConfigError("Unknown attribute: %s" % attr_name)
        else:
            raise ConfigError("Invalid %s value '%s': expected type %s"
                              % (token['key'][0],
                                 token['key'][1],
                                 ", ".join(expected_val_types)))

    @property
    def current(self):
        return self._configs[-1]

    @current.setter
    def current(self, config_tree):
        self._configs.append(config_tree)

    def undo(self):
        '''
        Restores the previous state of the configuration, before the last set,
        load, delete, update or clear operation. If there is nothing to undo, a
        ConfigError exception will be raised.
        '''
        if len(self._configs) < 2:
            raise ConfigError("Nothing to undo")
        else:
            self._configs.pop()

    def set(self, configuration):
        '''
        Evaluates the configuration (a string in LIO configuration format) and
        sets the relevant objects, attributes and atttribute groups.

        Existing attributes and objects will be updated if needed and new ones
        will be added.

        The list of created configuration nodes will be returned.

        If an error occurs, the operation will be aborted, leaving the current
        configuration intact.
        '''
        parse_tree = self._parser.parse_string(configuration)
        source = {'operation': 'set',
                  'data': configuration,
                  'timestamp': time.time()}
        return self._load_parse_tree(parse_tree, source=source)

    def delete(self, pattern, node_filter=lambda x:x):
        '''
        Deletes all configuration objects and attributes whose paths match the
        pattern, along with their children.

        The pattern is a single LIO configuration statement without any block,
        where object identifiers, attributes names, attribute values and
        attribute groups are regular expressions patterns. Object types have to
        use their exact string representation to match.

        node_filter is a function applied to each node before returning it:
            node_filter(node_in) -> node_out | None (aka filtered out)

        Returns a list of all deleted nodes.

        If an error occurs, the operation will be aborted, leaving the current
        configuration intact.
        '''
        path = [token for token in
               self._pattern_parser.parse_string(pattern)]
        log.debug("delete(%s)" % pattern)
        source = {'operation': 'delete',
                  'pattern': pattern,
                  'timestamp': time.time()}
        stage = self.current.get_clone()
        stage.data['source'] = source
        deleted = []
        for node in stage.search(path, node_filter):
            log.debug("delete() found node %s" % node)
            deleted.append(stage.delete(node.path))
        self.current = stage
        return deleted

    def load(self, filepath, allow_new_attrs=False):
        '''
        Loads an LIO configuration file and replace the current configuration
        with it.

        All existing objects and attributes will be deleted, and new ones will
        be added.

        If an error occurs, the operation will be aborted, leaving the current
        configuration intact.
        '''
        parse_tree = self._parser.parse_file(filepath)
        source = {'operation': 'load',
                  'filepath': filepath,
                  'timestamp': time.time(),
                  'mtime': os.path.getmtime(filepath)}
        self._load_parse_tree(parse_tree, replace=True,
                              source=source, allow_new_attrs=allow_new_attrs)

    def load_live(self):
        '''
        Loads the live-running configuration.
        '''
        from config_live import dump_live
        live = dump_live()
        parse_tree = self._parser.parse_string(live)
        source = {'operation': 'resync',
                  'timestamp': time.time()}
        self._load_parse_tree(parse_tree, replace=True,
                              source=source, allow_new_attrs=True)

    def update(self, filepath):
        '''
        Updates the current configuration with the contents of an LIO
        configuration file.

        Existing attributes and objects will be updated if needed and new ones
        will be added.

        If an error occurs, the operation will be aborted, leaving the current
        configuration intact.
        '''
        parse_tree = self._parser.parse_file(filepath)
        source = {'operation': 'update',
                  'filepath': filepath,
                  'timestamp': time.time(),
                  'mtime': os.path.getmtime(filepath)}
        self._load_parse_tree(parse_tree, source=source)

    def clear(self):
        '''
        Clears the current configuration.

        This removes all current objects and attributes from the configuration.
        '''
        source = {'operation': 'clear',
                  'timestamp': time.time()}
        self.current = ConfigTree({'source': source}, sort_key, key_to_string)

    def search(self, search_statement, node_filter=lambda x:x):
        '''
        Returns a list of nodes matching the search_statement, relative to the
        current node, or an empty list if no match was found.

        The search_statement is a single LIO configuration statement without
        any block, where object identifiers, attributes names, attribute values
        and attribute groups are regular expressions patterns. Object types
        have to use their exact string representation to match.

        node_filter is a function applied to each node before returning it:
            node_filter(node_in) -> node_out | None (aka filtered out)
        '''
        path = [token for token in
               self._pattern_parser.parse_string(search_statement)]
        return self.current.search(path, node_filter)

    def dump(self, search_statement=None, node_filter=lambda x:x):
        '''
        Returns a LIO configuration file format dump of the nodes matching
        the search_statement, or of all nodes if search_statement is None.

        The search_statement is a single LIO configuration statement without
        any block, where object identifiers, attributes names, attribute values
        and attribute groups are regular expressions patterns. Object types
        have to use their exact string representation to match.

        node_filter is a function applied to each node before dumping it:
            node_filter(node_in) -> node_out | None (aka filtered out)
        '''
        # FIXME: Breaks with filter_only_missing
        if not search_statement:
            root_nodes = [self.current]
        else:
            root_nodes = self.search(search_statement, node_filter)

        if root_nodes:
            parts = []
            for root_node_in in root_nodes:
                root_node = node_filter(root_node_in)
                if root_node is None:
                    break
                dump = ''
                if root_node.key_str:
                    dump = "%s " % root_node.key_str
                nodes = root_node.nodes
                if root_node.is_root or len(nodes) == 1:
                    for node in nodes:
                        section = self.dump(node.path_str, node_filter)
                        if section:
                            dump += section
                elif len(nodes) > 1:
                    dump += "{\n"
                    for node in nodes:
                        section = self.dump(node.path_str, node_filter)
                        if section is not None:
                            lines = section.splitlines()
                        else:
                            lines = []
                        dump += "\n".join("    %s" % line
                                          for line in lines if line)
                        dump += "\n"
                    dump += "}\n"
                parts.append(dump)
            dump = "\n".join(parts)
            if dump.strip():
                return dump

    def save(self, filepath, pattern=None):
        '''
        Saves the current configuration to filepath, using LIO configuration
        file format. If path is not None, only objects and attributes starting
        at path and hanging under it will be saved.

        For convenience, the saved configuration will also be returned as a
        string.

        The pattern is a whitespace-separated string of regular expressions,
        each of which will be matched against configuration objects and
        attributes. In case of dump, the pattern must be non-ambiguous and
        match only a single configuration node.
        
        If the pattern matches either zero or more than one configuration
        nodes, a ConfigError exception will be raised.
        '''
        dump = self.dump(pattern, filter_no_missing)
        if dump is None:
            dump = ''
        with open(filepath, 'w') as f:
            f.write(dump)
        return dump

    def verify(self):
        '''
        Validates the configuration for the following points:
            - Portal IP Addresses exist
            - Devices and file paths exist
            - Files for fileio exist
            - No required attributes are missing
            - References are correct
        Returns a dictionary of validation_test: [errors]
        '''
        return {}

    def apply(self, brute_force=True):
        '''
        Applies the configuration to the live system:
            - Remove objects absent from the configuration and objects in the
              configuration with different required attributes
            - Create new storage objects
            - Create new fabric objects
            - Update relevant storage objects
            - Update relevant fabric objects
        '''
        from config_live import apply_create_obj, apply_delete_obj

        if brute_force:
            from config_live import apply_create_obj, clear_configfs
            yield "[clear] delete all live objects"
            clear_configfs()
            for obj in self.current.walk(get_filter_on_type(['obj'])):
                yield("[create] %s" % obj.path_str)
                apply_create_obj(obj)
        else:
            # TODO for minor_obj, update instead of create/delete
            diff = self.diff_live()
            delete_list = diff['removed'] + diff['major_obj'] + diff['minor_obj']
            delete_list.reverse()
            for obj in delete_list:
                yield "[delete] %s" % obj.path_str
                apply_delete_obj(obj)

            for obj in diff['created'] + diff['major_obj'] + diff['minor_obj']:
                yield "[create] %s" % obj.path_str
                apply_create_obj(obj)

    def diff_live(self):
        '''
        Returns a diff between the current configuration and the live
        configuration as a reference.
        '''
        from config_live import dump_live
        parse_tree = self._parser.parse_string(dump_live())
        source = {'operation': 'load',
                  'timestamp': time.time()}
        self._load_parse_tree(parse_tree, replace=True,
                              source=source, target='reference',
                              allow_new_attrs=True)
        return self.diff()

    def diff(self):
        '''
        Computes differences between a valid current configuration and a
        previously loaded valid reference configuration.

        Returns a dict of:
            - 'removed': list of removed objects
            - 'major': list of changed required attributes
            - 'major_obj': list of obj with major changes
            - 'minor': list of changed non-required attributes
            - 'major_obj': list of obj with minor changes
            - 'created': list of new objects in the current configuration
        '''
        # FIXME  data['required'] check should be enough without NO_VALUE check
        # FIXME Can't we just pass the reference config instead of having to preload it?
        diffs = {}
        keys = ('removed', 'major', 'major_obj',
                'minor', 'minor_obj', 'created')
        for key in keys:
            diffs[key] = []

        for obj in self.current.walk(get_filter_on_type(['obj'])):
            if not self.reference.get_path(obj.path):
                diffs['created'].append(obj)

        for obj in self.reference.walk(get_filter_on_type(['obj'])):
            if not self.current.get_path(obj.path):
                diffs['removed'].append(obj)

        for obj in self.current.walk(get_filter_on_type(['obj'])):
            if self.reference.get_path(obj.path):
                for node in obj.nodes:
                    if node.data['type'] == 'attr' \
                       and (node.data['required'] \
                            or node.key[1] == NO_VALUE):
                        if not self.reference.get_path(node.path):
                            diffs['major'].append(node)
                            diffs['major_obj'].append(node.parent)

        for obj in self.current.walk(get_filter_on_type(['obj'])):
            if self.reference.get_path(obj.path):
                for node in obj.nodes:
                    if node.data['type'] == 'attr' \
                       and not node.data['required'] \
                       and node.key[1] != NO_VALUE:
                        if not self.reference.get_path(node.path):
                            diffs['minor'].append(node)
                            if node.parent not in diffs['minor_obj'] \
                               and node.parent not in diffs['major_obj']:
                                diffs['minor_obj'].append(node.parent)
                    elif node.data['type'] == 'group':
                        for attr in node.nodes:
                            if attr.data['type'] == 'attr' \
                               and not attr.data['required'] \
                               and attr.key[1] != NO_VALUE:
                                if not self.reference.get_path(attr.path):
                                    diffs['minor'].append(attr)
                                    if node.parent not in diffs['minor_obj'] \
                                       and node.parent not in diffs['major_obj']:
                                        diffs['minor_obj'].append(node.parent)
        return diffs
