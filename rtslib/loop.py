'''
Implements the RTS SAS loopback classes.

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

import re
import os
import glob
import uuid
import shutil

# rtslib modules
from root import RTSRoot
from node import CFSNode
from utils import RTSLibError, RTSLibBrokenLink
from utils import generate_wwn, fwrite, fread

class LUN(CFSNode):
    '''
    This is an interface to RTS Target LUNs in configFS.
    A LUN is identified by its parent Nexus and LUN index.
    '''

    # LUN private stuff

    def __init__(self, parent_nexus, lun, storage_object=None, alias=None):
        '''
        A LUN object can be instantiated in two ways:
            - B{Creation mode}: If I{storage_object} is specified, the
              underlying configFS object will be created with that parameter.
              No LUN with the same I{lun} index can pre-exist in the parent
              Nexus in that mode, or instantiation will fail.
            - B{Lookup mode}: If I{storage_object} is not set, then the LUN
              will be bound to the existing configFS LUN object of the parent
              Nexus having the specified I{lun} index. The underlying configFS
              object must already exist in that mode.

        @param parent_nexus: The parent Nexus object.
        @type parent_nexus: Nexus
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

        if isinstance(parent_nexus, Nexus):
            self._parent_nexus = parent_nexus
        else:
            raise RTSLibError("Invalid parent Nexus.")

        try:
            lun = int(lun)
        except ValueError:
            raise RTSLibError("Invalid LUN index: %s" % str(lun))
        else:
            if lun > 255 or lun < 0:
                raise RTSLibError("Invalid LUN index, it must be "
                                  + "between 0 and 255: %d" % lun)
            self._lun = lun

        self._path = "%s/lun/lun_%d" % (self.parent_nexus.path, self.lun)

        if storage_object is None and alias is not None:
            raise RTSLibError("The alias parameter has no meaning "
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

    def __str__(self):
        try:
            storage_object = self.storage_object
        except RTSLibBrokenLink:
            desc = "[BROKEN STORAGE LINK]"
        else:
            backstore = storage_object.backstore
            soname = storage_object.name
            if backstore.plugin.startswith("rd"):
                path = "ramdisk"
            else:
                path = storage_object.udev_path
            desc = "-> %s%d '%s' (%s)" \
                    % (backstore.plugin, backstore.index, soname, path)
        return "LUN %d %s" % (self.lun, desc)

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
        from tcm import StorageObject
        if isinstance(storage_object, StorageObject):
            if storage_object.exists:
                source = storage_object.path
            else:
                raise RTSLibError("The storage_object does not exist "
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
            raise RTSLibBrokenLink("Broken LUN in configFS, no " \
                                         + "storage object attached.")
        rtsroot = RTSRoot()
        for storage_object in rtsroot.storage_objects:
            if storage_object.path == alias_path:
                return storage_object
        raise RTSLibBrokenLink("Broken storage object link in LUN.")

    def _get_parent_nexus(self):
        return self._parent_nexus

    def _get_lun(self):
        return self._lun

    def _get_alua_metadata_path(self):
        return "%s/lun_%d" % (self.parent_nexus.alua_metadata_path, self.lun)

    # LUN public stuff

    def delete(self):
        '''
        If the underlying configFS object does not exists, this method does
        nothing. If the underlying configFS object exists, this method attempts
        to delete it.
        '''
        self._check_self()
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
    parent_nexus = property(_get_parent_nexus,
            doc="Get the parent Nexus object.")
    lun = property(_get_lun,
            doc="Get the LUN index as an int.")
    storage_object = property(_get_storage_object,
            doc="Get the storage object attached to the LUN.")
    alias = property(_get_alias,
            doc="Get the LUN alias.")

class Nexus(CFSNode):
    '''
    This is a an interface to Target Portal Groups in configFS.
    A Nexus is identified by its parent Target object and its nexus Tag.
    To a Nexus object is attached a list of NetworkPortals.
    '''

    # Nexus private stuff

    def __init__(self, parent_target, tag, mode='any'):
        '''
        @param parent_target: The parent Target object of the Nexus.
        @type parent_target: Target
        @param tag: The Nexus Tag (TPGT).
        @type tag: int > 0
        @param mode:An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up or
              created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A Nexus object.
        '''

        super(Nexus, self).__init__()

        try:
            self._tag = int(tag)
        except ValueError:
            raise RTSLibError("Invalid Tag.")

        if tag < 1:
            raise RTSLibError("Invalig Tag, it must be >0.")

        if isinstance(parent_target, Target):
            self._parent_target = parent_target
        else:
            raise RTSLibError("Invalid parent Target.")

        self._path = "%s/tpgt_%d" % (self.parent_target.path, self.tag)
        self._create_in_cfs_ine(mode)

    def __str__(self):
        try:
            initiator = self.initiator
        except RTSLibError:
            initiator = "[BROKEN]"
        return "Nexus %d / initiator %s" % (self.tag, initiator)

    def _get_initiator(self):
        nexus_path = self._path + "/nexus"
        if os.path.isfile(nexus_path):
            try:
                initiator = fread(nexus_path)
            except IOError, msg:
                raise RTSLibError("Cannot read Nexus initiator address "
                                  + "(>=4.0 style, %s): %s."
                                  % (nexus_path, msg))
        else:
            try:
                initiator = os.listdir(nexus_path)[0]
            except IOError, msg:
                raise RTSLibError("Cannot read Nexus initiator address "
                                  + "(<4.0 style, %s): %s."
                                  % (nexus_path, msg))
        return initiator.strip()

    def _get_tag(self):
        return self._tag

    def _get_parent_target(self):
        return self._parent_target

    def _create_in_cfs_ine(self, mode):
        super(Nexus, self)._create_in_cfs_ine(mode)

        if not os.path.isdir(self.alua_metadata_path):
            os.makedirs(self.alua_metadata_path)

        if self._fresh:
            initiator = generate_wwn('naa')
            nexus_path = self._path + "/nexus"
            if os.path.isfile(nexus_path):
                try:
                    fwrite(nexus_path, initiator)
                except IOError, msg:
                    raise RTSLibError("Cannot create Nexus initiator "
                                      + "(>=4.0 style, %s): %s."
                                      % (nexus_path, msg))
            else:
                try:
                    os.makedirs(nexus_path + "/" + initiator)
                except IOError, msg:
                    raise RTSLibError("Cannot create Nexus initiator."
                                      + "(<4.0 style, %s): %s."
                                      % (nexus_path, msg))

    def _list_luns(self):
        self._check_self()
        luns = []
        lun_dirs = [os.path.basename(path)
                    for path in os.listdir("%s/lun" % self.path)]
        for lun_dir in lun_dirs:
            lun = lun_dir.split('_')[1]
            lun = int(lun)
            luns.append(LUN(self, lun))
        return luns

    def _control(self, command):
        self._check_self()
        path = "%s/control" % self.path
        fwrite(path, "%s\n" % str(command))

    def _get_alua_metadata_path(self):
        return "%s/%s+%d"  \
                % (self.alua_metadata_dir,
                   self.parent_target.naa, self.tag)

    # Nexus public stuff

    def delete(self):
        '''
        Recursively deletes a Nexus object.
        This will delete all attached LUN, and then the Nexus itself.
        '''
        self._check_self()
        for lun in self.luns:
            lun.delete()

        # TODO: check that ALUA MD removal works while removing Nexus
        if os.path.isdir(self.alua_metadata_path):
            shutil.rmtree(self.alua_metadata_path)

        nexus_path = self._path + "/nexus"
        if os.path.isfile(nexus_path):
            try:
                fwrite(nexus_path, "NULL")
            except IOError, msg:
                raise RTSLibError("Cannot delete Nexus initiator "
                                  + "(>=4.0 style, %s): %s."
                                  % (nexus_path, msg))
        else:
            try:
                os.rmdir(nexus_path + "/" + self.initiator)
            except IOError, msg:
                raise RTSLibError("Cannot delete Nexus initiator."
                                  + "(<4.0 style, %s): %s."
                                  % (nexus_path, msg))

        super(Nexus, self).delete()

    def lun(self, lun, storage_object=None, alias=None):
        '''
        Same as LUN() but without specifying the parent_nexus.
        '''
        self._check_self()
        return LUN(self, lun=lun, storage_object=storage_object, alias=alias)

    alua_metadata_path = property(_get_alua_metadata_path,
                                  doc="Get the ALUA metadata directory path " \
                                  + "for the Nexus.")
    tag = property(_get_tag,
            doc="Get the Nexus Tag as an int.")
    initiator = property(_get_initiator,
            doc="Get the Nexus initiator address as a string.")
    parent_target = property(_get_parent_target,
                             doc="Get the parent Target object to which the " \
                             + "Nexus is attached.")
    luns = property(_list_luns,
                    doc="Get the list of LUN objects currently attached " \
                    + "to the Nexus.")

class Target(CFSNode):
    '''
    This is an interface to loopback SAS Targets in configFS.
    A Target is identified by its naa SAS address.
    To a Target is attached a list of Nexus objects.
    '''

    # Target private stuff

    def __init__(self, naa=None, mode='any'):
        '''
        @param naa: The optionnal Target's address.
            If no address or an empty address is specified, one will be
            generated for you.
        @type naa: string
        @param mode:An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up
              or created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A Target object.
        '''

        super(Target, self).__init__()

        if naa is None:
            naa = generate_wwn('naa')
        else:
            naa = str(naa).lower().strip()
        self._naa = naa
        self._path = "%s/loopback/%s" % (self.configfs_dir, self._naa)
        if not self:
            if not re.match(
                "naa\.[0-9]+", naa) \
               or re.search(' ', naa) \
               or re.search('_', naa):
                raise RTSLibError("Invalid naa: %s"
                                  % naa)
        self._create_in_cfs_ine(mode)

    def __str__(self):
        return "SAS loopback %s" % self.naa

    def _list_nexuses(self):
        self._check_self()
        nexuses = []
        nexus_dirs = glob.glob("%s/tpgt*" % self.path)
        for nexus_dir in nexus_dirs:
            tag = os.path.basename(nexus_dir).split('_')[1]
            tag = int(tag)
            nexuses.append(Nexus(self, tag, 'lookup'))
        return nexuses

    def _get_naa(self):
        return self._naa

    # Target public stuff

    def delete(self):
        '''
        Recursively deletes a Target object.
        This will delete all attached Nexus objects and then the Target itself.
        '''
        self._check_self()
        for nexus in self.nexuses:
            nexus.delete()
        super(Target, self).delete()

    def nexus(self, tag, mode='any'):
        '''
        Same as Nexus() but without the parent_target parameter.
        '''
        self._check_self()
        return Nexus(self, tag=tag, mode=mode)

    naa = property(_get_naa,
                   doc="Get the naa of the Target object as a string.")
    nexuses = property(_list_nexuses,
                       doc="Get the list of Nexus objects currently "
                       + "attached to the Target.")

def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
