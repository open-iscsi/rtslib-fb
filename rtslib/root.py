'''
Implements the RTSRoot class.

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

import os
import stat
import json

from .node import CFSNode
from .target import Target
from .fabric import FabricModule
from .tcm import so_mapping, bs_cache, StorageObject
from .utils import RTSLibError, RTSLibALUANotSupported, modprobe, mount_configfs
from .utils import dict_remove, set_attributes
from .alua import ALUATargetPortGroup

default_save_file = "/etc/target/saveconfig.json"

class RTSRoot(CFSNode):
    '''
    This is an interface to the root of the configFS object tree.
    Is allows one to start browsing Target and StorageObjects,
    as well as helper methods to return arbitrary objects from the
    configFS tree.

    >>> import rtslib.root as root
    >>> rtsroot = root.RTSRoot()
    >>> rtsroot.path
    '/sys/kernel/config/target'
    >>> rtsroot.exists
    True
    >>> rtsroot.targets # doctest: +ELLIPSIS
    [...]
    >>> rtsroot.tpgs # doctest: +ELLIPSIS
    [...]
    >>> rtsroot.storage_objects # doctest: +ELLIPSIS
    [...]
    >>> rtsroot.network_portals # doctest: +ELLIPSIS
    [...]

    '''

    # RTSRoot private stuff
    def __init__(self):
        '''
        Instantiate an RTSRoot object. Basically checks for configfs setup and
        base kernel modules (tcm)
        '''
        super(RTSRoot, self).__init__()
        try:
            mount_configfs()
        except RTSLibError:
            modprobe('configfs')
            mount_configfs()

        try:
            self._create_in_cfs_ine('any')
        except RTSLibError:
            modprobe('target_core_mod')
            self._create_in_cfs_ine('any')

    def _list_targets(self):
        self._check_self()
        for fabric_module in self.fabric_modules:
            for target in fabric_module.targets:
                yield target

    def _list_storage_objects(self):
        self._check_self()
        for so in StorageObject.all():
            yield so

    def _list_alua_tpgs(self):
        self._check_self()
        for so in self.storage_objects:
            for a in so.alua_tpgs:
                yield a

    def _list_tpgs(self):
        self._check_self()
        for t in self.targets:
            for tpg in t.tpgs:
                yield tpg

    def _list_node_acls(self):
        self._check_self()
        for t in self.tpgs:
            for node_acl in t.node_acls:
                yield node_acl

    def _list_node_acl_groups(self):
        self._check_self()
        for t in self.tpgs:
            for nag in t.node_acl_groups:
                yield nag

    def _list_mapped_luns(self):
        self._check_self()
        for na in self.node_acls:
            for mlun in na.mapped_luns:
                yield mlun

    def _list_mapped_lun_groups(self):
        self._check_self()
        for nag in self.node_acl_groups:
            for mlg in nag.mapped_lun_groups:
                yield mlg

    def _list_network_portals(self):
        self._check_self()
        for t in self.tpgs:
            for p in t.network_portals:
                yield p

    def _list_luns(self):
        self._check_self()
        for t in self.tpgs:
            for lun in t.luns:
                yield lun

    def _list_sessions(self):
        self._check_self()
        for na in self.node_acls:
            if na.session:
                yield na.session

    def _list_fabric_modules(self):
        self._check_self()
        for mod in FabricModule.all():
            yield mod

    def __str__(self):
        return "rtslib"

    # RTSRoot public stuff

    def dump(self):
        '''
        Returns a dict representing the complete state of the target
        config, suitable for serialization/deserialization, and then
        handing to restore().
        '''
        d = super(RTSRoot, self).dump()
        d['storage_objects'] = [so.dump() for so in self.storage_objects]
        d['targets'] = [t.dump() for t in self.targets]
        d['fabric_modules'] = [f.dump() for f in self.fabric_modules
                               if f.has_feature("discovery_auth")
                               if f.discovery_enable_auth]
        return d

    def clear_existing(self, confirm=False):
        '''
        Remove entire current configuration.
        '''
        if not confirm:
            raise RTSLibError("As a precaution, confirm=True needs to be set")

        # Targets depend on storage objects, delete them first.
        for t in self.targets:
            t.delete()
        for fm in (f for f in self.fabric_modules if f.has_feature("discovery_auth")):
            fm.clear_discovery_auth_settings()
        for so in self.storage_objects:
            so.delete()

    def restore(self, config, clear_existing=False, abort_on_error=False):
        '''
        Takes a dict generated by dump() and reconfigures the target to match.
        Returns list of non-fatal errors that were encountered.
        Will refuse to restore over an existing configuration unless clear_existing
            is True.
        '''
        if clear_existing:
            self.clear_existing(confirm=True)
        elif any(self.storage_objects) or any(self.targets):
            raise RTSLibError("storageobjects or targets present, not restoring")

        errors = []

        if abort_on_error:
            def err_func(err_str):
                raise RTSLibError(err_str)
        else:
            def err_func(err_str):
                errors.append(err_str + ", skipped")

        for index, so in enumerate(config.get('storage_objects', [])):
            if 'name' not in so:
                err_func("'name' not defined in storage object %d" % index)
                continue
            try:
                so_cls = so_mapping[so['plugin']]
            except KeyError:
                err_func("'plugin' not defined or invalid in storageobject %s" % so['name'])
                continue
            kwargs = so.copy()
            dict_remove(kwargs, ('exists', 'attributes', 'plugin', 'buffered_mode', 'alua_tpgs'))
            try:
                so_obj = so_cls(**kwargs)
            except Exception as e:
                err_func("Could not create StorageObject %s: %s" % (so['name'], e))
                continue

            # Custom err func to include block name
            def so_err_func(x):
                return err_func("Storage Object %s/%s: %s" % (so['plugin'], so['name'], x))

            set_attributes(so_obj, so.get('attributes', {}), so_err_func)

            for alua_tpg in so.get('alua_tpgs', {}):
               try:
                   ALUATargetPortGroup.setup(so_obj, alua_tpg, err_func)
               except RTSLibALUANotSupported:
                   pass

        # Don't need to create fabric modules
        for index, fm in enumerate(config.get('fabric_modules', [])):
            if 'name' not in fm:
                err_func("'name' not defined in fabricmodule %d" % index)
                continue
            for fm_obj in self.fabric_modules:
                if fm['name'] == fm_obj.name:
                    fm_obj.setup(fm, err_func)
                    break

        for index, t in enumerate(config.get('targets', [])):
            if 'wwn' not in t:
                err_func("'wwn' not defined in target %d" % index)
                continue
            if 'fabric' not in t:
                err_func("target %s missing 'fabric' field" % t['wwn'])
                continue
            if t['fabric'] not in (f.name for f in self.fabric_modules):
                err_func("Unknown fabric '%s'" % t['fabric'])
                continue

            fm_obj = FabricModule(t['fabric'])

            # Instantiate target
            Target.setup(fm_obj, t, err_func)

        return errors

    def save_to_file(self, save_file=None):
        '''
        Write the configuration in json format to a file.
        Save file defaults to '/etc/targets/saveconfig.json'.
        '''
        if not save_file:
            save_file = default_save_file

        with open(save_file+".temp", "w+") as f:
            os.fchmod(f.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            f.write(json.dumps(self.dump(), sort_keys=True, indent=2))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
            f.close()

        os.rename(save_file+".temp", save_file)

    def restore_from_file(self, restore_file=None, clear_existing=True, abort_on_error=False):
        '''
        Restore the configuration from a file in json format.
        Restore file defaults to '/etc/targets/saveconfig.json'.
        Returns a list of non-fatal errors. If abort_on_error is set,
          it will raise the exception instead of continuing.
        '''
        if not restore_file:
            restore_file = default_save_file

        with open(restore_file, "r") as f:
            config = json.loads(f.read())
            return self.restore(config, clear_existing=clear_existing,
                                abort_on_error=abort_on_error)

    def invalidate_caches(self):
        '''
        Invalidate any caches used throughout the hierarchy
        '''
        bs_cache.clear()

    targets = property(_list_targets,
            doc="Get the list of Target objects.")
    tpgs = property(_list_tpgs,
            doc="Get the list of all the existing TPG objects.")
    node_acls = property(_list_node_acls,
            doc="Get the list of all the existing NodeACL objects.")
    node_acl_groups = property(_list_node_acl_groups,
            doc="Get the list of all the existing NodeACLGroup objects.")
    mapped_luns = property(_list_mapped_luns,
            doc="Get the list of all the existing MappedLUN objects.")
    mapped_lun_groups = property(_list_mapped_lun_groups,
            doc="Get the list of all the existing MappedLUNGroup objects.")
    sessions = property(_list_sessions,
            doc="Get the list of all the existing sessions.")
    network_portals = property(_list_network_portals,
            doc="Get the list of all the existing Network Portal objects.")
    storage_objects = property(_list_storage_objects,
            doc="Get the list of all the existing Storage objects.")
    luns = property(_list_luns,
            doc="Get the list of all existing LUN objects.")
    fabric_modules = property(_list_fabric_modules,
            doc="Get the list of all FabricModule objects.")
    alua_tpgs = property(_list_alua_tpgs,
            doc="Get the list of all ALUA TPG objects.")

def _test():
    '''Run the doctests.'''
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
