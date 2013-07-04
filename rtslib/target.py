'''
Implements the RTS generic Target fabric classes.

This file is part of RTSLib.
Copyright (c) 2011-2013 by Datera, Inc

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

import re
import os
import glob
import uuid
import shutil

from node import CFSNode
from os.path import isdir
from doctest import testmod
from configobj import ConfigObj
from utils import RTSLibError, RTSLibBrokenLink, modprobe
from utils import is_ipv6_address, is_ipv4_address
from utils import fread, fwrite, generate_wwn, is_valid_wwn, exec_argv

class FabricModule(CFSNode):
    '''
    This is an interface to RTS Target Fabric Modules.
    It can load/unload modules, provide information about them and
    handle the configfs housekeeping. It uses module configuration
    files in /var/target/fabric/*.spec. After instantiation, whether or
    not the fabric module is loaded and
    '''

    version_attributes = set(["lio_version", "version"])
    discovery_auth_attributes = set(["discovery_auth"])
    target_names_excludes = version_attributes | discovery_auth_attributes

    # FabricModule private stuff
    def __init__(self, name):
        '''
        Instantiate a FabricModule object, according to the provided name.
        @param name: the name of the FabricModule object. It must match an
        existing target fabric module specfile (name.spec).
        @type name: str
        '''
        super(FabricModule, self).__init__()
        self.name = name
        self.spec = self._parse_spec()
        self._path = "%s/%s" % (self.configfs_dir,
                                self.spec['configfs_group'])
    # FabricModule public stuff

    def has_feature(self, feature):
        '''
        Whether or not this FabricModule has a certain feature.
        '''
        if feature in self.spec['features']:
            return True
        else:
            return False

    def load(self, yield_steps=False):
        '''
        Attempt to load the target fabric kernel module as defined in the
        specfile.
        @param yield_steps: Whether or not to yield an (action, taken, desc)
        tuple at each step: action is either 'load_module' or
        'create_cfs_group', 'taken' is a bool indicating whether the action was
        taken (if needed) or not, and desc is a text description of the step
        suitable for logging.
        @type yield_steps: bool
        @raises RTSLibError: For failure to load kernel module and/or create
        configfs group.
        '''
        module = self.spec['kernel_module']
        load_module = modprobe(module)
        if yield_steps:
            yield ('load_module', load_module,
                   "Loaded %s kernel module." % module)

        # TODO: Also load saved targets and config if needed. For that, support
        #  XXX: from the configfs side would be nice: have a config ID present
        #  XXX: both on the on-disk saved config and a configfs attibute.

        # Create the configfs group
        self._create_in_cfs_ine('any')
        if yield_steps:
            yield ('create_cfs_group', self._fresh,
                   "Created '%s'." % self.path)

    def _parse_spec(self):
        '''
        Parses the fabric module spec file.
        '''
        # Recognized options and their default values
        defaults = dict(features=['discovery_auth', 'acls', 'acls_auth', 'nps',
                                  'tpgts'],
                        kernel_module="%s_target_mod" % self.name,
                        configfs_group=self.name,
                        wwn_from_files=[],
                        wwn_from_files_filter='',
                        wwn_from_cmds=[],
                        wwn_from_cmds_filter='',
                        wwn_type='free')

        spec_file = "%s/%s.spec" % (self.spec_dir, self.name)
        spec = ConfigObj(spec_file).dict()
        if spec:
            self.spec_file = spec_file
        else:
            self.spec_file = ''

        # Do not allow unknown options
        unknown_options =  set(spec.keys()) - set(defaults.keys())
        if unknown_options:
            raise RTSLibError("Unknown option(s) in %s: %s"
                              % (spec_file, list(unknown_options)))

        # Use defaults for missing options
        missing_options = set(defaults.keys()) - set(spec.keys())
        for option in missing_options:
            spec[option] = defaults[option]

        # Type conversion and checking
        for option in spec:
            spec_type = type(spec[option]).__name__
            defaults_type = type(defaults[option]).__name__
            if spec_type != defaults_type:
                # Type mismatch, go through acceptable conversions
                if spec_type == 'str' and defaults_type == 'list':
                    spec[option] = [spec[option]]
                else:
                    raise RTSLibError("Wrong type for option '%s' in %s. "
                                      % (option, spec_file)
                                      + "Expected type '%s' and got '%s'."
                                      % (defaults_type, spec_type))

        # Generate the list of fixed WWNs if not empty
        wwn_list = None
        wwn_type = spec['wwn_type']

        if spec['wwn_from_files']:
            for wwn_pattern in spec['wwn_from_files']:
                for wwn_file in glob.iglob(wwn_pattern):
                    wwns_in_file = [wwn for wwn in
                                    re.split('\t|\0|\n| ', fread(wwn_file))
                                    if wwn.strip()]
                    if spec['wwn_from_files_filter']:
                        wwns_filtered = []
                        for wwn in wwns_in_file:
                            filter = "echo %s|%s" \
                                    % (wwn, spec['wwn_from_files_filter'])
                            wwns_filtered.append(exec_argv(filter, shell=True))
                    else:
                        wwns_filtered = wwns_in_file

                    if wwn_list is None:
                        wwn_list = set([])
                    wwn_list.update(set([wwn for wwn in wwns_filtered
                                         if is_valid_wwn(wwn_type, wwn)
                                         if wwn]
                                       ))
        if spec['wwn_from_cmds']:
            for wwn_cmd in spec['wwn_from_cmds']:
                cmd_result = exec_argv(wwn_cmd, shell=True)
                wwns_from_cmd = [wwn for wwn in
                                 re.split('\t|\0|\n| ', cmd_result)
                                 if wwn.strip()]
                if spec['wwn_from_cmds_filter']:
                    wwns_filtered = []
                    for wwn in wwns_from_cmd:
                        filter = "echo %s|%s" \
                                % (wwn, spec['wwn_from_cmds_filter'])
                        wwns_filtered.append(exec_argv(filter, shell=True))
                else:
                    wwns_filtered = wwns_from_cmd

                if wwn_list is None:
                    wwn_list = set([])
                wwn_list.update(set([wwn for wwn in wwns_filtered
                                     if is_valid_wwn(wwn_type, wwn)
                                     if wwn]
                                   ))

        spec['wwn_list'] = wwn_list
        return spec

    def _list_targets(self):
        if self.exists:
            return set(
                [Target(self, wwn, 'lookup')
                 for wwn in os.listdir(self.path)
                 if os.path.isdir("%s/%s" % (self.path, wwn))
                 if wwn not in self.target_names_excludes])
        else:
            return set([])

    def _get_version(self):
        if self.exists:
            for attr in self.version_attributes:
                path = "%s/%s" % (self.path, attr)
                if os.path.isfile(path):
                    return fread(path)
            else:
                raise RTSLibError("Can't find version for fabric module %s."
                                  % self.name)
        else:
            return None

    # FabricModule public stuff

    def is_valid_wwn(self, wwn):
        '''
        Checks whether or not the provided WWN is valid for this fabric module
        according to the spec file.
        '''
        return is_valid_wwn(self.spec['wwn_type'], wwn, self.spec['wwn_list'])

    def _assert_feature(self, feature):
        if not self.has_feature(feature):
            raise RTSLibError("This fabric module does not implement "
                              + "the %s feature." % feature)

    def _get_discovery_mutual_password(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_mutual_password(self, password):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password_mutual" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_discovery_mutual_userid(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_mutual_userid(self, userid):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid_mutual" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

    def _get_discovery_password(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_password(self, password):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_discovery_userid(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_userid(self, userid):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

    def _get_discovery_enable_auth(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/enforce_discovery_auth" % self.path
        value = fread(path).strip()
        return value

    def _set_discovery_enable_auth(self, enable):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/enforce_discovery_auth" % self.path
        if enable:
            enable = 1
        else:
            enable = 0
        fwrite(path, "%s" % enable)

    discovery_userid = \
            property(_get_discovery_userid,
                     _set_discovery_userid,
                     doc="Set or get the initiator discovery userid.")
    discovery_password = \
            property(_get_discovery_password,
                     _set_discovery_password,
                     doc="Set or get the initiator discovery password.")
    discovery_mutual_userid = \
            property(_get_discovery_mutual_userid,
                     _set_discovery_mutual_userid,
                     doc="Set or get the mutual discovery userid.")
    discovery_mutual_password = \
            property(_get_discovery_mutual_password,
                     _set_discovery_mutual_password,
                     doc="Set or get the mutual discovery password.")
    discovery_enable_auth = \
            property(_get_discovery_enable_auth,
                     _set_discovery_enable_auth,
                     doc="Set or get the discovery enable_auth flag.")

    targets = property(_list_targets,
                       doc="Get the list of target objects.")

    version = property(_get_version,
                       doc="Get the fabric module version string.")

class LUN(CFSNode):
    '''
    This is an interface to RTS Target LUNs in configFS.
    A LUN is identified by its parent TPG and LUN index.
    '''

    # LUN private stuff

    def __init__(self, parent_tpg, lun, storage_object=None, alias=None):
        '''
        A LUN object can be instantiated in two ways:
            - B{Creation mode}: If I{storage_object} is specified, the
              underlying configFS object will be created with that parameter.
              No LUN with the same I{lun} index can pre-exist in the parent TPG
              in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{storage_object} is not set, then the LUN
              will be bound to the existing configFS LUN object of the parent
              TPG having the specified I{lun} index. The underlying configFS
              object must already exist in that mode.

        @param parent_tpg: The parent TPG object.
        @type parent_tpg: TPG
        @param lun: The LUN index.
        @type lun: 0-255
        @param storage_object: The storage object to be exported as a LUN.
        @type storage_object: StorageObject subclass
        @param alias: An optional parameter to manually specify the LUN alias.
        You probably do not need this.
        @type alias: string
        @return: A LUN object.
        '''
        super(LUN, self).__init__()

        if isinstance(parent_tpg, TPG):
            self._parent_tpg = parent_tpg
        else:
            raise RTSLibError("Invalid parent TPG.")

        try:
            lun = int(lun)
        except ValueError:
            raise RTSLibError("Invalid LUN index: %s" % str(lun))
        else:
            if lun > 255 or lun < 0:
                raise RTSLibError("Invalid LUN index, it must be " \
                                  + "between 0 and 255: %d" % lun)
            self._lun = lun

        self._path = "%s/lun/lun_%d" % (self.parent_tpg.path, self.lun)

        if storage_object is None and alias is not None:
            raise RTSLibError("The alias parameter has no meaning " \
                              + "without the storage_object parameter.")

        if storage_object is not None:
            self._create_in_cfs_ine('create')
            try:
                self._configure(storage_object, alias)
            except:
                self.delete()
                raise
        else:
            self._create_in_cfs_ine('lookup')

    def _create_in_cfs_ine(self, mode):
        super(LUN, self)._create_in_cfs_ine(mode)

    def _configure(self, storage_object, alias):
        self._check_self()
        if alias is None:
            alias = str(uuid.uuid4())[-10:]
        else:
            alias = str(alias).strip()
            if '/' in alias:
                raise RTSLibError("Invalid alias: %s", alias)
        destination = "%s/%s" % (self.path, alias)
        from tcm import StorageObject
        if isinstance(storage_object, StorageObject):
            if storage_object.exists:
                source = storage_object.path
            else:
                raise RTSLibError("The storage_object does not exist " \
                                  + "in configFS.")
        else:
            raise RTSLibError("Invalid storage object.")

        os.symlink(source, destination)

    def _get_alias(self):
        self._check_self()
        alias = None
        for path in os.listdir(self.path):
            if os.path.islink("%s/%s" % (self.path, path)):
                alias = os.path.basename(path)
                break
        if alias is None:
            raise RTSLibBrokenLink("Broken LUN in configFS, no " \
                                         + "storage object attached.")
        else:
            return alias

    def _get_storage_object(self):
        self._check_self()
        alias_path = None
        for path in os.listdir(self.path):
            if os.path.islink("%s/%s" % (self.path, path)):
                alias_path = os.path.realpath("%s/%s" % (self.path, path))
                break
        if alias_path is None:
            raise RTSLibBrokenLink("Broken LUN in configFS, no "
                                   + "storage object attached.")
        from root import RTSRoot
        rtsroot = RTSRoot()
        for storage_object in rtsroot.storage_objects:
            if storage_object.path == alias_path:
                return storage_object
        raise RTSLibBrokenLink("Broken storage object link in LUN.")

    def _get_parent_tpg(self):
        return self._parent_tpg

    def _get_lun(self):
        return self._lun

    def _get_alua_metadata_path(self):
        return "%s/lun_%d" % (self.parent_tpg.alua_metadata_path, self.lun)

    def _list_mapped_luns(self):
        self._check_self()
        listdir = os.listdir
        realpath = os.path.realpath
        path = self.path

        tpg = self.parent_tpg
        if not tpg.has_feature('acls'):
            return []
        else:
            base = "%s/acls/" % tpg.path
            xmlun = ["param", "info", "cmdsn_depth", "auth", "attrib",
                     "node_name", "port_name"]
            return [MappedLUN(NodeACL(tpg, nodeacl), mapped_lun.split('_')[1])
                    for nodeacl in listdir(base)
                    for mapped_lun in listdir("%s/%s" % (base, nodeacl))
                    if mapped_lun not in xmlun
                    if isdir("%s/%s/%s" % (base, nodeacl, mapped_lun))
                    for link in listdir("%s/%s/%s" \
                                        % (base, nodeacl, mapped_lun))
                    if realpath("%s/%s/%s/%s" \
                                % (base, nodeacl, mapped_lun, link)) == path]

    # LUN public stuff

    def delete(self):
        '''
        If the underlying configFS object does not exists, this method does
        nothing. If the underlying configFS object exists, this method attempts
        to delete it along with all MappedLUN objects referencing that LUN.
        '''
        self._check_self()
        [mlun.delete() for mlun in self._list_mapped_luns()]
        try:
            link = self.alias
        except RTSLibBrokenLink:
            pass
        else:
            if os.path.islink("%s/%s" % (self.path, link)):
                os.unlink("%s/%s" % (self.path, link))

        super(LUN, self).delete()
        if os.path.isdir(self.alua_metadata_path):
            shutil.rmtree(self.alua_metadata_path)

    alua_metadata_path = property(_get_alua_metadata_path,
            doc="Get the ALUA metadata directory path for the LUN.")
    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    lun = property(_get_lun,
            doc="Get the LUN index as an int.")
    storage_object = property(_get_storage_object,
            doc="Get the storage object attached to the LUN.")
    alias = property(_get_alias,
            doc="Get the LUN alias.")
    mapped_luns = property(_list_mapped_luns,
            doc="List all MappedLUN objects referencing this LUN.")

class MappedLUN(CFSNode):
    '''
    This is an interface to RTS Target Mapped LUNs.
    A MappedLUN is a mapping of a TPG LUN to a specific initiator node, and is
    part of a NodeACL. It allows the initiator to actually access the TPG LUN
    if ACLs are enabled for the TPG. The initial TPG LUN will then be seen by
    the initiator node as the MappedLUN.
    '''

    # MappedLUN private stuff

    def __init__(self, parent_nodeacl, mapped_lun,
                 tpg_lun=None, write_protect=None):
        '''
        A MappedLUN object can be instantiated in two ways:
            - B{Creation mode}: If I{tpg_lun} is specified, the underlying
              configFS object will be created with that parameter. No MappedLUN
              with the same I{mapped_lun} index can pre-exist in the parent
              NodeACL in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{tpg_lun} is not set, then the MappedLUN will
              be bound to the existing configFS MappedLUN object of the parent
              NodeACL having the specified I{mapped_lun} index. The underlying
              configFS object must already exist in that mode.

        @param mapped_lun: The mapped LUN index.
        @type mapped_lun: int
        @param tpg_lun: The TPG LUN index to map, or directly a LUN object that
        belong to the same TPG as the
        parent NodeACL.
        @type tpg_lun: int or LUN
        @param write_protect: The write-protect flag value, defaults to False
        (write-protection disabled).
        @type write_protect: bool
        '''

        super(MappedLUN, self).__init__()

        if not isinstance(parent_nodeacl, NodeACL):
            raise RTSLibError("The parent_nodeacl parameter must be " \
                              + "a NodeACL object.")
        else:
            self._parent_nodeacl = parent_nodeacl
            if not parent_nodeacl.exists:
                raise RTSLibError("The parent_nodeacl does not exist.")

        try:
            self._mapped_lun = int(mapped_lun)
        except ValueError:
            raise RTSLibError("The mapped_lun parameter must be an " \
                              + "integer value.")

        self._path = "%s/lun_%d" % (self.parent_nodeacl.path, self.mapped_lun)

        if tpg_lun is None and write_protect is not None:
            raise RTSLibError("The write_protect parameter has no " \
                              + "meaning without the tpg_lun parameter.")

        if tpg_lun is not None:
            self._create_in_cfs_ine('create')
            try:
                self._configure(tpg_lun, write_protect)
            except:
                self.delete()
                raise
        else:
            self._create_in_cfs_ine('lookup')

    def _configure(self, tpg_lun, write_protect):
        self._check_self()
        if isinstance(tpg_lun, LUN):
            tpg_lun = tpg_lun.lun
        else:
            try:
                tpg_lun = int(tpg_lun)
            except ValueError:
                raise RTSLibError("The tpg_lun must be either an "
                                  + "integer or a LUN object.")
        # Check that the tpg_lun exists in the TPG
        for lun in self.parent_nodeacl.parent_tpg.luns:
            if lun.lun == tpg_lun:
                tpg_lun = lun
                break
        if not (isinstance(tpg_lun, LUN) and tpg_lun):
            raise RTSLibError("LUN %s does not exist in this TPG."
                              % str(tpg_lun))
        os.symlink(tpg_lun.path, "%s/%s"
                   % (self.path, str(uuid.uuid4())[-10:]))

        try:
            self.write_protect = int(write_protect) > 0
        except:
            self.write_protect = False

    def _get_alias(self):
        self._check_self()
        alias = None
        for path in os.listdir(self.path):
            if os.path.islink("%s/%s" % (self.path, path)):
                alias = os.path.basename(path)
                break
        if alias is None:
            raise RTSLibBrokenLink("Broken LUN in configFS, no " \
                                         + "storage object attached.")
        else:
            return alias

    def _get_mapped_lun(self):
        return self._mapped_lun

    def _get_parent_nodeacl(self):
        return self._parent_nodeacl

    def _set_write_protect(self, write_protect):
        self._check_self()
        path = "%s/write_protect" % self.path
        if write_protect:
            fwrite(path, "1")
        else:
            fwrite(path, "0")

    def _get_write_protect(self):
        self._check_self()
        path = "%s/write_protect" % self.path
        write_protect = fread(path).strip()
        if write_protect == "1":
            return True
        else:
            return False

    def _get_tpg_lun(self):
        self._check_self()
        path = os.path.realpath("%s/%s" % (self.path, self._get_alias()))
        for lun in self.parent_nodeacl.parent_tpg.luns:
            if lun.path == path:
                return lun

        raise RTSLibBrokenLink("Broken MappedLUN, no TPG LUN found !")

    def _get_node_wwn(self):
        self._check_self()
        return self.parent_nodeacl.node_wwn

    # MappedLUN public stuff

    def delete(self):
        '''
        Delete the MappedLUN.
        '''
        self._check_self()
        try:
            lun_link = "%s/%s" % (self.path, self._get_alias())
        except RTSLibBrokenLink:
            pass
        else:
            if os.path.islink(lun_link):
                os.unlink(lun_link)
        super(MappedLUN, self).delete()

    mapped_lun = property(_get_mapped_lun,
            doc="Get the integer MappedLUN mapped_lun index.")
    parent_nodeacl = property(_get_parent_nodeacl,
            doc="Get the parent NodeACL object.")
    write_protect = property(_get_write_protect, _set_write_protect,
            doc="Get or set the boolean write protection.")
    tpg_lun = property(_get_tpg_lun,
            doc="Get the TPG LUN object the MappedLUN is pointing at.")
    node_wwn = property(_get_node_wwn,
            doc="Get the wwn of the node for which the TPG LUN is mapped.")

class NodeACL(CFSNode):
    '''
    This is an interface to node ACLs in configFS.
    A NodeACL is identified by the initiator node wwn and parent TPG.
    '''

    # NodeACL private stuff

    def __init__(self, parent_tpg, node_wwn, mode='any'):
        '''
        @param parent_tpg: The parent TPG object.
        @type parent_tpg: TPG
        @param node_wwn: The wwn of the initiator node for which the ACL is
        created.
        @type node_wwn: string
        @param mode:An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up or
            created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A NodeACL object.
        '''

        super(NodeACL, self).__init__()

        if isinstance(parent_tpg, TPG):
            self._parent_tpg = parent_tpg
        else:
            raise RTSLibError("Invalid parent TPG.")

        self._node_wwn = str(node_wwn).lower()
        self._path = "%s/acls/%s" % (self.parent_tpg.path, self.node_wwn)
        self._create_in_cfs_ine(mode)

    def _get_node_wwn(self):
        return self._node_wwn

    def _get_parent_tpg(self):
        return self._parent_tpg

    def _get_tcq_depth(self):
        self._check_self()
        path = "%s/cmdsn_depth" % self.path
        return fread(path).strip()

    def _set_tcq_depth(self, depth):
        self._check_self()
        path = "%s/cmdsn_depth" % self.path
        try:
            fwrite(path, "%s" % depth)
        except IOError, msg:
            msg = msg[1]
            raise RTSLibError("Cannot set tcq_depth: %s" % str(msg))

    def _list_mapped_luns(self):
        self._check_self()
        mapped_luns = []
        mapped_lun_dirs = glob.glob("%s/lun_*" % self.path)
        for mapped_lun_dir in mapped_lun_dirs:
            mapped_lun = int(os.path.basename(mapped_lun_dir).split("_")[1])
            mapped_luns.append(MappedLUN(self, mapped_lun))
        return mapped_luns

    # NodeACL public stuff
    def has_feature(self, feature):
        '''
        Whether or not this NodeACL has a certain feature.
        '''
        return self.parent_tpg.has_feature(feature)

    def delete(self):
        '''
        Delete the NodeACL, including all MappedLUN objects.
        If the underlying configFS object does not exist, this method does
        nothing.
        '''
        self._check_self()
        for mapped_lun in self.mapped_luns:
            mapped_lun.delete()
        super(NodeACL, self).delete()

    def mapped_lun(self, mapped_lun, tpg_lun=None, write_protect=None):
        '''
        Same as MappedLUN() but without the parent_nodeacl parameter.
        '''
        self._check_self()
        return MappedLUN(self, mapped_lun=mapped_lun, tpg_lun=tpg_lun,
                         write_protect=write_protect)

    tcq_depth = property(_get_tcq_depth, _set_tcq_depth,
                         doc="Set or get the TCQ depth for the initiator " \
                         + "sessions matching this NodeACL.")
    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    node_wwn = property(_get_node_wwn,
            doc="Get the node wwn.")
    mapped_luns = property(_list_mapped_luns,
            doc="Get the list of all MappedLUN objects in this NodeACL.")

class NetworkPortal(CFSNode):
    '''
    This is an interface to NetworkPortals in configFS.  A NetworkPortal is
    identified by its IP and port, but here we also require the parent TPG, so
    instance objects represent both the NetworkPortal and its association to a
    TPG. This is necessary to get path information in order to create the
    portal in the proper configFS hierarchy.
    '''

    # NetworkPortal private stuff

    def __init__(self, parent_tpg, ip_address, port=3260, mode='any'):
        '''
        @param parent_tpg: The parent TPG object.
        @type parent_tpg: TPG
        @param ip_address: The ipv4 IP address of the NetworkPortal.
        @type ip_address: string
        @param port: The optional (defaults to 3260) NetworkPortal TCP/IP port.
        @type port: int
        @param mode: An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up or
              created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A NetworkPortal object.
        '''
        super(NetworkPortal, self).__init__()
        if not (is_ipv4_address(ip_address) or is_ipv6_address(ip_address)):
            raise RTSLibError("Invalid IP address: %s" % ip_address)
        else:
            self._ip_address = str(ip_address)

        try:
            self._port = int(port)
        except ValueError:
            raise RTSLibError("Invalid port.")

        if isinstance(parent_tpg, TPG):
            self._parent_tpg = parent_tpg
        else:
            raise RTSLibError("Invalid parent TPG.")

        if is_ipv4_address(ip_address):
            self._path = "%s/np/%s:%d" \
                    % (self.parent_tpg.path, self.ip_address, self.port)
        else:
            self._path = "%s/np/[%s]:%d" \
                    % (self.parent_tpg.path, self.ip_address, self.port)
        try:
            self._create_in_cfs_ine(mode)
        except OSError, msg:
            raise RTSLibError(msg[1])

    def _get_ip_address(self):
        return self._ip_address

    def _get_port(self):
        return self._port

    def _get_parent_tpg(self):
        return self._parent_tpg

    def _set_iser_attr(self, iser_attr):
        path = "%s/iser" % self.path
        if os.path.isfile(path):
            if iser_attr:
                fwrite(path, "1")
            else:
                fwrite(path, "0")
        else:
            raise RTSLibError("iser network portal attribute does not exist.")

    def _get_iser_attr(self):
        path = "%s/iser" % self.path
        if os.path.isfile(path):
            iser_attr = fread(path).strip()
            if iser_attr == "1":
                return True
            else:
                return False
        else:
            return False

    # NetworkPortal public stuff

    def delete(self):
        '''
        Delete the NetworkPortal.
        '''
        path = "%s/iser" % self.path
        if os.path.isfile(path):
            iser_attr = fread(path).strip()
            if iser_attr == "1":
                fwrite(path, "0")
        super(NetworkPortal, self).delete()

    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    port = property(_get_port,
            doc="Get the NetworkPortal's TCP port as an int.")
    ip_address = property(_get_ip_address,
            doc="Get the NetworkPortal's IP address as a string.")

class TPG(CFSNode):
    '''
    This is a an interface to Target Portal Groups in configFS.
    A TPG is identified by its parent Target object and its TPG Tag.
    To a TPG object is attached a list of NetworkPortals. Targets without
    the 'tpgts' feature cannot have more than a single TPG, so attempts
    to create more will raise an exception.
    '''

    # TPG private stuff

    def __init__(self, parent_target, tag, mode='any'):
        '''
        @param parent_target: The parent Target object of the TPG.
        @type parent_target: Target
        @param tag: The TPG Tag (TPGT).
        @type tag: int > 0
        @param mode:An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up or
              created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A TPG object.
        '''

        super(TPG, self).__init__()

        try:
            self._tag = int(tag)
        except ValueError:
            raise RTSLibError("Invalid Tag.")

        if tag < 1:
            raise RTSLibError("Invalig Tag, it must be >0.")

        if isinstance(parent_target, Target):
            self._parent_target = parent_target
        else:
            raise RTSLibError("Invalid parent Target.")

        self._path = "%s/tpgt_%d" % (self.parent_target.path, self.tag)

        target_path = self.parent_target.path
        if not self.has_feature('tpgts') and not os.path.isdir(self._path):
            for filename in os.listdir(target_path):
                if filename.startswith("tpgt_") \
                   and os.path.isdir("%s/%s" % (target_path, filename)) \
                   and filename != "tpgt_%d" % self.tag:
                    raise RTSLibError("Target cannot have multiple TPGs.")

        self._create_in_cfs_ine(mode)
        if self.has_feature('nexus') and not self._get_nexus():
            self._set_nexus()

    def _get_tag(self):
        return self._tag

    def _get_parent_target(self):
        return self._parent_target

    def _list_network_portals(self):
        self._check_self()
        if not self.has_feature('nps'):
            return []
        network_portals = []
        network_portal_dirs = os.listdir("%s/np" % self.path)
        for network_portal_dir in network_portal_dirs:
            if network_portal_dir.startswith('['):
                # IPv6 portals are [IPv6]:PORT
                (ip_address, port) = \
                        os.path.basename(network_portal_dir)[1:].split("]")
                port = port[1:]
            else:
                # IPv4 portals are IPv4:PORT
                (ip_address, port) = \
                        os.path.basename(network_portal_dir).split(":")
            port = int(port)
            network_portals.append(
                NetworkPortal(self, ip_address, port, 'lookup'))
        return network_portals

    def _get_enable(self):
        self._check_self()
        path = "%s/enable" % self.path
        # If the TPG does not have the enable attribute, then it is always
        # enabled.
        if os.path.isfile(path):
            return int(fread(path))
        else:
            return 1

    def _set_enable(self, boolean):
        '''
        Enables or disables the TPG. Raises an error if trying to disable a TPG
        without en enable attribute (but enabling works in that case).
        '''
        self._check_self()
        path = "%s/enable" % self.path
        if os.path.isfile(path):
            if boolean and not self._get_enable():
                fwrite(path, "1")
            elif not boolean and self._get_enable():
                fwrite(path, "0")
        elif not boolean:
            raise RTSLibError("TPG cannot be disabled.")

    def _get_nexus(self):
        '''
        Gets the nexus initiator WWN, or None if the TPG does not have one.
        '''
        self._check_self()
        if self.has_feature('nexus'):
            try:
                nexus_wwn = fread("%s/nexus" % self.path).strip()
            except IOError:
                nexus_wwn = ''
            return nexus_wwn
        else:
            return None

    def _set_nexus(self, nexus_wwn=None):
        '''
        Sets the nexus initiator WWN. Raises an exception if the nexus is
        already set or if the TPG does not use a nexus.
        '''
        self._check_self()
        if not self.has_feature('nexus'):
            raise RTSLibError("The TPG does not use a nexus.")
        elif self._get_nexus():
            raise RTSLibError("The TPG's nexus initiator WWN is already set.")
        else:
            if nexus_wwn is None:
                nexus_wwn = generate_wwn(self.parent_target.wwn_type)
            elif not is_valid_wwn(self.parent_target.wwn_type, nexus_wwn):
                raise RTSLibError("WWN '%s' is not of type '%s'."
                                  % (nexus_wwn, self.parent_target.wwn_type))
        fwrite("%s/nexus" % self.path, nexus_wwn)

    def _create_in_cfs_ine(self, mode):
        super(TPG, self)._create_in_cfs_ine(mode)
        if not os.path.isdir(self.alua_metadata_path):
            os.makedirs(self.alua_metadata_path)

    def _list_node_acls(self):
        self._check_self()
        if not self.has_feature('acls'):
            return []
        node_acls = []
        node_acl_dirs = [os.path.basename(path)
                         for path in os.listdir("%s/acls" % self.path)]
        for node_acl_dir in node_acl_dirs:
            node_acls.append(NodeACL(self, node_acl_dir, 'lookup'))
        return node_acls

    def _list_luns(self):
        self._check_self()
        luns = []
        lun_dirs = [os.path.basename(path)
                    for path in os.listdir("%s/lun" % self.path)]
        for lun_dir in lun_dirs:
            lun = lun_dir.split('_')[1]
            lun = int(lun)
            luns.append(LUN(self, lun))
        return luns

    def _control(self, command):
        self._check_self()
        path = "%s/control" % self.path
        fwrite(path, "%s\n" % str(command))

    def _get_alua_metadata_path(self):
        return "%s/%s+%d"  \
                % (self.alua_metadata_dir, self.parent_target.wwn, self.tag)

    # TPG public stuff

    def has_feature(self, feature):
        '''
        Whether or not this TPG has a certain feature.
        '''
        return self.parent_target.has_feature(feature)

    def delete(self):
        '''
        Recursively deletes a TPG object.
        This will delete all attached LUN, NetworkPortal and Node ACL objects
        and then the TPG itself. Before starting the actual deletion process,
        all sessions will be disconnected.
        '''
        self._check_self()

        path = "%s/enable" % self.path
        if os.path.isfile(path):
            self.enable = False

        for acl in self.node_acls:
            acl.delete()
        for lun in self.luns:
            lun.delete()
        for portal in self.network_portals:
            portal.delete()
        super(TPG, self).delete()
        # TODO: check that ALUA MD removal works while removing TPG
        if os.path.isdir(self.alua_metadata_path):
            shutil.rmtree(self.alua_metadata_path)

    def node_acl(self, node_wwn, mode='any'):
        '''
        Same as NodeACL() but without specifying the parent_tpg.
        '''
        self._check_self()
        return NodeACL(self, node_wwn=node_wwn, mode=mode)

    def network_portal(self, ip_address, port, mode='any'):
        '''
        Same as NetworkPortal() but without specifying the parent_tpg.
        '''
        self._check_self()
        return NetworkPortal(self, ip_address=ip_address, port=port, mode=mode)

    def lun(self, lun, storage_object=None, alias=None):
        '''
        Same as LUN() but without specifying the parent_tpg.
        '''
        self._check_self()
        return LUN(self, lun=lun, storage_object=storage_object, alias=alias)

    alua_metadata_path = property(_get_alua_metadata_path,
                                  doc="Get the ALUA metadata directory path " \
                                  + "for the TPG.")
    tag = property(_get_tag,
            doc="Get the TPG Tag as an int.")
    parent_target = property(_get_parent_target,
                             doc="Get the parent Target object to which the " \
                             + "TPG is attached.")
    enable = property(_get_enable, _set_enable,
                      doc="Get or set a boolean value representing the " \
                      + "enable status of the TPG. " \
                      + "True means the TPG is enabled, False means it is " \
                      + "disabled.")
    network_portals = property(_list_network_portals,
            doc="Get the list of NetworkPortal objects currently attached " \
                               + "to the TPG.")
    node_acls = property(_list_node_acls,
                         doc="Get the list of NodeACL objects currently " \
                         + "attached to the TPG.")
    luns = property(_list_luns,
                    doc="Get the list of LUN objects currently attached " \
                    + "to the TPG.")

    nexus = property(_get_nexus, _set_nexus,
                     doc="Get or set (once) the TPG's Nexus is used.")

class Target(CFSNode):
    '''
    This is an interface to Targets in configFS.
    A Target is identified by its wwn.
    To a Target is attached a list of TPG objects.
    '''

    # Target private stuff

    def __init__(self, fabric_module, wwn=None, mode='any'):
        '''
        @param fabric_module: The target's fabric module.
        @type fabric_module: FabricModule
        @param wwn: The optionnal Target's wwn.
            If no wwn or an empty wwn is specified, one will be generated
            for you.
        @type wwn: string
        @param mode:An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up
              or created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A Target object.
        '''

        super(Target, self).__init__()
        self.fabric_module = fabric_module
        self.wwn_type = fabric_module.spec['wwn_type']

        if wwn is not None:
            wwn = str(wwn).strip()
        elif fabric_module.spec['wwn_list']:
            existing_wwns = set([child.wwn for child in fabric_module.targets])
            free_wwns = fabric_module.spec['wwn_list'] - existing_wwns
            if free_wwns:
                wwn = free_wwns.pop()
            else:
                raise RTSLibError("All WWN are in use, can't create target.")
        else:
            wwn = generate_wwn(self.wwn_type)

        self.wwn = wwn
        self._path = "%s/%s" % (self.fabric_module.path, self.wwn)
        if not self:
            if not self.fabric_module.is_valid_wwn(self.wwn):
                raise RTSLibError("Invalid %s wwn: %s"
                                  % (self.wwn_type, self.wwn))
        self._create_in_cfs_ine(mode)

    def _list_tpgs(self):
        self._check_self()
        tpgs = []
        tpg_dirs = glob.glob("%s/tpgt*" % self.path)
        for tpg_dir in tpg_dirs:
            tag = os.path.basename(tpg_dir).split('_')[1]
            tag = int(tag)
            tpgs.append(TPG(self, tag, 'lookup'))
        return tpgs

    # Target public stuff

    def has_feature(self, feature):
        '''
        Whether or not this Target has a certain feature.
        '''
        return self.fabric_module.has_feature(feature)

    def delete(self):
        '''
        Recursively deletes a Target object.
        This will delete all attached TPG objects and then the Target itself.
        '''
        self._check_self()
        for tpg in self.tpgs:
            tpg.delete()
        super(Target, self).delete()

    tpgs = property(_list_tpgs, doc="Get the list of TPG for the Target.")

def _test():
    testmod()

if __name__ == "__main__":
    _test()
