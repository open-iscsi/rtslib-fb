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
'''

if __name__ == "rtslib-fb":
    from warnings import warn
    warn("'rtslib' package name for rtslib-fb is deprecated, please"
         + " instead import 'rtslib_fb'", UserWarning, stacklevel=2)

from .root import RTSRoot
from .utils import RTSLibError, RTSLibBrokenLink, RTSLibNotInCFS
from .utils import RTSLibALUANotSupported

from .target import LUN, MappedLUN
from .target import NodeACL, NetworkPortal, TPG, Target
from .target import NodeACLGroup, MappedLUNGroup
from .fabric import FabricModule

from .tcm import FileIOStorageObject, BlockStorageObject
from .tcm import PSCSIStorageObject, RDMCPStorageObject, UserBackedStorageObject
from .tcm import StorageObjectFactory

from .alua import ALUATargetPortGroup

__version__ = '2.1.72'
__author__ = "Jerome Martin <jxm@risingtidesystems.com>"
__url__ = 'http://github.com/open-iscsi/rtslib-fb'
__description__ = 'API for Linux kernel SCSI target (aka LIO)'
__license__ = 'Apache 2.0'
