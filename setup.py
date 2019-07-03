#! /usr/bin/env python
'''
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
import re
from setuptools import setup

# Get version without importing.
init_file_path = os.path.join(os.path.dirname(__file__), 'rtslib/__init__.py')

with open(init_file_path) as f:
    for line in f:
        match = re.match(r"__version__.*'([0-9.]+)'", line)
        if match:
            version = match.group(1)
            break
    else:
        raise Exception("Couldn't find version in setup.py")

setup (
    name = 'rtslib-fb',
    version = version,
    description = 'API for Linux kernel SCSI target (aka LIO)',
    license = 'Apache 2.0',
    maintainer = 'Andy Grover',
    maintainer_email = 'agrover@redhat.com',
    url = 'http://github.com/open-iscsi/rtslib-fb',
    packages = ['rtslib_fb', 'rtslib'],
    scripts = ['scripts/targetctl'],
    install_requires = [
        'pyudev >= 0.16.1',
        'six',
    ],
    classifiers = [
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
    ],
    )
