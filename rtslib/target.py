'''
Implements the RTS generic Target fabric classes.

This file is part of RTSLib Community Edition.
Copyright (c) 2011 by RisingTide Systems LLC

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, version 3 (AGPLv3).

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import re
import os
import glob
import uuid
import shutil

from node import CFSNode
from os.path import isdir
from doctest import testmod
from utils import RTSLibError, RTSLibBrokenLink, modprobe
from utils import is_ipv6_address, is_ipv4_address
from utils import fread, fwrite, generate_wwn, is_valid_wwn
from utils import dict_remove, set_attributes, set_parameters

# Where do we store the fabric modules spec files ?
spec_dir = "/var/lib/target/fabric"

class FabricModule(CFSNode):
    '''
    This is an interface to RTS Target Fabric Modules.
    It can load/unload modules, provide information about them and
    handle the configfs housekeeping. It uses module configuration
    files in /var/target/fabric/*.spec. After instanciation, whether or
    not the fabric module is loaded and
    '''

    version_attributes = set(["lio_version", "version"])
    discovery_auth_attributes = set(["discovery_auth"])
    target_names_excludes = version_attributes | discovery_auth_attributes

    @classmethod
    def all(cls):
        mod_names = [mod_name[:-5] for mod_name in os.listdir(spec_dir)
                     if mod_name.endswith('.spec')]
        for name in mod_names:
            yield FabricModule(name)


    # FabricModule private stuff
    def __init__(self, name):
        '''
        Instanciate a FabricModule object, according to the provided name.
        @param name: the name of the FabricModule object. It must match an
        existing target fabric module specfile (name.spec).
        @type name: str
        '''
        super(FabricModule, self).__init__()
        self.name = str(name)
        self.spec = self._parse_spec(spec_dir+"/"+name+".spec")
        self._path = "%s/%s" % (self.configfs_dir,
                                self.spec['configfs_group'])
    # FabricModule public stuff

    def _check_self(self):
        if not self.exists:
            modprobe(self.spec['kernel_module'])
            self._create_in_cfs_ine('any')
        super(FabricModule, self)._check_self()

    def has_feature(self, feature):
        '''
        Whether or not this FabricModule has a certain feature.
        '''
        if feature in self.spec['features']:
            return True
        else:
            return False

    def _parse_spec(self, spec_file):
        '''
        Parses the fabric module spec file.
        spec files are in Python, and may use functions defined for
        convenience in 'specfile_funcs' below
        '''

        def colonize(str):
            '''
            helper function for the specfiles to add colons every 2 chars
            '''
            new_str = ""
            while str:
                new_str += str[:2] + ":"
                str = str[2:]
            return new_str[:-1]

        specfile_funcs = dict(glob=glob.iglob, fread=fread, colonize=colonize)

        spec = dict(features=('discovery_auth', 'acls', 'acls_auth', 'nps',
                                  'tpgts'),
                        kernel_module="%s_target_mod" % self.name,
                        configfs_group=self.name,
                        wwn_type='free',
                        wwn_list=None,
                    )

        execfile(spec_file, specfile_funcs, spec)

        wwns = spec.get('wwns', None)
        if wwns:
            spec['wwn_list'] = list(wwns())

        return spec

    def _list_targets(self):
        if self.exists:
            for wwn in os.listdir(self.path):
                if os.path.isdir("%s/%s" % (self.path, wwn)) and \
                        wwn not in self.target_names_excludes:
                    yield Target(self, wwn, 'lookup')

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
        return is_valid_wwn(self.spec['wwn_type'], wwn)

    def needs_wwn(self):
        '''
        This fabric requires wwn to be specified when creating a target,
        it cannot be autogenerated.
        '''
        return self.spec['wwn_list'] != None

    def _assert_feature(self, feature):
        if not self.has_feature(feature):
            raise RTSLibError("This fabric module does not implement "
                              + "the %s feature." % feature)

    def clear_discovery_auth_settings(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        self.discovery_mutual_password = ''
        self.discovery_mutual_userid = ''
        self.discovery_password = ''
        self.discovery_userid = ''
        self.discovery_enable_auth = False

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
        return int(value)

    def _set_discovery_enable_auth(self, enable):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/enforce_discovery_auth" % self.path
        if int(enable):
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

    def setup(self, fm):
        '''
        Setup fabricmodule with settings from fm dict.
        Returns int of how many nonfatal errors were encountered
        '''
        for name, value in fm.iteritems():
            if name != 'name':
                setattr(self, name, value)
        return 0

    def dump(self):
        d = super(FabricModule, self).dump()
        d['name'] = self.name
        for attr in ("userid", "password", "mutual_userid", "mutual_password"):
            val = getattr(self, "discovery_" + attr, None)
            if val:
                d["discovery_" + attr] = val
        d['discovery_enable_auth'] = bool(int(self.discovery_enable_auth))
        return d


class LUN(CFSNode):
    '''
    This is an interface to RTS Target LUNs in configFS.
    A LUN is identified by its parent TPG and LUN index.
    '''

    MAX_LUN = 255

    # LUN private stuff

    def __init__(self, parent_tpg, lun=None, storage_object=None, alias=None):
        '''
        A LUN object can be instanciated in two ways:
            - B{Creation mode}: If I{storage_object} is specified, the
              underlying configFS object will be created with that parameter.
              No LUN with the same I{lun} index can pre-exist in the parent TPG
              in that mode, or instanciation will fail.
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

        if lun is None:
            luns = [lun.lun for lun in self.parent_tpg.luns]
            for index in xrange(self.MAX_LUN):
                if index not in luns:
                    lun = index
                    break
            if lun is None:
                raise RTSLibError("Cannot find an available LUN.")
        else:
            lun = int(lun)
            if lun < 0 or lun > self.MAX_LUN:
                raise RTSLibError("LUN must be 0 to %d" % self.MAX_LUN)

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

    def dump(self):
        d = super(LUN, self).dump()
        d['storage_object'] = "/backstores/%s/%s" % \
            (self.storage_object.plugin,  self.storage_object.name)
        d['index'] = self.lun
        return d


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
        A MappedLUN object can be instanciated in two ways:
            - B{Creation mode}: If I{tpg_lun} is specified, the underlying
              configFS object will be created with that parameter. No MappedLUN
              with the same I{mapped_lun} index can pre-exist in the parent
              NodeACL in that mode, or instanciation will fail.
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
        if write_protect:
            self.write_protect = True
        else:
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

    def dump(self):
        d = super(MappedLUN, self).dump()
        d['write_protect'] = self.write_protect
        d['index'] = self.mapped_lun
        d['tpg_lun'] = self.tpg_lun.lun
        return d


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

    def _get_chap_mutual_password(self):
        self._check_self()
        path = "%s/auth/password_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_mutual_password(self, password):
        self._check_self()
        path = "%s/auth/password_mutual" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_chap_mutual_userid(self):
        self._check_self()
        path = "%s/auth/userid_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_mutual_userid(self, userid):
        self._check_self()
        path = "%s/auth/userid_mutual" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

    def _get_chap_password(self):
        self._check_self()
        path = "%s/auth/password" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_password(self, password):
        self._check_self()
        path = "%s/auth/password" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_chap_userid(self):
        self._check_self()
        path = "%s/auth/userid" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_userid(self, userid):
        self._check_self()
        path = "%s/auth/userid" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

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

    def _get_authenticate_target(self):
        self._check_self()
        path = "%s/auth/authenticate_target" % self.path
        if fread(path).strip() == "1":
            return True
        else:
            return False

    def _list_mapped_luns(self):
        self._check_self()
        for mapped_lun_dir in glob.glob("%s/lun_*" % self.path):
            mapped_lun = int(os.path.basename(mapped_lun_dir).split("_")[1])
            yield MappedLUN(self, mapped_lun)

    def _get_session(self):
        lines = fread("%s/info" % self.path).splitlines()

        if lines[0].startswith("No active"):
            return None

        session = {}

        for line in lines:
            if line.startswith("InitiatorName:"):
                session['parent_nodeacl'] = self
                session['connections'] = []
            elif line.startswith("InitiatorAlias:"):
                session['alias'] = line.split(":")[1].strip()
            elif line.startswith("LIO Session ID:"):
                session['id'] = int(line.split(":")[1].split()[0])
                session['type'] = line.split("SessionType:")[1].split()[0].strip()
            elif "TARG_SESS_STATE_" in line:
                session['state'] = line.split("_STATE_")[1].split()[0]
            elif "TARG_CONN_STATE_" in line:
                cid = int(line.split(":")[1].split()[0])
                cstate = line.split("_STATE_")[1].split()[0]
                session['connections'].append(dict(cid=cid, cstate=cstate))
            elif "Address" in line:
                session['connections'][-1]['address'] = line.split()[1]
                session['connections'][-1]['transport'] = line.split()[2]

        return session

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

    chap_userid = property(_get_chap_userid, _set_chap_userid,
                           doc="Set or get the initiator CHAP auth userid.")
    chap_password = property(_get_chap_password, _set_chap_password,
                             doc=\
                             "Set or get the initiator CHAP auth password.")
    chap_mutual_userid = property(_get_chap_mutual_userid,
                                  _set_chap_mutual_userid,
                                  doc=\
                                  "Set or get the mutual CHAP auth userid.")
    chap_mutual_password = property(_get_chap_mutual_password,
                                    _set_chap_mutual_password,
                                    doc=\
                                    "Set or get the mutual CHAP password.")
    tcq_depth = property(_get_tcq_depth, _set_tcq_depth,
                         doc="Set or get the TCQ depth for the initiator " \
                         + "sessions matching this NodeACL.")
    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    node_wwn = property(_get_node_wwn,
            doc="Get the node wwn.")
    authenticate_target = property(_get_authenticate_target,
            doc="Get the boolean authenticate target flag.")
    mapped_luns = property(_list_mapped_luns,
            doc="Get the list of all MappedLUN objects in this NodeACL.")
    session = property(_get_session,
            doc="Gives a snapshot of the current session or C{None}")

    def dump(self):
        d = super(NodeACL, self).dump()
        if self.has_feature("acls_auth"):
            for attr in ("userid", "password", "mutual_userid", "mutual_password"):
                val = getattr(self, "chap_" + attr, None)
                if val:
                    d["chap_" + attr] = val
        d['node_wwn'] = self.node_wwn
        d['mapped_luns'] = [lun.dump() for lun in self.mapped_luns]
        return d


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

    # NetworkPortal public stuff

    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    port = property(_get_port,
            doc="Get the NetworkPortal's TCP port as an int.")
    ip_address = property(_get_ip_address,
            doc="Get the NetworkPortal's IP address as a string.")

    def dump(self):
        d = super(NetworkPortal, self).dump()
        d['port'] = self.port
        d['ip_address'] = self.ip_address
        return d


class TPG(CFSNode):
    '''
    This is a an interface to Target Portal Groups in configFS.
    A TPG is identified by its parent Target object and its TPG Tag.
    To a TPG object is attached a list of NetworkPortals. Targets without
    the 'tpgts' feature cannot have more than a single TPG, so attempts
    to create more will raise an exception.
    '''

    # TPG private stuff

    def __init__(self, parent_target, tag=None, mode='any'):
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

        if tag is None:
            tags = [tpg.tag for tpg in parent_target.tpgs]
            for index in xrange(1048576):
                if index not in tags and index > 0:
                    tag = index
                    break
            if tag is None:
                raise RTSLibError("Cannot find an available TPG Tag.")
        else:
            tag = int(tag)
            if not tag > 0:
                raise RTSLibError("The TPG Tag must be >0.")
        self._tag = tag

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
            return

        for network_portal_dir in os.listdir("%s/np" % self.path):
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
            yield NetworkPortal(self, ip_address, port, 'lookup')

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

    def _list_node_acls(self):
        self._check_self()
        if not self.has_feature('acls'):
            return

        node_acl_dirs = [os.path.basename(path)
                         for path in os.listdir("%s/acls" % self.path)]
        for node_acl_dir in node_acl_dirs:
            yield NodeACL(self, node_acl_dir, 'lookup')

    def _list_luns(self):
        self._check_self()
        lun_dirs = [os.path.basename(path)
                    for path in os.listdir("%s/lun" % self.path)]
        for lun_dir in lun_dirs:
            lun = lun_dir.split('_')[1]
            lun = int(lun)
            yield LUN(self, lun)

    def _control(self, command):
        self._check_self()
        path = "%s/control" % self.path
        fwrite(path, "%s\n" % str(command))

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

    def dump(self):
        d = super(TPG, self).dump()
        d['tag'] = self.tag
        d['enable'] = self.enable
        d['luns'] = [lun.dump() for lun in self.luns]
        d['portals'] = [portal.dump() for portal in self.network_portals]
        d['node_acls'] =  [acl.dump() for acl in self.node_acls]
        return d


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

        fabric_module._check_self()

	if not wwn and self.fabric_module.needs_wwn():
            raise RTSLibError("Must specify wwn for %s fabric" %
                              self.fabric_module.name)

        if wwn is not None:
            wwn = str(wwn).strip()
            if not fabric_module.is_valid_wwn(wwn):
                raise RTSLibError("Invalid wwn %s for %s fabric" %
                                  (wwn, self.fabric_module.name))
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
        if not self.fabric_module.is_valid_wwn(self.wwn):
            raise RTSLibError("Invalid %s wwn: %s"
                              % (self.wwn_type, self.wwn))
        self._create_in_cfs_ine(mode)

    def _list_tpgs(self):
        self._check_self()
        for tpg_dir in glob.glob("%s/tpgt*" % self.path):
            tag = os.path.basename(tpg_dir).split('_')[1]
            tag = int(tag)
            yield TPG(self, tag, 'lookup')

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

    @classmethod
    def setup(cls, fm_obj, storage_objects, t):
        '''
        Set up target objects based upon t dict, from saved config.
        Guard against missing or bad dict items, but keep going.
        Returns how many recoverable errors happened.
        '''

        try:
            t_obj = Target(fm_obj, t.get('wwn'))
        except RTSLibError:
            return 1

        errors = 0

        for tpg in t.get('tpgs', []):
            tpg_obj = TPG(t_obj)
            tpg_obj.enable = tpg.get('enable', True)
            set_attributes(tpg_obj, tpg.get('attributes', {})) 
            set_parameters(tpg_obj, tpg.get('parameters', {}))

            for lun in tpg.get('luns', []):
                try:
                    bs_name, so_name = lun['storage_object'].split('/')[2:]
                except:
                    errors += 1
                    continue

                for so in storage_objects:
                    if so_name == so.name and bs_name == so.plugin:
                        match_so = so
                        break
                else:
                    errors += 1
                    continue

                try:
                    LUN(tpg_obj, lun['index'], storage_object=match_so)
                except (RTSLibError, KeyError):
                    errors += 1

            for p in tpg.get('portals', []):
                try:
                    NetworkPortal(tpg_obj, p['ip_address'], p['port'])
                except (RTSLibError, KeyError):
                    errors += 1

            for acl in tpg.get('node_acls', []):
                try:
                    acl_obj = NodeACL(tpg_obj, acl['node_wwn'])
                    set_attributes(tpg_obj, tpg.get('attributes', {}))
                    for mlun in acl.get('mapped_luns', []):
                        # mapped lun needs to correspond with already-created
                        # TPG lun
                        for lun in tpg_obj.luns:
                            if lun.lun == mlun['tpg_lun']:
                                tpg_lun_obj = lun
                                break
                        else:
                            errors += 1
                            continue

                        try:
                            mlun_obj = MappedLUN(acl_obj, mlun['index'],
                                                 tpg_lun_obj, mlun.get('write_protect'))
                        except (RTSLibError, KeyError):
                            errors += 1
                            continue

                    dict_remove(acl, ('attributes', 'mapped_luns', 'node_wwn'))
                    for name, value in acl.iteritems():
                        if value:
                            setattr(acl_obj, name, value)
                except (RTSLibError, KeyError):
                    errors += 1

        return errors

    def dump(self):
        d = super(Target, self).dump()
        d['wwn'] = self.wwn
        d['fabric'] = self.fabric_module.name
        d['tpgs'] = [tpg.dump() for tpg in self.tpgs]
        return d


def _test():
    testmod()

if __name__ == "__main__":
    _test()
