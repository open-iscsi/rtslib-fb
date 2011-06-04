'''
Implements the base CFSNode class and a few inherited variants.

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

import os
import stat
from utils import fread, fwrite, RTSLibError, RTSLibNotInCFS


class CFSNode(object):

    # Where do we store the fabric modules spec files ?
    spec_dir = "/var/target/fabric"
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
        if not self:
            os.mkdir(self.path)
            self._fresh = True
        else:
            self._fresh = False

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
                fwrite(path, "%s \n" % str(value))
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
                        + "when instanciating this particular object. Is " \
                        + "False if this object instanciation just looked " \
                        + "up the underlying configFS object.")

def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
