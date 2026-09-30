'''
Deprecated alias of the rtslib package.

The rtslib_fb module has been renamed to rtslib. This module only keeps
existing "import rtslib_fb" code working, new code should import rtslib
instead.

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

import importlib
import pkgutil
import sys
import warnings

import rtslib

warnings.warn(
    "The 'rtslib_fb' module is deprecated, import 'rtslib' instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Alias rtslib_fb and all of its submodules to the rtslib module objects,
# so that classes and exceptions are shared, e.g. an RTSLibError raised by
# rtslib is caught by "except rtslib_fb.utils.RTSLibError".
for _module in pkgutil.iter_modules(rtslib.__path__):
    sys.modules[f"{__name__}.{_module.name}"] = importlib.import_module(f"rtslib.{_module.name}")
sys.modules[__name__] = rtslib
