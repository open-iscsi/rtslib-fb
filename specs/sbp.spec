# See README for details on this file's format

# The fabric module feature set
features = ()

# Non-standard module naming scheme
kernel_module = "sbp_target"

# This *will* return the first local 1394 device's guid, but until
# 3.6 when is_local is available, return an arbitrary value
def wwns():
  return ["1234567890abcdef"]

# The configfs group
configfs_group = "sbp"

