'''
Implements the RTS generic Target fabric classes.

This file is part of RTSLib.
Copyright (c) 2011-2013 by Datera, Inc.
Copyright (c) 2011-2014 by Red Hat, Inc.

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

import os
from glob import iglob as glob
from functools import partial
from six.moves import range
import uuid

from .node import CFSNode
from .utils import RTSLibBrokenLink, RTSLibError
from .utils import fread, fwrite, normalize_wwn, generate_wwn
from .utils import dict_remove, set_attributes, set_parameters, ignored
from .utils import _get_auth_attr, _set_auth_attr
from . import tcm

import six

auth_params = ('userid', 'password', 'mutual_userid', 'mutual_password')

class Target(CFSNode):
    '''
    This is an interface to Targets in configFS.
    A Target is identified by its wwn.
    To a Target is attached a list of TPG objects.
    '''

    # Target private stuff

    def __repr__(self):
        return "<Target %s/%s>" % (self.fabric_module.name, self.wwn)

    def __init__(self, fabric_module, wwn=None, mode='any'):
        '''
        @param fabric_module: The target's fabric module.
        @type fabric_module: FabricModule
        @param wwn: The optional Target's wwn.
            If no wwn is specified, one will be generated.
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

        fabric_module._check_self()

        if wwn is not None:
            # old versions used wrong NAA prefix, fixup
            if wwn.startswith("naa.6"):
                wwn = "naa.5" + wwn[5:]
            self.wwn, self.wwn_type = fabric_module.to_normalized_wwn(wwn)
        elif not fabric_module.wwns:
            self.wwn = generate_wwn(fabric_module.wwn_types[0])
            self.wwn_type = fabric_module.wwn_types[0]
        else:
            raise RTSLibError("Fabric cannot generate WWN but it was not given")

        # Checking is done, convert to format the fabric wants
        fabric_wwn = fabric_module.to_fabric_wwn(self.wwn)
        self._path = "%s/%s" % (self.fabric_module.path, fabric_wwn)
        self._create_in_cfs_ine(mode)

    def _list_tpgs(self):
        self._check_self()
        for tpg_dir in glob("%s/tpgt*" % self.path):
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
    def setup(cls, fm_obj, t, err_func):
        '''
        Set up target objects based upon t dict, from saved config.
        Guard against missing or bad dict items, but keep going.
        Call 'err_func' for each error.
        '''

        if 'wwn' not in t:
            err_func("'wwn' not defined for Target")
            return

        try:
            t_obj = Target(fm_obj, t['wwn'])
        except RTSLibError as e:
            err_func("Could not create Target object: %s" % e)
            return

        for tpg in t.get('tpgs', []):
            TPG.setup(t_obj, tpg, err_func)

    def dump(self):
        d = super(Target, self).dump()
        d['wwn'] = self.wwn
        d['fabric'] = self.fabric_module.name
        d['tpgs'] = [tpg.dump() for tpg in self.tpgs]
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

    def __repr__(self):
        return "<TPG %d>" % self.tag

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
            for index in range(1048576):
                if index not in tags and index > 0:
                    tag = index
                    break
            if tag is None:
                raise RTSLibError("Cannot find an available TPG Tag")
        else:
            tag = int(tag)
            if not tag > 0:
                raise RTSLibError("The TPG Tag must be >0")
        self._tag = tag

        if isinstance(parent_target, Target):
            self._parent_target = parent_target
        else:
            raise RTSLibError("Invalid parent Target")

        self._path = "%s/tpgt_%d" % (self.parent_target.path, self.tag)

        target_path = self.parent_target.path
        if not self.has_feature('tpgts') and not os.path.isdir(self._path):
            for filename in os.listdir(target_path):
                if filename.startswith("tpgt_") \
                   and os.path.isdir("%s/%s" % (target_path, filename)) \
                   and filename != "tpgt_%d" % self.tag:
                    raise RTSLibError("Target cannot have multiple TPGs")

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
            (ip_address, port) = \
                os.path.basename(network_portal_dir).rsplit(":", 1)
            port = int(port)
            yield NetworkPortal(self, ip_address, port, 'lookup')

    def _get_enable(self):
        self._check_self()
        path = "%s/enable" % self.path
        # If the TPG does not have the enable attribute, then it is always
        # enabled.
        if os.path.isfile(path):
            return bool(int(fread(path)))
        else:
            return True

    def _set_enable(self, boolean):
        '''
        Enables or disables the TPG. If the TPG doesn't support the enable
        attribute, do nothing.
        '''
        self._check_self()
        path = "%s/enable" % self.path
        if os.path.isfile(path) and (boolean != self._get_enable()):
            try:
                fwrite(path, str(int(boolean)))
            except IOError as e:
                raise RTSLibError("Cannot change enable state: %s" % e)

    def _get_nexus(self):
        '''
        Gets the nexus initiator WWN, or None if the TPG does not have one.
        '''
        self._check_self()
        if self.has_feature('nexus'):
            try:
                nexus_wwn = fread("%s/nexus" % self.path)
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
            raise RTSLibError("The TPG does not use a nexus")
        if self._get_nexus():
            raise RTSLibError("The TPG's nexus initiator WWN is already set")

        fm = self.parent_target.fabric_module

        if nexus_wwn:
            nexus_wwn = fm.to_normalized_wwn(nexus_wwn)[0]
        else:
            # Nexus wwn type should match parent target
            nexus_wwn = generate_wwn(self.parent_target.wwn_type)

        fwrite("%s/nexus" % self.path, fm.to_fabric_wwn(nexus_wwn))

    def _list_node_acls(self):
        self._check_self()
        if not self.has_feature('acls'):
            return

        node_acl_dirs = [os.path.basename(path)
                         for path in os.listdir("%s/acls" % self.path)]
        for node_acl_dir in node_acl_dirs:
            fm = self.parent_target.fabric_module
            yield NodeACL(self, fm.from_fabric_wwn(node_acl_dir), 'lookup')

    def _list_node_acl_groups(self):
        self._check_self()
        if not self.has_feature('acls'):
            return

        names = set([])

        for na in self.node_acls:
            tag = na.tag
            if tag:
                names.add(tag)

        return (NodeACLGroup(self, n) for n in names)

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
    node_acl_groups = property(_list_node_acl_groups,
                         doc="Get the list of NodeACL groups currently " \
                         + "attached to the TPG.")
    luns = property(_list_luns,
                    doc="Get the list of LUN objects currently attached " \
                    + "to the TPG.")

    nexus = property(_get_nexus, _set_nexus,
                     doc="Get or set (once) the TPG's Nexus is used.")

    chap_userid = property(partial(_get_auth_attr, attribute='auth/userid', ignore=True),
                           partial(_set_auth_attr, attribute='auth/userid', ignore=True),
                           doc="Set or get the initiator CHAP auth userid.")
    chap_password = property(partial(_get_auth_attr, attribute='auth/password', ignore=True),
                             partial(_set_auth_attr, attribute='auth/password', ignore=True),
                             doc="Set or get the initiator CHAP auth password.")
    chap_mutual_userid = property(partial(_get_auth_attr, attribute='auth/userid_mutual', ignore=True),
                                  partial(_set_auth_attr, attribute='auth/userid_mutual', ignore=True),
                                  doc="Set or get the initiator CHAP auth userid.")
    chap_mutual_password = property(partial(_get_auth_attr, attribute='auth/password_mutual', ignore=True),
                                    partial(_set_auth_attr, attribute='auth/password_mutual', ignore=True),
                                    doc="Set or get the initiator CHAP auth password.")

    def _get_authenticate_target(self):
        self._check_self()
        path = "%s/auth/authenticate_target" % self.path
        try:
            return bool(int(fread(path)))
        except:
            return None

    authenticate_target = property(_get_authenticate_target,
                                   doc="Get the boolean authenticate target flag.")

    @classmethod
    def setup(cls, t_obj, tpg, err_func):
        tpg_obj = cls(t_obj, tag=tpg.get("tag", None))
        set_attributes(tpg_obj, tpg.get('attributes', {}), err_func)
        set_parameters(tpg_obj, tpg.get('parameters', {}), err_func)

        for lun in tpg.get('luns', []):
            LUN.setup(tpg_obj, lun, err_func)

        for p in tpg.get('portals', []):
            NetworkPortal.setup(tpg_obj, p, err_func)

        for acl in tpg.get('node_acls', []):
            NodeACL.setup(tpg_obj, acl, err_func)

        tpg_obj.enable = tpg.get('enable', True)
        dict_remove(tpg, ('luns', 'portals', 'node_acls', 'tag',
                          'attributes', 'parameters', 'enable'))
        for name, value in six.iteritems(tpg):
            if value:
                try:
                    setattr(tpg_obj, name, value)
                except:
                    err_func("Could not set tpg %s attribute '%s'" %
                             (tpg_obj.tag, name))

    def dump(self):
        d = super(TPG, self).dump()
        d['tag'] = self.tag
        d['enable'] = self.enable
        d['luns'] = [lun.dump() for lun in self.luns]
        d['portals'] = [portal.dump() for portal in self.network_portals]
        d['node_acls'] =  [acl.dump() for acl in self.node_acls]
        if self.has_feature("auth"):
            for attr in auth_params:
                val = getattr(self, "chap_" + attr, None)
                if val:
                    d["chap_" + attr] = val
        return d


class LUN(CFSNode):
    '''
    This is an interface to RTS Target LUNs in configFS.
    A LUN is identified by its parent TPG and LUN index.
    '''

    MAX_LUN = 255

    # LUN private stuff

    def __repr__(self):
        return "<LUN %d (%s/%s)>" % (self.lun, self.storage_object.plugin,
                                    self.storage_object.name)

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
            raise RTSLibError("Invalid parent TPG")

        if lun is None:
            luns = [l.lun for l in self.parent_tpg.luns]
            for index in range(self.MAX_LUN+1):
                if index not in luns:
                    lun = index
                    break
            if lun is None:
                raise RTSLibError("All LUNs 0-%d in use" % self.MAX_LUN)
        else:
            lun = int(lun)
            if lun < 0 or lun > self.MAX_LUN:
                raise RTSLibError("LUN must be 0 to %d" % self.MAX_LUN)

        self._lun = lun

        self._path = "%s/lun/lun_%d" % (self.parent_tpg.path, self.lun)

        if storage_object is None and alias is not None:
            raise RTSLibError("The alias parameter has no meaning " \
                              + "without the storage_object parameter")

        if storage_object is not None:
            self._create_in_cfs_ine('create')
            try:
                self._configure(storage_object, alias)
            except:
                self.delete()
                raise
        else:
            self._create_in_cfs_ine('lookup')

    def _configure(self, storage_object, alias):
        self._check_self()
        if alias is None:
            alias = str(uuid.uuid4())[-10:]
        else:
            alias = str(alias).strip()
            if '/' in alias:
                raise RTSLibError("Invalid alias: %s", alias)

        destination = "%s/%s" % (self.path, alias)

        if storage_object.exists:
            source = storage_object.path
        else:
            raise RTSLibError("storage_object does not exist in configFS")

        os.symlink(source, destination)

    def _get_alias(self):
        self._check_self()
        for path in os.listdir(self.path):
            if os.path.islink("%s/%s" % (self.path, path)):
                return os.path.basename(path)

        raise RTSLibBrokenLink("Broken LUN in configFS, no storage object")

    def _get_storage_object(self):
        self._check_self()
        alias_path = os.path.realpath("%s/%s" % (self.path, self.alias))
        return tcm.StorageObject.so_from_path(alias_path)

    def _get_parent_tpg(self):
        return self._parent_tpg

    def _get_lun(self):
        return self._lun

    def _list_mapped_luns(self):
        self._check_self()

        tpg = self.parent_tpg
        if not tpg.has_feature('acls'):
            return

        for na in tpg.node_acls:
            for mlun in na.mapped_luns:
                if os.path.realpath("%s/%s" % (mlun.path, mlun.alias)) == self.path:
                    yield mlun


    # pass through backends will not have setup all the default
    # ALUA structs in the kernel. If the kernel has been setup,
    # a user created group or default_tg_pt_gp will be returned.
    # If the kernel was not properly setup an empty string is
    # return in alua_tg_pt_gp. Writing to alua_tg_pt_gp will crash
    # older kernels and will return a -Exyz code in newer ones.
    def _get_alua_tg_pt_gp_name(self):
        self._check_self()

        storage_object = self._get_storage_object()
        if storage_object.alua_supported is False:
            return None

        path = "%s/alua_tg_pt_gp" % self.path
        try:
            info = fread(path)
            if not info:
                return None
            group_line = info.splitlines()[0]
            return group_line.split(':')[1].strip()
        except IOError as e:
            return None

    def _set_alua_tg_pt_gp_name(self, group_name):
        self._check_self()

        if not self._get_alua_tg_pt_gp_name():
            return -1

        path = "%s/alua_tg_pt_gp" % self.path
        try:
            fwrite(path, group_name)
        except IOError as e:
            return -1

        return 0

    # LUN public stuff

    def delete(self):
        '''
        If the underlying configFS object does not exist, this method does
        nothing. If the underlying configFS object exists, this method attempts
        to delete it along with all MappedLUN objects referencing that LUN.
        '''
        self._check_self()

        for mlun in self.mapped_luns:
            mlun.delete()

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
    alua_tg_pt_gp_name = property(_get_alua_tg_pt_gp_name, _set_alua_tg_pt_gp_name,
            doc="Get and Set the LUN's ALUA Target Port Group")

    @classmethod
    def setup(cls, tpg_obj, lun, err_func):
        if 'index' not in lun:
            err_func("'index' missing from a LUN in TPG %d" % tpg_obj.tag)
            return

        try:
            bs_name, so_name = lun['storage_object'].split('/')[2:]
        except:
            err_func("Malformed storage object field for LUN %d" % lun['index'])
            return

        for so in tcm.StorageObject.all():
            if so_name == so.name and bs_name == so.plugin:
                match_so = so
                break
        else:
            err_func("Could not find matching StorageObject for LUN %d" % lun['index'])
            return

        try:
           lun_obj =  cls(tpg_obj, lun['index'], storage_object=match_so, alias=lun.get('alias'))
        except (RTSLibError, KeyError):
            err_func("Creating TPG %d LUN index %d failed" %
                     (tpg_obj.tag, lun['index']))

        try:
            lun_obj.alua_tg_pt_gp_name = lun['alua_tg_pt_gp_name']
        except KeyError:
            # alua_tg_pt_gp support not present in older versions
            pass

    def dump(self):
        d = super(LUN, self).dump()
        d['storage_object'] = "/backstores/%s/%s" % \
            (self.storage_object.plugin,  self.storage_object.name)
        d['index'] = self.lun
        d['alias'] = self.alias
        d['alua_tg_pt_gp_name'] = self.alua_tg_pt_gp_name
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

    def __repr__(self):
        return "<NetworkPortal %s port %s>" % (self.ip_address, self.port)

    def __init__(self, parent_tpg, ip_address, port=3260, mode='any'):
        '''
        @param parent_tpg: The parent TPG object.
        @type parent_tpg: TPG
        @param ip_address: The ipv4/v6 IP address of the NetworkPortal. ipv6
            addresses should be surrounded by '[]'.
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

        self._ip_address = str(ip_address)

        try:
            self._port = int(port)
        except ValueError:
            raise RTSLibError("Invalid port")

        if isinstance(parent_tpg, TPG):
            self._parent_tpg = parent_tpg
        else:
            raise RTSLibError("Invalid parent TPG")

        self._path = "%s/np/%s:%d" \
            % (self.parent_tpg.path, self.ip_address, self.port)

        try:
            self._create_in_cfs_ine(mode)
        except OSError as msg:
            raise RTSLibError(msg)

    def _get_ip_address(self):
        return self._ip_address

    def _get_port(self):
        return self._port

    def _get_parent_tpg(self):
        return self._parent_tpg

    def _get_iser(self):
        try:
            return bool(int(fread("%s/iser" % self.path)))
        except IOError:
            return False

    def _set_iser(self, boolean):
        path = "%s/iser" % self.path
        try:
            fwrite(path, str(int(boolean)))
        except IOError:
            # b/w compat: don't complain if iser entry is missing
            if os.path.isfile(path):
                raise RTSLibError("Cannot change iser")

    def _get_offload(self):
        try:
            # only offload at the moment is cxgbit
            return bool(int(fread("%s/cxgbit" % self.path)))
        except IOError:
            return False

    def _set_offload(self, boolean):
        path = "%s/cxgbit" % self.path
        try:
            fwrite(path, str(int(boolean)))
        except IOError:
            # b/w compat: don't complain if cxgbit entry is missing
            if os.path.isfile(path):
                raise RTSLibError("Cannot change offload")

    # NetworkPortal public stuff

    def delete(self):
        self.iser = False
        self.offload = False
        super(NetworkPortal, self).delete()

    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    port = property(_get_port,
            doc="Get the NetworkPortal's TCP port as an int.")
    ip_address = property(_get_ip_address,
            doc="Get the NetworkPortal's IP address as a string.")
    iser = property(_get_iser, _set_iser,
                    doc="Get or set a boolean value representing if this " \
                        + "NetworkPortal supports iSER.")
    offload = property(_get_offload, _set_offload,
                    doc="Get or set a boolean value representing if this " \
                        + "NetworkPortal supports offload.")

    @classmethod
    def setup(cls, tpg_obj, p, err_func):
        if 'ip_address' not in p:
            err_func("'ip_address' field missing from a portal in TPG %d" % tpg_obj.tag)
            return
        if 'port' not in p:
            err_func("'port' field missing from a portal in TPG %d" % tpg_obj.tag)
            return

        try:
            np = cls(tpg_obj, p['ip_address'], p['port'])
            np.iser = p.get('iser', False)
            np.offload = p.get('offload', False)
        except (RTSLibError, KeyError) as e:
            err_func("Creating NetworkPortal object %s:%s failed: %s" %
                     (p['ip_address'], p['port'], e))

    def dump(self):
        d = super(NetworkPortal, self).dump()
        d['port'] = self.port
        d['ip_address'] = self.ip_address
        d['iser'] = self.iser
        d['offload'] = self.offload
        return d


class NodeACL(CFSNode):
    '''
    This is an interface to node ACLs in configFS.
    A NodeACL is identified by the initiator node wwn and parent TPG.
    '''

    # NodeACL private stuff

    def __repr__(self):
        return "<NodeACL %s>" % self.node_wwn

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
            raise RTSLibError("Invalid parent TPG")

        fm = self.parent_tpg.parent_target.fabric_module
        self._node_wwn, self.wwn_type = normalize_wwn(fm.wwn_types, node_wwn)
        self._path = "%s/acls/%s" % (self.parent_tpg.path, fm.to_fabric_wwn(self.node_wwn))
        self._create_in_cfs_ine(mode)

    def _get_node_wwn(self):
        return self._node_wwn

    def _get_parent_tpg(self):
        return self._parent_tpg

    def _get_tcq_depth(self):
        self._check_self()
        path = "%s/cmdsn_depth" % self.path
        return fread(path)

    def _set_tcq_depth(self, depth):
        self._check_self()
        path = "%s/cmdsn_depth" % self.path
        try:
            fwrite(path, "%s" % depth)
        except IOError as msg:
            msg = msg[1]
            raise RTSLibError("Cannot set tcq_depth: %s" % str(msg))

    def _get_tag(self):
        self._check_self()
        try:
            tag = fread("%s/tag" % self.path)
            if tag:
                return tag
            return None
        except IOError:
            return None

    def _set_tag(self, tag_str):
        with ignored(IOError):
            if tag_str is None:
                fwrite("%s/tag" % self.path, 'NULL')
            else:
                fwrite("%s/tag" % self.path, tag_str)

    def _list_mapped_luns(self):
        self._check_self()
        for mapped_lun_dir in glob("%s/lun_*" % self.path):
            mapped_lun = int(os.path.basename(mapped_lun_dir).split("_")[1])
            yield MappedLUN(self, mapped_lun)

    def _get_session(self):
        try:
            lines = fread("%s/info" % self.path).splitlines()
        except IOError:
            return None

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

    tcq_depth = property(_get_tcq_depth, _set_tcq_depth,
                         doc="Set or get the TCQ depth for the initiator " \
                         + "sessions matching this NodeACL.")
    tag = property(_get_tag, _set_tag,
            doc="Set or get the NodeACL tag. If not supported, return None")
    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    node_wwn = property(_get_node_wwn,
            doc="Get the node wwn.")
    mapped_luns = property(_list_mapped_luns,
            doc="Get the list of all MappedLUN objects in this NodeACL.")
    session = property(_get_session,
            doc="Gives a snapshot of the current session or C{None}")

    chap_userid = property(partial(_get_auth_attr, attribute='auth/userid'),
                           partial(_set_auth_attr, attribute='auth/userid'),
                           doc="Set or get the initiator CHAP auth userid.")
    chap_password = property(partial(_get_auth_attr, attribute='auth/password'),
                             partial(_set_auth_attr, attribute='auth/password',),
                             doc="Set or get the initiator CHAP auth password.")
    chap_mutual_userid = property(partial(_get_auth_attr, attribute='auth/userid_mutual'),
                                  partial(_set_auth_attr, attribute='auth/userid_mutual'),
                                  doc="Set or get the initiator CHAP auth userid.")
    chap_mutual_password = property(partial(_get_auth_attr, attribute='auth/password_mutual'),
                                    partial(_set_auth_attr, attribute='auth/password_mutual'),
                                    doc="Set or get the initiator CHAP auth password.")

    def _get_authenticate_target(self):
        self._check_self()
        path = "%s/auth/authenticate_target" % self.path
        return bool(int(fread(path)))

    authenticate_target = property(_get_authenticate_target,
                                   doc="Get the boolean authenticate target flag.")

    @classmethod
    def setup(cls, tpg_obj, acl, err_func):
        if 'node_wwn' not in acl:
            err_func("'node_wwn' missing in node_acl")
            return
        try:
            acl_obj = cls(tpg_obj, acl['node_wwn'])
        except RTSLibError as e:
            err_func("Error when creating NodeACL for %s: %s" % (acl['node_wwn'], e))
            return

        set_attributes(acl_obj, acl.get('attributes', {}), err_func)

        for mlun in acl.get('mapped_luns', []):
            MappedLUN.setup(tpg_obj, acl_obj, mlun, err_func)

        dict_remove(acl, ('attributes', 'mapped_luns', 'node_wwn'))
        for name, value in six.iteritems(acl):
            if value:
                try:
                    setattr(acl_obj, name, value)
                except:
                    err_func("Could not set nodeacl %s attribute '%s'" %
                             (acl['node_wwn'], name))

    def dump(self):
        d = super(NodeACL, self).dump()
        d['node_wwn'] = self.node_wwn
        d['mapped_luns'] = [lun.dump() for lun in self.mapped_luns]
        if self.tag:
            d['tag'] = self.tag
        if self.has_feature("auth"):
            for attr in auth_params:
                val = getattr(self, "chap_" + attr, None)
                if val:
                    d["chap_" + attr] = val
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

    def __repr__(self):
        return "<MappedLUN %s lun %d -> tpg%d lun %d>" % \
            (self.parent_nodeacl.node_wwn, self.mapped_lun,
             self.parent_nodeacl.parent_tpg.tag, self.tpg_lun.lun)

    def __init__(self, parent_nodeacl, mapped_lun,
                 tpg_lun=None, write_protect=None, alias=None):
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
                              + "a NodeACL object")
        else:
            self._parent_nodeacl = parent_nodeacl
            if not parent_nodeacl.exists:
                raise RTSLibError("The parent_nodeacl does not exist")

        try:
            self._mapped_lun = int(mapped_lun)
        except ValueError:
            raise RTSLibError("The mapped_lun parameter must be an " \
                              + "integer value")

        self._path = "%s/lun_%d" % (self.parent_nodeacl.path, self.mapped_lun)

        if tpg_lun is None and write_protect is not None:
            raise RTSLibError("The write_protect parameter has no " \
                              + "meaning without the tpg_lun parameter")

        if tpg_lun is not None:
            self._create_in_cfs_ine('create')
            try:
                self._configure(tpg_lun, write_protect, alias)
            except:
                self.delete()
                raise
        else:
            self._create_in_cfs_ine('lookup')

    def _configure(self, tpg_lun, write_protect, alias):
        self._check_self()
        if isinstance(tpg_lun, LUN):
            tpg_lun = tpg_lun.lun
        else:
            try:
                tpg_lun = int(tpg_lun)
            except ValueError:
                raise RTSLibError("The tpg_lun must be either an "
                                  + "integer or a LUN object")
        # Check that the tpg_lun exists in the TPG
        for lun in self.parent_nodeacl.parent_tpg.luns:
            if lun.lun == tpg_lun:
                tpg_lun = lun
                break
        if not (isinstance(tpg_lun, LUN) and tpg_lun):
            raise RTSLibError("LUN %s does not exist in this TPG"
                              % str(tpg_lun))

        if not alias:
            alias = str(uuid.uuid4())[-10:]
        os.symlink(tpg_lun.path, "%s/%s" % (self.path, alias))

        try:
            self.write_protect = int(write_protect) > 0
        except:
            self.write_protect = False

    def _get_alias(self):
        self._check_self()
        for path in os.listdir(self.path):
            if os.path.islink("%s/%s" % (self.path, path)):
                return os.path.basename(path)

        raise RTSLibBrokenLink("Broken LUN in configFS, no storage object")

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
        return bool(int(fread(path)))

    def _get_tpg_lun(self):
        self._check_self()
        path = os.path.realpath("%s/%s" % (self.path, self.alias))
        for lun in self.parent_nodeacl.parent_tpg.luns:
            if lun.path == path:
                return lun

        raise RTSLibBrokenLink("Broken MappedLUN, no TPG LUN found")

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
            lun_link = "%s/%s" % (self.path, self.alias)
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
    alias = property(_get_alias,
            doc="Get the MappedLUN alias.")

    @classmethod
    def setup(cls, tpg_obj, acl_obj, mlun, err_func):
        if 'tpg_lun' not in mlun:
            err_func("'tpg_lun' not in a mapped_lun")
            return
        if 'index' not in mlun:
            err_func("'index' not in a mapped_lun")
            return

        # Mapped lun needs to correspond with already-created
        # TPG lun
        for lun in tpg_obj.luns:
            if lun.lun == mlun['tpg_lun']:
                tpg_lun_obj = lun
                break
        else:
            err_func("Could not find matching TPG LUN %d for MappedLUN %s" %
                     (mlun['tpg_lun'], mlun['index']))
            return

        try:
            mlun_obj = cls(acl_obj, mlun['index'],
                           tpg_lun_obj, mlun.get('write_protect'),
                           mlun.get('alias'))
            mlun_obj.tag = mlun.get("tag", None)
        except (RTSLibError, KeyError):
            err_func("Creating MappedLUN object %d failed" % mlun['index'])

    def dump(self):
        d = super(MappedLUN, self).dump()
        d['write_protect'] = self.write_protect
        d['index'] = self.mapped_lun
        d['tpg_lun'] = self.tpg_lun.lun
        d['alias'] = self.alias
        return d


class Group(object):
    '''
    An abstract base class akin to CFSNode, but for classes that
    emulate a higher-level group object across the actual NodeACL
    configfs structure.
    '''
    def __init__(self, members_func):
        '''
        members_func is a function that takes a self argument
        and returns an iterator of the objects that the
        derived Group class is grouping.
        '''
        self._mem_func = members_func

    def _get_first_member(self):
        try:
            return next(self._mem_func(self))
        except StopIteration:
            raise IndexError("Group is empty")

    def _get_prop(self, prop):
        '''
        Helper fn to use with partial() to support getting a
        property value from the first member of the group.
        (All members of the group should be identical.)
        '''
        return getattr(self._get_first_member(), prop)

    def _set_prop(self, value, prop):
        '''
        Helper fn to use with partial() to support setting a
        property value in all members of the group.

        Caution: Arguments reversed!
        This is so partial() can be used on property name.
        '''

        for mem in self._mem_func(self):
            setattr(mem, prop, value)

    def list_attributes(self, writable=None):
        return self._get_first_member().list_attributes(writable)

    def list_parameters(self, writable=None):
        return self._get_first_member().list_parameters(writable)

    def set_attribute(self, attribute, value):
        for obj in self._mem_func(self):
            obj.set_attribute(attribute, value)

    def set_parameter(self, parameter, value):
        for obj in self._mem_func(self):
            obj.set_parameter(parameter, value)

    def get_attribute(self, attribute):
        return self._get_first_member().get_attribute(attribute)

    def get_parameter(self, parameter):
        return self._get_first_member().get_parameter(parameter)

    def delete(self):
        '''
        Delete all members of the group.
        '''
        for mem in self._mem_func(self):
            mem.delete()

    @property
    def exists(self):
        return any(self._mem_func(self))


def _check_group_name(name):
    # Since all WWNs have a '.' in them, let's avoid confusion.
    if '.' in name:
        raise RTSLibError("'.' not permitted in group names.")


class NodeACLGroup(Group):
    '''
    Allow a group of NodeACLs that share a tag to be managed collectively.
    '''
    def __repr__(self):
        return "<NodeACLGroup %s>" % self.name

    def __init__(self, parent_tpg, name):
        super(NodeACLGroup, self).__init__(NodeACLGroup._node_acls.fget)
        _check_group_name(name)
        self._name = name
        self._parent_tpg = parent_tpg

    def _get_name(self):
        return self._name

    def _set_name(self, name):
        _check_group_name(name)
        for na in self._node_acls:
            na.tag = name
        self._name = name

    @property
    def parent_tpg(self):
        '''
        Get the parent TPG object.
        '''
        return self._parent_tpg

    def add_acl(self, node_wwn):
        '''
        Add a WWN to the NodeACLGroup. If a NodeACL already exists for this WWN,
        its configuration will be changed to match the NodeACLGroup, except for its
        auth parameters, which can vary among group members.
        @param node_wwn: An initiator WWN
        @type node_wwn: string
        '''
        nacl = NodeACL(self.parent_tpg, node_wwn)

        if nacl in self._node_acls:
            return

        # if joining a group, take its config
        try:
            model = next(self._node_acls)
        except StopIteration:
            pass
        else:
            for mlun in nacl.mapped_luns:
                mlun.delete()

            for mlun in model.mapped_luns:
                MappedLUN(nacl, mlun.mapped_lun, mlun.tpg_lun, mlun.write_protect)

            for item in model.list_attributes(writable=True):
                nacl.set_attribute(item, model.get_attribute(item))
            for item in model.list_parameters(writable=True):
                nacl.set_parameter(item, model.get_parameter(item))
        finally:
            nacl.tag = self.name

    def remove_acl(self, node_wwn):
        '''
        Remove a WWN from the NodeACLGroup.
        @param node_wwn: An initiator WWN
        @type node_wwn: string
        '''
        nacl = NodeACL(self.parent_tpg, node_wwn, mode='lookup')

        nacl.delete()

    @property
    def _node_acls(self):
        '''
        Gives access to the underlying NodeACLs within this group.
        '''
        for na in self.parent_tpg.node_acls:
            if na.tag == self.name:
                yield na

    @property
    def wwns(self):
        '''
        Give the Node WWNs of members of this group.
        '''
        return (na.node_wwn for na in self._node_acls)

    def has_feature(self, feature):
        '''
        Whether or not this NodeACL has a certain feature.
        '''
        return self._parent_tpg.has_feature(feature)

    @property
    def sessions(self):
        '''
        Yields any current sessions.
        '''
        for na in self._node_acls:
            session = na.session
            if session:
                yield session

    def mapped_lun_group(self, mapped_lun, tpg_lun=None, write_protect=None):
        '''
        Add a mapped lun to all group members.
        '''
        return MappedLUNGroup(self, mapped_lun=mapped_lun, tpg_lun=tpg_lun,
                      write_protect=write_protect)

    @property
    def mapped_lun_groups(self):
        '''
        Generates all MappedLUNGroup objects in this NodeACLGroup.
        '''
        try:
            first = self._get_first_member()
        except IndexError:
            return

        for mlun in first.mapped_luns:
            yield MappedLUNGroup(self, mlun.mapped_lun)

    name = property(_get_name, _set_name,
                    doc="Get/set NodeACLGroup name.")

    def _get_chap(self, name):
        for na in self._node_acls:
            yield (na.node_wwn, getattr(na, "chap_" + name))

    def _set_chap(self, name, value, wwn):
        for na in self._node_acls:
            if not wwn:
                setattr(na, "chap_" + name, value)
            elif wwn == na.node_wwn:
                setattr(na, "chap_" + name, value)
                break

    def get_userids(self):
        '''
        Returns a (wwn, userid) tuple for each member of the group.
        '''
        return self._get_chap(name="userid")

    def set_userids(self, value, wwn=None):
        '''
        If wwn, set the userid for just that wwn, otherwise set it for
        all group members.
        '''
        return self._set_chap("userid", value, wwn)

    def get_passwords(self):
        '''
        Returns a (wwn, password) tuple for each member of the group.
        '''
        return self._get_chap(name="password")

    def set_passwords(self, value, wwn=None):
        '''
        If wwn, set the password for just that wwn, otherwise set it for
        all group members.
        '''
        return self._set_chap("password", value, wwn)

    def get_mutual_userids(self):
        '''
        Returns a (wwn, mutual_userid) tuple for each member of the group.
        '''
        return self._get_chap(name="mutual_userid")

    def set_mutual_userids(self, value, wwn=None):
        '''
        If wwn, set the mutual_userid for just that wwn, otherwise set it for
        all group members.
        '''
        return self._set_chap("mutual_userid", value, wwn)

    def get_mutual_passwords(self):
        '''
        Returns a (wwn, mutual_password) tuple for each member of the group.
        '''
        return self._get_chap(name="mutual_password")

    def set_mutual_passwords(self, value, wwn=None):
        '''
        If wwn, set the mutual_password for just that wwn, otherwise set it for
        all group members.
        '''
        return self._set_chap("mutual_password", value, wwn)

    tcq_depth = property(partial(Group._get_prop, prop="tcq_depth"),
                         partial(Group._set_prop, prop="tcq_depth"),
                         doc="Set or get the TCQ depth for the initiator "
                         + "sessions matching this NodeACLGroup")
    authenticate_target = property(partial(Group._get_prop, prop="authenticate_target"),
                                   doc="Get the boolean authenticate target flag.")


class MappedLUNGroup(Group):
    '''
    Used with NodeACLGroup, this aggregates all MappedLUNs with the same LUN
    so that it can be configured across all members of the NodeACLGroup.
    '''

    def __repr__(self):
        return "<MappedLUNGroup %s:lun %d>" % (self._nag.name, self._mapped_lun)

    def __init__(self, nodeaclgroup, mapped_lun, *args, **kwargs):
        super(MappedLUNGroup, self).__init__(MappedLUNGroup._mapped_luns.fget)
        self._nag = nodeaclgroup
        self._mapped_lun = mapped_lun
        for na in self._nag._node_acls:
            MappedLUN(na, mapped_lun=mapped_lun, *args, **kwargs)

    @property
    def _mapped_luns(self):
        for na in self._nag._node_acls:
            for mlun in na.mapped_luns:
                if mlun.mapped_lun == self.mapped_lun:
                    yield mlun

    @property
    def mapped_lun(self):
        '''
        Get the integer MappedLUN mapped_lun index.
        '''
        return self._mapped_lun

    @property
    def parent_nodeaclgroup(self):
        '''
        Get the parent NodeACLGroup object.
        '''
        return self._nag

    write_protect = property(partial(Group._get_prop, prop="write_protect"),
                             partial(Group._set_prop, prop="write_protect"),
                             doc="Get or set the boolean write protection.")
    tpg_lun = property(partial(Group._get_prop, prop="tpg_lun"),
                       doc="Get the TPG LUN object the MappedLUN is pointing at.")


def _test():
    from doctest import testmod
    testmod()

if __name__ == "__main__":
    _test()
