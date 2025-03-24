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

import errno
import json
import os
from contextlib import suppress
from pathlib import Path

from .alua import ALUATargetPortGroup
from .fabric import FabricModule
from .node import CFSNode
from .target import Target
from .tcm import StorageObject, bs_cache, so_mapping
from .utils import (
    RTSLibALUANotSupportedError,
    RTSLibError,
    dict_remove,
    fread,
    fwrite,
    modprobe,
    mount_configfs,
    set_attributes,
)

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

    # this should match the kernel target driver default db dir
    _default_dbroot = "/var/target"
    # this is where the target DB is to be located (instead of the default)
    _preferred_dbroot = "/etc/target"

    def __init__(self):
        '''
        Instantiate an RTSRoot object. Basically checks for configfs setup and
        base kernel modules (tcm)
        '''
        super().__init__()
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

        self._set_dbroot()

    def _list_targets(self):
        self._check_self()
        for fabric_module in self.fabric_modules:
            yield from fabric_module.targets

    def _list_storage_objects(self):
        self._check_self()
        yield from StorageObject.all()

    def _list_alua_tpgs(self):
        self._check_self()
        for so in self.storage_objects:
            yield from so.alua_tpgs

    def _list_tpgs(self):
        self._check_self()
        for t in self.targets:
            yield from t.tpgs

    def _list_node_acls(self):
        self._check_self()
        for t in self.tpgs:
            yield from t.node_acls

    def _list_node_acl_groups(self):
        self._check_self()
        for t in self.tpgs:
            yield from t.node_acl_groups

    def _list_mapped_luns(self):
        self._check_self()
        for na in self.node_acls:
            yield from na.mapped_luns

    def _list_mapped_lun_groups(self):
        self._check_self()
        for nag in self.node_acl_groups:
            yield from nag.mapped_lun_groups

    def _list_network_portals(self):
        self._check_self()
        for t in self.tpgs:
            yield from t.network_portals

    def _list_luns(self):
        self._check_self()
        for t in self.tpgs:
            yield from t.luns

    def _list_sessions(self):
        self._check_self()
        for na in self.node_acls:
            if na.session:
                yield na.session

    def _list_fabric_modules(self):
        self._check_self()
        yield from FabricModule.all()

    def __str__(self):
        return "rtslib"

    def _set_dbroot(self):
        dbroot_path = Path(self.path) / "dbroot"
        if not dbroot_path.exists():
            self._dbroot = self._default_dbroot
            return
        self._dbroot = fread(dbroot_path)
        if self._dbroot != self._preferred_dbroot:
            try:
                fwrite(dbroot_path, f"{self._preferred_dbroot}\n")
            except:
                if not Path(self._preferred_dbroot).is_dir():
                    raise RTSLibError(f"Cannot set dbroot to {self._preferred_dbroot}. "
                                      f"Please check if this directory exists.")
                else:
                    # Writing to dbroot_path after devices have been registered will make the
                    # kernel emit this error: db_root: cannot be changed: target devices registered
                    from warnings import warn
                    warn(f"Cannot set dbroot to {self._preferred_dbroot}. "
                         f"Target devices have already been registered.", stacklevel=1)
                    return

            self._dbroot = fread(dbroot_path)

    def _get_dbroot(self):
        return self._dbroot

    def _get_saveconf(self, so_path, save_file):
        '''
        Fetch the configuration of all the blocks and return conf with
        updated storageObject info and its related target configuraion of
        given storage object path
        '''
        current = self.dump()

        try:
            with Path(save_file).open() as f:
                saveconf = json.loads(f.read())
        except OSError as e:
            if e.errno == errno.ENOENT:
                saveconf = {'storage_objects': [], 'targets': []}
            else:
                raise OSError(f"Could not open {save_file}")

        fetch_cur_so = False
        fetch_cur_tg = False
        # Get the given block current storageObj configuration
        for sidx, sobj in enumerate(current.get('storage_objects', [])):
            if '/backstores/' + sobj['plugin'] + '/' + sobj['name'] == so_path:
                current_so = current['storage_objects'][sidx]
                fetch_cur_so = True
                break

        # Get the given block current target configuration
        if fetch_cur_so:
            for tidx, tobj in enumerate(current.get('targets', [])):
                if fetch_cur_tg:
                    break
                for luns in tobj.get('tpgs', []):
                    if fetch_cur_tg:
                        break
                    for lun in luns.get('luns', []):
                        if lun['storage_object'] == so_path:
                            current_tg = current['targets'][tidx]
                            fetch_cur_tg = True
                            break

        fetch_sav_so = False
        fetch_sav_tg = False
        # Get the given block storageObj from saved configuration
        for sidx, sobj in enumerate(saveconf.get('storage_objects', [])):
            if '/backstores/' + sobj['plugin'] + '/' + sobj['name'] == so_path:
                # Merge StorageObj
                if fetch_cur_so:
                    saveconf['storage_objects'][sidx] = current_so
                # Remove StorageObj
                else:
                    saveconf['storage_objects'].remove(saveconf['storage_objects'][sidx])
                fetch_sav_so = True
                break

        # Get the given block target from saved configuration
        if fetch_sav_so:
            for tidx, tobj in enumerate(saveconf.get('targets', [])):
                if fetch_sav_tg:
                    break
                for luns in tobj.get('tpgs', []):
                    if fetch_sav_tg:
                        break
                    for lun in luns.get('luns', []):
                        if lun['storage_object'] == so_path:
                            # Merge target
                            if fetch_cur_tg:
                                saveconf['targets'][tidx] = current_tg
                            # Remove target
                            else:
                                saveconf['targets'].remove(saveconf['targets'][tidx])
                            fetch_sav_tg = True
                            break

        # Insert storageObj
        if fetch_cur_so and not fetch_sav_so:
            saveconf['storage_objects'].append(current_so)
        # Insert target
        if fetch_cur_tg and not fetch_sav_tg:
            saveconf['targets'].append(current_tg)

        return saveconf

    # RTSRoot public stuff

    def dump(self):
        '''
        Returns a dict representing the complete state of the target
        config, suitable for serialization/deserialization, and then
        handing to restore().
        '''
        d = super().dump()
        d['storage_objects'] = [so.dump() for so in self.storage_objects]
        d['targets'] = [t.dump() for t in self.targets]
        d['fabric_modules'] = [f.dump() for f in self.fabric_modules
                               if f.has_feature("discovery_auth")
                               if f.discovery_enable_auth]
        return d

    def clear_existing(self, target=None, storage_object=None, confirm=False):
        '''
        Remove entire current configuration.
        '''
        if not confirm:
            raise RTSLibError("As a precaution, confirm=True needs to be set")

        # Targets depend on storage objects, delete them first.
        for t in self.targets:
            # * Delete the single matching target if target=iqn.xxx was supplied
            #   with restoreconfig command
            # * If only storage_object=blockx option is supplied then do not
            #   delete any targets
            # * If restoreconfig was not supplied with neither target=iqn.xxx
            #   nor storage_object=blockx then delete all targets
            if (not storage_object and not target) or (target and t.wwn == target):
                t.delete()
                if target:
                    break

        for fm in (f for f in self.fabric_modules if f.has_feature("discovery_auth")):
            fm.clear_discovery_auth_settings()

        for so in self.storage_objects:
            # * Delete the single matching storage object if storage_object=blockx
            #   was supplied with restoreconfig command
            # * If only target=iqn.xxx option is supplied then do not
            #   delete any storage_object's
            # * If restoreconfig was not supplied with neither target=iqn.xxx
            #   nor storage_object=blockx then delete all storage_object's
            if (not storage_object and not target) or (storage_object and so.name == storage_object):  # noqa: E501
                so.delete()
                if storage_object:
                    break

        # If somehow some hbas still exist (no storage object within?) clean
        # them up too.
        if not (storage_object or target):
            for hba_dir in Path(self.configfs_dir, 'core').glob('*_*'):
                hba_dir.rmdir()

    def restore(self, config, target=None, storage_object=None,
                clear_existing=False, abort_on_error=False):
        '''
        Takes a dict generated by dump() and reconfigures the target to match.
        Returns list of non-fatal errors that were encountered.
        Will refuse to restore over an existing configuration unless clear_existing
            is True.
        '''
        if clear_existing:
            self.clear_existing(target, storage_object, confirm=True)
        elif any(self.storage_objects) or any(self.targets):
            if any(self.storage_objects):
                for config_so in config.get('storage_objects', []):
                    for loaded_so in self.storage_objects:
                        if config_so['name'] == loaded_so.name and \
                           config_so['plugin'] == loaded_so.plugin:
                            raise RTSLibError(f"storageobject '{loaded_so.plugin}:"
                                              f"{loaded_so.name}' exist not restoring")

            if any(self.targets):
                for config_tg in config.get('targets', []):
                    for loaded_tg in self.targets:
                        if config_tg['wwn'] == loaded_tg.wwn:
                            raise RTSLibError(
                                f"target with wwn {loaded_tg.wwn} exist, not restoring")
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

            # * Restore/load the single matching storage object if
            #   storage_object=blockx was supplied with restoreconfig command
            # * In case if no storage_object was supplied but only target=iqn.xxx
            #   was supplied then do not load any storage_object's
            # * If neither storage_object nor target option was supplied to
            #   restoreconfig, then go ahead and load all storage_object's
            if (not storage_object and not target) or (storage_object and so['name'] == storage_object):  # noqa: E501
                try:
                    so_cls = so_mapping[so['plugin']]
                except KeyError:
                    err_func(f"'plugin' not defined or invalid in storageobject {so['name']}")
                    if storage_object:
                        break
                    continue
                kwargs = so.copy()
                dict_remove(kwargs, (
                    'exists', 'attributes', 'plugin', 'buffered_mode', 'alua_tpgs'))
                try:
                    so_obj = so_cls(**kwargs)
                except Exception as e:
                    err_func(f"Could not create StorageObject {so['name']}: {e}")
                    if storage_object:
                        break
                    continue

                # Custom err func to include block name
                def so_err_func(x):
                    return err_func(f"Storage Object {so['plugin']}/{so['name']}: {x}")  # noqa: B023 TODO

                set_attributes(so_obj, so.get('attributes', {}), so_err_func)

                for alua_tpg in so.get('alua_tpgs', {}):
                    with suppress(RTSLibALUANotSupportedError):
                        ALUATargetPortGroup.setup(so_obj, alua_tpg, err_func)

                if storage_object:
                    break

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

            # * Restore/load the single matching target if target=iqn.xxx was
            #   supplied with restoreconfig command
            # * In case if no target was supplied but only storage_object=blockx
            #   was supplied then do not load any targets
            # * If neither storage_object nor target option was supplied to
            #   restoreconfig, then go ahead and load all targets
            if (not storage_object and not target) or (target and t['wwn'] == target):
                if 'fabric' not in t:
                    err_func(f"target {t['wwn']} missing 'fabric' field")
                    if target:
                        break
                    continue
                if t['fabric'] not in (f.name for f in self.fabric_modules):
                    err_func(f"Unknown fabric '{t['fabric']}'")
                    if target:
                        break
                    continue

                fm_obj = FabricModule(t['fabric'])

                # Instantiate target
                Target.setup(fm_obj, t, err_func)

                if target:
                    break

        return errors

    def save_to_file(self, save_file=None, so_path=None):
        '''
        Write the configuration in json format to a file.
        Save file defaults to '/etc/target/saveconfig.json'.
        '''
        save_file = Path(default_save_file) if not save_file else Path(save_file)

        saveconf = self._get_saveconf(so_path, save_file) if so_path else self.dump()

        tmp_file = save_file.with_name(f"{save_file.name}.temp")

        mode = 0o600  # rw-------
        umask = 0o777 ^ mode  # Prevents always downgrading umask to 0

        # For security, remove file with potentially elevated mode
        tmp_file.unlink(missing_ok=True)

        original_umask = os.umask(umask)
        # Even though the old file is first deleted, a race condition is still
        # possible. mode='x' opens the file for exclusive creation,
        # failing if the file already exists
        try:
            with tmp_file.open(mode="x") as f:
                json.dump(saveconf, f, sort_keys=True, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise RuntimeError(f"Could not open {tmp_file}") from e

        # move along with permissions
        tmp_file.replace(save_file)
        save_file.chmod(mode)
        os.umask(original_umask)

    def restore_from_file(self, restore_file=None, clear_existing=True,
                          target=None, storage_object=None,
                          abort_on_error=False):
        '''
        Restore the configuration from a file in json format.
        Restore file defaults to '/etc/target/saveconfig.json'.
        Returns a list of non-fatal errors. If abort_on_error is set,
          it will raise the exception instead of continuing.
        '''
        if not restore_file:
            restore_file = default_save_file

        with Path(restore_file).open() as f:
            config = json.loads(f.read())
            return self.restore(config, target, storage_object,
                                clear_existing=clear_existing,
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
    dbroot = property(_get_dbroot,
            doc="Get the target database root")

def _test():
    '''Run the doctests.'''
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
