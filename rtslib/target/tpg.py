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

from os.path import isdir
from doctest import testmod
from configobj import ConfigObj

from rtslib.node import CFSNode
from rtslib.utils import RTSLibError, RTSLibBrokenLink, modprobe
from rtslib.utils import is_ipv6_address, is_ipv4_address
from rtslib.utils import fread, fwrite, generate_wwn, is_valid_wwn, exec_argv
from rtslib.utils import dict_remove, set_attributes

from rtslib.target import LUN, NodeACL, NetworkPortal

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

        if parent_target.wwn is None:
            raise RTSLibError("Invalid parent Target.")
        else:
            self._parent_target = parent_target

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

    def _create_in_cfs_ine(self, mode):
        super(TPG, self)._create_in_cfs_ine(mode)
        if not os.path.isdir(self.alua_metadata_path):
            os.makedirs(self.alua_metadata_path)

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

    def dump(self):
        d = super(TPG, self).dump()
        d['tag'] = self.tag
        d['luns'] = [lun.dump() for lun in self.luns]
        d['portals'] = [portal.dump() for portal in self.network_portals]
        d['node_acls'] =  [acl.dump() for acl in self.node_acls]
        return d


def _test():
    testmod()

if __name__ == "__main__":
    _test()
