'''
Implements the base CFSNode class and a few inherited variants.

This file is part of RTSLib.
Copyright (c) 2011-2013 by Datera, Inc

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
import stat
from utils import fread, fwrite, RTSLibError, RTSLibNotInCFS


class CFSNode(object):

    # Where is the configfs base LIO directory ?
    configfs_dir = '/sys/kernel/config/target'
    # TODO: Make the ALUA path generic, not iscsi-centric
    # What is the ALUA directory ?
    alua_metadata_dir = "/var/target/alua/iSCSI"

    # CFSNode private stuff

    def __init__(self):
        self._path = self.configfs_dir

    def __nonzero__(self):
        if os.path.isdir(self.path):
            return True
        else:
            return False

    def __str__(self):
        return self.path

    def _get_path(self):
        return self._path

    def _create_in_cfs_ine(self, mode):
        '''
        Creates the configFS node if it does not already exists depending on
        the mode.
        any -> makes sure it exists, also works if the node already does exists
        lookup -> make sure it does NOT exists
        create -> create the node which must not exists beforehand
        Upon success (no exception raised), self._fresh is True if a node was
        created, else self._fresh is False.
        '''
        if mode not in ['any', 'lookup', 'create']:
            raise RTSLibError("Invalid mode: %s" % mode)
        if self and mode == 'create':
            raise RTSLibError("This %s already exists in configFS."
                              % self.__class__.__name__)
        elif not self and mode == 'lookup':
            raise RTSLibNotInCFS("No such %s in configfs: %s."
                                 % (self.__class__.__name__, self.path))
        if self:
            self._fresh = False
            return

        try:
            os.mkdir(self.path)
            self._fresh = True
        except:
            raise RTSLibError("Could not create %s in configFS."
                              % self.__class__.__name__)

    def _exists(self):
        return bool(self)

    def _check_self(self):
        if not self:
            raise RTSLibNotInCFS("This %s does not exist in configFS."
                                 % self.__class__.__name__)

    def _is_fresh(self):
        return self._fresh

    def _list_files(self, path, writable=None):
        '''
        List files under a path depending on their owner's write permissions.
        @param path: The path under which the files are expected to be. If the
        path itself is not a directory, an empty list will be returned.
        @type path: str
        @param writable: If None (default), returns all parameters, if True,
        returns read-write parameters, if False, returns just the read-only
        parameters.
        @type writable: bool or None
        @return: List of file names filtered according to their write perms.
        '''
        if not os.path.isdir(path):
            return []

        if writable is None:
            names = os.listdir(path)
        elif writable:
            names = [name for name in os.listdir(path)
                     if (os.stat("%s/%s" % (path, name))[stat.ST_MODE] \
                         & stat.S_IWUSR)]
        else:
            names = [os.path.basename(name) for name in os.listdir(path)
                     if not (os.stat("%s/%s" % (path, name))[stat.ST_MODE] \
                             & stat.S_IWUSR)]
        names.sort()
        return names

    # CFSNode public stuff

    def list_parameters(self, writable=None):
        '''
        @param writable: If None (default), returns all parameters, if True,
        returns read-write parameters, if False, returns just the read-only
        parameters.
        @type writable: bool or None
        @return: The list of existing RFC-3720 parameter names.
        '''
        self._check_self()
        path = "%s/param" % self.path
        return self._list_files(path, writable)

    def list_attributes(self, writable=None):
        '''
        @param writable: If None (default), returns all attributes, if True,
        returns read-write attributes, if False, returns just the read-only
        attributes.
        @type writable: bool or None
        @return: A list of existing attribute names as strings.
        '''
        self._check_self()
        path = "%s/attrib" % self.path
        return self._list_files(path, writable)

    def list_auth_attrs(self, writable=None):
        '''
        @param writable: If None (default), returns all auth attrs, if True,
        returns read-write auth attrs, if False, returns just the read-only
        auth attrs.
        @type writable: bool or None
        @return: A list of existing attribute names as strings.
        '''
        self._check_self()
        path = "%s/auth" % self.path
        return self._list_files(path, writable)

    def set_attribute(self, attribute, value):
        '''
        Sets the value of a named attribute.
        The attribute must exist in configFS.
        @param attribute: The attribute's name. It is case-sensitive.
        @type attribute: string
        @param value: The attribute's value.
        @type value: string
        '''
        self._check_self()
        path = "%s/attrib/%s" % (self.path, str(attribute))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find attribute: %s."
                              % str(attribute))
        else:
            try:
                fwrite(path, "%s\n" % str(value))
            except IOError, msg:
                msg = msg[1]
                raise RTSLibError("Cannot set attribute %s: %s"
                                  % (str(attribute), str(msg)))

    def get_attribute(self, attribute):
        '''
        @param attribute: The attribute's name. It is case-sensitive.
        @return: The named attribute's value, as a string.
        '''
        self._check_self()
        path = "%s/attrib/%s" % (self.path, str(attribute))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find attribute: %s."
                              % str(attribute))
        else:
            return fread(path).strip()

    def set_parameter(self, parameter, value):
        '''
        Sets the value of a named RFC-3720 parameter.
        The parameter must exist in configFS.
        @param parameter: The RFC-3720 parameter's name. It is case-sensitive.
        @type parameter: string
        @param value: The parameter's value.
        @type value: string
        '''
        self._check_self()
        path = "%s/param/%s" % (self.path, str(parameter))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find parameter: %s."
                              % str(parameter))
        else:
            try:
                fwrite(path, "%s\n" % str(value))
            except IOError, msg:
                msg = msg[1]
                raise RTSLibError("Cannot set parameter %s: %s"
                                  % (str(parameter), str(msg)))

    def get_parameter(self, parameter):
        '''
        @param parameter: The RFC-3720 parameter's name. It is case-sensitive.
        @type parameter: string
        @return: The named parameter value as a string.
        '''
        self._check_self()
        path = "%s/param/%s" % (self.path, str(parameter))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find RFC-3720 parameter: %s."
                              % str(parameter))
        else:
            return fread(path).rstrip()

    def set_auth_attr(self, auth_attr, value):
        '''
        Sets the value of a named auth_attr.
        The auth_attr must exist in configFS.
        @param auth_attr: The auth_attr's name. It is case-sensitive.
        @type auth_attr: string
        @param value: The auth_attr's value.
        @type value: string
        '''
        self._check_self()
        path = "%s/auth/%s" % (self.path, str(auth_attr))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find auth attribute: %s."
                              % str(auth_attr))
        else:
            try:
                fwrite(path, "%s" % str(value))
            except IOError, msg:
                msg = msg[1]
                raise RTSLibError("Cannot set auth attribute %s: %s"
                                  % (str(auth_attr), str(msg)))

    def get_auth_attr(self, auth_attr):
        '''
        @param auth_attr: The auth_attr's name. It is case-sensitive.
        @return: The named auth_attr's value, as a string.
        '''
        self._check_self()
        path = "%s/auth/%s" % (self.path, str(auth_attr))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find auth attribute: %s."
                              % str(auth_attr))
        else:
            return fread(path).strip()

    def delete(self):
        '''
        If the underlying configFS object does not exists, this method does
        nothing. If the underlying configFS object exists, this method attempts
        to delete it.
        '''
        if self:
            os.rmdir(self.path)

    path = property(_get_path,
            doc="Get the configFS object path.")
    exists = property(_exists,
            doc="Is True as long as the underlying configFS object exists. " \
                      + "If the underlying configFS objects gets deleted " \
                      + "either by calling the delete() method, or by any " \
                      + "other means, it will be False.")
    is_fresh = property(_is_fresh,
            doc="Is True if the underlying configFS object has been created " \
                        + "when instantiating this particular object. Is " \
                        + "False if this object instantiation just looked " \
                        + "up the underlying configFS object.")

def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
