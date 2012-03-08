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

from rtslib.target import Target

class FabricModule(CFSNode):
    '''
    This is an interface to RTS Target Fabric Modules.
    It can load/unload modules, provide information about them and
    handle the configfs housekeeping. It uses module configuration
    files in /var/target/fabric/*.spec. After instanciation, whether or
    not the fabric module is loaded and
    '''

    version_attributes = set(["lio_version", "version"])
    discovery_auth_attributes = set(["discovery_auth"])
    target_names_excludes = version_attributes | discovery_auth_attributes

    # FabricModule private stuff
    def __init__(self, name):
        '''
        Instanciate a FabricModule object, according to the provided name.
        @param name: the name of the FabricModule object. It must match an
        existing target fabric module specfile (name.spec).
        @type name: str
        '''
        super(FabricModule, self).__init__()
        self.name = str(name)
        self.spec = self._parse_spec()
        self._path = "%s/%s" % (self.configfs_dir,
                                self.spec['configfs_group'])
    # FabricModule public stuff

    def _check_self(self):
        if not self.exists:
            self._load()
        super(FabricModule, self)._check_self()

    def has_feature(self, feature):
        '''
        Whether or not this FabricModule has a certain feature.
        '''
        if feature in self.spec['features']:
            return True
        else:
            return False

    def _load(self):
        '''
        Attempt to load the target fabric kernel module as defined in the
        specfile.
        @raises RTSLibError: For failure to load kernel module and/or create
        configfs group.
        '''
        module = self.spec['kernel_module']
        load_module = modprobe(module)

        # TODO: Also load saved targets and config if needed. For that, support
        #  XXX: from the configfs side would be nice: have a config ID present
        #  XXX: both on the on-disk saved config and a configfs attibute.

        # Create the configfs group
        self._create_in_cfs_ine('any')

    def _parse_spec(self):
        '''
        Parses the fabric module spec file.
        '''
        # Recognized options and their default values
        defaults = dict(features=['discovery_auth', 'acls', 'acls_auth', 'nps',
                                  'tpgts'],
                        kernel_module="%s_target_mod" % self.name,
                        configfs_group=self.name,
                        wwn_from_files=[],
                        wwn_from_files_filter='',
                        wwn_from_cmds=[],
                        wwn_from_cmds_filter='',
                        wwn_type='free')

        spec_file = "%s/%s.spec" % (self.spec_dir, self.name)
        spec = ConfigObj(spec_file).dict()
        if spec:
            self.spec_file = spec_file
        else:
            self.spec_file = ''

        # Do not allow unknown options
        unknown_options =  set(spec.keys()) - set(defaults.keys())
        if unknown_options:
            raise RTSLibError("Unknown option(s) in %s: %s"
                              % (spec_file, list(unknown_options)))

        # Use defaults for missing options
        missing_options = set(defaults.keys()) - set(spec.keys())
        for option in missing_options:
            spec[option] = defaults[option]

        # Type conversion and checking
        for option in spec:
            spec_type = type(spec[option]).__name__
            defaults_type = type(defaults[option]).__name__
            if spec_type != defaults_type:
                # Type mismatch, go through acceptable conversions
                if spec_type == 'str' and defaults_type == 'list':
                    spec[option] = [spec[option]]
                else:
                    raise RTSLibError("Wrong type for option '%s' in %s. "
                                      % (option, spec_file)
                                      + "Expected type '%s' and got '%s'."
                                      % (defaults_type, spec_type))

        # Generate the list of fixed WWNs if not empty
        wwn_list = None
        wwn_type = spec['wwn_type']

        if spec['wwn_from_files']:
            if wwn_list is None:
                wwn_list = set([])
            for wwn_pattern in spec['wwn_from_files']:
                for wwn_file in glob.iglob(wwn_pattern):
                    wwns_in_file = [wwn for wwn in
                                    re.split('\t|\0|\n| ', fread(wwn_file))
                                    if wwn.strip()]
                    if spec['wwn_from_files_filter']:
                        wwns_filtered = []
                        for wwn in wwns_in_file:
                            filter = "echo %s|%s" \
                                    % (wwn, spec['wwn_from_files_filter'])
                            wwns_filtered.append(exec_argv(filter, shell=True))
                    else:
                        wwns_filtered = wwns_in_file

                    wwn_list.update(set([wwn for wwn in wwns_filtered
                                         if is_valid_wwn(wwn_type, wwn)
                                         if wwn]
                                       ))
        if spec['wwn_from_cmds']:
            if wwn_list is None:
                wwn_list = set([])
            for wwn_cmd in spec['wwn_from_cmds']:
                cmd_result = exec_argv(wwn_cmd, shell=True)
                wwns_from_cmd = [wwn for wwn in
                                 re.split('\t|\0|\n| ', cmd_result)
                                 if wwn.strip()]
                if spec['wwn_from_cmds_filter']:
                    wwns_filtered = []
                    for wwn in wwns_from_cmd:
                        filter = "echo %s|%s" \
                                % (wwn, spec['wwn_from_cmds_filter'])
                        wwns_filtered.append(exec_argv(filter, shell=True))
                else:
                    wwns_filtered = wwns_from_cmd

                wwn_list.update(set([wwn for wwn in wwns_filtered
                                     if is_valid_wwn(wwn_type, wwn)
                                     if wwn]
                                   ))

        spec['wwn_list'] = wwn_list
        return spec

    def _list_targets(self):
        if self.exists:
            for wwn in os.listdir(self.path):
                if os.path.isdir("%s/%s" % (self.path, wwn)) and \
                        wwn not in self.target_names_excludes:
                    yield Target(self, wwn, 'lookup')

    def _get_version(self):
        if self.exists:
            for attr in self.version_attributes:
                path = "%s/%s" % (self.path, attr)
                if os.path.isfile(path):
                    return fread(path)
            else:
                raise RTSLibError("Can't find version for fabric module %s."
                                  % self.name)
        else:
            return None

    # FabricModule public stuff

    def is_valid_wwn(self, wwn):
        '''
        Checks whether or not the provided WWN is valid for this fabric module
        according to the spec file.
        '''
        return is_valid_wwn(self.spec['wwn_type'], wwn, self.spec['wwn_list'])

    def needs_wwn(self):
        '''
        This fabric requires wwn to be specified when creating a target,
        it cannot be autogenerated.
        '''
        return bool(self.spec['wwn_from_files']) or bool(self.spec['wwn_from_cmds'])

    def _assert_feature(self, feature):
        if not self.has_feature(feature):
            raise RTSLibError("This fabric module does not implement "
                              + "the %s feature." % feature)

    def clear_discovery_auth_settings(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        self.discovery_mutual_password = ''
        self.discovery_mutual_userid = ''
        self.discovery_password = ''
        self.discovery_userid = ''
        self.discovery_enable_auth = False

    def _get_discovery_mutual_password(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_mutual_password(self, password):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password_mutual" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_discovery_mutual_userid(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid_mutual" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_mutual_userid(self, userid):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid_mutual" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

    def _get_discovery_password(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_password(self, password):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/password" % self.path
        if password.strip() == '':
            password = "NULL"
        fwrite(path, "%s" % password)

    def _get_discovery_userid(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid" % self.path
        value = fread(path).strip()
        if value == "NULL":
            return ''
        else:
            return value

    def _set_discovery_userid(self, userid):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/userid" % self.path
        if userid.strip() == '':
            userid = "NULL"
        fwrite(path, "%s" % userid)

    def _get_discovery_enable_auth(self):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/enforce_discovery_auth" % self.path
        value = fread(path).strip()
        return int(value)

    def _set_discovery_enable_auth(self, enable):
        self._check_self()
        self._assert_feature('discovery_auth')
        path = "%s/discovery_auth/enforce_discovery_auth" % self.path
        if int(enable):
            enable = 1
        else:
            enable = 0
        fwrite(path, "%s" % enable)

    discovery_userid = \
            property(_get_discovery_userid,
                     _set_discovery_userid,
                     doc="Set or get the initiator discovery userid.")
    discovery_password = \
            property(_get_discovery_password,
                     _set_discovery_password,
                     doc="Set or get the initiator discovery password.")
    discovery_mutual_userid = \
            property(_get_discovery_mutual_userid,
                     _set_discovery_mutual_userid,
                     doc="Set or get the mutual discovery userid.")
    discovery_mutual_password = \
            property(_get_discovery_mutual_password,
                     _set_discovery_mutual_password,
                     doc="Set or get the mutual discovery password.")
    discovery_enable_auth = \
            property(_get_discovery_enable_auth,
                     _set_discovery_enable_auth,
                     doc="Set or get the discovery enable_auth flag.")

    targets = property(_list_targets,
                       doc="Get the list of target objects.")

    version = property(_get_version,
                       doc="Get the fabric module version string.")

    def setup(self, fm):
        '''
        Setup fabricmodule with settings from fm dict.
        Returns int of how many nonfatal errors were encountered
        '''
        for name, value in fm.iteritems():
            if name != 'name':
                setattr(self, name, value)
        return 0

    def dump(self):
        d = super(FabricModule, self).dump()
        d['name'] = self.name
        for attr in ("userid", "password", "mutual_userid", "mutual_password"):
            val = getattr(self, "discovery_" + attr, None)
            if val:
                d["discovery_" + attr] = val
        d['discovery_enable_auth'] = bool(int(self.discovery_enable_auth))
        return d


def _test():
    testmod()

if __name__ == "__main__":
    _test()
