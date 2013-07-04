# The tcm_fc fabric module specfile.
#

# The fabric module feature set
features = acls

# Non-standard module naming scheme
kernel_module = tcm_fc

# The module uses hardware addresses from there
wwn_from_files = /sys/class/fc_host/host*/port_name
# Transform '0x1234567812345678' WWN notation to '12:34:56:78:12:34:56:78'
wwn_from_files_filter = "sed -e s/0x// -e 's/../&:/g' -e s/:$//"

# The configfs group
configfs_group = fc
