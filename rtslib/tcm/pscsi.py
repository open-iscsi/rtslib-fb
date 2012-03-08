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

class PSCSIBackstore(Backstore):
    '''
    This is an interface to pscsi backstore plugin objects in configFS.
    A PSCSIBackstore object is identified by its backstore index.
    '''

    # PSCSIBackstore private stuff

    def __init__(self, index, mode='any', legacy=False):
        '''
        @param index: The backstore index matching a physical SCSI HBA.
        @type index: int
        @param mode: An optionnal string containing the object creation mode:
            - I{'any'} the configFS object will be either lookuped or created.
            - I{'lookup'} the object MUST already exist configFS.
            - I{'create'} the object must NOT already exist in configFS.
        @type mode:string
        @param legacy: Enable legacy physcal HBA mode. If True, you must
        specify it also in lookup mode for StorageObjects to be notified.
        You've been warned !
        @return: A PSCSIBackstore object.
        '''
        self._legacy = legacy
        super(PSCSIBackstore, self).__init__("pscsi",
                                              PSCSIStorageObject,
                                              index,
                                              mode)

    def _create_in_cfs_ine(self, mode):
        if self.legacy_mode and self._index not in list_scsi_hbas():
            raise RTSLibError("Cannot create backstore, hba "
                              + "scsi%d does not exist."
                              % self._index)
        else:
            Backstore._create_in_cfs_ine(self, mode)

    def _get_legacy(self):
        return self._legacy

    # PSCSIBackstore public stuff

    def storage_object(self, name, dev=None):
        '''
        Same as PSCSIStorageObject() without specifying the backstore
        '''
        self._check_self()
        return PSCSIStorageObject(self, name=name, dev=dev)

    legacy_mode = property(_get_legacy,
            doc="Get the legacy mode flag. If True, the Vitualbackstore "
                + " index must match the StorageObjects real HBAs.")

    def dump(self):
        d = super(PSCSIBackstore, self).dump()
        d['legacy_mode'] = self.legacy_mode
        return d


class PSCSIStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for pscsi backstore.
    '''

    # PSCSIStorageObject private stuff

    def __init__(self, backstore, name, dev=None):
        '''
        A PSCSIStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{dev} is specified, the underlying configFS
              object will be created with that parameter. No PSCSIStorageObject
              with the same I{name} can pre-exist in the parent PSCSIBackstore
              in that mode, or instanciation will fail.
            - B{Lookup mode}: If I{dev} is not set, then the PSCSIStorageObject
              will be bound to the existing configFS object in the parent
              PSCSIBackstore having the specified I{name}. The underlying
              configFS object must already exist in that mode, or instanciation
              will fail.

        @param backstore: The parent backstore of the PSCSIStorageObject.
        @type backstore: PSCSIBackstore
        @param name: The name of the PSCSIStorageObject.
        @type name: string
        @param dev: You have two choices:
            - Use the SCSI id of the device: I{dev="H:C:T:L"}. If the parent
              backstore is in legacy mode, you must use I{dev="C:T:L"}
              instead, as the backstore index of the SCSI dev device would then be
              constrained by the parent backstore index.
            - Use the path to the SCSI device: I{dev="/path/to/dev"}.
              Note that if the parent Backstore is in legacy mode, the device
              must have the same backstore index as the parent backstore.
        @type dev: string
        @return: A PSCSIStorageObject object.
        '''
        if dev is not None:
            super(PSCSIStorageObject, self).__init__(backstore,
                                                     PSCSIBackstore,
                                                     name, 'create')
            try:
                self._configure(dev)
            except:
                self.delete()
                raise
        else:
            super(PSCSIStorageObject, self).__init__(backstore,
                                                     PSCSIBackstore,
                                                     name, 'lookup')

    def _configure(self, dev):
        self._check_self()
        parent_hostid = self.backstore.index
        legacy = self.backstore.legacy_mode
        if legacy:
            try:
                (hostid, channelid, targetid, lunid) = \
                        convert_scsi_path_to_hctl(dev)
            except TypeError:
                try:
                    (channelid, targetid, lunid) = dev.split(':')
                    channelid = int(channelid)
                    targetid = int(targetid)
                    lunid = int(lunid)
                except ValueError:
                    raise RTSLibError("Cannot find SCSI device by "
                                      + "path, and dev parameter not "
                                      + "in C:T:L format: %s." % dev)
                else:
                    udev_path = convert_scsi_hctl_to_path(parent_hostid,
                                                                channelid,
                                                                targetid,
                                                                lunid)
                if not udev_path:
                    raise RTSLibError("SCSI device does not exist.")
            else:
                if hostid != parent_hostid:
                    raise RTSLibError("The specified SCSI device does "
                                      + "not belong to the backstore.")
                else:
                    udev_path = dev.strip()
        else:
            # The Backstore is not in legacy mode.
            # Use H:C:T:L format or preserve the path given by the user.
            try:
                (hostid, channelid, targetid, lunid) = \
                        convert_scsi_path_to_hctl(dev)
            except TypeError:
                try:
                    (hostid, channelid, targetid, lunid) = dev.split(':')
                    hostid = int(hostid)
                    channelid = int(channelid)
                    targetid = int(targetid)
                    lunid = int(lunid)
                except ValueError:
                    raise RTSLibError("Cannot find SCSI device by "
                                      + "path, and dev "
                                      + "parameter not in H:C:T:L "
                                      + "format: %s." % dev)
                else:
                    udev_path = convert_scsi_hctl_to_path(hostid,
                                                                channelid,
                                                                targetid,
                                                                lunid)
                if not udev_path:
                    raise RTSLibError("SCSI device does not exist.")
            else:
                udev_path = dev.strip()

        if is_dev_in_use(udev_path):
            raise RTSLibError("Cannot configure StorageObject because "
                              + "device %s (SCSI %d:%d:%d:%d) "
                              % (udev_path, hostid, channelid,
                                 targetid, lunid)
                              + "is already in use.")

        if legacy:
            self._control("scsi_channel_id=%d," % channelid \
                          + "scsi_target_id=%d," % targetid \
                          + "scsi_lun_id=%d" %  lunid)
        else:
            self._control("scsi_host_id=%d," % hostid \
                          + "scsi_channel_id=%d," % channelid \
                          + "scsi_target_id=%d," % targetid \
                          + "scsi_lun_id=%d" % lunid)
        self._set_udev_path(udev_path)
        self._enable()

    def _get_model(self):
        self._check_self()
        info = fread("%s/info" % self.path)
        return str(re.search(".*Model:(.*)Rev:",
                             ' '.join(info.split())).group(1)).strip()

    def _get_vendor(self):
        self._check_self()
        info = fread("%s/info" % self.path)
        return str(re.search(".*Vendor:(.*)Model:",
                             ' '.join(info.split())).group(1)).strip()

    def _get_revision(self):
        self._check_self()
        return self._parse_info('Rev')

    def _get_channel_id(self):
        self._check_self()
        return int(self._parse_info('Channel ID'))

    def _get_target_id(self):
        self._check_self()
        return int(self._parse_info('Target ID'))

    def _get_lun(self):
        self._check_self()
        return int(self._parse_info('LUN'))

    def _get_host_id(self):
        self._check_self()
        return int(self._parse_info('Host ID'))

    # PSCSIStorageObject public stuff

    wwn = property(StorageObject._get_wwn,
            doc="Get the StorageObject T10 WWN Unit Serial as a string."
            + " You cannot set it for pscsi-backed StorageObjects.")
    model = property(_get_model,
            doc="Get the SCSI device model string")
    vendor = property(_get_vendor,
            doc="Get the SCSI device vendor string")
    revision = property(_get_revision,
            doc="Get the SCSI device revision string")
    host_id = property(_get_host_id,
            doc="Get the SCSI device host id")
    channel_id = property(_get_channel_id,
            doc="Get the SCSI device channel id")
    target_id = property(_get_target_id,
            doc="Get the SCSI device target id")
    lun = property(_get_lun,
            doc="Get the SCSI device LUN")


def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
