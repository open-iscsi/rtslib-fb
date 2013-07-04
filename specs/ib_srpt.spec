# The ib_srpt fabric module specfile.
#

# The fabric module feature set
features = acls

# Non-standard module naming scheme
kernel_module = ib_srpt

# The module uses hardware addresses from there
wwn_from_files = /sys/class/infiniband/*/ports/*/gids/0
# Transform 'fe80:0000:0000:0000:0002:1903:000e:8acd' WWN notation to
# '0x00000000000000000002c903000e8acd'
wwn_from_files_filter = "sed -e s/fe80/0xfe80/ -e 's/\://g'"

# The configfs group
configfs_group = srpt

