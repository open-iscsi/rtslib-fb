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

class NodeACL(CFSNode):
    '''
    This is an interface to node ACLs in configFS.
    A NodeACL is identified by the initiator node wwn and parent TPG.
    '''

    # NodeACL private stuff

    def __init__(self, parent_tpg, node_wwn, mode='any'):
        '''
        @param parent_tpg: The parent TPG object.
        @type parent_tpg: TPG
        @param node_wwn: The wwn of the initiator node for which the ACL is
        created.
        @type node_wwn: string
        @param mode:An optionnal string containing the object creation mode:
            - I{'any'} means the configFS object will be either looked up or
            created.
            - I{'lookup'} means the object MUST already exist configFS.
            - I{'create'} means the object must NOT already exist in configFS.
        @type mode:string
        @return: A NodeACL object.
        '''

        super(NodeACL, self).__init__()

        if parent_tpg.luns is None:
            raise RTSLibError("Invalid parent TPG.")
        else:
            self._parent_tpg = parent_tpg

        self._node_wwn = str(node_wwn).lower()
        self._path = "%s/acls/%s" % (self.parent_tpg.path, self.node_wwn)
        self._create_in_cfs_ine(mode)

    def _get_node_wwn(self):
        return self._node_wwn

    def _get_parent_tpg(self):
        return self._parent_tpg

    def _get_chap_mutual_password(self):
        self._check_self()
        path = "%s/auth/password_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_mutual_password(self, password):
        self._check_self()
        path = "%s/auth/password_mutual" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_chap_mutual_userid(self):
        self._check_self()
        path = "%s/auth/userid_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_mutual_userid(self, userid):
        self._check_self()
        path = "%s/auth/userid_mutual" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

    def _get_chap_password(self):
        self._check_self()
        path = "%s/auth/password" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_password(self, password):
        self._check_self()
        path = "%s/auth/password" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_chap_userid(self):
        self._check_self()
        path = "%s/auth/userid" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_chap_userid(self, userid):
        self._check_self()
        path = "%s/auth/userid" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

    def _get_tcq_depth(self):
        self._check_self()
        path = "%s/cmdsn_depth" % self.path
        return fread(path).strip()

    def _set_tcq_depth(self, depth):
        self._check_self()
        path = "%s/cmdsn_depth" % self.path
        fwrite(path, "%s" % depth)

    def _get_authenticate_target(self):
        self._check_self()
        path = "%s/auth/authenticate_target" % self.path
        if fread(path).strip() == "1":
            return True
        else:
            return False

    def _list_mapped_luns(self):
        self._check_self()
        for mapped_lun_dir in glob.glob("%s/lun_*" % self.path):
            mapped_lun = int(os.path.basename(mapped_lun_dir).split("_")[1])
            yield MappedLUN(self, mapped_lun)

    # NodeACL public stuff
    def has_feature(self, feature):
        '''
        Whether or not this NodeACL has a certain feature.
        '''
        return self.parent_tpg.has_feature(feature)

    def delete(self):
        '''
        Delete the NodeACL, including all MappedLUN objects.
        If the underlying configFS object does not exist, this method does
        nothing.
        '''
        self._check_self()
        for mapped_lun in self.mapped_luns:
            mapped_lun.delete()
        super(NodeACL, self).delete()

    def mapped_lun(self, mapped_lun, tpg_lun=None, write_protect=None):
        '''
        Same as MappedLUN() but without the parent_nodeacl parameter.
        '''
        self._check_self()
        return MappedLUN(self, mapped_lun=mapped_lun, tpg_lun=tpg_lun,
                         write_protect=write_protect)

    chap_userid = property(_get_chap_userid, _set_chap_userid,
                           doc="Set or get the initiator CHAP auth userid.")
    chap_password = property(_get_chap_password, _set_chap_password,
                             doc=\
                             "Set or get the initiator CHAP auth password.")
    chap_mutual_userid = property(_get_chap_mutual_userid,
                                  _set_chap_mutual_userid,
                                  doc=\
                                  "Set or get the mutual CHAP auth userid.")
    chap_mutual_password = property(_get_chap_mutual_password,
                                    _set_chap_mutual_password,
                                    doc=\
                                    "Set or get the mutual CHAP password.")
    tcq_depth = property(_get_tcq_depth, _set_tcq_depth,
                         doc="Set or get the TCQ depth for the initiator " \
                         + "sessions matching this NodeACL.")
    parent_tpg = property(_get_parent_tpg,
            doc="Get the parent TPG object.")
    node_wwn = property(_get_node_wwn,
            doc="Get the node wwn.")
    authenticate_target = property(_get_authenticate_target,
            doc="Get the boolean authenticate target flag.")
    mapped_luns = property(_list_mapped_luns,
            doc="Get the list of all MappedLUN objects in this NodeACL.")

    def dump(self):
        d = super(NodeACL, self).dump()
        for attr in ("userid", "password", "mutual_userid", "mutual_password"):
            val = getattr(self, "chap_" + attr, None)
            if val:
                d["chap_" + attr] = val
        d['tcq_depth'] = int(self.tcq_depth)
        d['node_wwn'] = self.node_wwn
        d['mapped_luns'] = [lun.dump() for lun in self.mapped_luns]
        return d


class MappedLUN(CFSNode):
    '''
    This is an interface to RTS Target Mapped LUNs.
    A MappedLUN is a mapping of a TPG LUN to a specific initiator node, and is
    part of a NodeACL. It allows the initiator to actually access the TPG LUN
    if ACLs are enabled for the TPG. The initial TPG LUN will then be seen by
    the initiator node as the MappedLUN.
    '''

    # MappedLUN private stuff

    def __init__(self, parent_nodeacl, mapped_lun,
                 tpg_lun=None, write_protect=None):
        '''
        A MappedLUN object can be instanciated in two ways:
            - B{Creation mode}: If I{tpg_lun} is specified, the underlying
              configFS object will be created with that parameter. No MappedLUN
              with the same I{mapped_lun} index can pre-exist in the parent
              NodeACL in that mode, or instanciation will fail.
            - B{Lookup mode}: If I{tpg_lun} is not set, then the MappedLUN will
              be bound to the existing configFS MappedLUN object of the parent
              NodeACL having the specified I{mapped_lun} index. The underlying
              configFS object must already exist in that mode.

        @param mapped_lun: The mapped LUN index.
        @type mapped_lun: int
        @param tpg_lun: The TPG LUN index to map, or directly a LUN object that
        belong to the same TPG as the
        parent NodeACL.
        @type tpg_lun: int or LUN
        @param write_protect: The write-protect flag value, defaults to False
        (write-protection disabled).
        @type write_protect: bool
        '''

        super(MappedLUN, self).__init__()

        if not isinstance(parent_nodeacl, NodeACL):
            raise RTSLibError("The parent_nodeacl parameter must be " \
                              + "a NodeACL object.")
        else:
            self._parent_nodeacl = parent_nodeacl
            if not parent_nodeacl.exists:
                raise RTSLibError("The parent_nodeacl does not exist.")

        try:
            self._mapped_lun = int(mapped_lun)
        except ValueError:
            raise RTSLibError("The mapped_lun parameter must be an " \
                              + "integer value.")

        self._path = "%s/lun_%d" % (self.parent_nodeacl.path, self.mapped_lun)

        if tpg_lun is None and write_protect is not None:
            raise RTSLibError("The write_protect parameter has no " \
                              + "meaning without the tpg_lun parameter.")

        if tpg_lun is not None:
            self._create_in_cfs_ine('create')
            try:
                self._configure(tpg_lun, write_protect)
            except:
                self.delete()
                raise
        else:
            self._create_in_cfs_ine('lookup')

    def _configure(self, tpg_lun, write_protect):
        self._check_self()
        if isinstance(tpg_lun, LUN):
            tpg_lun = tpg_lun.lun
        else:
            try:
                tpg_lun = int(tpg_lun)
            except ValueError:
                raise RTSLibError("The tpg_lun must be either an "
                                  + "integer or a LUN object.")
        # Check that the tpg_lun exists in the TPG
        for lun in self.parent_nodeacl.parent_tpg.luns:
            if lun.lun == tpg_lun:
                tpg_lun = lun
                break
        if not (isinstance(tpg_lun, LUN) and tpg_lun):
            raise RTSLibError("LUN %s does not exist in this TPG."
                              % str(tpg_lun))
        os.symlink(tpg_lun.path, "%s/%s"
                   % (self.path, str(uuid.uuid4())[-10:]))
        if write_protect:
            self.write_protect = True
        else:
            self.write_protect = False

    def _get_alias(self):
        self._check_self()
        alias = None
        for path in os.listdir(self.path):
            if os.path.islink("%s/%s" % (self.path, path)):
                alias = os.path.basename(path)
                break
        if alias is None:
            raise RTSLibBrokenLink("Broken LUN in configFS, no " \
                                         + "storage object attached.")
        else:
            return alias

    def _get_mapped_lun(self):
        return self._mapped_lun

    def _get_parent_nodeacl(self):
        return self._parent_nodeacl

    def _set_write_protect(self, write_protect):
        self._check_self()
        path = "%s/write_protect" % self.path
        if write_protect:
            fwrite(path, "1")
        else:
            fwrite(path, "0")

    def _get_write_protect(self):
        self._check_self()
        path = "%s/write_protect" % self.path
        write_protect = fread(path).strip()
        if write_protect == "1":
            return True
        else:
            return False

    def _get_tpg_lun(self):
        self._check_self()
        path = os.path.realpath("%s/%s" % (self.path, self._get_alias()))
        for lun in self.parent_nodeacl.parent_tpg.luns:
            if lun.path == path:
                return lun

        raise RTSLibBrokenLink("Broken MappedLUN, no TPG LUN found !")

    def _get_node_wwn(self):
        self._check_self()
        return self.parent_nodeacl.node_wwn

    # MappedLUN public stuff

    def delete(self):
        '''
        Delete the MappedLUN.
        '''
        self._check_self()
        try:
            lun_link = "%s/%s" % (self.path, self._get_alias())
        except RTSLibBrokenLink:
            pass
        else:
            if os.path.islink(lun_link):
                os.unlink(lun_link)
        super(MappedLUN, self).delete()

    mapped_lun = property(_get_mapped_lun,
            doc="Get the integer MappedLUN mapped_lun index.")
    parent_nodeacl = property(_get_parent_nodeacl,
            doc="Get the parent NodeACL object.")
    write_protect = property(_get_write_protect, _set_write_protect,
            doc="Get or set the boolean write protection.")
    tpg_lun = property(_get_tpg_lun,
            doc="Get the TPG LUN object the MappedLUN is pointing at.")
    node_wwn = property(_get_node_wwn,
            doc="Get the wwn of the node for which the TPG LUN is mapped.")

    def dump(self):
        d = super(MappedLUN, self).dump()
        d['write_protect'] = self.write_protect
        d['index'] = self.mapped_lun
        d['tpg_lun'] = self.tpg_lun.lun
        return d


def _test():
    testmod()

if __name__ == "__main__":
    _test()
