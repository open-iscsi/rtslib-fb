# The ib_srpt fabric module specfile.
#
# This file is part of RTSLib Community Edition.
# Copyright (c) 2011 by RisingTide Systems LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, version 3 (AGPLv3).
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# The fabric module feature set
features = ("acls",)

# Non-standard module naming scheme
kernel_module = "ib_srpt"

# Transform 'fe80:0000:0000:0000:0002:1903:000e:8acd' WWN notation to
# '0xfe8000000000000000021903000e8acd'
def wwns():
  for wwn_file in glob("/sys/class/infiniband/*/ports/*/gids/0"):
      yield "0x" + fread(wwn_file).strip(":")

# The configfs group
configfs_group = "srpt"

