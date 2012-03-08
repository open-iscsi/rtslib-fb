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

class FileIOBackstore(Backstore):
    '''
    This is an interface to fileio backstore plugin objects in configFS.
    A FileIOBackstore object is identified by its backstore index.
    '''

    # FileIOBackstore private stuff

    def __init__(self, index, mode='any'):
        '''
        @param index: The backstore index.
        @type index: int
        @param mode: An optionnal string containing the object creation mode:
            - I{'any'} the configFS object will be either lookuped or created.
            - I{'lookup'} the object MUST already exist configFS.
            - I{'create'} the object must NOT already exist in configFS.
        @type mode:string
        @return: A FileIOBackstore object.
        '''

        super(FileIOBackstore, self).__init__("fileio", FileIOStorageObject,
                                               index, mode)

    # FileIOBackstore public stuff

    def storage_object(self, name, dev=None, size=None,
                       wwn=None, buffered_mode=False):
        '''
        Same as FileIOStorageObject() without specifying the backstore
        '''
        self._check_self()
        return FileIOStorageObject(self, name=name, dev=dev,
                                   size=size, wwn=wwn,
                                   buffered_mode=buffered_mode)

class FileIOStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for fileio backstore.
    '''

    # FileIOStorageObject private stuff

    def __init__(self, backstore, name, dev=None, size=None,
                 wwn=None, buffered_mode=False):
        '''
        A FileIOStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{dev} and I{size} are specified, the
              underlying configFS object will be created with those parameters.
              No FileIOStorageObject with the same I{name} can pre-exist in the
              parent FileIOBackstore in that mode, or instanciation will fail.
            - B{Lookup mode}: If I{dev} and I{size} are not set, then the
              FileIOStorageObject will be bound to the existing configFS object
              in the parent FileIOBackstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instanciation will fail.

        @param backstore: The parent backstore of the FileIOStorageObject.
        @type backstore: FileIOBackstore
        @param name: The name of the FileIOStorageObject.
        @type name: string
        @param dev: The path to the backend file or block device to be used.
            - Examples: I{dev="/dev/sda"}, I{dev="/tmp/myfile"}
            - The only block device type that is accepted I{TYPE_DISK}, or
              partitions of a I{TYPE_DISK} device.
              For other device types, use pscsi.
        @type dev: string
        @param size: The maximum size to allocate for the file.
        Not used for block devices.
            - If size is an int, it represents a number of bytes
            - If size is a string, the following units can be used :
                - B{B} or no unit present for bytes
                - B{k}, B{K}, B{kB}, B{KB} for kB (kilobytes)
                - B{m}, B{M}, B{mB}, B{MB} for MB (megabytes)
                - B{g}, B{G}, B{gB}, B{GB} for GB (gigabytes)
                - B{t}, B{T}, B{tB}, B{TB} for TB (terabytes)
                Example: size="1MB" for a one megabytes storage object.
                - The base value for kilo is 1024, aka 1kB = 1024B.
                  Strictly speaking, we use kiB, MiB, etc.
        @type size: string or int
        @param wwn: T10 WWN Unit Serial, will generate if None
        @type wwn: string
        @param buffered_mode: Should we create the StorageObject in buffered
        mode or not ? Byt default, we create it in synchronous mode
        (non-buffered). This cannot be changed later.
        @type buffered_mode: bool
        @return: A FileIOStorageObject object.
        '''

        if dev is not None:
            super(FileIOStorageObject, self).__init__(backstore,
                                                      FileIOBackstore,
                                                      name,
                                                      'create')
            try:
                self._configure(dev, size, wwn, buffered_mode)
            except:
                self.delete()
                raise
        else:
            super(FileIOStorageObject, self).__init__(backstore,
                                                      FileIOBackstore,
                                                      name,
                                                      'lookup')

    def _configure(self, dev, size, wwn, buffered_mode):
        self._check_self()
        rdev = os.path.realpath(dev)
        if not os.path.isdir(os.path.dirname(rdev)):
            raise RTSLibError("The dev parameter must be a path to a "
                              + "file inside an existing directory, "
                              + "not %s." % str(os.path.dirname(dev)))
        if os.path.isdir(rdev):
            raise RTSLibError("The dev parameter must be a path to a "
                              + "file or block device not a directory:"
                              + "%s." % dev)

        block_type = get_block_type(rdev)
        if block_type is None and not is_disk_partition(rdev):
            if os.path.exists(rdev) and not os.path.isfile(dev):
                raise RTSLibError("Device %s is neither a file, " % dev
                                  + "a disk partition or a block device.")
            # It is a file
            if size is None:
                raise RTSLibError("The size parameter is mandatory "
                                  + "when using a file.")
            size = human_to_bytes(size)
            self._control("fd_dev_name=%s,fd_dev_size=%d" % (dev, size))
        else:
            # it is a block device or a disk partition
            if size is not None:
                raise RTSLibError("You cannot specify a size for a "
                                  + "block device.")
            if block_type != 0 and block_type is not None:
                raise RTSLibError("Device %s is a block device, " % dev
                                  + "but not of TYPE_DISK.")
            if is_dev_in_use(rdev):
                raise RTSLibError("Cannot configure StorageObject "
                                  + "because device "
                                  + "%s is already in use." % dev)
            if is_disk_partition(rdev):
                size = get_disk_size(rdev)
                print "fd_dev_name=%s,fd_dev_size=%d" % (dev, size)
                self._control("fd_dev_name=%s,fd_dev_size=%d" % (dev, size))
            else:
                self._control("fd_dev_name=%s" % dev)

        self._set_udev_path(dev)

        if buffered_mode:
            self._set_buffered_mode()

        self._enable()

        if not wwn:
            wwn = generate_wwn('unit_serial')
        self.wwn = wwn

    def _get_buffered_mode(self):
        self._check_self()
        if self._parse_info('Mode') == 'buffered':
            return True
        else:
            return False

    def _get_size(self):
        self._check_self()
        return int(self._parse_info('Size'))

    def _set_buffered_mode(self):
        '''
        FileIOStorage objects have synchronous mode enable by default.
        This allows to move them to buffered mode.
        Warning, setting the object back to synchronous mode is not
        implemented yet, so there is no turning back unless you delete
        and recreate the FileIOStorageObject.
        '''
        self._check_self()
        self._control("fd_buffered_io=1")

    # FileIOStorageObject public stuff

    buffered_mode = property(_get_buffered_mode,
            doc="True if buffered, False if synchronous (O_SYNC)")
    size = property(_get_size,
            doc="Get the current FileIOStorage size in bytes")

    def dump(self):
        d = super(FileIOStorageObject, self).dump()
        d['buffered_mode'] = self.buffered_mode
        d['dev'] = self.udev_path
        d['size'] = self.size
        return d


def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
