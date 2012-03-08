'''
Implements the RTS Target backstore and storage object classes.

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

import os
import re

from rtslib.target import LUN, TPG, Target, FabricModule
from rtslib.node import CFSNode
from rtslib.utils import fread, fwrite, RTSLibError, list_scsi_hbas, generate_wwn
from rtslib.utils import convert_scsi_path_to_hctl, convert_scsi_hctl_to_path
from rtslib.utils import human_to_bytes, is_dev_in_use, get_block_type
from rtslib.utils import is_disk_partition, get_disk_size
from rtslib.utils import dict_remove, set_attributes
from rtslib.tcm import Backstore, StorageObject

class RDMCPBackstore(Backstore):
    '''
    This is an interface to rd_mcp backstore plugin objects in configFS.
    A RDMCPBackstore object is identified by its backstore index.
    '''

    # RDMCPBackstore private stuff

    def __init__(self, index, mode='any'):
        '''
        @param index: The backstore index.
        @type index: int
        @param mode: An optionnal string containing the object creation mode:
            - I{'any'} the configFS object will be either lookupd or created.
            - I{'lookup'} the object MUST already exist configFS.
            - I{'create'} the object must NOT already exist in configFS.
        @type mode:string
        @return: A RDMCPBackstore object.
        '''

        super(RDMCPBackstore, self).__init__("ramdisk", RDMCPStorageObject,
                                               index, mode, alt_dirprefix="rd_mcp")

    # RDMCPBackstore public stuff

    def storage_object(self, name, size=None, wwn=None):
        '''
        Same as RDMCPStorageObject() without specifying the backstore
        '''
        self._check_self()
        return RDMCPStorageObject(self, name=name,
                                  size=size, wwn=wwn)

class RDMCPStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for rd_mcp backstore.
    '''

    # RDMCPStorageObject private stuff

    def __init__(self, backstore, name, size=None, wwn=None):
        '''
        A RDMCPStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{size} is specified, the underlying
              configFS object will be created with that parameter.
              No RDMCPStorageObject with the same I{name} can pre-exist in the
              parent RDMCPBackstore in that mode, or instanciation will fail.
            - B{Lookup mode}: If I{size} is not set, then the
              RDMCPStorageObject will be bound to the existing configFS object
              in the parent RDMCPBackstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instanciation will fail.

        @param backstore: The parent backstore of the RDMCPStorageObject.
        @type backstore: RDMCPBackstore
        @param name: The name of the RDMCPStorageObject.
        @type name: string
        @param size: The size of the ramdrive to create:
            - If size is an int, it represents a number of bytes
            - If size is a string, the following units can be used :
                - B{B} or no unit present for bytes
                - B{k}, B{K}, B{kB}, B{KB} for kB (kilobytes)
                - B{m}, B{M}, B{mB}, B{MB} for MB (megabytes)
                - B{g}, B{G}, B{gB}, B{GB} for GB (gigabytes)
                - B{t}, B{T}, B{tB}, B{TB} for TB (terabytes)
                Example: size="1MB" for a one megabytes storage object.
                - Note that the size will be rounded to the closest 4096 Bytes
                  RAM pages count. For instance, a size of 100000 Bytes will be
                  rounded to 24 pages, really 98304 Bytes.
                - The base value for kilo is 1024, aka 1kB = 1024B.
                  Strictly speaking, we use kiB, MiB, etc.
        @type size: string or int
        @param wwn: T10 WWN Unit Serial, will generate if None
        @type wwn: string
        @return: A RDMCPStorageObject object.
        '''

        if size is not None:
            super(RDMCPStorageObject, self).__init__(backstore,
                                                     RDMCPBackstore,
                                                     name,
                                                     'create')
            try:
                self._configure(size, wwn)
            except:
                self.delete()
                raise
        else:
            super(RDMCPStorageObject, self).__init__(backstore,
                                                     RDMCPBackstore,
                                                     name,
                                                     'lookup')

    def _configure(self, size, wwn):
        self._check_self()
        size = human_to_bytes(size)
        # convert to 4k pages
        size = round(float(size)/4096)
        if size == 0:
            size = 1

        self._control("rd_pages=%d" % size)
        self._enable()
        if not wwn:
            wwn = generate_wwn('unit_serial')
        self.wwn = wwn

    def _get_page_size(self):
        self._check_self()
        return int(self._parse_info("PAGES/PAGE_SIZE").split('*')[1])

    def _get_pages(self):
        self._check_self()
        return int(self._parse_info("PAGES/PAGE_SIZE").split('*')[0])

    def _get_size(self):
        self._check_self()
        size = self._get_page_size() * self._get_pages()
        return size

    # RDMCPStorageObject public stuff

    page_size = property(_get_page_size,
            doc="Get the ramdisk page size.")
    pages = property(_get_pages,
            doc="Get the ramdisk number of pages.")
    size = property(_get_size,
            doc="Get the ramdisk size in bytes.")

    def dump(self):
        d = super(RDMCPStorageObject, self).dump()
        d['size'] = self.size
        return d


def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
