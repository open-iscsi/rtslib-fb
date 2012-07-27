# The iscsi fabric module specfile.
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

# The iscsi fabric module features set.
features = ("discovery_auth", "acls", "acls_auth", "nps", "tpgts")

# Obviously, this module uses IQN strings as WWNs.
wwn_type = "iqn"

# This is default too
# kernel_module = iscsi_target_mod

# The configfs group name, default too
# configfs_group = iscsi

