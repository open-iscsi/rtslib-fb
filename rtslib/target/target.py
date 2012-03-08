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

from rtslib.target import TPG

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
            tpg_obj.enable = True
            set_attributes(tpg_obj, tpg.get('attributes', {}))

            for lun in tpg.get('luns', []):
                try:
                    bs_name, so_name = lun['storage_object'].split('/')[2:]
                except:
                    errors += 1
                    continue

                for so in storage_objects:
                    if so_name == so.name and bs_name == so.backstore.plugin:
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
