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
import glob

from target import LUN, TPG, Target, FabricModule
from node import CFSNode
from utils import fread, fwrite, RTSLibError, list_scsi_hbas, generate_wwn
from utils import convert_scsi_path_to_hctl, convert_scsi_hctl_to_path
from utils import is_dev_in_use, get_block_type
from utils import is_disk_partition, get_disk_size


class StorageObject(CFSNode):
    '''
    This is an interface to storage objects in configFS. A StorageObject is
    identified by its backstore and its name.
    '''
    # StorageObject private stuff

    def __init__(self, name, mode):
        super(StorageObject, self).__init__()
        if "/" in name or " " in name or "\t" in name or "\n" in name:
            raise RTSLibError("A storage object's name cannot contain "
                              " /, newline or spaces/tabs.")
        else:
            self._name = name
        self._backstore = _Backstore(name, type(self), mode)
        self._path = "%s/%s" % (self._backstore.path, self.name)
        self.plugin = self._backstore.plugin
        try:
            self._create_in_cfs_ine(mode)
        except:
            self._backstore.delete()
            raise

    @classmethod
    def all(cls, path):
        mapping = dict(
            fileio=FileIOStorageObject,
            pscsi=PSCSIStorageObject,
            iblock=BlockStorageObject,
            rd_mcp=RDMCPStorageObject,
            )
        for so_type, so_name in cls._hbas(path):
            yield mapping[so_type](so_name)

    @classmethod
    def _hbas(cls, path):
        if os.path.isdir("%s/core" % path):
            for backstore_dir in glob.glob("%s/core/*_*/*" % path):
                if os.path.isdir(backstore_dir):
                    so_name = os.path.basename(backstore_dir)
                    so_type = backstore_dir.split("/")[-2].rsplit("_", 1)[0]
                    yield (so_type, so_name)

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
        if not udev_path and self._backstore.plugin == "fileio":
            udev_path = self._parse_info('File').strip()
        return udev_path

    def _get_version(self):
        return self._backstore.version

    def _get_name(self):
        return self._name

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

        for base, fm in ((fm.path, fm) for fm in rtsroot.fabric_modules if fm.exists):
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
                                        target = Target(fm, tgt_dir)
                                        yield LUN(TPG(target, val[1]), val[3])

    def _list_attached_luns(self):
        '''
        Generates all luns attached to a storage object.
        '''
        self._check_self()
        for lun in self._gen_attached_luns():
            yield lun

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
        self._backstore.delete()

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

    version = property(_get_version,
            doc="Get the version of the StorageObject's backstore")
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

    def dump(self):
        d = super(StorageObject, self).dump()
        d['name'] = self.name
        d['wwn'] = self.wwn
        d['plugin'] = self.plugin
        return d


class PSCSIStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for pscsi backstore.
    '''

    # PSCSIStorageObject private stuff

    def __init__(self, name, dev=None):
        '''
        A PSCSIStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{dev} is specified, the underlying configFS
              object will be created with that parameter. No PSCSIStorageObject
              with the same I{name} can pre-exist in the parent Backstore
              in that mode, or instanciation will fail.
            - B{Lookup mode}: If I{dev} is not set, then the PSCSIStorageObject
              will be bound to the existing configFS object in the parent
              Backstore having the specified I{name}. The underlying
              configFS object must already exist in that mode, or instanciation
              will fail.

        @param name: The name of the PSCSIStorageObject.
        @type name: string
        @param dev: You have two choices:
            - Use the SCSI id of the device: I{dev="H:C:T:L"}.
            - Use the path to the SCSI device: I{dev="/path/to/dev"}.
        @type dev: string
        @return: A PSCSIStorageObject object.
        '''
        if dev is not None:
            super(PSCSIStorageObject, self).__init__(name, 'create')
            try:
                self._configure(dev)
            except:
                self.delete()
                raise
        else:
            super(PSCSIStorageObject, self).__init__(name, 'lookup')

    def _configure(self, dev):
        self._check_self()
        parent_hostid = self.backstore.index

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


class RDMCPStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for rd_mcp backstore.
    '''

    # RDMCPStorageObject private stuff

    def __init__(self, name, size=None, wwn=None):
        '''
        A RDMCPStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{size} is specified, the underlying
              configFS object will be created with that parameter.
              No RDMCPStorageObject with the same I{name} can pre-exist in the
              parent Backstore in that mode, or instanciation will fail.
            - B{Lookup mode}: If I{size} is not set, then the
              RDMCPStorageObject will be bound to the existing configFS object
              in the parent Backstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instanciation will fail.

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
            super(RDMCPStorageObject, self).__init__(name, 'create')
            try:
                self._configure(size, wwn)
            except:
                self.delete()
                raise
        else:
            super(RDMCPStorageObject, self).__init__(name, 'lookup')

    def _configure(self, size, wwn):
        self._check_self()
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


class FileIOStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for fileio backstore.
    '''

    # FileIOStorageObject private stuff

    def __init__(self, name, dev=None, size=None,
                 wwn=None, write_back=False):
        '''
        A FileIOStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{dev} and I{size} are specified, the
              underlying configFS object will be created with those parameters.
              No FileIOStorageObject with the same I{name} can pre-exist in the
              parent Backstore in that mode, or instanciation will fail.
            - B{Lookup mode}: If I{dev} and I{size} are not set, then the
              FileIOStorageObject will be bound to the existing configFS object
              in the parent Backstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instanciation will fail.

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
        @param write_back: Should we create the StorageObject with
        write caching enabled? Disabled by default
        @type write_back: bool
        @return: A FileIOStorageObject object.
        '''

        if dev is not None:
            super(FileIOStorageObject, self).__init__(name, 'create')
            try:
                self._configure(dev, size, wwn, write_back)
            except:
                self.delete()
                raise
        else:
            super(FileIOStorageObject, self).__init__(name, 'lookup')

    def _configure(self, dev, size, wwn, write_back):
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

        self._enable()

        if write_back:
            self.set_attribute("emulate_write_cache", 1)

        if not wwn:
            wwn = generate_wwn('unit_serial')
        self.wwn = wwn

    def _get_wb_enabled(self):
        self._check_self()
        return bool(int(self.get_attribute("emulate_write_cache")))

    def _get_size(self):
        self._check_self()
        return int(self._parse_info('Size'))

    # FileIOStorageObject public stuff

    write_back = property(_get_wb_enabled,
            doc="True if write-back, False if write-through (write cache disabled)")
    size = property(_get_size,
            doc="Get the current FileIOStorage size in bytes")

    def dump(self):
        d = super(FileIOStorageObject, self).dump()
        d['write_back'] = self.write_back
        d['dev'] = self.udev_path
        d['size'] = self.size
        return d


class BlockStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for block backstore.
    '''

    # BlockStorageObject private stuff

    def __init__(self, name, dev=None, wwn=None, readonly=False,
                 write_back=False):
        '''
        A BlockIOStorageObject can be instanciated in two ways:
            - B{Creation mode}: If I{dev} is specified, the underlying configFS
              object will be created with that parameter.
              No BlockIOStorageObject with the same I{name} can pre-exist in
              the parent Backstore in that mode.
            - B{Lookup mode}: If I{dev} is not set, then the
              BlockIOStorageObject will be bound to the existing configFS
              object in the parent Backstore having the specified
              I{name}. The underlying configFS object must already exist in
              that mode, or instanciation will fail.

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
            super(BlockStorageObject, self).__init__(name, 'create')
            try:
                self._configure(dev, wwn, readonly, write_back)
            except:
                self.delete()
                raise
        else:
            super(BlockStorageObject, self).__init__(name, 'lookup')

    def _configure(self, dev, wwn, readonly, write_back):
        self._check_self()
        if get_block_type(dev) != 0:
            raise RTSLibError("Device is not a TYPE_DISK block device.")
        if is_dev_in_use(dev):
            raise RTSLibError("Cannot configure StorageObject because "
                              + "device %s is already in use." % dev)
        self._set_udev_path(dev)
        self._control("udev_path=%s" % dev)
        self._control("readonly=%d" % readonly)
        self._enable()

        if write_back:
            self.set_attribute("emulate_write_cache", 1)

        if not wwn:
            wwn = generate_wwn('unit_serial')
        self.wwn = wwn

    def _get_major(self):
        self._check_self()
        return int(self._parse_info('Major'))

    def _get_minor(self):
        self._check_self()
        return int(self._parse_info('Minor'))

    def _get_size(self):
        return get_disk_size(self.udev_path)

    def _get_wb_enabled(self):
        self._check_self()
        return bool(int(self.get_attribute("emulate_write_cache")))

    def _get_readonly(self):
        self._check_self()
        return bool(int(self._parse_info('readonly')))

    # BlockStorageObject public stuff

    major = property(_get_major,
            doc="Get the block device major number")
    minor = property(_get_minor,
            doc="Get the block device minor number")
    size = property(_get_size,
            doc="Get the block device size")
    write_back = property(_get_wb_enabled,
            doc="True if write-back, False if write-through (write cache disabled)")
    readonly = property(_get_readonly,
            doc="True if the device is read-only, False if read/write")

    def dump(self):
        d = super(BlockStorageObject, self).dump()
        d['write_back'] = self.write_back
        d['readonly'] = self.readonly
        d['dev'] = self.udev_path
        return d


bs_params = {
    PSCSIStorageObject: dict(name='pscsi'),
    RDMCPStorageObject: dict(name='ramdisk', alt_dirprefix='rd_mcp'),
    FileIOStorageObject: dict(name='fileio'),
    BlockStorageObject: dict(name='block', alt_dirprefix='iblock'),
    }


class _Backstore(CFSNode):
    """
    Backstore is needed as a level in the configfs hierarchy, but otherwise useless.
    1:1 so:backstore.
    Created by storageobject ctor before SO configfs entry.
    """

    def __init__(self, name, storage_object_cls, mode, index=None):
        super(_Backstore, self).__init__()
        self._so_cls = storage_object_cls
        self._plugin = bs_params[self._so_cls]['name']
        self._index = index

        dirp = bs_params[self._so_cls].get("alt_dirprefix", self._plugin)

        # does (so_cls, index) exist already?
        for plugin, num in self._hbas(self.path):
            if os.path.isdir("%s/core/%s_%s/%s" %
                             (self.path, dirp, num, name)):
                if mode == 'create':
                    raise RTSLibError("Storage object %s/%s already exists" %
                                      (self._plugin, name))
                else:
                    self._index = int(num)
                    break

        if self._index == None:
            self._index = self._next_hba_index(self.configfs_dir)

        self._path = "%s/core/%s_%d" % (self.configfs_dir,
                                        dirp,
                                        self._index)
        self._create_in_cfs_ine(mode)

    @classmethod
    def _next_hba_index(cls, path):
        indexes = [int(y) for x, y in cls._hbas(path)]
        for index in xrange(1048576):
            if index not in indexes:
                return index
        else:
            raise ExecutionError("Cannot find an available backstore index.")

    @classmethod
    def _hbas(cls, path):
        if os.path.isdir("%s/core" % path):
            backstore_dirs = glob.glob("%s/core/*_*" % path)
            for backstore_dir in [os.path.basename(path)
                                  for path in backstore_dirs]:
                regex = re.search("([a-z]+[_]*[a-z]+)(_)([0-9]+)",
                                  backstore_dir)
                if regex:
                    yield(regex.group(1), regex.group(3))

    def _get_index(self):
        return self._index

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
        return self._plugin

    def _get_name(self):
        self._check_self()
        return "%s%d" % (self.plugin, self.index)

    plugin = property(_get_plugin,
            doc="Get the backstore plugin name.")
    index = property(_get_index,
            doc="Get the backstore index as an int.")
    version = property(_get_version,
            doc="Get the Backstore plugin version string.")
    name = property(_get_name,
            doc="Get the backstore name.")


def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
