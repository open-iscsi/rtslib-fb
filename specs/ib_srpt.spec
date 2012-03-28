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
features = acls

# Non-standard module naming scheme
kernel_module = ib_srpt

# The module uses hardware addresses from there
wwn_from_files = /sys/class/infiniband/*/ports/*/gids/0
# Transform 'fe80:0000:0000:0000:0002:1903:000e:8acd' WWN notation to
# '0xfe800000000000000002c903000e8acd'
wwn_from_files_filter = "sed -e s/fe80/0xfe80/ -e 's/\://g'"

# The configfs group
configfs_group = srpt

