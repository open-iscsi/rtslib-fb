'''
Implements the RTS generic Target fabric classes.

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
import uuid
import shutil

from os.path import isdir
from doctest import testmod
from configobj import ConfigObj

from rtslib.node import CFSNode
from rtslib.utils import RTSLibError, RTSLibBrokenLink, modprobe
from rtslib.utils import is_ipv6_address, is_ipv4_address
from rtslib.utils import fread, fwrite, generate_wwn, is_valid_wwn, exec_argv
from rtslib.utils import dict_remove, set_attributes

class NetworkPortal(CFSNode):
    '''
    This is an interface to NetworkPortals in configFS.  A NetworkPortal is
    identified by its IP and port, but here we also require the parent TPG, so
    instance objects represent both the NetworkPortal and its association to a
    TPG. This is necessary to get path information in order to create the
    portal in the proper configFS hierarchy.
    '''

    # NetworkPortal private stuff

    def __init__(self, parent_tpg, ip_address, port, mode='any'):
        '''
        @param parent_tpg: The parent TPG object.
        @type parent_tpg: TPG
        @param ip_address: The ipv4 IP address of the NetworkPortal.
        @type ip_address: string
        @param port: The NetworkPortal TCP/IP port.
        @type port: int
        @param mode:An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up or
              created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A NetworkPortal object.
        '''
        super(NetworkPortal, self).__init__()
        if not (is_ipv4_address(ip_address) or is_ipv6_address(ip_address)):
            raise RTSLibError("Invalid IP address: %s" % ip_address)
        else:
            self._ip_address = str(ip_address)

        try:
            self._port = int(port)
        except ValueError:
            raise RTSLibError("Invalid port.")

        if parent_tpg.luns is None:
            raise RTSLibError("Invalid parent TPG.")
        else:
            self._parent_tpg = parent_tpg

        if is_ipv4_address(ip_address):
            self._path = "%s/np/%s:%d" \
                    % (self.parent_tpg.path, self.ip_address, self.port)
        else:
            self._path = "%s/np/[%s]:%d" \
                    % (self.parent_tpg.path, self.ip_address, self.port)
        try:
            self._create_in_cfs_ine(mode)
        except OSError, msg:
            raise RTSLibError(msg[1])

    def _get_ip_address(self):
        return self._ip_address

    def _get_port(self):
        return self._port

    def _get_parent_tpg(self):
        return self._parent_tpg

    # NetworkPortal public stuff

    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    port = property(_get_port,
            doc="Get the NetworkPortal's TCP port as an int.")
    ip_address = property(_get_ip_address,
            doc="Get the NetworkPortal's IP address as a string.")

    def dump(self):
        d = super(NetworkPortal, self).dump()
        d['port'] = self.port
        d['ip_address'] = self.ip_address
        return d


def _test():
    testmod()

if __name__ == "__main__":
    _test()
