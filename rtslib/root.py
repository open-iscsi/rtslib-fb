'''
Implements the RTSRoot class.

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

import re
import os
import glob

from node import CFSNode
from target import Target, FabricModule, TPG, MappedLUN, LUN, NetworkPortal, NodeACL
from tcm import FileIOBackstore, BlockBackstore
from tcm import PSCSIBackstore, RDMCPBackstore
from utils import RTSLibError, RTSLibBrokenLink, modprobe

backstores = dict(
    fileio=FileIOBackstore,
    block=BlockBackstore,
    pscsi=PSCSIBackstore,
    rd_mcp=RDMCPBackstore,
    )

class RTSRoot(CFSNode):
    '''
    This is an interface to the root of the configFS object tree.
    Is allows one to start browsing Target and Backstore objects,
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
    >>> rtsroot.backstores # doctest: +ELLIPSIS
    [...]
    >>> rtsroot.tpgs # doctest: +ELLIPSIS
    [...]
    >>> rtsroot.storage_objects # doctest: +ELLIPSIS
    [...]
    >>> rtsroot.network_portals # doctest: +ELLIPSIS
    [...]

    '''

    # The core target/tcm kernel module
    target_core_mod = 'target_core_mod'

    # RTSRoot private stuff
    def __init__(self):
        '''
        Instanciate an RTSRoot object. Basically checks for configfs setup and
        base kernel modules (tcm )
        '''
        super(RTSRoot, self).__init__()
        modprobe(self.target_core_mod)
        self._create_in_cfs_ine('any')

    def _list_targets(self):
        self._check_self()
        targets = set([])
        for fabric_module in self.fabric_modules:
            for target in fabric_module.targets:
                yield target

    def _list_backstores(self):
        self._check_self()
        if os.path.isdir("%s/core" % self.path):
            backstore_dirs = glob.glob("%s/core/*_*" % self.path)
            for backstore_dir in [os.path.basename(path)
                                  for path in backstore_dirs]:
                regex = re.search("([a-z]+[_]*[a-z]+)(_)([0-9]+)",
                                  backstore_dir)
                if regex:
                    if regex.group(1) == "fileio":
                        yield FileIOBackstore(int(regex.group(3)), 'lookup')
                    elif regex.group(1) == "pscsi":
                        yield PSCSIBackstore(int(regex.group(3)), 'lookup')
                    elif regex.group(1) == "iblock":
                        yield BlockBackstore(int(regex.group(3)), 'lookup')
                    elif regex.group(1) == "rd_mcp":
                        yield RDMCPBackstore(int(regex.group(3)), 'lookup')

    def _list_storage_objects(self):
        self._check_self()
        for bs in self.backstores:
            for so in bs.storage_objects:
                yield so

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

    def _list_fabric_modules(self):
        self._check_self()
        mod_names = [mod_name[:-5] for mod_name in os.listdir(self.spec_dir)
                     if mod_name.endswith('.spec')]
        for name in mod_names:
            yield FabricModule(name)

    def _list_loaded_fabric_modules(self):
        for module in self._list_fabric_modules():
            if module.exists:
                yield module

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
        # backstores:storage_object is *usually* 1:1. In any case, they're an
        # implementation detail that the user doesn't need to care about.
        # Return an array of storageobject info with the crucial plugin name
        # added from backstore, instead of a list of sos for each bs.
        d['storage_objects'] = []
        for bs in self.backstores:
            for so in bs.storage_objects:
                so_dump = so.dump()
                so_dump['plugin'] = bs.plugin
                d['storage_objects'].append(so_dump)
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
        # Deleting backstores deletes associated storageobjects.
        for t in self.targets:
            t.delete()
        for fm in (f for f in self.fabric_modules if f.has_feature("discovery_auth")):
            fm.clear_discovery_auth_settings()
        for bs in self.backstores:
            bs.delete()

    def restore(self, config, clear_existing=False):
        '''
        Takes a dict generated by dump() and reconfigures the target to match.
        '''
        if clear_existing:
            self.clear_existing(confirm=True)

        if not clear_existing and (list(self.storage_objects) or list(self.targets)):
            raise RTSLibError("backstores or targets present, not restoring." +
                              " Set clear_existing=True?")

        def del_if_there(d, items):
            for item in items:
                if item in d:
                    del d[item]

        def set_attributes(obj, attr_dict):
            for name, value in attr_dict.iteritems():
                try:
                    obj.set_attribute(name, value)
                except RTSLibError:
                    # Setting some attributes may return an error, before kernel 3.3
                    pass

        for index, so in enumerate(config['storage_objects']):
            # We need to create a Backstore object for each StorageObject
            bs_obj = backstores[so['plugin']](index)

            # Instantiate storageobject
            kwargs = so.copy()
            del_if_there(kwargs, ('exists', 'attributes', 'plugin'))
            so_obj = bs_obj._storage_object_class(bs_obj, **kwargs)
            set_attributes(so_obj, so['attributes'])

        for fm in config['fabric_modules']:
            # will not have config for FMs that don't support discovery_auth
            fm_obj = FabricModule(fm['name'])
            del fm['name']
            for name, value in fm.iteritems():
                setattr(fm_obj, name, value)

        for t in config['targets']:
            fm_obj = FabricModule(t['fabric'])

            # Instantiate target
            t_obj = Target(fm_obj, t.get('wwn'))

            for tpg in t['tpgs']:
                tpg_obj = TPG(t_obj)
                set_attributes(tpg_obj, tpg['attributes'])

                for lun in tpg['luns']:
                    bs_name, so_name = lun['storage_object'].split('/')[2:]
                    match_so = [x for x in self.storage_objects if so_name == x.name]
                    match_so = [x for x in match_so if bs_name == x.backstore.plugin]
                    if len(match_so) != 1:
                        raise RTSLibError("Can't find storage object %s" %
                                          lun['storage_object'])
                    lun_obj = LUN(tpg_obj, lun.get('index'), storage_object=match_so[0])

                for p in tpg['portals']:
                    NetworkPortal(tpg_obj, p['ip_address'], p['port'])

                for acl in tpg['node_acls']:
                    acl_obj = NodeACL(tpg_obj, acl['node_wwn'])
                    set_attributes(tpg_obj, tpg['attributes'])
                    for mlun in acl['mapped_luns']:
                        mlun_obj = MappedLUN(acl_obj, mlun['index'],
                                             mlun['index'], mlun.get('write_protect'))

                    del_if_there(acl, ('attributes', 'mapped_luns', 'node_wwn'))
                    for name, value in acl.iteritems():
                        if value:
                            setattr(acl_obj, name, value)

    backstores = property(_list_backstores,
            doc="Get the list of Backstore objects.")
    targets = property(_list_targets,
            doc="Get the list of Target objects.")
    tpgs = property(_list_tpgs,
            doc="Get the list of all the existing TPG objects.")
    node_acls = property(_list_node_acls,
            doc="Get the list of all the existing NodeACL objects.")
    network_portals = property(_list_network_portals,
            doc="Get the list of all the existing Network Portal objects.")
    storage_objects = property(_list_storage_objects,
            doc="Get the list of all the existing Storage objects.")
    luns = property(_list_luns,
            doc="Get the list of all existing LUN objects.")
    fabric_modules = property(_list_fabric_modules,
            doc="Get the list of all FabricModule objects.")
    loaded_fabric_modules = property(_list_loaded_fabric_modules,
            doc="Get the list of all loaded FabricModule objects.")

def _test():
    '''Run the doctests.'''
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
