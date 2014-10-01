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

from root import RTSRoot
from utils import RTSLibError, RTSLibBrokenLink, RTSLibNotInCFS

from target import LUN, MappedLUN
from target import NodeACL, NetworkPortal, TPG, Target
from fabric import FabricModule

from tcm import FileIOStorageObject, BlockStorageObject
from tcm import PSCSIStorageObject, RDMCPStorageObject, UserBackedStorageObject
from tcm import StorageObjectFactory

__version__ = 'GIT_VERSION'
__author__ = "Jerome Martin <jxm@risingtidesystems.com>"
__url__ = "http://www.risingtidesystems.com"
__description__ = "API for RisingTide Systems generic SCSI target."
__license__ = __doc__
