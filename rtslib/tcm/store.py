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

class Backstore(CFSNode):

    # Backstore private stuff

    def __init__(self, plugin, storage_class, index, mode, alt_dirprefix=None):
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
        if alt_dirprefix:
            dirp = alt_dirprefix
        else:
            dirp = plugin
        self._path = "%s/core/%s_%d" % (self.configfs_dir,
                                        dirp,
                                        self._index)
        self._create_in_cfs_ine(mode)

    def _get_index(self):
        return self._index

    def _list_storage_objects(self):
        self._check_self()
        storage_object_names = [os.path.basename(s)
                                for s in os.listdir(self.path)
                                if s not in set(["hba_info", "hba_mode"])]

        for storage_object_name in storage_object_names:
            yield self._storage_object_class(self, storage_object_name)

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
        return self._plugin

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
    name = property(_get_name,
            doc="Get the backstore name.")

    def dump(self):
        d = super(Backstore, self).dump()
        d['storage_objects'] = [so.dump() for so in self.storage_objects]
        d['plugin'] = self.plugin
        d['name'] = self.name
        return d


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

        for base in (fm.path for fm in rtsroot.fabric_modules if fm.exists):
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

    @classmethod
    def setup(cls, bs_obj, **so):
        '''
        Set up storage objects based upon so dict, from saved config.
        Guard against missing or bad dict items, but keep going.
        Returns how many recoverable errors happened.
        '''
        errors = 0
        kwargs = so.copy()
        dict_remove(kwargs, ('exists', 'attributes', 'plugin'))
        try:
            so_obj = bs_obj._storage_object_class(bs_obj, **kwargs)
            set_attributes(so_obj, so.get('attributes', {}))
        except (RTSLibError, TypeError):
            errors += 1 # config was broken, but keep going
        return errors

    def dump(self):
        d = super(StorageObject, self).dump()
        d['name'] = self.name
        d['wwn'] = self.wwn
        return d


def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
