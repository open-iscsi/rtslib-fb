'''
This file is part of LIO(tm).

Copyright (c) 2012-2014 by Datera, Inc.
More information on www.datera.io.

Original author: Jerome Martin <jxm@netiant.com>

Datera and LIO are trademarks of Datera, Inc., which may be registered in some
jurisdictions.

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
import logging

from rtslib.config_tree import NO_VALUE
from rtslib.config import dump_value, ConfigError
from rtslib.utils import convert_bytes_to_human, convert_human_to_bytes

from rtslib import (RTSRoot, Target, FabricModule, LUN, MappedLUN,
                    NetworkPortal, TPG, NodeACL, FileIOBackstore,
                    FileIOStorageObject, IBlockBackstore,
                    IBlockStorageObject, PSCSIBackstore,
                    PSCSIStorageObject, RDMCPBackstore,
                    RDMCPStorageObject, RTSLibError)

# TODO There seems to be a bug in LIO, affecting both this API and rtslib:
# when a tpg does not contain any objects, it cannot be removed.

_rtsroot = None
_indent = ' '*4

DEBUG = False
if DEBUG:
    logging.basicConfig()
    log = logging.getLogger('Config')
    log.setLevel(logging.DEBUG)
else:
    log = logging.getLogger('Config')
    log.setLevel(logging.INFO)

def _b2h(b):
    return convert_bytes_to_human(b)

def get_root():
    global _rtsroot
    if _rtsroot is None:
        _rtsroot = RTSRoot()
    return _rtsroot

def _list_live_group_attrs(rts_obj):
    '''
    Returns a list of all group attributes for the rts_obj rtslib object
    currently running on the live system, in LIO configuration file format.
    '''
    attrs = []
    for attribute in rts_obj.list_attributes(writable=True):
        value = rts_obj.get_attribute(attribute)
        attrs.append("attribute %s %s" % (attribute, dump_value(value)))
    for parameter in rts_obj.list_parameters(writable=True):
        value = rts_obj.get_parameter(parameter)
        attrs.append("parameter %s %s" % (parameter, dump_value(value)))
    for auth_attr in rts_obj.list_auth_attrs(writable=True):
        value = rts_obj.get_auth_attr(auth_attr)
        attrs.append("auth %s %s" % (auth_attr, dump_value(value)))
    return attrs

def dump_live():
    '''
    Returns a text dump of the objects and attributes currently running on
    the live system, in LIO configuration file format.
    '''
    dump = []
    dump.append(dump_live_storage())
    dump.append(dump_live_fabric())
    return "\n".join(dump)

def dump_live_storage():
    '''
    Returns a text dump of the storage objects and attributes currently
    running on the live system, in LIO configuration file format.
    '''
    dump = []
    for so in sorted(get_root().storage_objects, key=lambda so: so.name):
        dump.append("storage %s disk %s {"
                    % (so.backstore.plugin, so.name))
        attrs = []
        if so.backstore.plugin in ['fileio', 'rd_mcp', 'iblock']:
            attrs.append("%swwn %s" % (_indent, so.wwn))
        if so.backstore.plugin in ['fileio', 'pscsi', 'iblock']:
            attrs.append("%spath %s" % (_indent, so.udev_path))
        if so.backstore.plugin in ['fileio', 'rd_mcp']:
            attrs.append("%ssize %s" % (_indent, _b2h(so.size)))
        if so.backstore.plugin in ['rd_mcp']:
            if so.nullio:
                nullio = 'yes'
            else:
                nullio = 'no'
            attrs.append("%snullio %s" % (_indent, nullio))
        if so.backstore.plugin in ['fileio']:
            is_buffered = "buffered" in so.mode
            if is_buffered:
                is_buffered = 'yes'
            else:
                is_buffered = 'no'
            attrs.append("%sbuffered %s" % (_indent, is_buffered))

        group_attrs = _list_live_group_attrs(so)
        attrs.extend(["%s%s" % (_indent, attr) for attr in group_attrs])

        dump.append("\n".join(attrs))
        dump.append("}")

    return "\n".join(dump)

def dump_live_fabric():
    '''
    Returns a text dump of the fabric objects and attributes currently
    running on the live system, in LIO configuration file format.
    '''
    dump = []
    for fm in sorted(get_root().fabric_modules, key=lambda fm: fm.name):
        if fm.has_feature('discovery_auth'):
            dump.append("fabric %s {" % fm.name)
            dump.append("%sdiscovery_auth enable %s"
                        % (_indent, dump_value(fm.discovery_enable_auth)))
            dump.append("%sdiscovery_auth userid %s"
                        % (_indent, dump_value(fm.discovery_userid)))
            dump.append("%sdiscovery_auth password %s"
                        % (_indent, dump_value(fm.discovery_password)))
            dump.append("%sdiscovery_auth mutual_userid %s"
                        % (_indent, dump_value(fm.discovery_mutual_userid)))
            dump.append("%sdiscovery_auth mutual_password %s"
                        % (_indent, dump_value(fm.discovery_mutual_password)))
            dump.append("}")

        for tg in fm.targets:
            tpgs = []
            if not list(tg.tpgs):
                dump.append("fabric %s target %s" % (fm.name, tg.wwn))
            for tpg in tg.tpgs:
                if tpg.has_feature("tpgts"):
                    head = ("fabric %s target %s tpgt %s"
                            % (fm.name, tg.wwn, tpg.tag))
                else:
                    head = ("fabric %s target %s"
                            % (fm.name, tg.wwn))

                if tpg.has_enable():
                    enable = int(tpg.enable)
                else:
                    enable = None

                section = []
                if tpg.has_feature("nexus"):
                    section.append("%snexus_wwn %s" % (_indent, tpg.nexus_wwn))

                attrs = ["%s%s" % (_indent, attr)
                         for attr in _list_live_group_attrs(tpg)]
                if attrs:
                    section.append("\n".join(attrs))

                for lun in sorted(tpg.luns, key=lambda l: l.lun):
                    attrs = ["%s%s" % (_indent, attr)
                             for attr in _list_live_group_attrs(lun)]
                    if attrs:
                        fmt = "%slun %s %s %s {"
                    else:
                        fmt = "%slun %s backend %s:%s"
                    section.append(fmt % (_indent, lun.lun,
                                       lun.storage_object.backstore.plugin,
                                       lun.storage_object.name))
                    if attrs:
                        section.append("\n".join(attrs))
                        section.append("%s}" % _indent)

                if tpg.has_feature("acls"):
                    for acl in tpg.node_acls:
                        section.append("%sacl %s {" % (_indent, acl.node_wwn))
                        attrs = ["%s%s" % (2*_indent, attr)
                                 for attr in _list_live_group_attrs(acl)]
                        if attrs:
                            section.append("\n".join(attrs))
                        for mlun in acl.mapped_luns:
                            section.append("%smapped_lun %s {"
                                        % (2*_indent, mlun.mapped_lun))
                            section.append("%s target_lun %s"
                                           % (3*_indent, mlun.tpg_lun.lun))
                            section.append("%s write_protect %s"
                                           % (3*_indent,
                                              int(mlun.write_protect)))
                            section.append("%s}" % (2*_indent))
                        section.append("%s}" % (_indent))

                if tpg.has_feature("nps"):
                    for np in tpg.network_portals:
                        section.append("%sportal %s:%s"
                                    % (_indent, np.ip_address, np.port))
                if section:
                    if enable is not None:
                        section.append("%senable %s"
                                       % (_indent, enable))
                    dump.append("%s {" % head)
                    dump.append("\n".join(section))
                    dump.append("}")
                else:
                    if enable is not None:
                        dump.append("%s enable %s" % (head, enable))
                    else:
                        dump.append(head)

    return "\n".join(dump)

def obj_attr(obj, attr):
    '''
    Returns the value of attribute attr of the ConfigTree obj.
    If we cannot find the attribute, a ConfigError exception will be raised.
    Else, the attribute's value will be converted from its internal string
    representation to whatever rtslib expects.
    '''
    # TODO Factorize a bit the val_type switch.
    # TODO Maybe consolidate with validate_val in config.py
    log.debug("obj_attr(%s, %s)" % (obj, attr))
    matches = obj.search([(attr, ".*")])
    if len(matches) != 1:
        raise ConfigError("Could not determine value of %s attribute for %s"
                          % (attr, obj.path_str))

    if matches[0].data['type'] not in ['attr', 'group']:
        raise ConfigError("Configuration error, expected attribute for %s"
                          % obj.path_str)

    string = matches[0].key[1]
    if string == NO_VALUE:
        raise ConfigError("Value of %s attribute is not set for %s"
                          % (attr, obj.path_str))

    val_type = matches[0].data.get('val_type')
    ref_path = matches[0].data.get('ref_path')

    valid_value = None
    if val_type == 'bool':
        # FIXME There are inconsistencies in bools at the configfs level
        # The parameters take Yes/No values, the attributes 1/0
        # Maybe something can be done about it ?
        if string in ['yes', 'true', '1', 'enable']:
            valid_value = 1
        elif string in ['no', 'false', '0', 'disable']:
            valid_value = 0
        if obj.key[0] == 'parameter':
            if valid_value == 1:
                valid_value = 'Yes'
            else:
                valid_value = 'No'
    elif val_type == 'bytes':
        mults = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
        val = float(string[:-2])
        unit = string[-2:-1]
        valid_value = int(val * mults[unit])
    elif val_type == 'int':
        valid_value = int(string)
    elif val_type == 'ipport':
        (addr, _, port) = string.rpartition(":")
        valid_value = (addr, int(port))
    elif val_type == 'posint':
        valid_value = int(string)
    elif val_type == 'str':
        valid_value = string
    elif val_type == 'erl':
        valid_value = int(string)
    elif val_type == 'iqn':
        valid_value = string
    elif val_type == 'naa':
        valid_value = string
    elif val_type == 'backend':
        (plugin, _, name) = string.partition(':')
        valid_value = (plugin, name)
    elif val_type == 'raw':
        valid_value = string
    elif ref_path:
        valid_value = ref_path
    else:
        raise ConfigError("Unknown value type '%s' when validating %s"
                          % (val_type, matches[0]))
    return valid_value

def apply_group_attrs(obj, lio_obj):
    '''
    Applies group attributes obj to the live lio_obj.
    '''
    # TODO Split that one up, too much indentation there!
    unsupported_fmt = "Unsupported %s %s: consider upgrading your kernel"
    for group in obj.nodes:
        if group.data['type'] == 'group':
            group_name = group.key[0]
            for attr in group.nodes:
                if attr.data['type'] == 'attr' \
                   and not attr.data['required']:
                    name = attr.key[0]
                    value = obj_attr(group, name)
                    if group_name == 'auth':
                        try:
                            lio_obj.get_auth_attr(name)
                        except RTSLibError:
                            log.info(unsupported_fmt % ("auth attribute", name))
                        else:
                            log.debug("Setting auth %s to %s" % (name, value))
                            lio_obj.set_auth_attr(name, value)
                    elif group_name == 'attribute':
                        try:
                            lio_obj.get_attribute(name)
                        except RTSLibError:
                            log.info(unsupported_fmt % ("attribute", name))
                        else:
                            log.debug("Setting attribute %s to %s" % (name, value))
                            lio_obj.set_attribute(name, value)
                    elif group_name == 'parameter':
                        try:
                            lio_obj.get_parameter(name)
                        except RTSLibError:
                            log.info(unsupported_fmt % ("parameter", name))
                        else:
                            log.debug("Setting parameter %s to %s" % (name, value))
                            lio_obj.set_parameter(name, value)
                    elif group_name == 'discovery_auth':
                        log.debug("Setting discovery_auth %s to %s" % (name, value))
                        if name == 'enable':
                            lio_obj.discovery_enable_auth = value
                        elif name == 'mutual_password':
                            lio_obj.discovery_mutual_password = value
                        elif name == 'mutual_userid':
                            lio_obj.discovery_mutual_userid = value
                        elif name == 'password':
                            lio_obj.discovery_password = value
                        elif name == 'userid':
                            lio_obj.discovery_userid = value
                        else:
                            raise ConfigError("Unexpected discovery_auth "
                                              "attribute: %s" % name)

def apply_create_obj(obj):
    '''
    Creates an object on the live system.
    '''
    # TODO Factorize this when stable, merging it with update and delete,
    # leveraging rtslib 'any' mode (create if not exist)
    # TODO storage
    root = get_root()
    log.debug("apply_create(%s)" % obj.data)
    if obj.key[0] == 'mapped_lun':
        acl = obj.parent
        if acl.parent.key[0] == 'tpgt':
            tpg = acl.parent
            target = tpg.parent
        else:
            tpg = None
            target = acl.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        node_wwn = acl.key[1]
        lio_acl = NodeACL(lio_tpg, node_wwn, mode='lookup')
        mlun = int(obj.key[1])

        write_protect = obj_attr(obj, "write_protect")
        tpg_lun = int(obj_attr(obj, "target_lun").rpartition(' ')[2])
        lio_mlun = MappedLUN(lio_acl, mlun, tpg_lun, write_protect)
        apply_group_attrs(obj, lio_mlun)

    elif obj.key[0] == 'acl':
        if obj.parent.key[0] == 'tpgt':
            tpg = obj.parent
            target = tpg.parent
        else:
            tpg = None
            target = obj.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        node_wwn = obj.key[1]
        lio_acl = NodeACL(lio_tpg, node_wwn)
        apply_group_attrs(obj, lio_acl)

    elif obj.key[0] == 'portal':
        if obj.parent.key[0] == 'tpgt':
            tpg = obj.parent
            target = tpg.parent
        else:
            tpg = None
            target = obj.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        (address, _, port) = obj.key[1].partition(':')
        port = int(port)
        lio_portal = NetworkPortal(lio_tpg, address, port)
        apply_group_attrs(obj, lio_portal)

    elif obj.key[0] == 'lun':
        if obj.parent.key[0] == 'tpgt':
            tpg = obj.parent
            target = tpg.parent
        else:
            tpg = None
            target = obj.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        lun = int(obj.key[1])
        (plugin, name) = obj_attr(obj, "backend")

        # TODO move that to a separate function, use for disk too
        matching_lio_so = [so for so in root.storage_objects if
                           so.backstore.plugin == plugin and so.name == name]

        if len(matching_lio_so) > 1:
            raise ConfigError("Detected unsupported configfs storage objects "
                              "allocation schema for storage object '%s'"
                              % obj.path_str)
        elif len(matching_lio_so) == 0:
            raise ConfigError("Could not find storage object '%s %s' for '%s'"
                              % (plugin, name, obj.path_str))
        else:
            lio_so = matching_lio_so[0]

        lio_lun = LUN(lio_tpg, lun, lio_so)
        apply_group_attrs(obj, lio_lun)

    elif obj.key[0] == 'tpgt':
        target = obj.parent
        fabric = target.parent
        has_enable = len(obj.search([("enable", ".*")])) != 0
        if has_enable:
            enable = obj_attr(obj, "enable")
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        tpgt = int(obj.key[1])
        try:
            nexus_wwn = obj_attr(obj, "nexus_wwn")
            lio_tpg = TPG(lio_target, tpgt, nexus_wwn=nexus_wwn)
        except ConfigError:
            lio_tpg = TPG(lio_target, tpgt)
        if has_enable:
            lio_tpg.enable = enable
        apply_group_attrs(obj, lio_tpg)

    elif obj.key[0] == 'target':
        fabric = obj.parent
        wwn = obj.key[1]
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=wwn)
        apply_group_attrs(obj, lio_target)
        if not lio_target.has_feature("tpgts"):
            try:
                nexus_wwn = obj_attr(obj, "nexus_wwn")
                lio_tpg = TPG(lio_target, 1, nexus_wwn=nexus_wwn)
            except ConfigError:
                lio_tpg = TPG(lio_target, 1)
            if len(obj.search([("enable", ".*")])) != 0:
                lio_tpg.enable = True

    elif obj.key[0] == 'fabric':
        lio_fabric = FabricModule(obj.key[1])
        apply_group_attrs(obj, lio_fabric)

    elif obj.key[0] == 'disk':
        plugin = obj.parent.key[1]
        name = obj.key[1]
        idx = max([0] + [b.index for b in root.backstores if b.plugin == plugin]) + 1
        if plugin == 'fileio':
            dev = obj_attr(obj, "path")
            size = obj_attr(obj, "size")
            try:
                wwn = obj_attr(obj, "wwn")
            except ConfigError:
                wwn = None
            buffered = obj_attr(obj, "buffered")
            lio_bs = FileIOBackstore(idx)
            lio_so = lio_bs.storage_object(name, dev, size, wwn, buffered)
            apply_group_attrs(obj, lio_so)
        elif plugin == 'iblock':
            # TODO Add policy for iblock
            lio_bs = IBlockBackstore(idx)
            dev = obj_attr(obj, "path")
            wwn = obj_attr(obj, "wwn")
            lio_so = lio_bs.storage_object(name, dev, wwn)
            apply_group_attrs(obj, lio_so)
        elif plugin == 'pscsi':
            # TODO Add policy for pscsi
            lio_bs = PSCSIBackstore(idx)
            dev = obj_attr(obj, "path")
            lio_so = lio_bs.storage_object(name, dev)
            apply_group_attrs(obj, lio_so)
        elif plugin == 'rd_mcp':
            # TODO Add policy for rd_mcp
            lio_bs = RDMCPBackstore(idx)
            size = obj_attr(obj, "size")
            wwn = obj_attr(obj, "wwn")
            nullio = obj_attr(obj, "nullio")
            lio_so = lio_bs.storage_object(name, size, wwn, nullio)
            apply_group_attrs(obj, lio_so)
        else:
            raise ConfigError("Unknown backend '%s' for backstore '%s'"
                              % (plugin, obj))

        matching_lio_so = [so for so in root.storage_objects if
                           so.backstore.plugin == plugin and so.name == name]
        if len(matching_lio_so) > 1:
            raise ConfigError("Detected unsupported configfs storage objects "
                              "allocation schema for '%s'" % obj.path_str)
        elif len(matching_lio_so) == 0:
            raise ConfigError("Could not find backstore '%s'" % obj.path_str)
        else:
            lio_so = matching_lio_so[0]

def apply_delete_obj(obj):
    '''
    Deletes an object from the live system.
    '''
    # TODO Factorize this when stable
    # TODO storage fabric cannot be deleted from the system, find a way to
    # handle this when i.e. path 'storage fileio' is in current config, but
    # no objects are hanging under it.

    root = get_root()
    log.debug("apply_delete(%s)" % obj.data)
    if obj.key[0] == 'mapped_lun':
        acl = obj.parent
        if acl.parent.key[0] == 'tpgt':
            tpg = acl.parent
            target = tpg.parent
        else:
            tpg = None
            target = acl.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        node_wwn = acl.key[1]
        lio_acl = NodeACL(lio_tpg, node_wwn, mode='lookup')
        mlun = int(obj.key[1])
        lio_mlun = MappedLUN(lio_acl, mlun)
        lio_mlun.delete()

    elif obj.key[0] == 'acl':
        if obj.parent.key[0] == 'tpgt':
            tpg = obj.parent
            target = tpg.parent
        else:
            tpg = None
            target = obj.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        node_wwn = obj.key[1]
        lio_acl = NodeACL(lio_tpg, node_wwn, mode='lookup')
        lio_acl.delete()

    elif obj.key[0] == 'portal':
        if obj.parent.key[0] == 'tpgt':
            tpg = obj.parent
            target = tpg.parent
        else:
            tpg = None
            target = obj.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        (address, _, port) = obj.key[1].partition(':')
        port = int(port)
        lio_portal = NetworkPortal(lio_tpg, address, port, mode='lookup')
        lio_portal.delete()

    elif obj.key[0] == 'lun':
        if obj.parent.key[0] == 'tpgt':
            tpg = obj.parent
            target = tpg.parent
        else:
            tpg = None
            target = obj.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        if tpg is None:
            tpgt = 1
        else:
            tpgt = int(tpg.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        lun = int(obj.key[1])
        lio_lun = LUN(lio_tpg, lun)
        lio_lun.delete()

    elif obj.key[0] == 'tpgt':
        target = obj.parent
        fabric = target.parent
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=target.key[1], mode='lookup')
        tpgt = int(obj.key[1])
        lio_tpg = TPG(lio_target, tpgt, mode='lookup')
        # FIXME IS this really needed ?
        lio_tpg.enable = True
        lio_tpg.delete()

    elif obj.key[0] == 'target':
        fabric = obj.parent
        wwn = obj.key[1]
        lio_fabric = FabricModule(fabric.key[1])
        lio_target = Target(lio_fabric, wwn=wwn, mode='lookup')
        lio_target.delete()

    elif obj.key[0] == 'disk':
        plugin = obj.parent.key[1]
        name = obj.key[1]
        matching_lio_so = [so for so in root.storage_objects if
                           so.backstore.plugin == plugin and so.name == name]
        log.debug("Looking for storage object %s in %s"
                  % (obj.path_str,
                     str(["%s/%s" % (so.backstore.plugin, so.name)
                          for so in root.storage_objects])))
        if len(matching_lio_so) > 1:
            raise ConfigError("Detected unsupported configfs storage objects "
                              "allocation schema for storage object '%s'"
                              % obj.path_str)
        elif len(matching_lio_so) == 0:
            raise ConfigError("Could not find storage object '%s'"
                              % obj.path_str)
        else:
            lio_so = matching_lio_so[0]
            lio_so.delete()

def clear_configfs():
    '''
    Clears the live configfs by deleteing all nodes.
    '''
    root = get_root()
    for target in root.targets:
        target.delete()
    for backstore in root.backstores:
        backstore.delete()
