# The iscsi fabric module specfile.
#

# The iscsi fabric module features set.
features = discovery_auth, acls, acls_auth, acls_tcq_depth, nps, tpgts

# Obviously, this module uses IQN strings as WWNs.
wwn_type = iqn

# This is default too
# kernel_module = iscsi_target_mod

# The configfs group name, default too
# configfs_group = iscsi

