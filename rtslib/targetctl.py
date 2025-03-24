#!/usr/bin/python3
'''
targetctl

This file is part of RTSLib.
Copyright (c) 2013 by Red Hat, Inc.

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

#
# A script to save/restore LIO configuration to/from a file in json format
#

import os
import sys
from pathlib import Path

from rtslib_fb import RTSRoot

default_save_file = "/etc/target/saveconfig.json"
err = sys.stderr

def usage():
    print(f"syntax: {sys.argv[0]} save [file_to_save_to]\n"
          f"        {sys.argv[0]} restore [file_to_restore_from]\n"
          f"        {sys.argv[0]} clear\n"
          f"default file is: {default_save_file}", file=err)
    sys.exit(-1)

def save(to_file):
    RTSRoot().save_to_file(save_file=to_file)

def restore(from_file):

    try:
        errors = RTSRoot().restore_from_file(restore_file=from_file)
    except OSError:
        # Not an error if the restore file is not present
        print(f"No saved config file at {from_file}, ok, exiting")
        sys.exit(0)

    for error in errors:
        print(error, file=err)

def clear():
    RTSRoot().clear_existing(confirm=True)

funcs = {"save": save, "restore": restore, "clear": clear}

def main():
    if os.geteuid() != 0:
        print("Must run as root", file=err)
        sys.exit(-1)

    if len(sys.argv) < 2 or len(sys.argv) > 3:
        usage()

    if sys.argv[1] == "--help":
        usage()

    if sys.argv[1] not in funcs:
        usage()

    savefile = default_save_file
    if len(sys.argv) == 3:
        savefile = Path(sys.argv[2]).expanduser()

    funcs[sys.argv[1]](savefile)

if __name__ == "__main__":
    main()
