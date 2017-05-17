'''
Provides various utility functions.

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
import re
import six
import socket
import stat
import subprocess
import uuid
from contextlib import contextmanager

import pyudev

_CONTEXT = pyudev.Context()

class RTSLibError(Exception):
    '''
    Generic rtslib error.
    '''
    pass

class RTSLibALUANotSupported(RTSLibError):
    '''
    Backend does not support ALUA.
    '''
    pass

class RTSLibBrokenLink(RTSLibError):
    '''
    Broken link in configfs, i.e. missing LUN storage object.
    '''
    pass

class RTSLibNotInCFS(RTSLibError):
    '''
    The underlying configfs object does not exist. Happens when
    calling methods of an object that is instantiated but have
    been deleted from congifs, or when trying to lookup an
    object that does not exist.
    '''
    pass

def fwrite(path, string):
    '''
    This function writes a string to a file, and takes care of
    opening it and closing it. If the file does not exist, it
    will be created.

    >>> from rtslib.utils import *
    >>> fwrite("/tmp/test", "hello")
    >>> fread("/tmp/test")
    'hello'

    @param path: The file to write to.
    @type path: string
    @param string: The string to write to the file.
    @type string: string

    '''
    with open(path, 'w') as file_fd:
        file_fd.write(str(string))

def fread(path):
    '''
    This function reads the contents of a file.
    It takes care of opening and closing it.

    >>> from rtslib.utils import *
    >>> fwrite("/tmp/test", "hello")
    >>> fread("/tmp/test")
    'hello'
    >>> fread("/tmp/notexistingfile") # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    IOError: [Errno 2] No such file or directory: '/tmp/notexistingfile'

    @param path: The path to the file to read from.
    @type path: string
    @return: A string containing the file's contents.

    '''
    with open(path, 'r') as file_fd:
        return file_fd.read().strip()

def is_dev_in_use(path):
    '''
    This function will check if the device or file referenced by path is
    already mounted or used as a storage object backend.  It works by trying to
    open the path with O_EXCL flag, which will fail if someone else already
    did.  Note that the file is closed before the function returns, so this
    does not guaranteed the device will still be available after the check.
    @param path: path to the file of device to check
    @type path: string
    @return: A boolean, True is we cannot get exclusive descriptor on the path,
             False if we can.
    '''
    path = os.path.realpath(str(path))
    try:
        file_fd = os.open(path, os.O_EXCL|os.O_NDELAY)
    except OSError:
        return True
    else:
        os.close(file_fd)
        return False

def _get_size_for_dev(device):
    '''
    @param device: the device
    @type device: pyudev.Device
    @return: the size in logical blocks, 0 if none found
    @rtype: int
    '''
    attributes = device.attributes
    try:
        sect_size = attributes.asint('size')
    except (KeyError, UnicodeDecodeError, ValueError):
        return 0

    try:
        logical_block_size = attributes.asint('queue/logical_block_size')
    except (KeyError, UnicodeDecodeError, ValueError):
        return 0

    return (sect_size * 512) // logical_block_size

def get_size_for_blk_dev(path):
    '''
    @param path: The path to a block device
    @type path: string
    @return: The size in logical blocks of the device
    @raises: DeviceNotFoundError if corresponding device not found
    @raises: EnvironmentError, ValueError in some situations
    '''
    device = Device.from_device_file(_CONTEXT, os.path.realpath(str(path)))
    return _get_size_for_dev(device)

get_block_size = get_size_for_blk_dev

def get_size_for_disk_name(name):
    '''
    @param name: a kernel disk name, as found in /proc/partitions
    @type name: string
    @return: The size in logical blocks of a disk-type block device.
    @raises: DeviceNotFoundError
    '''

    # size is in 512-byte sectors, we want to return number of logical blocks
    def get_size(name):
        """
        :param str name: name of block device
        :raises DeviceNotFoundError: if device not found
        """
        device = pyudev.Device.from_name(_CONTEXT, 'block', name)
        return _get_size_for_dev(device)

    # Disk names can include '/' (e.g. 'cciss/c0d0') but these are changed to
    # '!' when listed in /sys/block.
    # in pyudev 0.19 it should no longer be necessary to swap '/'s in name
    name = name.replace("/", "!")

    try:
        return get_size(name)
    except pyudev.DeviceNotFoundError:
        # Maybe it's a partition?
        m = re.search(r'^([a-z0-9_\-!]+?)(\d+)$', name)
        if m:
            # If disk name ends with a digit, Linux sticks a 'p' between it and
            # the partition number in the blockdev name.
            disk = m.groups()[0]
            if disk[-1] == 'p' and disk[-2].isdigit():
                disk = disk[:-1]
            return get_size(m.group())
        else:
            raise

def get_blockdev_type(path):
    '''
    This function returns a block device's type.
    Example: 0 is TYPE_DISK
    If no match is found, None is returned.

    >>> from rtslib.utils import *
    >>> get_blockdev_type("/dev/sda")
    0
    >>> get_blockdev_type("/dev/sr0")
    5
    >>> get_blockdev_type("/dev/scd0")
    5
    >>> get_blockdev_type("/dev/nodevicehere") is None
    True

    @param path: path to the block device
    @type path: string
    @return: An int for the block device type, or None if not a block device.
    '''
    try:
        device = pyudev.Device.from_device_file(_CONTEXT, path)
    except (pyudev.DeviceNotFoundError, EnvironmentError, ValueError):
        return None

    if device.subsystem != u'block':
        return None

    attributes = device.attributes

    disk_type = 0
    try:
        disk_type = attributes.asint('device/type')
    except (KeyError, UnicodeDecodeError, ValueError):
        pass
    return disk_type

get_block_type = get_blockdev_type

def convert_scsi_path_to_hctl(path):
    '''
    This function returns the SCSI ID in H:C:T:L form for the block
    device being mapped to the udev path specified.
    If no match is found, None is returned.

    >>> import rtslib.utils as utils
    >>> utils.convert_scsi_path_to_hctl('/dev/scd0')
    (2, 0, 0, 0)
    >>> utils.convert_scsi_path_to_hctl('/dev/sr0')
    (2, 0, 0, 0)
    >>> utils.convert_scsi_path_to_hctl('/dev/sda')
    (3, 0, 0, 0)
    >>> utils.convert_scsi_path_to_hctl('/dev/sda1')
    >>> utils.convert_scsi_path_to_hctl('/dev/sdb')
    (3, 0, 1, 0)
    >>> utils.convert_scsi_path_to_hctl('/dev/sdc')
    (3, 0, 2, 0)

    @param path: The udev path to the SCSI block device.
    @type path: string
    @return: An (host, controller, target, lun) tuple of integer
    values representing the SCSI ID of the device, or raise RTSLibError.
    '''
    try:
        path = os.path.realpath(path)
        device = pyudev.Device.from_device_file(_CONTEXT, path)
        parent = device.find_parent(subsystem='scsi')
        return [int(data) for data in parent.sys_name.split(':')]
    except:
        raise RTSLibError("Could not convert scsi path to hctl")

def convert_scsi_hctl_to_path(host, controller, target, lun):
    '''
    This function returns a udev path pointing to the block device being
    mapped to the SCSI device that has the provided H:C:T:L.

    >>> import rtslib.utils as utils
    >>> utils.convert_scsi_hctl_to_path(0,0,0,0)
    ''
    >>> utils.convert_scsi_hctl_to_path(2,0,0,0) # doctest: +ELLIPSIS
    '/dev/s...0'
    >>> utils.convert_scsi_hctl_to_path(3,0,2,0)
    '/dev/sdc'

    @param host: The SCSI host id.
    @type host: int
    @param controller: The SCSI controller id.
    @type controller: int
    @param target: The SCSI target id.
    @type target: int
    @param lun: The SCSI Logical Unit Number.
    @type lun: int
    @return: A string for the canonical path to the device, or raise RTSLibError.
    '''
    try:
        host = int(host)
        controller = int(controller)
        target = int(target)
        lun = int(lun)
    except ValueError:
        raise RTSLibError(
            "The host, controller, target and lun parameter must be integers")

    hctl = [str(host), str(controller), str(target), str(lun)]
    try:
        scsi_device = pyudev.Device.from_name(_CONTEXT, 'scsi', ':'.join(hctl))
    except pyudev.DeviceNotFoundError:
        raise RTSLibError("Could not find path for SCSI hctl")

    devices = _CONTEXT.list_devices(
       subsystem='block',
       parent=scsi_device
    )

    path = next((dev.device_node for dev in devices), '')
    if path == None:
        raise RTSLibError("Could not find path for SCSI hctl")
    return path

def generate_wwn(wwn_type):
    '''
    Generates a random WWN of the specified type:
        - unit_serial: T10 WWN Unit Serial.
        - iqn: iSCSI IQN
        - naa: SAS NAA address
    @param wwn_type: The WWN address type.
    @type wwn_type: str
    @returns: A string containing the WWN.
    '''
    wwn_type = wwn_type.lower()
    if wwn_type == 'free':
        return str(uuid.uuid4())
    if wwn_type == 'unit_serial':
        return str(uuid.uuid4())
    elif wwn_type == 'iqn':
        localname = socket.gethostname().split(".")[0]
        localarch = os.uname()[4].replace("_", "")
        prefix = "iqn.2003-01.org.linux-iscsi.%s.%s" % (localname, localarch)
        prefix = prefix.strip().lower()
        serial = "sn.%s" % str(uuid.uuid4())[24:]
        return "%s:%s" % (prefix, serial)
    elif wwn_type == 'naa':
        # see http://standards.ieee.org/develop/regauth/tut/fibre.pdf
        # 5 = IEEE registered
        # 001405 = OpenIB OUI (they let us use it I guess?)
        # rest = random
        return "naa.5001405" + uuid.uuid4().hex[-9:]
    elif wwn_type == 'eui':
        return "eui.001405" + uuid.uuid4().hex[-10:]
    else:
        raise ValueError("Unknown WWN type: %s" % wwn_type)

def colonize(str):
    '''
    helper function to add colons every 2 chars
    '''
    return ":".join(str[i:i+2] for i in range(0, len(str), 2))

def _cleanse_wwn(wwn_type, wwn):
    '''
    Some wwns may have alternate text representations. Adjust to our
    preferred representation.
    '''
    wwn = str(wwn.strip()).lower()

    if wwn_type in ('naa', 'eui', 'ib'):
        if wwn.startswith("0x"):
            wwn = wwn[2:]
        wwn = wwn.replace("-", "")
        wwn = wwn.replace(":", "")

        if not (wwn.startswith("naa.") or wwn.startswith("eui.") or \
            wwn.startswith("ib.")):
            wwn = wwn_type + "." + wwn

    return wwn

def normalize_wwn(wwn_types, wwn):
    '''
    Take a WWN as given by the user and convert it to a standard text
    representation.

    Returns (normalized_wwn, wwn_type), or exception if invalid wwn.
    '''
    wwn_test = {
    'free': lambda wwn: True,
    'iqn': lambda wwn: \
        re.match("iqn\.[0-9]{4}-[0-1][0-9]\..*\..*", wwn) \
        and not re.search(' ', wwn) \
        and not re.search('_', wwn),
    'naa': lambda wwn: re.match("naa\.[125][0-9a-fA-F]{15}$", wwn),
    'eui': lambda wwn: re.match("eui\.[0-9a-f]{16}$", wwn),
    'ib': lambda wwn: re.match("ib\.[0-9a-f]{32}$", wwn),
    'unit_serial': lambda wwn: \
        re.match("[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$", wwn),
    }

    for wwn_type in wwn_types:
        clean_wwn = _cleanse_wwn(wwn_type, wwn)
        found_type = wwn_test[wwn_type](clean_wwn)
        if found_type:
            break
    else:
        raise RTSLibError("WWN not valid as: %s" % ", ".join(wwn_types))

    return (clean_wwn, wwn_type)

def list_loaded_kernel_modules():
    '''
    List all currently loaded kernel modules
    '''
    return [line.split(" ")[0] for line in
            fread("/proc/modules").split('\n') if line]

def modprobe(module):
    '''
    Load the specified kernel module if needed.
    @param module: The name of the kernel module to be loaded.
    @type module: str
    '''
    if module in list_loaded_kernel_modules():
        return

    try:
        import kmod
    except ImportError:
        process = subprocess.Popen(("modprobe", module),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        (stdoutdata, stderrdata) = process.communicate()
        if process.returncode != 0:
            raise RTSLibError(stderrdata)
        return

    try:
        kmod.Kmod().modprobe(module)
    except kmod.error.KmodError:
        raise RTSLibError("Could not load module: %s" % module)

def mount_configfs():
    if not os.path.ismount("/sys/kernel/config"):
        cmdline = "mount -t configfs none /sys/kernel/config"
        process = subprocess.Popen(cmdline.split(),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        (stdoutdata, stderrdata) = process.communicate()
        if process.returncode != 0 and not os.path.ismount(
            "/sys/kernel/config"):
            raise RTSLibError("Cannot mount configfs")

def dict_remove(d, items):
    for item in items:
        if item in d:
            del d[item]

@contextmanager
def ignored(*exceptions):
    try:
        yield
    except exceptions:
        pass

#
# These two functions are meant to be used with functools.partial and
# properties.
#
# 'ignore=True' will silently return None if the attribute is not present.
# This is good for attributes only present in some kernel versions.
#
# All curried arguments should be keyword args.
#
# These should only be used for attributes that follow the convention of
# "NULL" having a special sentinel value, such as auth attributes, and
# that return a string.
#
def _get_auth_attr(self, attribute, ignore=False):
    self._check_self()
    path = "%s/%s" % (self.path, attribute)
    try:
        value = fread(path)
    except:
        if not ignore:
            raise
        return None
    if value == "NULL":
        return ''
    else:
        return value

# Auth params take the string "NULL" to unset the attribute
def _set_auth_attr(self, value, attribute, ignore=False):
    self._check_self()
    path = "%s/%s" % (self.path, attribute)
    value = value.strip()
    if value == "NULL":
        raise RTSLibError("'NULL' is not a permitted value")
    if len(value) > 255:
        raise RTSLibError("Value longer than maximum length of 255")
    if value == '':
        value = "NULL"
    try:
        fwrite(path, "%s" % value)
    except:
        if not ignore:
            raise

def set_attributes(obj, attr_dict, err_func):
    for name, value in six.iteritems(attr_dict):
        try:
            obj.set_attribute(name, value)
        except RTSLibError as e:
            err_func(str(e))

def set_parameters(obj, param_dict, err_func):
    for name, value in six.iteritems(param_dict):
        try:
            obj.set_parameter(name, value)
        except RTSLibError as e:
            err_func(str(e))

def _test():
    '''Run the doctests'''
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
