'''
Implements the RTS Target backstore and storage object classes.

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

import os
import re

from target import LUN, TPG, Target, FabricModule
from node import CFSNode
from utils import fread, fwrite, RTSLibError, list_scsi_hbas, generate_wwn
from utils import convert_scsi_path_to_hctl, convert_scsi_hctl_to_path
from utils import convert_human_to_bytes, is_dev_in_use, get_block_type
from utils import is_disk_partition, get_disk_size

class Backstore(CFSNode):

    # Backstore private stuff

    def __init__(self, plugin, storage_class, index, mode):
        super(Backstore, self).__init__()
        if issubclass(storage_class, StorageObject):
            self._storage_object_class = storage_class
            self._plugin = plugin
        else:
            raise RTSLibError("StorageClass must derive from StorageObject.")
        try:
            self._index = int(index)
        except ValueError:
            raise RTSLibError("Invalid backstore index: %s" % index)
        self._path = "%s/core/%s_%d" % (self.configfs_dir,
                                        self._plugin,
                                        self._index)
        self._create_in_cfs_ine(mode)

    def _get_plugin(self):
        return self._plugin

    def _get_index(self):
        return self._index

    def _list_storage_objects(self):
        self._check_self()
        storage_objects = []
        storage_object_names = [os.path.basename(s)
                                for s in os.listdir(self.path)
                                if s not in set(["hba_info", "hba_mode"])]

        for storage_object_name in storage_object_names:
            storage_objects.append(self._storage_object_class(
                self, storage_object_name))

        return storage_objects

    def _create_in_cfs_ine(self, mode):
        try:
            super(Backstore, self)._create_in_cfs_ine(mode)
        except OSError, msg:
            raise RTSLibError("Cannot create backstore: %s" % msg)

    def _parse_info(self, key):
        self._check_self()
        info = fread("%s/hba_info" % self.path)
        return re.search(".*%s: ([^: ]+).*" \
                         % key, ' '.join(info.split())).group(1).lower()

    def _get_version(self):
        self._check_self()
        return self._parse_info("version")

    def _get_plugin(self):
        self._check_self()
        return self._parse_info("plugin")

    def _get_name(self):
        self._check_self()
        return "%s%d" % (self.plugin, self.index)


    # Backstore public stuff

    def delete(self):
        '''
        Recursively deletes a Backstore object.
        This will delete all attached StorageObject objects, and then the
        Backstore itself. The underlying file and block storages will not be
        touched, but all ramdisk data will be lost.
        '''
        self._check_self()
        for storage in self.storage_objects:
            storage.delete()
        super(Backstore, self).delete()

    plugin = property(_get_plugin,
            doc="Get the backstore plugin name.")
    index = property(_get_index,
            doc="Get the backstore index as an int.")
    storage_objects = property(_list_storage_objects,
            doc="Get the list of StorageObjects attached to the backstore.")
    version = property(_get_version,
            doc="Get the Backstore plugin version string.")
    plugin = property(_get_plugin,
            doc="Get the Backstore plugin name.")
    name = property(_get_name,
            doc="Get the backstore name.")

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

class RDDRBackstore(Backstore):
    '''
    This is an interface to rd_dr backstore plugin objects in configFS.
    A RDDRBackstore object is identified by its backstore index.
    '''

    # RDDRBackstore private stuff

    def __init__(self, index, mode='any'):
        '''
        @param index: The backstore index.
        @type index: int
        @param mode: An optionnal string containing the object creation mode:
            - I{'any'} the configFS object will be either lookupd or created.
            - I{'lookup'} the object MUST already exist configFS.
            - I{'create'} the object must NOT already exist in configFS.
        @type mode:string
        @return: A RDDRBackstore object.
        '''

        super(RDDRBackstore, self).__init__("rd_dr", RDDRStorageObject,
                                             index, mode)

    # RDDRBackstore public stuff

    def storage_object(self, name, size=None, gen_wwn=True):
        '''
        Same as RDDRStorageObject() without specifying the backstore
        '''
        self._check_self()
        return RDDRStorageObject(self, name=name,
                                 size=size, gen_wwn=gen_wwn)

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

        super(RDMCPBackstore, self).__init__("rd_mcp", RDMCPStorageObject,
                                              index, mode)

    # RDMCPBackstore public stuff

    def storage_object(self, name, size=None, gen_wwn=True):
        '''
        Same as RDMCPStorageObject() without specifying the backstore
        '''
        self._check_self()
        return RDMCPStorageObject(self, name=name,
                                  size=size, gen_wwn=gen_wwn)

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
                       gen_wwn=True, buffered_mode=False):
        '''
        Same as FileIOStorageObject() without specifying the backstore
        '''
        self._check_self()
        return FileIOStorageObject(self, name=name, dev=dev,
                                   size=size, gen_wwn=gen_wwn,
                                   buffered_mode=buffered_mode)

class IBlockBackstore(Backstore):
    '''
    This is an interface to iblock backstore plugin objects in configFS.
    An IBlockBackstore object is identified by its backstore index.
    '''

    # IBlockBackstore private stuff

    def __init__(self, index, mode='any'):
        '''
        @param index: The backstore index.
        @type index: int
        @param mode: An optionnal string containing the object creation mode:
            - I{'any'} the configFS object will be either lookupd or created.
            - I{'lookup'} the object MUST already exist configFS.
            - I{'create'} the object must NOT already exist in configFS.
        @type mode:string
        @return: An IBlockBackstore object.
        '''

        super(IBlockBackstore, self).__init__("iblock", IBlockStorageObject,
                                               index, mode)

    # IBlockBackstore public stuff

    def storage_object(self, name, dev=None, gen_wwn=True):
        '''
        Same as IBlockStorageObject() without specifying the backstore
        '''
        self._check_self()
        return IBlockStorageObject(self, name=name, dev=dev,
                                   gen_wwn=gen_wwn)

class StorageObject(CFSNode):
    '''
    This is an interface to storage objects in configFS. A StorageObject is
    identified by its backstore and its name.
    '''
    # StorageObject private stuff

    def __init__(self, backstore, backstore_class, name, mode):
        if not isinstance(backstore, backstore_class):
            raise RTSLibError("The parent backstore must be of "
                              + "type %s" % backstore_class.__name__)
        super(StorageObject, self).__init__()
        self._backstore = backstore
        if "/" in name or " " in name or "\t" in name or "\n" in name:
            raise RTSLibError("A storage object's name cannot contain "
                              " /, newline or spaces/tabs.")
        else:
            self._name = name
        self._path = "%s/%s" % (self.backstore.path, self.name)
        self._create_in_cfs_ine(mode)

    def _get_wwn(self):
        self._check_self()
        if self.is_configured():
            path = "%s/wwn/vpd_unit_serial" % self.path
            return fread(path).partition(":")[2].strip()
        else:
            return ""

    def _set_wwn(self, wwn):
        self._check_self()
        if self.is_configured():
            path = "%s/wwn/vpd_unit_serial" % self.path
            fwrite(path, "%s\n" % wwn)
        else:
            raise RTSLibError("Cannot write a T10 WWN Unit Serial to "
                              + "an unconfigured StorageObject.")

    def _set_udev_path(self, udev_path):
        self._check_self()
        path = "%s/udev_path" % self.path
        fwrite(path, "%s" % udev_path)

    def _get_udev_path(self):
        self._check_self()
        path = "%s/udev_path" % self.path
        udev_path = fread(path).strip()
        if not udev_path and self.backstore.plugin == "fileio":
            udev_path = self._parse_info('File').strip()
        return udev_path

    def _get_name(self):
        return self._name

    def _get_backstore(self):
        return self._backstore

    def _enable(self):
        self._check_self()
        path = "%s/enable" % self.path
        fwrite(path, "1\n")

    def _control(self, command):
        self._check_self()
        path = "%s/control" % self.path
        fwrite(path, "%s" % str(command).strip())

    def _write_fd(self, contents):
        self._check_self()
        path = "%s/fd" % self.path
        fwrite(path, "%s" % str(contents).strip())

    def _parse_info(self, key):
        self._check_self()
        info = fread("%s/info" % self.path)
        return re.search(".*%s: ([^: ]+).*" \
                         % key, ' '.join(info.split())).group(1).lower()

    def _get_status(self):
        self._check_self()
        return self._parse_info('Status')

    def _gen_attached_luns(self):
        '''
        Fast scan of luns attached to a storage object. This is an order of
        magnitude faster than using root.luns and matching path on them.
        '''
        isdir = os.path.isdir
        islink = os.path.islink
        listdir = os.listdir
        realpath = os.path.realpath
        path = self.path
        from root import RTSRoot
        rtsroot = RTSRoot()
        target_names_excludes = FabricModule.target_names_excludes

        for fabric_module in rtsroot.loaded_fabric_modules:
            base = fabric_module.path
            for tgt_dir in listdir(base):
                if tgt_dir not in target_names_excludes:
                    tpgts_base = "%s/%s" % (base, tgt_dir)
                    for tpgt_dir in listdir(tpgts_base):
                        luns_base = "%s/%s/lun" % (tpgts_base, tpgt_dir)
                        if isdir(luns_base):
                            for lun_dir in listdir(luns_base):
                                links_base = "%s/%s" % (luns_base, lun_dir)
                                for lun_file in listdir(links_base):
                                    link = "%s/%s" % (links_base, lun_file)
                                    if islink(link) and realpath(link) == path:
                                        val = (tpgt_dir + "_" + lun_dir)
                                        val = val.split('_')
                                        target = Target(fabric_module, tgt_dir)
                                        yield LUN(TPG(target, val[1]), val[3])

    def _list_attached_luns(self):
        '''
        Just returns a set of all luns attached to a storage object.
        '''
        self._check_self()
        luns = set([])
        for lun in self._gen_attached_luns():
            luns.add(lun)
        return luns

    # StorageObject public stuff

    def delete(self):
        '''
        Recursively deletes a StorageObject object.
        This will delete all attached LUNs currently using the StorageObject
        object, and then the StorageObject itself. The underlying file and
        block storages will not be touched, but all ramdisk data will be lost.
        '''
        self._check_self()

        # If we are called after a configure error, we can skip this
        if self.is_configured():
            for lun in self._gen_attached_luns():
                if self.status != 'activated':
                    break
                else:
                    lun.delete()

        super(StorageObject, self).delete()

    def is_configured(self):
        '''
        @return: True if the StorageObject is configured, else returns False
        '''

        self._check_self()
        path = "%s/info" % self.path
        try:
            fread(path)
        except IOError:
            return False
        else:
            return True

    backstore = property(_get_backstore,
            doc="Get the backstore object.")
    name = property(_get_name,
            doc="Get the StorageObject name as a string.")
    udev_path = property(_get_udev_path,
            doc="Get the StorageObject udev_path as a string.")
    wwn = property(_get_wwn, _set_wwn,
            doc="Get or set the StorageObject T10 WWN Serial as a string.")
    status = property(_get_status,
            doc="Get the storage object status, depending on wether or not it"\
                + "is used by any LUN")
    attached_luns = property(_list_attached_luns,
            doc="Get the list of all LUN objects attached.")

class PSCSIStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for pscsi backstore.
    '''

    # PSCSIStorageObject private stuff

    def __init__(self, backstore, name, dev=None):
        '''
        A PSCSIStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{dev} is specified, the underlying configFS
              object will be created with that parameter. No PSCSIStorageObject
              with the same I{name} can pre-exist in the parent PSCSIBackstore
              in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{dev} is not set, then the PSCSIStorageObject
              will be bound to the existing configFS object in the parent
              PSCSIBackstore having the specified I{name}. The underlying
              configFS object must already exist in that mode, or instantiation
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

class RDDRStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for rd_dr backstore.
    '''

    # RDDRStorageObject private stuff

    def __init__(self, backstore, name, size=None, gen_wwn=True):
        '''
        A RDDRStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{size} is specified, the underlying
              configFS object will be created with that parameter.
              No RDDRStorageObject with the same I{name} can pre-exist in the
              parent RDDRBackstore in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{size} is not set, then the RDDRStorageObject
              will be bound to the existing configFS object in the parent
              RDDRBackstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instantiation will fail.

        @param backstore: The parent backstore of the RDDRStorageObject.
        @type backstore: RDDRBackstore
        @param name: The name of the RDDRStorageObject.
        @type name: string
        @param size: The size of the ramdrive to create:
            - If size is an int, it represents a number of bytes
            - If size is a string, the following units can be used :
                - I{B} or no unit present for bytes
                - I{k}, I{K}, I{kB}, I{KB} for kB (kilobytes)
                - I{m}, I{M}, I{mB}, I{MB} for MB (megabytes)
                - I{g}, I{G}, I{gB}, I{GB} for GB (gigabytes)
                - I{t}, I{T}, I{tB}, I{TB} for TB (terabytes)
                Example: size="1MB" for a one megabytes storage object.
                - Note that the size will be rounded to the closest 4096 Bytes
                  RAM pages count. For instance, a size of 100000 Bytes will be
                  rounded to 24 pages, really 98304 Bytes.
                - The base value for kilo is 1024, aka 1kB = 1024B.
                  Strictly speaking, we use kiB, MiB, etc.
        @type size: string or int
        @param gen_wwn: Should we generate a T10 WWN Unit Serial ?
        @type gen_wwn: bool
        @return: A RDDRStorageObject object.
        '''

        if size is not None:
            super(RDDRStorageObject, self).__init__(backstore, RDDRBackstore,
                                                    name, 'create')
            try:
                self._configure(size, gen_wwn)
            except:
                self.delete()
                raise
        else:
            super(RDDRStorageObject, self).__init__(backstore, RDDRBackstore,
                                                    name, 'lookup')

    def _configure(self, size, wwn):
        self._check_self()
        size = convert_human_to_bytes(size)
        # convert to 4k pages
        size = round(float(size)/4096)
        if size == 0:
            size = 1

        self._control("rd_pages=%d" % size)
        self._enable()
        if wwn:
            self.wwn = generate_wwn('unit_serial')

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

    # RDDRStorageObject public stuff

    page_size = property(_get_page_size,
            doc="Get the ramdisk page size.")
    pages = property(_get_pages,
            doc="Get the ramdisk number of pages.")
    size = property(_get_size,
            doc="Get the ramdisk size in bytes.")

class RDMCPStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for rd_mcp backstore.
    '''

    # RDMCPStorageObject private stuff

    def __init__(self, backstore, name, size=None, gen_wwn=True):
        '''
        A RDMCPStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{size} is specified, the underlying
              configFS object will be created with that parameter.
              No RDMCPStorageObject with the same I{name} can pre-exist in the
              parent RDMCPBackstore in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{size} is not set, then the
              RDMCPStorageObject will be bound to the existing configFS object
              in the parent RDMCPBackstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instantiation will fail.

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
        @param gen_wwn: Should we generate a T10 WWN Unit Serial ?
        @type gen_wwn: bool
        @return: A RDMCPStorageObject object.
        '''

        if size is not None:
            super(RDMCPStorageObject, self).__init__(backstore,
                                                     RDMCPBackstore,
                                                     name,
                                                     'create')
            try:
                self._configure(size, gen_wwn)
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
        size = convert_human_to_bytes(size)
        # convert to 4k pages
        size = round(float(size)/4096)
        if size == 0:
            size = 1

        self._control("rd_pages=%d" % size)
        self._enable()
        if wwn:
            self.wwn = generate_wwn('unit_serial')

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


class FileIOStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for fileio backstore.
    '''

    # FileIOStorageObject private stuff

    def __init__(self, backstore, name, dev=None, size=None,
                 gen_wwn=True, buffered_mode=False):
        '''
        A FileIOStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{dev} and I{size} are specified, the
              underlying configFS object will be created with those parameters.
              No FileIOStorageObject with the same I{name} can pre-exist in the
              parent FileIOBackstore in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{dev} and I{size} are not set, then the
              FileIOStorageObject will be bound to the existing configFS object
              in the parent FileIOBackstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instantiation will fail.

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
        @param gen_wwn: Should we generate a T10 WWN Unit Serial ?
        @type gen_wwn: bool
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
                self._configure(dev, size, gen_wwn, buffered_mode)
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
            size = convert_human_to_bytes(size)
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

        if wwn:
            self.wwn = generate_wwn('unit_serial')

    def _get_mode(self):
        self._check_self()
        return self._parse_info('Mode')

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

    mode = property(_get_mode,
            doc="Get the current FileIOStorage mode, buffered or synchronous")
    size = property(_get_size,
            doc="Get the current FileIOStorage size in bytes")

class IBlockStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for iblock backstore.
    '''

    # IBlockStorageObject private stuff

    def __init__(self, backstore, name, dev=None, gen_wwn=True):
        '''
        A BlockIOStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{dev} is specified, the underlying configFS
              object will be created with that parameter.
              No BlockIOStorageObject with the same I{name} can pre-exist in
              the parent BlockIOBackstore in that mode.
            - B{Lookup mode}: If I{dev} is not set, then the
              BlockIOStorageObject will be bound to the existing configFS
              object in the parent BlockIOBackstore having the specified
              I{name}. The underlying configFS object must already exist in
              that mode, or instantiation will fail.

        @param backstore: The parent backstore of the BlockIOStorageObject.
        @type backstore: BlockIOBackstore
        @param name: The name of the BlockIOStorageObject.
        @type name: string
        @param dev: The path to the backend block device to be used.
            - Example: I{dev="/dev/sda"}.
            - The only device type that is accepted I{TYPE_DISK}.
              For other device types, use pscsi.
        @type dev: string
        @param gen_wwn: Should we generate a T10 WWN Unit Serial when
        creating the object ?
        @type gen_wwn: bool
        @return: A BlockIOStorageObject object.
        '''

        if dev is not None:
            super(IBlockStorageObject, self).__init__(backstore,
                                                      IBlockBackstore,
                                                      name,
                                                      'create')
            try:
                self._configure(dev, gen_wwn)
            except:
                self.delete()
                raise
        else:
            super(IBlockStorageObject, self).__init__(backstore,
                                                      IBlockBackstore,
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
        if wwn:
            self.wwn = generate_wwn('unit_serial')

    def _get_major(self):
        self._check_self()
        return int(self._parse_info('Major'))

    def _get_minor(self):
        self._check_self()
        return int(self._parse_info('Minor'))

    # IblockStorageObject public stuff

    major = property(_get_major,
            doc="Get the block device major number")
    minor = property(_get_minor,
            doc="Get the block device minor number")

def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
