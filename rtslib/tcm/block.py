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

class BlockBackstore(Backstore):
    '''
    This is an interface to iblock backstore plugin objects in configFS.
    A BlockBackstore object is identified by its backstore index.
    '''

    # BlockBackstore private stuff

    def __init__(self, index, mode='any'):
        '''
        @param index: The backstore index.
        @type index: int
        @param mode: An optionnal string containing the object creation mode:
            - I{'any'} the configFS object will be either lookupd or created.
            - I{'lookup'} the object MUST already exist configFS.
            - I{'create'} the object must NOT already exist in configFS.
        @type mode:string
        @return: A BlockBackstore object.
        '''

        super(BlockBackstore, self).__init__("block", BlockStorageObject,
                                               index, mode, alt_dirprefix="iblock")

    # BlockBackstore public stuff

    def storage_object(self, name, dev=None, wwn=None):
        '''
        Same as BlockStorageObject() without specifying the backstore
        '''
        self._check_self()
        return BlockStorageObject(self, name=name, dev=dev, wwn=wwn)


class BlockStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for block backstore.
    '''

    # BlockStorageObject private stuff

    def __init__(self, backstore, name, dev=None, wwn=None):
        '''
        A BlockIOStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{dev} is specified, the underlying configFS
              object will be created with that parameter.
              No BlockIOStorageObject with the same I{name} can pre-exist in
              the parent BlockIOBackstore in that mode.
            - B{Lookup mode}: If I{dev} is not set, then the
              BlockIOStorageObject will be bound to the existing configFS
              object in the parent BlockIOBackstore having the specified
              I{name}. The underlying configFS object must already exist in
              that mode, or instanciation will fail.

        @param backstore: The parent backstore of the BlockIOStorageObject.
        @type backstore: BlockIOBackstore
        @param name: The name of the BlockIOStorageObject.
        @type name: string
        @param dev: The path to the backend block device to be used.
            - Example: I{dev="/dev/sda"}.
            - The only device type that is accepted I{TYPE_DISK}.
              For other device types, use pscsi.
        @type dev: string
        @param wwn: T10 WWN Unit Serial, will generate if None
        @type wwn: string
        @return: A BlockIOStorageObject object.
        '''

        if dev is not None:
            super(BlockStorageObject, self).__init__(backstore,
                                                     BlockBackstore,
                                                     name,
                                                     'create')
            try:
                self._configure(dev, wwn)
            except:
                self.delete()
                raise
        else:
            super(BlockStorageObject, self).__init__(backstore,
                                                     BlockBackstore,
                                                     name,
                                                     'lookup')

    def _configure(self, dev, wwn):
        self._check_self()
        if get_block_type(dev) != 0:
            raise RTSLibError("Device is not a TYPE_DISK block device.")
        if is_dev_in_use(dev):
            raise RTSLibError("Cannot configure StorageObject because "
                              + "device %s is already in use." % dev)
        self._set_udev_path(dev)
        if self._backstore.version.startswith("v3."):
            # For 3.x, use the fd method
            file_fd = os.open(dev, os.O_RDWR)
            try:
                self._write_fd(file_fd)
            finally:
                os.close(file_fd)
        else:
            # For 4.x and above, use the generic udev_path method
            self._control("udev_path=%s" % dev)
            self._enable()
        if not wwn:
            wwn = generate_wwn('unit_serial')
        self.wwn = wwn

    def _get_major(self):
        self._check_self()
        return int(self._parse_info('Major'))

    def _get_minor(self):
        self._check_self()
        return int(self._parse_info('Minor'))

    # BlockStorageObject public stuff

    major = property(_get_major,
            doc="Get the block device major number")
    minor = property(_get_minor,
            doc="Get the block device minor number")

    def dump(self):
        d = super(BlockStorageObject, self).dump()
        d['dev'] = self.udev_path
        return d


def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
