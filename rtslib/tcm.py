'''
Implements the RTS Target backstore and storage object classes.

This file is part of RTSLib.
Copyright (c) 2011-2013 by Datera, Inc
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

import fcntl
import os
import re
import resource
from contextlib import suppress
from pathlib import Path

from .alua import ALUATargetPortGroup
from .node import CFSNode
from .utils import (
    RTSLibError,
    RTSLibNotInCFSError,
    convert_scsi_hctl_to_path,
    convert_scsi_path_to_hctl,
    fread,
    fwrite,
    generate_wwn,
    get_blockdev_type,
    get_size_for_blk_dev,
    get_size_for_disk_name,
    is_dev_in_use,
)

lock_file = '/var/run/rtslib_backstore.lock'

def storage_object_get_alua_support_attr(so):
    '''
    Helper function that can be called by passthrough type of backends.
    '''
    with suppress(RTSLibError):
        if int(so.get_attribute("alua_support")) == 1:
            return True
    # Default to false because older kernels will crash when
    # reading/writing to some ALUA files when ALUA was not
    # fully supported by pscsi and tcmu.
    return False

class StorageObject(CFSNode):
    '''
    This is an interface to storage objects in configFS. A StorageObject is
    identified by its backstore and its name.
    '''
    # StorageObject private stuff

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.plugin}/{self.name}>"

    def __init__(self, name, mode, index=None):
        super().__init__()
        if "/" in name or " " in name or "\t" in name or "\n" in name:
            raise RTSLibError("A storage object's name cannot contain "
                              " /, newline or spaces/tabs")
        else:
            self._name = name
        self._backstore = _Backstore(name, type(self), mode, index)
        self._path = f"{self._backstore.path}/{self.name}"
        self.plugin = self._backstore.plugin
        try:
            self._create_in_cfs_ine(mode)
        except:
            self._backstore.delete()
            raise

    def _configure(self, wwn=None):
        if not wwn:
            wwn = generate_wwn('unit_serial')
        self.wwn = wwn

        self._config_pr_aptpl()

    def __eq__(self, other):
        return self.plugin == other.plugin and self.name == other.name

    def __ne__(self, other):
        return not self == other

    def _config_pr_aptpl(self):
        """
        LIO actually *writes* pr aptpl info to the filesystem, so we
        need to read it in and squirt it back into configfs when we configure
        the storage object. BLEH.
        """
        from .root import RTSRoot
        aptpl_dir = f"{RTSRoot().dbroot}/pr"

        try:
            lines = fread(f"{aptpl_dir}/aptpl_{self.wwn}").split()
        except:
            return

        if not lines[0].startswith("PR_REG_START:"):
            return

        reservations = []
        for line in lines:
            if line.startswith("PR_REG_START:"):
                res_list = []
            elif line.startswith("PR_REG_END:"):
                reservations.append(res_list)
            else:
                res_list.append(line.strip())

        for res in reservations:
            fwrite(self.path + "/pr/res_aptpl_metadata", ",".join(res))

    @classmethod
    def all(cls):
        for so_dir in Path(cls.configfs_dir, 'core').glob('*_*/*'):
            if so_dir.is_dir():
                yield cls.so_from_path(so_dir)

    @classmethod
    def so_from_path(cls, path):
        '''
        Build a StorageObject of the correct type from a configfs path.
        '''
        path = Path(path)  # Ensure path is a Path object
        so_name = path.name
        so_type, so_index = path.parts[-2].rsplit("_", 1)
        return so_mapping[so_type](so_name, index=so_index)

    def _get_wwn(self):
        self._check_self()
        if self.is_configured():
            path = f"{self.path}/wwn/vpd_unit_serial"
            return fread(path).partition(":")[2].strip()
        else:
            raise RTSLibError(
                "Cannot read a T10 WWN Unit Serial from an unconfigured StorageObject")

    def _set_wwn(self, wwn):
        self._check_self()
        if self.is_configured():
            path = f"{self.path}/wwn/vpd_unit_serial"
            fwrite(path, f"{wwn}\n")
        else:
            raise RTSLibError(
                "Cannot write a T10 WWN Unit Serial to an unconfigured StorageObject")

    def _set_udev_path(self, udev_path):
        self._check_self()
        path = f"{self.path}/udev_path"
        fwrite(path, str(udev_path))

    def _get_udev_path(self):
        self._check_self()
        path = f"{self.path}/udev_path"
        udev_path = fread(path)
        if not udev_path and self._backstore.plugin == "fileio":
            udev_path = self._parse_info('File').strip()
        return udev_path

    def _get_version(self):
        return self._backstore.version

    def _get_name(self):
        return self._name

    def _enable(self):
        self._check_self()
        path = f"{self.path}/enable"
        fwrite(path, "1\n")

    def _control(self, command):
        self._check_self()
        path = f"{self.path}/control"
        fwrite(path, str(command).strip())

    def _write_fd(self, contents):
        self._check_self()
        path = f"{self.path}/fd"
        fwrite(path, str(contents).strip())

    def _parse_info(self, key):
        self._check_self()
        info = fread(f"{self.path}/info")
        try:
            return re.search(f".*{key}: ([^: ]+).*", ' '.join(info.split())).group(1)
        except AttributeError:
            return None

    def _get_status(self):
        self._check_self()
        return self._parse_info('Status').lower()

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
        from .fabric import target_names_excludes
        from .root import RTSRoot
        from .target import LUN, TPG, Target

        for base, fm in ((fm.path, fm) for fm in RTSRoot().fabric_modules if fm.exists):
            for tgt_dir in listdir(base):
                if tgt_dir not in target_names_excludes:
                    tpgts_base = f"{base}/{tgt_dir}"
                    for tpgt_dir in listdir(tpgts_base):
                        luns_base = f"{tpgts_base}/{tpgt_dir}/lun"
                        if isdir(luns_base):
                            for lun_dir in listdir(luns_base):
                                links_base = f"{luns_base}/{lun_dir}"
                                for lun_file in listdir(links_base):
                                    link = f"{links_base}/{lun_file}"
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
        yield from self._gen_attached_luns()

    def _list_alua_tpgs(self):
        '''
        Generate all ALUA groups attach to a storage object.
        '''
        self._check_self()
        for tpg in os.listdir(f"{self.path}/alua"):
            if self.alua_supported:
                yield ALUATargetPortGroup(self, tpg)

    def _get_alua_supported(self):
        '''
        Children should override if the backend did not always support ALUA
        '''
        self._check_self()
        return True

    # StorageObject public stuff

    def delete(self, save=False):
        '''
        Recursively deletes a StorageObject object.
        This will delete all attached LUNs currently using the StorageObject
        object, and then the StorageObject itself. The underlying file and
        block storages will not be touched, but all ramdisk data will be lost.
        '''
        self._check_self()

        for alua_tpg in self._list_alua_tpgs():
            if alua_tpg.name != 'default_tg_pt_gp':
                alua_tpg.delete()

        # If we are called after a configure error, we can skip this
        if self.is_configured():
            for lun in self._gen_attached_luns():
                if self.status != 'activated':
                    break
                else:
                    lun.delete()

        super().delete()
        self._backstore.delete()
        if save:
            from .root import RTSRoot, default_save_file
            RTSRoot().save_to_file(default_save_file, f'/backstores/{self.plugin}/{self._name}')

    def is_configured(self):
        '''
        @return: True if the StorageObject is configured, else returns False
        '''
        self._check_self()
        path = Path(self.path) / 'enable'
        # If the StorageObject does not have the enable attribute,
        # then it is always enabled.
        if path.is_file():
            return bool(int(fread(path)))
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
            doc="Get the storage object status, depending on whether or not it is used by any LUN")
    attached_luns = property(_list_attached_luns,
            doc="Get the list of all LUN objects attached.")
    alua_tpgs = property(_list_alua_tpgs,
            doc="Get list of ALUA Target Port Groups attached.")
    alua_supported = property(_get_alua_supported,
            doc="Returns true if ALUA can be setup. False if not supported.")

    def dump(self):
        d = super().dump()
        d['name'] = self.name
        d['plugin'] = self.plugin
        d['alua_tpgs'] = [tpg.dump() for tpg in self.alua_tpgs]
        return d


class PSCSIStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for pscsi backstore.
    '''

    # PSCSIStorageObject private stuff

    def __init__(self, name, dev=None, index=None):
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

        @param name: The name of the PSCSIStorageObject.
        @type name: string
        @param dev: You have two choices:
            - Use the SCSI id of the device: I{dev="H:C:T:L"}.
            - Use the path to the SCSI device: I{dev="/path/to/dev"}.
        @type dev: string
        @return: A PSCSIStorageObject object.
        '''
        if dev is not None:
            super().__init__(name, 'create', index)
            try:
                self._configure(dev)
            except:
                self.delete()
                raise
        else:
            super().__init__(name, 'lookup', index)

    def _configure(self, dev):
        self._check_self()

        # Use H:C:T:L format or use the path given by the user.
        try:
            # assume 'dev' is the path, try to get h:c:t:l values
            (hostid, channelid, targetid, lunid) = \
                    convert_scsi_path_to_hctl(dev)
            udev_path = dev.strip()
        except:
            # Oops, maybe 'dev' is in h:c:t:l format, try to get udev_path
            try:
                (hostid, channelid, targetid, lunid) = dev.split(':')
                hostid = int(hostid)
                channelid = int(channelid)
                targetid = int(targetid)
                lunid = int(lunid)
            except ValueError:
                raise RTSLibError("Cannot find SCSI device by path, and dev "
                                  "parameter not in H:C:T:L format: {dev}")

            udev_path = convert_scsi_hctl_to_path(hostid,
                                                  channelid,
                                                  targetid,
                                                  lunid)

        # -- now have all 5 values or have errored out --

        if is_dev_in_use(udev_path):
            raise RTSLibError("Cannot configure StorageObject because "
                              + "device %s (SCSI %d:%d:%d:%d) "
                              % (udev_path, hostid, channelid,
                                 targetid, lunid)
                              + "is already in use")

        self._control("scsi_host_id=%d," % hostid \
                      + "scsi_channel_id=%d," % channelid \
                      + "scsi_target_id=%d," % targetid \
                      + "scsi_lun_id=%d" % lunid)
        self._set_udev_path(udev_path)
        self._enable()

        super()._configure()

    def _set_wwn(self, wwn):
        # pscsi doesn't support setting wwn
        pass

    def _get_model(self):
        self._check_self()
        info = fread(f"{self.path}/info")
        return str(re.search(".*Model:(.*)Rev:",
                             ' '.join(info.split())).group(1)).strip()

    def _get_vendor(self):
        self._check_self()
        info = fread(f"{self.path}/info")
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

    def _get_alua_supported(self):
        self._check_self()
        return storage_object_get_alua_support_attr(self)

    # PSCSIStorageObject public stuff

    wwn = property(StorageObject._get_wwn, _set_wwn,
            doc="Get the StorageObject T10 WWN Unit Serial as a string. "
                "You cannot set it for pscsi-backed StorageObjects.")
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
    alua_supported = property(_get_alua_supported,
            doc="Returns true if ALUA can be setup. False if not supported.")

    def dump(self):
        d = super().dump()
        d['dev'] = self.udev_path
        return d


class RDMCPStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for rd_mcp backstore.
    '''

    # RDMCPStorageObject private stuff

    def __init__(self, name, size=None, wwn=None, nullio=False, index=None):
        '''
        A RDMCPStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{size} is specified, the underlying
              configFS object will be created with that parameter.
              No RDMCPStorageObject with the same I{name} can pre-exist in the
              parent Backstore in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{size} is not set, then the
              RDMCPStorageObject will be bound to the existing configFS object
              in the parent Backstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instantiation will fail.

        @param name: The name of the RDMCPStorageObject.
        @type name: string
        @param size: The size of the ramdrive to create, in bytes.
        @type size: int
        @param wwn: T10 WWN Unit Serial, will generate if None
        @type wwn: string
        @param nullio: If rd should be created w/o backing page store.
        @type nullio: boolean
        @return: A RDMCPStorageObject object.
        '''

        if size is not None:
            super().__init__(name, 'create', index)
            try:
                self._configure(size, wwn, nullio)
            except:
                self.delete()
                raise
        else:
            super().__init__(name, 'lookup', index)

    def _configure(self, size, wwn, nullio):
        self._check_self()
        # convert to pages
        size = round(float(size)/resource.getpagesize())
        if size == 0:
            size = 1

        self._control("rd_pages=%d" % size)
        if nullio:
            self._control("rd_nullio=1")
        self._enable()

        super()._configure(wwn)

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

    def _get_nullio(self):
        self._check_self()
        # nullio not present before 3.10
        try:
            return bool(int(self._parse_info('nullio')))
        except AttributeError:
            return False

    # RDMCPStorageObject public stuff

    page_size = property(_get_page_size,
            doc="Get the ramdisk page size.")
    pages = property(_get_pages,
            doc="Get the ramdisk number of pages.")
    size = property(_get_size,
            doc="Get the ramdisk size in bytes.")
    nullio = property(_get_nullio,
            doc="Get the nullio status.")

    def dump(self):
        d = super().dump()
        d['wwn'] = self.wwn
        d['size'] = self.size
        # only dump nullio if enabled
        if self.nullio:
            d['nullio'] = True
        return d


class FileIOStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for fileio backstore.
    '''

    # FileIOStorageObject private stuff

    def __init__(self, name, dev=None, size=None,
                 wwn=None, write_back=False, aio=False, index=None):
        '''
        A FileIOStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{dev} and I{size} are specified, the
              underlying configFS object will be created with those parameters.
              No FileIOStorageObject with the same I{name} can pre-exist in the
              parent Backstore in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{dev} and I{size} are not set, then the
              FileIOStorageObject will be bound to the existing configFS object
              in the parent Backstore having the specified I{name}.
              The underlying configFS object must already exist in that mode,
              or instantiation will fail.

        @param name: The name of the FileIOStorageObject.
        @type name: string
        @param dev: The path to the backend file or block device to be used.
            - Examples: I{dev="/dev/sda"}, I{dev="/tmp/myfile"}
            - The only block device type that is accepted I{TYPE_DISK}, or
              partitions of a I{TYPE_DISK} device.
              For other device types, use pscsi.
        @type dev: string
        @param size: Size of the object, if not a block device
        @type size: int
        @param wwn: T10 WWN Unit Serial, will generate if None
        @type wwn: string
        @param write_back: Should we create the StorageObject with
        write caching enabled? Disabled by default
        @type write_back: bool
        @return: A FileIOStorageObject object.
        '''

        if dev is not None:
            super().__init__(name, 'create', index)
            try:
                self._configure(dev, size, wwn, write_back, aio)
            except:
                self.delete()
                raise
        else:
            super().__init__(name, 'lookup', index)

    def _configure(self, dev, size, wwn, write_back, aio):
        self._check_self()
        block_type = get_blockdev_type(dev)
        if block_type is None: # a file
            if Path(dev).exists() and not Path(dev).is_file():
                raise RTSLibError("Path not to a file or block device")

            if size is None:
                raise RTSLibError("Path is to a file, size needed")

            self._control("fd_dev_name=%s,fd_dev_size=%d" % (dev, size))

        else: # a block device
            # size is ignored but we can't raise an exception because
            # dump() saves it and thus restore() will call us with it.

            if block_type != 0:
                raise RTSLibError("Device is not a TYPE_DISK block device")

            if is_dev_in_use(dev):
                raise RTSLibError(f"Device {dev} is already in use")

            self._control(f"fd_dev_name={dev}")

        if write_back:
            self.set_attribute("emulate_write_cache", 1)
            self._control("fd_buffered_io=%d" % write_back)

        if aio:
            self._control("fd_async_io=%d" % aio)

        self._set_udev_path(dev)

        self._enable()

        super()._configure(wwn)

    def _get_wb_enabled(self):
        self._check_self()
        return bool(int(self.get_attribute("emulate_write_cache")))

    def _get_size(self):
        self._check_self()

        if self.is_block:
            return (get_size_for_blk_dev(self._parse_info('File')) *
                    int(self._parse_info('SectorSize')))
        else:
            return int(self._parse_info('Size'))

    def _is_block(self):
        return get_blockdev_type(self.udev_path) is not None

    def _aio(self):
        self._check_self()
        info = fread(f"{self.path}/info")
        r = re.search(".*Async: ([^: ]+).*", ' '.join(info.split()))
        if not r:  # for backward compatibility with old kernels
            return False

        return bool(int(r.group(1)))

    # FileIOStorageObject public stuff

    write_back = property(_get_wb_enabled,
            doc="True if write-back, False if write-through (write cache disabled)")
    size = property(_get_size,
            doc="Get the current FileIOStorage size in bytes")
    is_block = property(_is_block,
            doc="True if FileIoStorage is backed by a block device instead of a file")
    aio = property(_aio,
            doc="True if asynchronous I/O is enabled")

    def dump(self):
        d = super().dump()
        d['write_back'] = self.write_back
        d['wwn'] = self.wwn
        d['dev'] = self.udev_path
        d['size'] = self.size
        d['aio'] = self.aio
        return d


class BlockStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for block backstore.
    '''

    # BlockStorageObject private stuff

    def __init__(self, name, dev=None, wwn=None, readonly=False,
                 write_back=False, index=None):  # noqa: ARG002 TODO
        '''
        A BlockIOStorageObject can be instantiated in two ways:
            - B{Creation mode}: If I{dev} is specified, the underlying configFS
              object will be created with that parameter.
              No BlockIOStorageObject with the same I{name} can pre-exist in
              the parent Backstore in that mode.
            - B{Lookup mode}: If I{dev} is not set, then the
              BlockIOStorageObject will be bound to the existing configFS
              object in the parent Backstore having the specified
              I{name}. The underlying configFS object must already exist in
              that mode, or instantiation will fail.

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
            super().__init__(name, 'create', index)
            try:
                self._configure(dev, wwn, readonly)
            except:
                self.delete()
                raise
        else:
            super().__init__(name, 'lookup', index)

    def _configure(self, dev, wwn, readonly):
        self._check_self()
        if get_blockdev_type(dev) != 0:
            raise RTSLibError(f"Device {dev} is not a TYPE_DISK block device")
        if is_dev_in_use(dev):
            raise RTSLibError(
                "Cannot configure StorageObject because device {dev} is already in use")
        self._set_udev_path(dev)
        self._control(f"udev_path={dev}")
        self._control("readonly=%d" % readonly)
        self._enable()

        super()._configure(wwn)

    def _get_major(self):
        self._check_self()
        return int(self._parse_info('Major'))

    def _get_minor(self):
        self._check_self()
        return int(self._parse_info('Minor'))

    def _get_size(self):
        # udev_path doesn't work here, what if LV gets renamed?
        return get_size_for_disk_name(
            self._parse_info('device')) * int(self._parse_info('SectorSize'))

    def _get_wb_enabled(self):
        self._check_self()
        return bool(int(self.get_attribute("emulate_write_cache")))

    def _get_readonly(self):
        self._check_self()
        # 'readonly' not present before kernel 3.6
        try:
            return bool(int(self._parse_info('readonly')))
        except AttributeError:
            return False

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
        d = super().dump()
        d['write_back'] = self.write_back
        d['readonly'] = self.readonly
        d['wwn'] = self.wwn
        d['dev'] = self.udev_path
        return d


class UserBackedStorageObject(StorageObject):
    '''
    An interface to configFS storage objects for userspace-backed backstore.
    '''

    def __init__(self, name, config=None, size=None, wwn=None,
                 hw_max_sectors=None, control=None, index=None):
        '''
        @param name: The name of the UserBackedStorageObject.
        @type name: string
        @param config: user-handler-specific config string.
            - e.g. "rbd/machine1@snap4"
        @type config: string
        @param size: The size of the device to create, in bytes.
        @type size: int
        @param wwn: T10 WWN Unit Serial, will generate if None
        @type wwn: string
        @hw_max_sectors: Max sectors per command limit to export to initiators.
        @type hw_max_sectors: int
        @control: String of control=value tuples separate by a ',' that will
            passed to the kernel control file.
        @type: string
        @return: A UserBackedStorageObject object.
        '''

        if size is not None:
            if config is None:
                raise RTSLibError("'size' and 'config' must be set when "
                                  "creating a new UserBackedStorageObject")
            if '/' not in config:
                raise RTSLibError("'config' must contain a '/' separating subtype "
                                  "from its configuration string")
            super().__init__(name, 'create', index)
            try:
                self._configure(config, size, wwn, hw_max_sectors, control)
            except:
                self.delete()
                raise
        else:
            super().__init__(name, 'lookup', index)

    def _configure(self, config, size, wwn, hw_max_sectors, control):
        self._check_self()

        if ':' in config:
            raise RTSLibError("':' not allowed in config string")
        self._control(f"dev_config={config}")
        self._control("dev_size=%d" % size)
        if hw_max_sectors is not None:
            self._control(f"hw_max_sectors={hw_max_sectors}")
        if control is not None:
            self._control(control)
        self._enable()

        super()._configure(wwn)

    def _get_size(self):
        self._check_self()
        return int(self._parse_info('Size'))

    def _get_hw_max_sectors(self):
        self._check_self()
        return int(self._parse_info('HwMaxSectors'))

    def _get_control_tuples(self):
        self._check_self()
        tuples = []
        # 1. max_data_area_mb
        val = self._parse_info('MaxDataAreaMB')
        if val != "NULL":
            tuples.append(f"max_data_area_mb={val}")
        val = self.get_attribute('hw_block_size')
        if val != "NULL":
            tuples.append(f"hw_block_size={val}")
        # 3. data_pages_per_blk
        val = self._parse_info('DataPagesPerBlk')
        if val != "NULL":
            tuples.append(f"data_pages_per_blk={val}")
        # 4. add next ...

        return ",".join(tuples)

    def _get_config(self):
        self._check_self()
        val = self._parse_info('Config')
        if val == "NULL":
            return None
        return val

    def _get_alua_supported(self):
        self._check_self()
        return storage_object_get_alua_support_attr(self)

    hw_max_sectors = property(_get_hw_max_sectors,
            doc="Get the max sectors per command.")
    control_tuples = property(_get_control_tuples,
            doc="Get the comma separated string containing control=value tuples.")
    size = property(_get_size,
            doc="Get the size in bytes.")
    config = property(_get_config,
            doc="Get the TCMU config.")
    alua_supported = property(_get_alua_supported,
            doc="Returns true if ALUA can be setup. False if not supported.")

    def dump(self):
        d = super().dump()
        d['wwn'] = self.wwn
        d['size'] = self.size
        d['config'] = self.config
        d['hw_max_sectors'] = self.hw_max_sectors
        d['control'] = self.control_tuples

        return d


class StorageObjectFactory:
    """
    Create a storage object based on a given path.
    Only works for file & block.
    """

    def __new__(cls, path):
        path = Path(path)
        name = path.name.replace("/", "-")
        if path.exists():
            if path.is_block_device():
                return BlockStorageObject(name=name, dev=str(path))
            elif path.is_file():
                return FileIOStorageObject(name=name, dev=str(path), size=path.stat().st_size)

        raise RTSLibError(f"Can't create storageobject from path: {path}")


# Used to convert either dirprefix or plugin to the SO. Instead of two
# almost-identical dicts we just have some duplicate entries.
so_mapping = {
    "pscsi": PSCSIStorageObject,
    "rd_mcp": RDMCPStorageObject,
    "ramdisk": RDMCPStorageObject,
    "fileio": FileIOStorageObject,
    "iblock": BlockStorageObject,
    "block": BlockStorageObject,
    "user": UserBackedStorageObject,
}


bs_params = {
    PSCSIStorageObject: {'name': 'pscsi'},
    RDMCPStorageObject: {'name': 'ramdisk', 'alt_dirprefix': 'rd_mcp'},
    FileIOStorageObject: {'name': 'fileio'},
    BlockStorageObject: {'name': 'block', 'alt_dirprefix': 'iblock'},
    UserBackedStorageObject: {'name': 'user'},
    }

bs_cache = {}

class _Backstore(CFSNode):
    """
    Backstore is needed as a level in the configfs hierarchy, but otherwise useless.
    1:1 so:backstore.
    Created by storageobject ctor before SO configfs entry.
    """

    def __init__(self, name, storage_object_cls, mode, index=None):
        super().__init__()
        self._so_cls = storage_object_cls
        self._plugin = bs_params[self._so_cls]['name']

        dirp = bs_params[self._so_cls].get("alt_dirprefix", self._plugin)

        # if the caller knows the index then skip the cache
        global bs_cache  # noqa: PLW0602  TODO
        if index is None and not bs_cache:
            for directory in Path(self.configfs_dir).glob("core/*_*/*/"):
                parts = directory.parts
                bs_name = parts[-1]
                bs_dirp, bs_index = parts[-2].rsplit("_", 1)
                current_key = f"{bs_dirp}/{bs_name}"
                bs_cache[current_key] = int(bs_index)

        self._lookup_key = f"{dirp}/{name}"
        if index is None:
            self._index = bs_cache.get(self._lookup_key, None)
            if self._index is not None and mode == 'create':
                raise RTSLibError(f"Storage object {self._plugin}/{name} exists")
        else:
            self._index = int(index)

        if self._index is None:
            if mode == 'lookup':
                raise RTSLibNotInCFSError(f"Storage object {self._plugin}/{name} not found")
            else:
                # Allocate new index value
                Path('/var/run').mkdir(parents=True, exist_ok=True)
                lock_file_path = Path(lock_file)
                with lock_file_path.open('w+') as lkfd:
                    fcntl.flock(lkfd, fcntl.LOCK_EX)
                    indexes = set(bs_cache.values())
                    for i in range(1048576):
                        if i not in indexes:
                            self._index = i
                            bs_cache[self._lookup_key] = self._index
                            break
                    else:
                        fcntl.flock(lkfd, fcntl.LOCK_UN)
                        raise RTSLibError("No available backstore index")
                    fcntl.flock(lkfd, fcntl.LOCK_UN)

        self._path = Path(self.configfs_dir) / "core" / f"{dirp}_{self._index}"
        try:
            self._create_in_cfs_ine(mode)
        except Exception as e:
            if self._lookup_key in bs_cache:
                del bs_cache[self._lookup_key]
            raise e

    def delete(self):
        super().delete()
        if self._lookup_key in bs_cache:
            del bs_cache[self._lookup_key]

    def _get_index(self):
        return self._index

    def _parse_info(self, key):
        self._check_self()
        info = fread(f"{self.path}/hba_info")
        try:
            return re.search(f".*{key}: ([^: ]+).*", ' '.join(info.split())).group(1)
        except AttributeError:
            return None

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
