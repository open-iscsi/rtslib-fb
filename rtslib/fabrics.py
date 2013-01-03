'''
Copyright (c) 2011 by RisingTide Systems LLC
Copyright (c) 2013 by Andy Grover

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, version 3 (AGPLv3).

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.


Description
-----------

Instead of having a class to handle each fabric type, rtslib uses a
single FabricModule class. An instance of FabricModule changes its
behavior depending on parameters it picks up from here. These used to
be listed in "spec" files, but are now here.


Available parameters
--------------------

* features
Lists the target fabric available features. Default value:
("discovery_auth", "acls", "acls_auth", "nps")
example: features = ("discovery_auth", "acls", "acls_auth")
example: features = () # no features supported

Detail of features:

  * tpgts
  The target fabric module is using iSCSI-style target portal group tags.

  * discovery_auth
  The target fabric module supports a fabric-wide authentication for
  discovery.
  
  * acls
  The target's TPGTs support explicit initiator ACLs.
  
  * acls_auth
  The target's TPGT's ACLs support per-ACL initiator authentication.
  
  * nps
  The TPGTs support iSCSI-like IPv4/IPv6 network portals, using IP:PORT
  group names.
  
  * nexus
  The TPGTs have a 'nexus' attribute that contains the local initiator
  serial unit. This attribute must be set before being able to create any
  LUNs.
  
* wwn_type
Sets the type of WWN expected by the target fabric. Defaults to 'free'.
Example: wwn_type = "iqn"
Current valid types are:

  * free
  Freeform WWN.

  * iqn
  The fabric module targets are using iSCSI-type IQNs.

  * naa
  NAA SAS address type WWN.

  * unit_serial
  Disk-type unit serial.

* wwns()
This function returns an iterable (either generator or list) of valid
target WWNs for the fabric, if WWNs should be chosen from existing
fabric interfaces. The most common case for this is hardware-set
WWNs. This function should return a string with the WWN formatted for
what the fabric module expects.

* kernel_module
Sets the name of the kernel module implementing the fabric modules. If not
specified, it will be assumed to be MODNAME_target_mod, where MODNAME is the
name of the fabric module, as used to name the spec file. Note that you must
not specify any .ko or such extension here.
Example: kernel_module = "my_module"

* configfs_group
Sets the name of the configfs group used by the fabric module. Defaults to the
name of the module as used to name the spec file.
Example: configfs_group = "iscsi"

'''

import os
from glob import iglob as glob
from utils import fread

def _colonize(str):
    '''
    helper function for the specfiles to add colons every 2 chars
    '''
    new_str = ""
    while str:
        new_str += str[:2] + ":"
        str = str[2:]
        return new_str[:-1]

# ---- Fabric override definitions ----

# Transform 'fe80:0000:0000:0000:0002:1903:000e:8acd' WWN notation to
# '0xfe8000000000000000021903000e8acd'
def _srpt_wwns():
    for wwn_file in glob("/sys/class/infiniband/*/ports/*/gids/0"):
        yield "0x" + fread(wwn_file).strip(":")

_ib_srpt = dict(features = ("acls",),
                kernel_module="ib_srpt",
                configfs_group="srpt",
                wwns=_srpt_wwns)


_iscsi = dict(wwn_type="iqn")


_loopback = dict(features=("nexus",),
                 wwn_type = "naa",                
                 kernel_module = "tcm_loop")                


def _qla_wwns():
    for wwn_file in glob("/sys/class/fc_host/host*/port_name"):
        yield _colonize(fread(wwn_file)[2:])

_qla2xxx = dict(features=("acls",),
                kernel_module="tcm_qla2xxx",
                wwns=_qla_wwns)


# We need a single unique value to create the target.
# Return the first local 1394 device's guid.
def _sbp_wwns():
    for fname in glob("/sys/bus/firewire/devices/fw*/is_local"):
        if bool(int(fread(fname))):
            guid_path = os.path.dirname(fname) + "/guid"
            yield fread(guid_path)[2:].strip()
            break

_sbp = dict(features=(),
            kernel_module="sbp_target",
            wwns=_sbp_wwns)


# Transform '0x1234567812345678' WWN notation to '12:34:56:78:12:34:56:78'
def _fc_wwns():
    for wwn_file in glob("/sys/class/fc_host/host*/port_name"):
        yield _colonize(fread(wwn_file)[2:])

_tcm_fc = dict(features = ("acls",),
               kernel_module = "tcm_fc",
               configfs_group = "fc",
               wwns=_fc_wwns)


_usb_gadget = dict(features=("nexus",),
                   wwn_type="naa",
                   kernel_module="tcm_usb_gadget")


# ---- Putting it all together ----


# list of tuples containing fabric name and spec overrides, if any
fabrics = [
    ("ib_srpt", _ib_srpt),
    ("iscsi", _iscsi),
    ("loopback", _loopback),
    ("qla2xxxx", _qla2xxx),
    ("sbp", _sbp),
    ("tcm_fc", _tcm_fc),
    ("usb_gadget", _usb_gadget),
    ]

_default_features = ('discovery_auth', 'acls', 'acls_auth', 'nps', 'tpgts')
_default_wwn_type = 'free'

# Merge defaults and overrides to create actual specfile dict
specs = {}
for f_name, f_ovr in fabrics:
    fabric = {}
    fabric['features'] = f_ovr.get("features", _default_features)
    fabric['kernel_module'] = f_ovr.get("kernel_module", "%s_target_mod" % f_name)
    fabric['configfs_group'] = f_ovr.get("configfs_group", f_name)
    fabric['wwn_type'] = f_ovr.get("wwn_type", _default_wwn_type)
    if 'wwns' in f_ovr:
        fabric['wwn_list'] = list(f_ovr['wwns']())
    else:
        fabric['wwn_list'] = None

    specs[f_name] = fabric
