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

        if parent_tpg.luns is None:
            raise RTSLibError("Invalid parent TPG.")
        else:
            self._parent_tpg = parent_tpg

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
        from rtslib.tcm import StorageObject
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
        from rtslib.root import RTSRoot
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

    def dump(self):
        d = super(LUN, self).dump()
        d['storage_object'] = "/backstores/%s/%s" % \
            (self.storage_object.backstore.plugin,  self.storage_object.name)
        d['index'] = self.lun
        return d


def _test():
    testmod()

if __name__ == "__main__":
    _test()
