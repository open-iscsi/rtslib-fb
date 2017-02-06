'''
Implements the RTS ALUA Target Port Group class.

This file is part of RTSLib.
Copyright (c) 2016 by Red Hat, Inc.

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

from .node import CFSNode
from .utils import RTSLibError, RTSLibALUANotSupported, fread, fwrite

alua_rw_params = ['alua_access_state', 'alua_access_status',
                  'alua_write_metadata', 'alua_access_type', 'preferred',
                  'nonop_delay_msecs', 'trans_delay_msecs',
                  'implicit_trans_secs', 'alua_support_offline',
                  'alua_support_standby', 'alua_support_transitioning',
                  'alua_support_active_nonoptimized',
                  'alua_support_unavailable', 'alua_support_active_optimized']
alua_ro_params = ['tg_pt_gp_id', 'members', 'alua_support_lba_dependent']
alua_types = ['None', 'Implicit', 'Explicit', 'Implicit and Explicit']
alua_statuses = ['None', 'Altered by Explicit STPG', 'Altered by Implicit ALUA']

class ALUATargetPortGroup(CFSNode):
    """
    ALUA Target Port Group interface
    """

    def __repr__(self):
        return "<ALUA TPG %s>" % self.name

    def __init__(self, storage_object, name, tag=None):
        """
        @param storage_object: backstore storage object to create ALUA group for
        @param name: name of ALUA group
        @param tag: target port group id. If not passed in, try to look
                    up existing ALUA TPG with the same name
        """
        # kernel partially sets up default_tg_pt_gp and will let you partially
        # setup ALUA groups for pscsi and user, but writing to some of the
        # files will crash the kernel. Just fail to even create groups until
        # the kernel is fixed.
        if storage_object.alua_supported is False:
            raise RTSLibALUANotSupported("Backend does not support ALUA setup")

        # default_tg_pt_gp takes tag 1
        if tag is not None and (tag > 65535 or tag < 1):
            raise RTSLibError("The TPG Tag must be between 1 and 65535")

        super(ALUATargetPortGroup, self).__init__()
        self.name = name
        self.storage_object = storage_object

        self._path = "%s/alua/%s" % (storage_object.path, name)

        if tag is not None:
            try:
                self._create_in_cfs_ine('create')
            except OSError as msg:
                raise RTSLibError(msg)

            try:
                fwrite("%s/tg_pt_gp_id" % self._path, tag)
            except IOError as msg:
                self.delete()
                raise RTSLibError("Cannot set id to %d: %s" % (tag, str(msg)))
        else:
            try:
                self._create_in_cfs_ine('lookup')
            except OSError as msg:
                raise RTSLibError(msg)

    # Public

    def delete(self):
        """
        Delete ALUA TPG and unmap from LUNs
        """
        self._check_self()

        # default_tg_pt_gp created by the kernel and cannot be deleted
        if self.name == "default_tg_pt_gp":
            raise RTSLibError("Can not delete default_tg_pt_gp")

        # This will reset the ALUA tpg to default_tg_pt_gp
        super(ALUATargetPortGroup, self).delete()

    def _get_alua_access_state(self):
        self._check_self()
        path = "%s/alua_access_state" % self.path
        return int(fread(path))

    def _set_alua_access_state(self, newstate):
        self._check_self()
        path = "%s/alua_access_state" % self.path
        try:
            fwrite(path, str(int(newstate)))
        except IOError as e:
            raise RTSLibError("Cannot change ALUA state: %s" % e)

    def _get_alua_access_status(self):
        self._check_self()
        path = "%s/alua_access_status" % self.path
        status = fread(path)
        return alua_statuses.index(status)

    def _set_alua_access_status(self, newstatus):
        self._check_self()
        path = "%s/alua_access_status" % self.path
        try:
            fwrite(path, str(int(newstatus)))
        except IOError as e:
            raise RTSLibError("Cannot change ALUA status: %s" % e)

    def _get_alua_access_type(self):
        self._check_self()
        path = "%s/alua_access_type" % self.path
        alua_type = fread(path)
        return alua_types.index(alua_type)

    def _set_alua_access_type(self, access_type):
        self._check_self()
        path = "%s/alua_access_type" % self.path
        try:
            fwrite(path, str(int(access_type)))
        except IOError as e:
            raise RTSLibError("Cannot change ALUA access type: %s" % e)

    def _get_preferred(self):
        self._check_self()
        path = "%s/preferred" % self.path
        return int(fread(path))

    def _set_preferred(self, pref):
        self._check_self()
        path = "%s/preferred" % self.path
        try:
            fwrite(path, str(int(pref)))
        except IOError as e:
            raise RTSLibError("Cannot set preferred: %s" % e)

    def _get_alua_write_metadata(self):
        self._check_self()
        path = "%s/alua_write_metadata" % self.path
        return int(fread(path))

    def _set_alua_write_metadata(self, pref):
        self._check_self()
        path = "%s/alua_write_metadata" % self.path
        try:
            fwrite(path, str(int(pref)))
        except IOError as e:
            raise RTSLibError("Cannot set alua_write_metadata: %s" % e)

    def _get_alua_support_active_nonoptimized(self):
        self._check_self()
        path = "%s/alua_support_active_nonoptimized" % self.path
        return int(fread(path))

    def _set_alua_support_active_nonoptimized(self, enabled):
        self._check_self()
        path = "%s/alua_support_active_nonoptimized" % self.path
        try:
            fwrite(path, str(int(enabled)))
        except IOError as e:
            raise RTSLibError("Cannot set alua_support_active_nonoptimized: %s" % e)

    def _get_alua_support_active_optimized(self):
        self._check_self()
        path = "%s/alua_support_active_optimized" % self.path
        return int(fread(path))

    def _set_alua_support_active_optimized(self, enabled):
        self._check_self()
        path = "%s/alua_support_active_optimized" % self.path
        try:
            fwrite(path, str(int(enabled)))
        except IOError as e:
            raise RTSLibError("Cannot set alua_support_active_optimized: %s" % e)

    def _get_alua_support_offline(self):
        self._check_self()
        path = "%s/alua_support_offline" % self.path
        return int(fread(path))

    def _set_alua_support_offline(self, enabled):
        self._check_self()
        path = "%s/alua_support_offline" % self.path
        try:
            fwrite(path, str(int(enabled)))
        except IOError as e:
            raise RTSLibError("Cannot set alua_support_offline: %s" % e)

    def _get_alua_support_unavailable(self):
        self._check_self()
        path = "%s/alua_support_unavailable" % self.path
        return int(fread(path))

    def _set_alua_support_unavailable(self, enabled):
        self._check_self()
        path = "%s/alua_support_unavailable" % self.path
        try:
            fwrite(path, str(int(enabled)))
        except IOError as e:
            raise RTSLibError("Cannot set alua_support_unavailable: %s" % e)

    def _get_alua_support_standby(self):
        self._check_self()
        path = "%s/alua_support_standby" % self.path
        return int(fread(path))

    def _set_alua_support_standby(self, enabled):
        self._check_self()
        path = "%s/alua_support_standby" % self.path
        try:
            fwrite(path, str(int(enabled)))
        except IOError as e:
            raise RTSLibError("Cannot set alua_support_standby: %s" % e)

    def _get_alua_support_transitioning(self):
        self._check_self()
        path = "%s/alua_support_transitioning" % self.path
        return int(fread(path))

    def _set_alua_support_transitioning(self, enabled):
        self._check_self()
        path = "%s/alua_support_transitioning" % self.path
        try:
            fwrite(path, str(int(enabled)))
        except IOError as e:
            raise RTSLibError("Cannot set alua_support_transitioning: %s" % e)

    def _get_alua_support_lba_dependent(self):
        self._check_self()
        path = "%s/alua_support_lba_dependent" % self.path
        return int(fread(path))

    def _get_members(self):
        self._check_self()
        path = "%s/members" % self.path
        return fread(path)

    def _get_tg_pt_gp_id(self):
        self._check_self()
        path = "%s/tg_pt_gp_id" % self.path
        return int(fread(path))

    def _get_trans_delay_msecs(self):
        self._check_self()
        path = "%s/trans_delay_msecs" % self.path
        return int(fread(path))

    def _set_trans_delay_msecs(self, secs):
        self._check_self()
        path = "%s/trans_delay_msecs" % self.path
        try:
            fwrite(path, str(int(secs)))
        except IOError as e:
            raise RTSLibError("Cannot set trans_delay_msecs: %s" % e)

    def _get_implicit_trans_secs(self):
        self._check_self()
        path = "%s/implicit_trans_secs" % self.path
        return int(fread(path))

    def _set_implicit_trans_secs(self, secs):
        self._check_self()
        path = "%s/implicit_trans_secs" % self.path
        try:
            fwrite(path, str(int(secs)))
        except IOError as e:
            raise RTSLibError("Cannot set implicit_trans_secs: %s" % e)

    def _get_nonop_delay_msecs(self):
        self._check_self()
        path = "%s/nonop_delay_msecs" % self.path
        return int(fread(path))

    def _set_nonop_delay_msecs(self, delay):
        self._check_self()
        path = "%s/nonop_delay_msecs" % self.path
        try:
            fwrite(path, str(int(delay)))
        except IOError as e:
            raise RTSLibError("Cannot set nonop_delay_msecs: %s" % e)

    def dump(self):
        d = super(ALUATargetPortGroup, self).dump()
        d['name'] = self.name
        d['tg_pt_gp_id'] = self.tg_pt_gp_id
        for param in alua_rw_params:
            d[param] = getattr(self, param, None)
        return d

    alua_access_state = property(_get_alua_access_state, _set_alua_access_state,
                                 doc="Get or set ALUA state. "
                                     "0 = Active/optimized, "
                                     "1 = Active/non-optimized, "
                                     "2 = Standby, "
                                     "3 = Unavailable, "
                                     "4 = LBA Dependent, "
                                     "14 = Offline, "
                                     "15 = Transitioning")

    alua_access_type = property(_get_alua_access_type, _set_alua_access_type,
                                doc="Get or set ALUA access type. "
                                    "1 = Implicit, 2 = Explicit, 3 = Both")

    alua_access_status = property(_get_alua_access_status,
                                  _set_alua_access_status,
                                  doc="Get or set ALUA access status. "
                                      "0 = None, "
                                      "1 = Altered by Explicit STPG, "
                                      "2 = Altered by Implicit ALUA")

    preferred = property(_get_preferred, _set_preferred,
                         doc="Get or set preferred bit. 1 = Pref, 0 Not-Pre")

    alua_write_metadata = property(_get_alua_write_metadata,
                                   _set_alua_write_metadata,
                                   doc="Get or set alua_write_metadata flag. "
                                       "enable (1) or disable (0)")

    tg_pt_gp_id = property(_get_tg_pt_gp_id, doc="Get ALUA Target Port Group ID")

    members = property(_get_members, doc="Get LUNs in Target Port Group")

    alua_support_active_nonoptimized = property(_get_alua_support_active_nonoptimized,
                                                _set_alua_support_active_nonoptimized,
                                                doc="Enable (1) or disable (0) "
                                                    "Active/non-optimized support")

    alua_support_active_optimized = property(_get_alua_support_active_optimized,
                                             _set_alua_support_active_optimized,
                                             doc="Enable (1) or disable (0) "
                                                 "Active/optimized support")

    alua_support_offline = property(_get_alua_support_offline,
                                    _set_alua_support_offline,
                                    doc="Enable (1) or disable (0) "
                                        "offline support")

    alua_support_unavailable = property(_get_alua_support_unavailable,
                                        _set_alua_support_unavailable,
                                        doc="enable (1) or disable (0) "
                                            "unavailable support")

    alua_support_standby = property(_get_alua_support_standby,
                                    _set_alua_support_standby,
                                    doc="enable (1) or disable (0) "
                                        "standby support")

    alua_support_lba_dependent = property(_get_alua_support_lba_dependent,
                                          doc="show lba_dependent support "
                                              "enabled (1) or disabled (0)")

    alua_support_transitioning = property(_get_alua_support_transitioning,
                                          _set_alua_support_transitioning,
                                          doc="enable (1) or disable (0) "
                                          "transitioning support")

    trans_delay_msecs = property(_get_trans_delay_msecs,
                                 _set_trans_delay_msecs,
                                 doc="msecs to delay state transition")

    implicit_trans_secs = property(_get_implicit_trans_secs,
                                   _set_implicit_trans_secs,
                                   doc="implicit transition time limit")

    nonop_delay_msecs = property(_get_nonop_delay_msecs, _set_nonop_delay_msecs,
                                 doc="msecs to delay IO when non-optimized")

    @classmethod
    def setup(cls, storage_obj, alua_tpg, err_func):
        name = alua_tpg['name']
        if name == 'default_tg_pt_gp':
            return

        alua_tpg_obj = cls(storage_obj, name, alua_tpg['tg_pt_gp_id'])
        for param in alua_rw_params:
            setattr(alua_tpg_obj, param, alua_tpg[param])
