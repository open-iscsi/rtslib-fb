'''
Provides various utility functions.

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
import stat
import uuid
import glob
import socket
import ipaddr
import netifaces
import subprocess

from array import array
from fcntl import ioctl
from threading import Thread
from Queue import Queue, Empty
from struct import pack, unpack

class RTSLibError(Exception):
    '''
    Generic rtslib error.
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
    calling methods of an object that is instanciated but have
    been deleted from congifs, or when trying to lookup an
    object that does not exist.
    '''
    pass

def flatten_nested_list(nested_list):
    '''
    Function to flatten a nested list.

    >>> import rtslib.utils as utils
    >>> utils.flatten_nested_list([[1,2,3,[4,5,6]],[7,8],[[[9,10]],[11,]]])
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    @param nested_list: A nested list (list of lists of lists etc.)
    @type nested_list: list
    @return: A list with only non-list elements
    '''
    return list(gen_list_item(nested_list))

def gen_list_item(nested_list):
    '''
    The generator for flatten_nested_list().
    It returns one by one items that are not a list, and recurses when
    he finds an item that is a list.
    '''
    for item in nested_list:
        if type(item) is list:
            for nested_item in gen_list_item(item):
                yield nested_item
        else:
            yield item

def fwrite(path, string):
    '''
    This function writes a string to a file, and takes care of
    opening it and closing it. If the file does not exists, it
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
    path = os.path.realpath(str(path))
    file_fd = open(path, 'w')
    try:
        file_fd.write("%s" % string)
    finally:
        file_fd.close()

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
    path = os.path.realpath(str(path))
    string = ""
    file_fd = open(path, 'r')
    try:
        string = file_fd.read()
    finally:
        file_fd.close()

    return string

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

def is_disk_partition(path):
    '''
    Try to find out if path is a partition of a TYPE_DISK device.
    Handles both /dev/sdaX and /dev/disk/by-*/*-part? schemes.
    '''
    regex = re.match(r'([a-z/]+)([1-9]+)$', path)
    if not regex:
        regex = re.match(r'(/dev/disk/.+)(-part[1-9]+)$', path)
    if not regex:
        return False
    else:
        if get_block_type(regex.group(1)) == 0:
            return True

def get_disk_size(path):
    '''
    This function returns the size in bytes of a disk-type
    block device, or None if path does not point to a disk-
    type device.
    '''
    (major, minor) = get_block_numbers(path)
    if major is None:
        return None
    # list of [major, minor, #blocks (1K), name
    partitions = [ x.split()[0:4]
                  for x in fread("/proc/partitions").split("\n")[2:] if x]
    size = None
    for partition in partitions:
        if partition[0:2] == [str(major), str(minor)]:
            size = int(partition[2]) * 1024
            break
    return size

def get_block_numbers(path):
    '''
    This function returns a (major,minor) tuple for the block
    device found at path, or (None, None) if path is
    not a block device.
    '''
    dev = os.path.realpath(path)
    try:
        mode = os.stat(dev)
    except OSError:
        return (None, None)

    if not stat.S_ISBLK(mode[stat.ST_MODE]):
        return (None, None)

    major = os.major(mode.st_rdev)
    minor = os.minor(mode.st_rdev)
    return (major, minor)

def get_block_type(path):
    '''
    This function returns a block device's type.
    Example: 0 is TYPE_DISK
    If no match is found, None is returned.

    >>> from rtslib.utils import *
    >>> get_block_type("/dev/sda")
    0
    >>> get_block_type("/dev/sr0")
    5
    >>> get_block_type("/dev/scd0")
    5
    >>> get_block_type("/dev/nodevicehere") is None
    True

    @param path: path to the block device
    @type path: string
    @return: An int for the block device type, or None if not a block device.
    '''
    dev = os.path.realpath(path)
    # TODO: Make adding new majors on-the-fly possible, using some config file
    # for instance, maybe an additionnal list argument, or even a match all
    # mode for overrides ?

    # Make sure we are dealing with a block device
    (major, minor) = get_block_numbers(dev)
    if major is None:
        return None

    # Treat disk partitions as TYPE_DISK
    if is_disk_partition(path):
        return 0

    # These devices are disk type block devices, but might not report this
    # correctly in /sys/block/xxx/device/type, so use their major number.
    type_disk_known_majors = [1,    # RAM disk
                              8,    # SCSI disk devices
                              9,    # Metadisk RAID devices
                              13,   # 8-bit MFM/RLL/IDE controller
                              19,   # "Double" compressed disk
                              21,   # Acorn MFM hard drive interface
                              30,   # FIXME: Normally 'Philips LMS CM-205
                                    # CD-ROM' in the Linux devices list but
                                    # used by Cirtas devices.
                              35,   # Slow memory ramdisk
                              36,   # MCA ESDI hard disk
                              37,   # Zorro II ramdisk
                              43,   # Network block devices
                              44,   # Flash Translation Layer (FTL) filesystems
                              45,   # Parallel port IDE disk devices
                              47,   # Parallel port ATAPI disk devices
                              48,   # Mylex DAC960 PCI RAID controller
                              48,   # Mylex DAC960 PCI RAID controller
                              49,   # Mylex DAC960 PCI RAID controller
                              50,   # Mylex DAC960 PCI RAID controller
                              51,   # Mylex DAC960 PCI RAID controller
                              52,   # Mylex DAC960 PCI RAID controller
                              53,   # Mylex DAC960 PCI RAID controller
                              54,   # Mylex DAC960 PCI RAID controller
                              55,   # Mylex DAC960 PCI RAID controller
                              58,   # Reserved for logical volume manager
                              59,   # Generic PDA filesystem device
                              60,   # LOCAL/EXPERIMENTAL USE
                              61,   # LOCAL/EXPERIMENTAL USE
                              62,   # LOCAL/EXPERIMENTAL USE
                              63,   # LOCAL/EXPERIMENTAL USE
                              64,   # Scramdisk/DriveCrypt encrypted devices
                              65,   # SCSI disk devices (16-31)
                              66,   # SCSI disk devices (32-47)
                              67,   # SCSI disk devices (48-63)
                              68,   # SCSI disk devices (64-79)
                              69,   # SCSI disk devices (80-95)
                              70,   # SCSI disk devices (96-111)
                              71,   # SCSI disk devices (112-127)
                              72,   # Compaq Intelligent Drive Array
                              73,   # Compaq Intelligent Drive Array
                              74,   # Compaq Intelligent Drive Array
                              75,   # Compaq Intelligent Drive Array
                              76,   # Compaq Intelligent Drive Array
                              77,   # Compaq Intelligent Drive Array
                              78,   # Compaq Intelligent Drive Array
                              79,   # Compaq Intelligent Drive Array
                              80,   # I2O hard disk
                              80,   # I2O hard disk
                              81,   # I2O hard disk
                              82,   # I2O hard disk
                              83,   # I2O hard disk
                              84,   # I2O hard disk
                              85,   # I2O hard disk
                              86,   # I2O hard disk
                              87,   # I2O hard disk
                              93,   # NAND Flash Translation Layer filesystem
                              94,   # IBM S/390 DASD block storage
                              96,   # Inverse NAND Flash Translation Layer
                              98,   # User-mode virtual block device
                              99,   # JavaStation flash disk
                              101,  # AMI HyperDisk RAID controller
                              102,  # Compressed block device
                              104,  # Compaq Next Generation Drive Array
                              105,  # Compaq Next Generation Drive Array
                              106,  # Compaq Next Generation Drive Array
                              107,  # Compaq Next Generation Drive Array
                              108,  # Compaq Next Generation Drive Array
                              109,  # Compaq Next Generation Drive Array
                              110,  # Compaq Next Generation Drive Array
                              111,  # Compaq Next Generation Drive Array
                              112,  # IBM iSeries virtual disk
                              114,  # IDE BIOS powered software RAID interfaces
                              115,  # NetWare (NWFS) Devices (0-255)
                              117,  # Enterprise Volume Management System
                              120,  # LOCAL/EXPERIMENTAL USE
                              121,  # LOCAL/EXPERIMENTAL USE
                              122,  # LOCAL/EXPERIMENTAL USE
                              123,  # LOCAL/EXPERIMENTAL USE
                              124,  # LOCAL/EXPERIMENTAL USE
                              125,  # LOCAL/EXPERIMENTAL USE
                              126,  # LOCAL/EXPERIMENTAL USE
                              127,  # LOCAL/EXPERIMENTAL USE
                              128,  # SCSI disk devices (128-143)
                              129,  # SCSI disk devices (144-159)
                              130,  # SCSI disk devices (160-175)
                              131,  # SCSI disk devices (176-191)
                              132,  # SCSI disk devices (192-207)
                              133,  # SCSI disk devices (208-223)
                              134,  # SCSI disk devices (224-239)
                              135,  # SCSI disk devices (240-255)
                              136,  # Mylex DAC960 PCI RAID controller
                              137,  # Mylex DAC960 PCI RAID controller
                              138,  # Mylex DAC960 PCI RAID controller
                              139,  # Mylex DAC960 PCI RAID controller
                              140,  # Mylex DAC960 PCI RAID controller
                              141,  # Mylex DAC960 PCI RAID controller
                              142,  # Mylex DAC960 PCI RAID controller
                              143,  # Mylex DAC960 PCI RAID controller
                              144,  # Non-device (e.g. NFS) mounts
                              145,  # Non-device (e.g. NFS) mounts
                              146,  # Non-device (e.g. NFS) mounts
                              147,  # DRBD device
                              152,  # EtherDrive Block Devices
                              153,  # Enhanced Metadisk RAID storage units
                              160,  # Carmel 8-port SATA Disks
                              161,  # Carmel 8-port SATA Disks
                              199,  # Veritas volume manager (VxVM) volumes
                              201,  # Veritas VxVM dynamic multipathing driver
                              240,  # LOCAL/EXPERIMENTAL USE
                              241,  # LOCAL/EXPERIMENTAL USE
                              242,  # LOCAL/EXPERIMENTAL USE
                              243,  # LOCAL/EXPERIMENTAL USE
                              244,  # LOCAL/EXPERIMENTAL USE
                              245,  # LOCAL/EXPERIMENTAL USE
                              246,  # LOCAL/EXPERIMENTAL USE
                              247,  # LOCAL/EXPERIMENTAL USE
                              248,  # LOCAL/EXPERIMENTAL USE
                              249,  # LOCAL/EXPERIMENTAL USE
                              250,  # LOCAL/EXPERIMENTAL USE
                              251,  # LOCAL/EXPERIMENTAL USE
                              252,  # LOCAL/EXPERIMENTAL USE
                              253,  # LOCAL/EXPERIMENTAL USE
                              254   # LOCAL/EXPERIMENTAL USE
                             ]
    if major in type_disk_known_majors:
        return 0

    # Same for LVM LVs, but as we cannot use major here
    # (it varies accross distros), use the realpath to check
    if os.path.dirname(dev) == "/dev/mapper":
        return 0

    # list of (major, minor, type) tuples
    blocks = [(fread("%s/dev" % fdev).strip().split(':')[0],
        fread("%s/dev" % fdev).strip().split(':')[1],
        fread("%s/device/type" % fdev).strip())
        for fdev in glob.glob("/sys/block/*")
        if os.path.isfile("%s/device/type" % fdev)]

    for block in blocks:
        if int(block[0]) == major and int(block[1]) == minor:
            return int(block[2])

    return None

def list_scsi_hbas():
    '''
    This function returns the list of HBA indexes for existing SCSI HBAs.
    '''
    return list(set([int(device.partition(":")[0])
        for device in os.listdir("/sys/bus/scsi/devices")
        if re.match("[0-9:]+", device)]))

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
    values representing the SCSI ID of the device, or None if no
    match is found.
    '''
    dev = os.path.realpath(path)
    scsi_devices = [os.path.basename(scsi_dev).split(':')
            for scsi_dev in glob.glob("/sys/class/scsi_device/*")]
    for (host, controller, target, lun) in scsi_devices:
        scsi_dev = convert_scsi_hctl_to_path(host, controller, target, lun)
        if dev == scsi_dev:
            return (int(host), int(controller), int(target), int(lun))

    return None

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
    @return: A string for the canonical path to the device, or empty string.
    '''
    try:
        host = int(host)
        controller = int(controller)
        target = int(target)
        lun = int(lun)
    except ValueError:
        raise RTSLibError(
            "The host, controller, target and lun parameter must be integers.")

    scsi_dev_path = "/sys/class/scsi_device"
    sysfs_names = [os.path.basename(name) for name
            in glob.glob("%s/%d:%d:%d:%d/device/block:*"
            % (scsi_dev_path, host, controller, target, lun))]
    if len(sysfs_names) == 0:
        sysfs_names = [os.path.basename(name) for name
                in glob.glob("%s/%d:%d:%d:%d/device/block/*"
                % (scsi_dev_path, host, controller, target, lun))]
    if len(sysfs_names) > 0:
        for name in sysfs_names:
            name1 = name.partition(":")[2].strip()
            if name1:
                name = name1
            dev = os.path.realpath("/dev/%s" % name)
            try:
                mode = os.stat(dev)[stat.ST_MODE]
            except OSError:
                pass
            if stat.S_ISBLK(mode):
                return dev
    else:
        return ''

def convert_human_to_bytes(hsize, kilo=1024):
    '''
    This function converts human-readable amounts of bytes to bytes.
    It understands the following units :
        - I{B} or no unit present for Bytes
        - I{k}, I{K}, I{kB}, I{KB} for kB (kilobytes)
        - I{m}, I{M}, I{mB}, I{MB} for MB (megabytes)
        - I{g}, I{G}, I{gB}, I{GB} for GB (gigabytes)
        - I{t}, I{T}, I{tB}, I{TB} for TB (terabytes)

    Note: The definition of I{kilo} defaults to 1kB = 1024Bytes.
    Strictly speaking, those should not be called I{kB} but I{kiB}.
    You can override that with the optional kilo parameter.

    Example:

    >>> import rtslib.utils as utils
    >>> utils.convert_human_to_bytes("1k")
    1024
    >>> utils.convert_human_to_bytes("1k", 1000)
    1000
    >>> utils.convert_human_to_bytes("1MB")
    1048576
    >>> utils.convert_human_to_bytes("12kB")
    12288

    @param hsize: The human-readable version of the Bytes amount to convert
    @type hsize: string or int
    @param kilo: Optionnal base for the kilo prefix
    @type kilo: int
    @return: An int representing the human-readable string converted to bytes
    '''
    size = str(hsize).replace("g","G").replace("K","k")
    size = size.replace("m","M").replace("t","T")
    if not re.match("^[0-9]+[T|G|M|k]?[B]?$", size):
        raise RTSLibError("Cannot interpret size, wrong format: %s" % hsize)

    size = size.rstrip('B')

    units = ['k', 'M', 'G', 'T']
    try:
        power = units.index(size[-1]) + 1
    except ValueError:
        power = 0
        size = int(size)
    else:
        size = int(size[:-1])

    size = size * int(kilo) ** power
    return size

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
        localarch = os.uname()[4].replace("_","")
        prefix = "iqn.2003-01.org.linux-iscsi.%s.%s" % (localname, localarch)
        prefix = prefix.strip().lower()
        serial = "sn.%s" % str(uuid.uuid4())[24:]
        return "%s:%s" % (prefix, serial)
    elif wwn_type == 'naa':
        sas_address = "naa.6001405%s" % str(uuid.uuid4())[:10]
        return sas_address.replace('-', '')
    else:
        raise ValueError("Unknown WWN type: %s." % wwn_type)

def is_valid_wwn(wwn_type, wwn, wwn_list=None):
    '''
    Returns True if the wwn is a valid wwn of type wwn_type.
    @param wwn_type: The WWN address type.
    @type wwn_type: str
    @param wwn: The WWN address to check.
    @type wwn: str
    @param wwn_list: An optional list of wwns to check the wwn parameter from.
    @type wwn_list: list of str
    @returns: bool.
    '''
    wwn_type = wwn_type.lower()

    if wwn_list is not None and wwn not in wwn_list:
        return False
    elif wwn_type == 'free':
        return True
    elif wwn_type == 'iqn' \
       and re.match("iqn\.[0-9]{4}-[0-1][0-9]\..*\..*", wwn) \
       and not re.search(' ', wwn) \
       and not re.search('_', wwn):
        return True
    elif wwn_type == 'naa' \
            and re.match("naa\.[0-9A-Fa-f]{16}$", wwn):
        return True
    elif wwn_type == 'unit_serial' \
            and re.match(
                "[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$", wwn):
        return True
    else:
        return False

def list_available_kernel_modules():
    '''
    List all loadable kernel modules as registered by depmod
    '''
    kver = os.uname()[2]
    depfile = "/lib/modules/%s/modules.dep" % kver
    return [module.split(".")[0] for module in
            re.findall(r"[a-zA-Z0-9_-]+\.ko:", fread(depfile))]

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
    @return: Whether of not we had to load the module.
    '''
    if module not in list_loaded_kernel_modules():
        if module in list_available_kernel_modules():
            try:
                exec_argv(["modprobe", module])
            except Exception, msg:
                raise RTSLibError("Kernel module %s exists "
                                  % module + "but fails to load: %s" % msg)
            else:
                return True
        else:
            raise RTSLibError("Kernel module %s does not exists on disk "
                                  % module + "and is not loaded.")
    else:
        return False

def exec_argv(argv, strip=True, shell=False):
    '''
    Executes a command line given as an argv table and either:
        - raise an exception if return != 0
        - return the output
    If strip is True, then output lines will be stripped.
    If shell is True, the argv must be a string that will be evaluated by the
    shell, instead of the argv list.

    '''
    process = subprocess.Popen(argv,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               shell=shell)
    (stdoutdata, stderrdata) = process.communicate()
    # Remove indents, trailing space and empty lines in output.
    if strip:
        stdoutdata = "\n".join([line.strip()
                                for line in stdoutdata.split("\n")
                                if line.strip()])
        stderrdata = "\n".join([line.strip()
                                for line in stderrdata.split("\n")
                                if line.strip()])
    if process.returncode != 0:
        raise RTSLibError(stderrdata)
    else:
        return stdoutdata

def list_eth_names(max_eth=1024):
    '''
    List the max_eth first local ethernet interfaces names from SIOCGIFCONF
    struct.
    '''
    SIOCGIFCONF = 0x8912
    if os.uname()[4].endswith("_64"):
        offset = 40
    else:
        offset = 32
    bytes = 32 * max_eth
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ifaces = array('B', '\0' * bytes)
    packed = pack('iL', bytes, ifaces.buffer_info()[0])
    outbytes = unpack('iL', ioctl(sock.fileno(), SIOCGIFCONF, packed))[0]
    names = ifaces.tostring()
    return [names[i:i+offset].split('\0', 1)[0]
            for i in range(0, outbytes, offset)]

def list_eth_ips(ifnames=None):
    '''
    List the IPv4 and IPv6 non-loopback, non link-local addresses of a list of
    ethernet interfaces from the SIOCGIFADDR struct. If ifname is omitted, list
    all IPs of all ifaces excepted for lo.
    '''
    if ifnames is None:
        ifnames = [iface for iface in list_eth_names() if iface != 'lo']
    addrs = []
    for iface in list_eth_names():
        ifaddresses = netifaces.ifaddresses(iface)
        if netifaces.AF_INET in ifaddresses:
            addrs.extend(addr['addr'] 
                         for addr in ifaddresses[netifaces.AF_INET]
                         if not addr['addr'].startswith('127.'))
        if netifaces.AF_INET6 in ifaddresses:
            addrs.extend(addr['addr']
                         for addr in ifaddresses[netifaces.AF_INET6]
                         if not '%' in addr['addr']
                         if not addr['addr'].startswith('::'))
    return sorted(set(addrs))

def is_ipv4_address(addr):
    try:
        ipaddr.IPv4Address(addr)
    except:
        return False
    else:
        return True

def is_ipv6_address(addr):
    try:
        ipaddr.IPv6Address(addr)
    except:
        return False
    else:
        return True

def get_main_ip():
    '''
    Try to guess the local machine non-loopback IP.
    If available, local hostname resolution is used (if non-loopback),
    else try to find an other non-loopback IP on configured NICs.
    If no usable IP address is found, returns None.
    '''
    # socket.gethostbyname does no have a timeout parameter
    # Let's use a thread to implement that in the background
    def start_thread(func):
        thread = Thread(target = func)
        thread.setDaemon(True)
        thread.start()

    def gethostbyname_timeout(hostname, timeout = 1):
        queue = Queue(1)

        def try_gethostbyname(hostname):
            try:
                hostname = socket.gethostbyname(hostname)
            except socket.gaierror:
                hostname = None
            return hostname

        def queue_try_gethostbyname():
            queue.put(try_gethostbyname(hostname))

        start_thread(queue_try_gethostbyname)

        try:
            result = queue.get(block = True, timeout = timeout)
        except Empty:
            result = None
        return result

    local_ips = list_eth_ips()
    # try to get a resolution in less than 1 second
    host_ip = gethostbyname_timeout(socket.gethostname())
    # Put the host IP in first position of the IP list if it exists
    if host_ip in local_ips:
        local_ips.remove(host_ip)
        local_ips.insert(0, host_ip)
    for ip_addr in local_ips:
        if not ip_addr.startswith("127.") and ip_addr.strip():
            return ip_addr
    return None

def _test():
    '''Run the doctests'''
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
