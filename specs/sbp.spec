# See README for details on this file's format

# The fabric module feature set
features = ()

# Non-standard module naming scheme
kernel_module = "sbp_target"

# We need a single unique value to create the target.
# Return the first local 1394 device's guid.
def wwns():
    import os
    for fname in glob("/sys/bus/firewire/devices/fw*/is_local"):
        if bool(int(fread(fname))):
            guid_path = os.path.dirname(fname) + "/guid"
            yield fread(guid_path)[2:]
            break

# The configfs group
configfs_group = "sbp"

