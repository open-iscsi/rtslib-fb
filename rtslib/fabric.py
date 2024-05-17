'''
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


Description
-----------

Fabrics may differ in how fabric WWNs are represented, as well as
what capabilities they support


Available parameters
--------------------

* features
Lists the target fabric available features. Default value:
("discovery_auth", "acls", "auth", "nps")
example: features = ("discovery_auth", "acls", "auth")
example: features = () # no features supported

Detail of features:

  * tpgts
  The target fabric module is using iSCSI-style target portal group tags.

  * discovery_auth
  The target fabric module supports a fabric-wide authentication for
  discovery.

  * acls
  The target's TPGTs support explicit initiator ACLs.

  * auth
  The target's TPGT's support per-TPG authentication, and
  the target's TPGT's ACLs support per-ACL initiator authentication.
  Fabrics that support auth must support acls.

  * nps
  The TPGTs support iSCSI-like IPv4/IPv6 network portals, using IP:PORT
  group names.

  * nexus
  The TPGTs have a 'nexus' attribute that contains the local initiator
  serial unit. This attribute must be set before being able to create any
  LUNs.

  * wwn_types
  Sets the type of WWN expected by the target fabric. Defaults to 'free'.
  Usually a fabric will only support one type but iSCSI supports more.
  First entry is the "native" wwn type - i.e. if a wwn can be generated, it
  will be of this type.
  Example: wwn_types = ("eui",)
  Current valid types are:

    * free
    Freeform WWN.

    * iqn
    The fabric module targets are using iSCSI-type IQNs.

    * naa
    NAA FC or SAS address type WWN.

    * eui
    EUI-64. See http://en.wikipedia.org/wiki/MAC_address for info on this format.

    * unit_serial
    Disk-type unit serial.

* wwns
This property returns an iterable (either generator or list) of valid
target WWNs for the fabric, if WWNs should be chosen from existing
fabric interfaces. The most common case for this is hardware-set
WWNs. WWNs should conform to rtslib's normalized internal format: the wwn
type (see above), a period, then the wwn with interstitial dividers like
':' removed.

* to_fabric_wwn()
Converts WWNs from normalized format (see above) to whatever the kernel code
expects when getting a wwn. Only needed if different from normalized format.

* kernel_module
Sets the name of the kernel module implementing the fabric modules. If
not specified, it will be assumed to be MODNAME_target_mod, where
MODNAME is the name of the fabric module, from the fabrics list. Note
that you must not specify any .ko or such extension here.
Example: self.kernel_module = "my_module"

* _path
Sets the path of the configfs group used by the fabric module. Defaults to the
name of the module from the fabrics list.
Example: self._path = f"{self.configfs_dir}/{my_cfs_dir}"

'''

import os
from contextlib import suppress
from functools import partial
from pathlib import Path

from .node import CFSNode
from .target import Target
from .utils import (
    RTSLibError,
    _get_auth_attr,
    _set_auth_attr,
    colonize,
    fread,
    fwrite,
    modprobe,
    normalize_wwn,
)

excludes_list = [
    # version_attributes
    "lio_version", "version",
    # discovery_auth_attributes
    "discovery_auth",
    # cpus_allowed_list_attributes
    "cpus_allowed_list",
]
target_names_excludes = set(excludes_list)


class _BaseFabricModule(CFSNode):
    '''
    Abstract Base clase for Fabric Modules.
    It can load modules, provide information about them and
    handle the configfs housekeeping. After instantiation, whether or
    not the fabric module is loaded depends on if a method requiring
    it (i.e. accessing configfs) is used. This helps limit loaded
    kernel modules to just the fabrics in use.
    '''

    # FabricModule ABC private stuff
    def __init__(self, name):
        '''
        Instantiate a FabricModule object, according to the provided name.
        @param name: the name of the FabricModule object.
        @type name: str
        '''
        super().__init__()
        self.name = name
        self.spec_file = "N/A"
        self._path = f"{self.configfs_dir}/{self.name}"
        self.features = ('discovery_auth', 'acls', 'auth', 'nps', 'tpgts',
            'cpus_allowed_list')
        self.wwn_types = ('free',)
        self.kernel_module = f"{self.name}_target_mod"

    # FabricModule public stuff

    def _check_self(self):
        if not self.exists:
            try:
                self._create_in_cfs_ine('any')
            except RTSLibError:
                modprobe(self.kernel_module)
                self._create_in_cfs_ine('any')
        super()._check_self()

    def has_feature(self, feature):
        # Handle a renamed feature
        if feature == 'acls_auth':
            feature = 'auth'
        return feature in self.features

    def _list_targets(self):
        if self.exists:
            for wwn in Path(self.path).iterdir():
                if wwn.is_dir() and wwn.name not in target_names_excludes:
                    yield Target(self, self.from_fabric_wwn(wwn.name), 'lookup')

    def _get_version(self):
        if self.exists:
            for attr in self.version_attributes:  # TODO
                path = Path(self.path) / attr
                if path.is_file():
                    return fread(path)
                else:
                    raise RTSLibError(f"Can't find version for fabric module {self.name}")
            return None
        return None

    def to_normalized_wwn(self, wwn):
        '''
        Checks whether or not the provided WWN is valid for this fabric module
        according to the spec, and returns a tuple of our preferred string
        representation of the wwn, and what type it turned out to be.
        '''
        return normalize_wwn(self.wwn_types, wwn)

    def to_fabric_wwn(self, wwn):
        '''
        Some fabrics need WWNs in a format different than rtslib's internal
        format. These fabrics should override this method.
        '''
        return wwn

    def from_fabric_wwn(self, wwn):
        '''
        Converts from WWN format used in this fabric's LIO configfs to canonical
        format.
        Note: Do not call from wwns(). There's no guarantee fabric wwn format is
        the same as wherever wwns() is reading from.
        '''
        return wwn

    def needs_wwn(self):
        '''
        This fabric requires wwn to be specified when creating a target,
        it cannot be autogenerated.
        '''
        return self.wwns is not None

    def _assert_feature(self, feature):
        if not self.has_feature(feature):
            raise RTSLibError(f"Fabric module {self.name} does not implement the {feature} feature")

    def _get_cpus_allowed_list(self):
        self._check_self()
        self._assert_feature('cpus_allowed_list')
        path = f"{self.path}/cpus_allowed_list"
        return fread(path)

    def _set_cpus_allowed_list(self, allowed):
        self._check_self()
        self._assert_feature('cpus_allowed_list')
        path = f"{self.path}/cpus_allowed_list"
        fwrite(path, allowed)

    def clear_discovery_auth_settings(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        self.discovery_mutual_password = ''
        self.discovery_mutual_userid = ''
        self.discovery_password = ''
        self.discovery_userid = ''
        self.discovery_enable_auth = False

    def _get_discovery_enable_auth(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = f"{self.path}/discovery_auth/enforce_discovery_auth"
        value = fread(path)
        return bool(int(value))

    def _set_discovery_enable_auth(self, enable):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = f"{self.path}/discovery_auth/enforce_discovery_auth"
        enable = 1 if int(enable) else 0
        fwrite(path, str(enable))

    def _get_discovery_authenticate_target(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = f"{self.path}/discovery_auth/authenticate_target"
        return bool(int(fread(path)))

    def _get_wwns(self):
        '''
        Returns either iterable or None. None means fabric allows
        arbitrary WWNs.
        '''

    def _get_disc_attr(self, *args, **kwargs):
        self._assert_feature('discovery_auth')
        return _get_auth_attr(self, *args, **kwargs)

    def _set_disc_attr(self, *args, **kwargs):
        self._assert_feature('discovery_auth')
        _set_auth_attr(self, *args, **kwargs)

    cpus_allowed_list = \
            property(_get_cpus_allowed_list,
                     _set_cpus_allowed_list,
                     doc="Set or get the cpus_allowed_list attribute.")

    discovery_enable_auth = \
            property(_get_discovery_enable_auth,
                     _set_discovery_enable_auth,
                     doc="Set or get the discovery enable_auth flag.")
    discovery_authenticate_target = property(_get_discovery_authenticate_target,
            doc="Get the boolean discovery authenticate target flag.")

    discovery_userid = property(
        partial(_get_disc_attr, attribute='discovery_auth/userid'),
        partial(_set_disc_attr, attribute='discovery_auth/userid'),
        doc="Set or get the initiator discovery userid.")
    discovery_password = property(
        partial(_get_disc_attr, attribute='discovery_auth/password'),
        partial(_set_disc_attr, attribute='discovery_auth/password'),
        doc="Set or get the initiator discovery password.")
    discovery_mutual_userid = property(
        partial(_get_disc_attr, attribute='discovery_auth/userid_mutual'),
        partial(_set_disc_attr, attribute='discovery_auth/userid_mutual'),
        doc="Set or get the mutual discovery userid.")
    discovery_mutual_password = property(
        partial(_get_disc_attr, attribute='discovery_auth/password_mutual'),
        partial(_set_disc_attr, attribute='discovery_auth/password_mutual'),
        doc="Set or get the mutual discovery password.")

    targets = property(_list_targets,
                       doc="Get the list of target objects.")

    version = property(_get_version,
                       doc="Get the fabric module version string.")

    wwns = property(_get_wwns,
                    doc="iterable of WWNs present for this fabric")

    def setup(self, fm, err_func):
        '''
        Setup fabricmodule with settings from fm dict.
        '''
        for name, value in fm.items():
            if name != 'name':
                try:
                    setattr(self, name, value)
                except:
                    err_func(f"Could not set fabric {fm['name']} attribute '{name}'")

    def dump(self):
        d = super().dump()
        d['name'] = self.name
        if self.has_feature("discovery_auth"):
            for attr in ("userid", "password", "mutual_userid", "mutual_password"):
                val = getattr(self, "discovery_" + attr, None)
                if val:
                    d["discovery_" + attr] = val
            d['discovery_enable_auth'] = self.discovery_enable_auth
        return d


class ISCSIFabricModule(_BaseFabricModule):

    def __init__(self):
        super().__init__('iscsi')
        self.wwn_types = ('iqn', 'naa', 'eui')


class LoopbackFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('loopback')
        self.features = ("nexus",)
        self.wwn_types = ('naa',)
        self.kernel_module = "tcm_loop"


class SBPFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('sbp')
        self.features = ()
        self.wwn_types = ('eui',)
        self.kernel_module = "sbp_target"

    def to_fabric_wwn(self, wwn):
        return wwn[4:]

    def from_fabric_wwn(self, wwn):
        return "eui." + wwn

    # return 1st local guid (is unique) so our share is named uniquely
    @property
    def wwns(self):
        for fname in Path("/sys/bus/firewire/devices").glob("fw*/is_local"):
            if bool(int(fread(fname))):
                guid_path = fname.parent / "guid"
                yield f"eui.{fread(guid_path)[2:]}"
                break


class Qla2xxxFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('qla2xxx')
        self.features = ("acls",)
        self.wwn_types = ('naa',)
        self.kernel_module = "tcm_qla2xxx"

    def to_fabric_wwn(self, wwn):
        # strip 'naa.' and add colons
        return colonize(wwn[4:])

    def from_fabric_wwn(self, wwn):
        return "naa." + wwn.replace(":", "")

    @property
    def wwns(self):
        for wwn_file in Path("/sys/class/fc_host").glob("host*/port_name"):
            with suppress(IOError):
                host = Path(wwn_file).resolve().parent
                device = host.parents[2]
                driver = (device / "driver").resolve().name
                if driver == "qla2xxx":  # TODO
                    yield f"naa.{fread(wwn_file)[2:]}"


class EfctFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('efct')
        self.features = ("acls",)
        self.wwn_types = ('naa',)
        self.kernel_module = "efct"

    def to_fabric_wwn(self, wwn):
        # strip 'naa.' and add colons
        return colonize(wwn[4:])

    def from_fabric_wwn(self, wwn):
        return "naa." + wwn.replace(":", "")

    @property
    def wwns(self):
        for wwn_file in Path("/sys/class/fc_host").glob("host*/port_name"):
            with suppress(IOError):
                host = Path(wwn_file).resolve().parent
                device = host.parents[2]
                driver = (device / "driver").resolve().name
                if driver == "efct":  # TODO
                    yield f"naa.{fread(wwn_file)[2:]}"


class SRPTFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('srpt')
        self.features = ("acls",)
        self.wwn_types = ('ib',)
        self.kernel_module = "ib_srpt"

    def to_fabric_wwn(self, wwn):
        # strip 'ib.' and re-add '0x'
        return "0x" + wwn[3:]

    def from_fabric_wwn(self, wwn):
        return "ib." + wwn[2:]

    @property
    def wwns(self):
        for wwn_file in Path("/sys/class/infiniband").glob("**/ports/*/gids/0"):
            yield f"ib.{fread(wwn_file).replace(':', '')}"


class FCoEFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('tcm_fc')

        self.features = ("acls",)
        self.kernel_module = "tcm_fc"
        self.wwn_types=('naa',)
        self._path = f"{self.configfs_dir}/fc"

    def to_fabric_wwn(self, wwn):
        # strip 'naa.' and add colons
        return colonize(wwn[4:])

    def from_fabric_wwn(self, wwn):
        return "naa." + wwn.replace(":", "")

    @property
    def wwns(self):
        for wwn_file in Path("/sys/class/fc_host").glob("host*/port_name"):
            with suppress(IOError):
                host = Path(wwn_file).resolve().parent
                device = host.parents[2]
                subsystem = (device / "subsystem").resolve().name
                if subsystem == "fcoe":
                    yield f"naa.{fread(wwn_file)[2:]}"


class USBGadgetFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('usb_gadget')
        self.features = ("nexus",)
        self.wwn_types = ('naa',)
        self.kernel_module = "tcm_usb_gadget"


class VhostFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('vhost')
        self.features = ("nexus", "acls", "tpgts")
        self.wwn_types = ('naa',)
        self.kernel_module = "tcm_vhost"

class XenPvScsiFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('xen-pvscsi')
        self._path = f"{self.configfs_dir}/xen-pvscsi"
        self.features = ("nexus", "tpgts")
        self.wwn_types = ('naa',)
        self.kernel_module = "xen-scsiback"


class IbmvscsisFabricModule(_BaseFabricModule):
    def __init__(self):
        super().__init__('ibmvscsis')
        self.features = ()
        self.kernel_module = "ibmvscsis"

    @property
    def wwns(self):
        for wwn_file in Path("/sys/module/ibmvscsis/drivers/vio:ibmvscsis").glob("*/devspec"):
            name = fread(wwn_file)
            yield name[name.find("@") + 1:]


fabric_modules = {
    "srpt": SRPTFabricModule,
    "iscsi": ISCSIFabricModule,
    "loopback": LoopbackFabricModule,
    "qla2xxx": Qla2xxxFabricModule,
    "efct": EfctFabricModule,
    "sbp": SBPFabricModule,
    "tcm_fc": FCoEFabricModule,
#    "usb_gadget": USBGadgetFabricModule, # very rare, don't show
    "vhost": VhostFabricModule,
    "xen-pvscsi": XenPvScsiFabricModule,
    "ibmvscsis": IbmvscsisFabricModule,
    }

#
# Maintain compatibility with existing FabricModule(fabricname) usage
# e.g. FabricModule('iscsi') returns an ISCSIFabricModule
#
class FabricModule:

    def __new__(cls, name):
        return fabric_modules[name]()

    @classmethod
    def all(cls):
        for mod in fabric_modules.values():
            yield mod()

    @classmethod
    def list_registered_drivers(cls):
        try:
            return os.listdir('/sys/module/target_core_mod/holders')
        except OSError:
            return []
