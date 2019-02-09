'''
Implements the base CFSNode class and a few inherited variants.

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
import stat
from .utils import fread, fwrite, RTSLibError, RTSLibNotInCFS


class CFSNode(object):

    # Where is the configfs base LIO directory ?
    configfs_dir = '/sys/kernel/config/target'

    # CFSNode private stuff

    def __init__(self):
        self._path = self.configfs_dir

    def __eq__(self, other):
        return self._path == other._path

    def __ne__(self, other):
        return self._path != other._path

    def _get_path(self):
        return self._path

    def _create_in_cfs_ine(self, mode):
        '''
        Creates the configFS node if it does not already exist, depending on
        the mode.
        any -> makes sure it exists, also works if the node already does exist
        lookup -> make sure it does NOT exist
        create -> create the node which must not exist beforehand
        '''
        if mode not in ['any', 'lookup', 'create']:
            raise RTSLibError("Invalid mode: %s" % mode)

        if self.exists and mode == 'create':
            # ensure that self.path is not stale hba-only dir
            if os.path.samefile(os.path.dirname(self.path), self.configfs_dir+'/core') \
               and not next(os.walk(self.path))[1]:
                os.rmdir(self.path)
            else:
               raise RTSLibError("This %s already exists in configFS"
                                 % self.__class__.__name__)

        elif not self.exists and mode == 'lookup':
            raise RTSLibNotInCFS("No such %s in configfs: %s"
                                 % (self.__class__.__name__, self.path))

        if not self.exists:
            try:
                os.mkdir(self.path)
            except:
                raise RTSLibError("Could not create %s in configFS"
                                  % self.__class__.__name__)

    def _exists(self):
        return os.path.isdir(self.path)

    def _check_self(self):
        if not self.exists:
            raise RTSLibNotInCFS("This %s does not exist in configFS"
                                 % self.__class__.__name__)

    def _list_files(self, path, writable=None, readable=None):
        '''
        List files under a path depending on their owner's write permissions.
        @param path: The path under which the files are expected to be. If the
        path itself is not a directory, an empty list will be returned.
        @type path: str
        @param writable: If None (default), return all files despite their
        writability. If True, return only writable files. If False, return
        only non-writable files.
        @type writable: bool or None
        @param readable: If None (default), return all files despite their
        readability. If True, return only readable files. If False, return
        only non-readable files.
        @type readable: bool or None
        @return: List of file names filtered according to their
        read/write perms.
        '''
        if not os.path.isdir(path):
            return []

        if writable is None and readable is None:
            names = os.listdir(path)
        else:
            names = []
            for name in os.listdir(path):
                sres = os.stat("%s/%s" % (path, name))
                if writable is not None:
                    if writable != ((sres[stat.ST_MODE] & stat.S_IWUSR) == \
                            stat.S_IWUSR):
                        continue
                if readable is not None:
                    if readable != ((sres[stat.ST_MODE] & stat.S_IRUSR) == \
                            stat.S_IRUSR):
                        continue
                names.append(name)

        names.sort()
        return names

    # CFSNode public stuff

    def list_parameters(self, writable=None, readable=None):
        '''
        @param writable: If None (default), return all parameters despite
        their writability. If True, return only writable parameters. If
        False, return only non-writable parameters.
        @type writable: bool or None
        @param readable: If None (default), return all parameters despite
        their readability. If True, return only readable parameters. If
        False, return only non-readable parameters.
        @type readable: bool or None
        @return: The list of existing RFC-3720 parameter names.
        '''
        self._check_self()
        path = "%s/param" % self.path
        return self._list_files(path, writable, readable)

    def list_attributes(self, writable=None, readable=None):
        '''
        @param writable: If None (default), return all files despite their
        writability. If True, return only writable files. If False, return
        only non-writable files.
        @type writable: bool or None
        @param readable: If None (default), return all files despite their
        readability. If True, return only readable files. If False, return
        only non-readable files.
        @type readable: bool or None
        @return: A list of existing attribute names as strings.
        '''
        self._check_self()
        path = "%s/attrib" % self.path
        return self._list_files(path, writable, readable)

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
            raise RTSLibError("Cannot find attribute: %s"
                              % str(attribute))
        else:
            try:
                fwrite(path, "%s" % str(value))
            except Exception as e:
                raise RTSLibError("Cannot set attribute %s: %s" % (attribute, e))

    def get_attribute(self, attribute):
        '''
        @param attribute: The attribute's name. It is case-sensitive.
        @return: The named attribute's value, as a string.
        '''
        self._check_self()
        path = "%s/attrib/%s" % (self.path, str(attribute))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find attribute: %s" % attribute)
        else:
            return fread(path)

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
            raise RTSLibError("Cannot find parameter: %s" % parameter)
        else:
            try:
                fwrite(path, "%s\n" % str(value))
            except Exception as e:
                raise RTSLibError("Cannot set parameter %s: %s" % (parameter, e))

    def get_parameter(self, parameter):
        '''
        @param parameter: The RFC-3720 parameter's name. It is case-sensitive.
        @type parameter: string
        @return: The named parameter value as a string.
        '''
        self._check_self()
        path = "%s/param/%s" % (self.path, str(parameter))
        if not os.path.isfile(path):
            raise RTSLibError("Cannot find RFC-3720 parameter: %s" % parameter)
        else:
            return fread(path)

    def delete(self):
        '''
        If the underlying configFS object does not exist, this method does
        nothing. If the underlying configFS object exists, this method attempts
        to delete it.
        '''
        if self.exists:
            os.rmdir(self.path)

    path = property(_get_path,
            doc="Get the configFS object path.")
    exists = property(_exists,
            doc="Is True as long as the underlying configFS object exists. " \
                      + "If the underlying configFS objects gets deleted " \
                      + "either by calling the delete() method, or by any " \
                      + "other means, it will be False.")

    def dump(self):
        d = {}
        attrs = {}
        params = {}
        for item in self.list_attributes(writable=True, readable=True):
            try:
                attrs[item] = int(self.get_attribute(item))
            except ValueError:
                attrs[item] = self.get_attribute(item)
        if attrs:
            d['attributes'] = attrs
        for item in self.list_parameters(writable=True, readable=True):
            params[item] = self.get_parameter(item)
        if params:
            d['parameters'] = params
        return d

def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
